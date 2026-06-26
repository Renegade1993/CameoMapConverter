#!/usr/bin/env python3
"""
water_crossing_detect.py -- proper ford/water-crossing detection for the Cameo
map converter.

Why the old algorithms found 0 crossings
----------------------------------------
1. Water-ness was tested at the TEMPLATE level with water = {1, 2}. But in a real
   map almost no land cell touches template 1/2 directly. A water body's edge is
   built from SHORE templates (Beach category, ids 3-56 = sh01..sh54), RIVER
   (112-127, 229-234) and WATER CLIFFS (59-96, ...). Those template ids were never
   counted as water, so the reconstructed "water bodies" were tiny disconnected
   fragments -> "4 bodies, 0 crossings".

2. Water is a PER-CELL terrain that lives INSIDE multi-cell templates. Example,
   shore template 24 (sh22, 6x5):
        index 0  -> Water        index 12 -> Beach
        index 22 -> Water        index 13 -> Beach   index 19 -> Clear
   The same template id 24 is Water in some cells and Beach/Clear in others. You
   can only tell which by the sub-tile INDEX (the 3rd byte of each cell in map.bin)
   looked up in that template's `Tiles:` map. The converter only read the template
   id, so it could never see the shore water.

3. ids 119/122 (algorithm #1's "beach/shore") are actually RIVER templates
   (rv08/rv11). Matching against them extended rivers, as observed.

What 225 and 591 really are
---------------------------
   225  rf10.tem   Debris  Size 2,1  -> Rough, Rough     (the source "rocky grass")
   591  fjord2.tem Bridge  Size 2,1  -> Rough, Rough     (horizontal ford)
   590  fjord1.tem Bridge  Size 1,2  -> Rough, Rough     (vertical ford)
   221  rf06.tem   Debris  Size 1,1  -> Rock             (cannot become a 2-cell ford)
   129  ford1.tem  Bridge  Size 3,3  -> Rough/River      (large ford for wider crossings)

225 and 591 have the SAME footprint (2x1) and SAME terrain (Rough). 225 -> 591 is a
clean, same-shape swap. A ford is exactly a "narrow land bridge across water", so
the right rule is: a 225 strip that is pinched by water on two opposite sides is a
crossing; convert it to the ford of the matching orientation. A 225 strip sitting
in open land is decoration; leave it.

Integration: call detect_and_convert_crossings(mb, terr) from convert_map() AFTER
remap_templates() but BEFORE fill_stray_water(). `terr` comes from
load_tileset_terrain(<path to ra_temperat.yaml>).
"""

import struct


# Terrain types that constitute a water channel a ford would cross.
WATER_TERRAINS = frozenset({"Water", "River"})
# Passable land a ford connects / is built on. (Rough = the ford/debris material.)
LAND_TERRAINS = frozenset({"Clear", "Rough", "Beach", "Road", "Ford"})

SOURCE_CROSSING_TEMPLATE = 225      # rocky-rough strip used as a crossing marker
FORD_H = 591                        # 2x1 horizontal ford (water north & south)
FORD_V = 590                        # 1x2 vertical ford   (water east & west)
FORD_LARGE = 129                   # 3x3 large ford (for wider crossings)


# --------------------------------------------------------------------------
# Tileset -> per-cell terrain table
# --------------------------------------------------------------------------

def _indent(line):
    n = 0
    for ch in line:
        if ch == "\t":
            n += 1
        else:
            break
    return n


def load_tileset_terrain(yaml_path):
    """Parse an OpenRA tileset YAML into {template_id(int): {tile_index(int): terrain(str)}}.

    This is the table that lets us resolve a single map cell -- (template id,
    sub-index) -- to its actual terrain, including the water cells buried inside
    shore/river/cliff templates.
    """
    table = {}
    cur_id = None
    in_tiles = False
    in_templates = False
    with open(yaml_path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            ind = _indent(raw)
            s = raw.strip()
            if ind == 0:
                in_templates = (s.rstrip(":") == "Templates")
                cur_id = None
                in_tiles = False
                continue
            if not in_templates:
                continue
            if ind == 1 and s.startswith("Template@"):
                cur_id = None
                in_tiles = False
            elif cur_id is None and ind == 2 and s.startswith("Id:"):
                cur_id = int(s.split(":", 1)[1].strip())
                table.setdefault(cur_id, {})
            elif ind == 2:
                in_tiles = (s.rstrip(":") == "Tiles")
            elif ind >= 3 and in_tiles and cur_id is not None and ":" in s:
                k, _, v = s.partition(":")
                try:
                    table[cur_id][int(k.strip())] = v.strip()
                except ValueError:
                    pass
    return table


# --------------------------------------------------------------------------
# Cell terrain resolution
# --------------------------------------------------------------------------

def cell_terrain(mb, i, terr):
    """Resolve map cell i to its terrain string, or None if unknown.

    Reads the template id (mb.tile_type) AND the sub-tile index (3rd byte) and
    looks both up in `terr`. This is the step every previous algorithm skipped.
    """
    tid = mb.tile_type(i)
    idx = mb.raw[mb.tiles_off + i * 3 + 2]
    sub = terr.get(tid)
    if sub is None:
        return None
    return sub.get(idx)


def _is_water(mb, col, row, terr, W, H):
    if not (0 <= col < W and 0 <= row < H):
        return False                      # map edge is a hard wall, not water
    t = cell_terrain(mb, col * H + row, terr)
    return t in WATER_TERRAINS


def _is_land(mb, col, row, terr, W, H):
    if not (0 <= col < W and 0 <= row < H):
        return False
    t = cell_terrain(mb, col * H + row, terr)
    return t in LAND_TERRAINS


# --------------------------------------------------------------------------
# Crossing detection
# --------------------------------------------------------------------------

def _pinched(mb, col, row, axis, terr, W, H, maxwidth):
    """Is this land cell pinched by water on both sides of `axis`?

    axis 'ns' -> scan up and down (water north & south)  => horizontal ford.
    axis 'ew' -> scan left and right (water east & west)  => vertical ford.

    Walks at most `maxwidth` land cells in each direction; both directions must
    terminate in water for the cell to count as a crossing (a narrow isthmus).
    """
    if axis == "ns":
        dirs = ((0, -1), (0, 1))
    else:
        dirs = ((-1, 0), (1, 0))
    for dcol, drow in dirs:
        c, r = col + dcol, row + drow
        steps = 0
        while _is_land(mb, c, r, terr, W, H) and steps < maxwidth:
            c += dcol
            r += drow
            steps += 1
        if not _is_water(mb, c, r, terr, W, H):
            return False
    return True


def _detect_crossing_cluster(mb, start_col, start_row, terr, W, H, maxwidth):
    """Detect a cluster of connected SOURCE_CROSSING_TEMPLATE cells forming a crossing.
    
    Returns: (min_col, min_row, max_col, max_row, orientation) or None if not a valid crossing
    """
    # BFS to find all connected 225 cells
    visited = set()
    queue = [(start_col, start_row)]
    cells = []
    
    while queue:
        col, row = queue.pop(0)
        if (col, row) in visited:
            continue
        if not (0 <= col < W and 0 <= row < H):
            continue
        cell = col * H + row
        if mb.tile_type(cell) != SOURCE_CROSSING_TEMPLATE:
            continue
        
        visited.add((col, row))
        cells.append((col, row))
        
        # Check 4 neighbors
        for dc, dr in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nc, nr = col + dc, row + dr
            if (nc, nr) not in visited:
                queue.append((nc, nr))
    
    if not cells:
        return None
    
    # Calculate cluster dimensions
    min_col = min(c for c, r in cells)
    max_col = max(c for c, r in cells)
    min_row = min(r for c, r in cells)
    max_row = max(r for c, r in cells)
    
    width = max_col - min_col + 1
    height = max_row - min_row + 1
    
    # Determine orientation based on dimensions
    if width > height:
        orientation = "h"  # horizontal crossing
    elif height > width:
        orientation = "v"  # vertical crossing
    else:
        orientation = "h"  # default to horizontal for square clusters
    
    # For 2x3 clusters, force horizontal orientation (the river crossing is horizontal)
    if width == 2 and height == 3:
        orientation = "h"
    
    # Verify this is actually a crossing (pinched by water)
    # Check center cell of cluster
    center_col = (min_col + max_col) // 2
    center_row = (min_row + max_row) // 2
    center_cell = center_col * H + center_row
    
    if mb.tile_type(center_cell) != SOURCE_CROSSING_TEMPLATE:
        return None
    
    # Check if center is pinched
    if orientation == "h":
        pinched = _pinched(mb, center_col, center_row, "ns", terr, W, H, maxwidth)
        if not pinched:
            # Try checking multiple cells in the cluster
            pinched_any = False
            for c in range(min_col, max_col + 1):
                for r in range(min_row, max_row + 1):
                    if _pinched(mb, c, r, "ns", terr, W, H, maxwidth):
                        pinched_any = True
                        break
                if pinched_any:
                    break
            if not pinched_any:
                return None
    else:
        pinched = _pinched(mb, center_col, center_row, "ew", terr, W, H, maxwidth)
        if not pinched:
            return None
    
    return (min_col, min_row, max_col, max_row, orientation)


def detect_crossings(mb, terr, maxwidth=1):
    """Return list of (cell_index, orientation, cluster_info) for crossings.
    
    cluster_info: (min_col, min_row, max_col, max_row) for larger crossings, or None for single cells
    orientation in {'h', 'v'}.
    
    maxwidth = how many land cells the bridge may be wide (1 = strictest).
    """
    W, H = mb.width, mb.height
    out = []
    visited = set()
    
    for i in range(mb.cells):
        if mb.tile_type(i) != SOURCE_CROSSING_TEMPLATE:
            continue
        col, row = i // H, i % H
        
        if (col, row) in visited:
            continue
        
        # Try to detect a cluster
        cluster = _detect_crossing_cluster(mb, col, row, terr, W, H, maxwidth)
        
        if cluster:
            min_col, min_row, max_col, max_row, orientation = cluster
            
            # Mark all cells in cluster as visited
            for c in range(min_col, max_col + 1):
                for r in range(min_row, max_row + 1):
                    visited.add((c, r))
            
            # Use the center cell as the representative
            center_col = (min_col + max_col) // 2
            center_row = (min_row + max_row) // 2
            center_cell = center_col * H + center_row
            
            cluster_info = (min_col, min_row, max_col, max_row)
            out.append((center_cell, orientation, cluster_info))
        else:
            # Fall back to single cell detection
            if _pinched(mb, col, row, "ns", terr, W, H, maxwidth):
                out.append((i, "h", None))          # water N/S -> horizontal ford 591
            elif _pinched(mb, col, row, "ew", terr, W, H, maxwidth):
                out.append((i, "v", None))          # water E/W -> vertical ford 590
    
    return out


def detect_and_convert_crossings(mb, terr, rpt=None, maxwidth=1):
    """Detect crossings and rewrite the 225 strips as fords (591 / 590 / 129).

    Small crossings (2 cells) use 591 (horizontal) or 590 (vertical).
    Large crossings (3x3 or larger) use 129 (3x3 large ford).
    """
    if mb is None or not terr:
        return 0
    W, H = mb.width, mb.height
    crossings = detect_crossings(mb, terr, maxwidth)
    done = set()
    converted = 0
    for i, orient, cluster_info in crossings:
        if i in done:
            continue
        col, row = i // H, i % H
        
        # Check if this is a large crossing (has cluster info)
        if cluster_info:
            min_col, min_row, max_col, max_row = cluster_info
            cluster_width = max_col - min_col + 1
            cluster_height = max_row - min_row + 1
            
            # Use large ford (129) for clusters 2x3 or larger
            if (cluster_width >= 2 and cluster_height >= 3) or (cluster_width >= 3 and cluster_height >= 2):
                # Place 3x3 ford starting at (min_col-1, min_row) to match user's fix
                start_col = min_col - 1
                start_row = min_row
                
                # Calculate 3x3 grid from start position
                for dc in range(3):
                    for dr in range(3):
                        c = start_col + dc
                        r = start_row + dr
                        if 0 <= c < W and 0 <= r < H:
                            cell = c * H + r
                            # Calculate sub-index for 3x3 template (column-major)
                            sub_index = dr * 3 + dc
                            mb.raw[mb.tiles_off + cell * 3:mb.tiles_off + cell * 3 + 2] = struct.pack('<H', FORD_LARGE)
                            mb.raw[mb.tiles_off + cell * 3 + 2] = sub_index
                            done.add(cell)
                            converted += 1
                
                if rpt:
                    rpt.add(f"  converted large crossing ({min_col},{min_row}):({max_col},{max_row}) -> ford 129")
                continue
        
        # Fall back to small ford (591/590) for single cells or small clusters
        if orient == "h":
            tid, partner = FORD_H, (col + 1, row)   # long axis = east-west
            back = (col - 1, row)
        else:
            tid, partner = FORD_V, (col, row + 1)   # long axis = north-south
            back = (col, row - 1)

        pc, pr = partner
        # Choose the partner cell: prefer the forward neighbour if it is land
        # (ideally another 225); otherwise fall back to the backward neighbour.
        def land225(c, r):
            if not (0 <= c < W and 0 <= r < H):
                return False
            return _is_land(mb, c, r, terr, W, H)

        if land225(pc, pr):
            head, tail = (col, row), (pc, pr)
        elif land225(*back):
            head, tail = back, (col, row)
        else:
            # No room for a 2-cell ford -- leave as-is (avoid a half-placed
            # template that would render the partner cell wrong).
            continue

        h_i = head[0] * H + head[1]
        t_i = tail[0] * H + tail[1]
        mb.set_tile(h_i, tid, 0)
        mb.set_tile(t_i, tid, 1)
        done.add(h_i)
        done.add(t_i)
        converted += 1

    if rpt is not None and converted:
        rpt.add("converted %d water crossing(s): %d cell-pair(s) -> ford 591/590"
                % (converted, converted))
    return converted


# --------------------------------------------------------------------------
# Standalone diagnostic
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "--terr":
        # Quick sanity dump: python water_crossing_detect.py --terr ra_temperat.yaml 24 225 591
        terr = load_tileset_terrain(sys.argv[2])
        for tid in sys.argv[3:]:
            print(tid, "->", dict(sorted(terr.get(int(tid), {}).items())))
    else:
        print(__doc__)
