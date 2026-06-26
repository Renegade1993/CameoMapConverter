#!/usr/bin/env python3
"""
minimap_render.py -- Shared OpenRA minimap (map.png) renderer for the Cameo converter.

ONE code path used by:
  * cameo_map_converter.convert_map()  -> writes the in-game preview map.png into the
    repackaged .oramap so OpenRA's map-list minimap reflects the CONVERTED terrain +
    resources (not the stale CA map.png).
  * cameo_map_converter.render_resource_preview() -> the side <name>.resources.png.
  * cameo_converter_gui PreviewWorker -> fast in-process GUI preview.

Format (matches OpenRA's stored map.png exactly):
  * 1 pixel per cell, sized to the playable Bounds rectangle (X, Y, Width, Height).
    e.g. a MapSize 98x98 map with Bounds 1,1,96,96 -> a 96x96 PNG covering cells
    col in [1..96], row in [1..96].  (Verified against real source map.png files.)
  * Per-cell TERRAIN colour from the tileset minimap palette (TerrainType Color),
    resolved via (template id, sub-tile index) -> terrain name -> RGB.
  * RESOURCE cells painted over terrain, coloured by Cameo resource tier (the project
    canonical palette, identical to render_corrected_distribution.py and the GUI legend).
  * Optional ACTOR dots: spawns (white) and, if requested, resource nodes.

map.bin is COLUMN-MAJOR: cell index = col * height + row  (col = x, row = y).

Pillow is required to render; callers treat ImportError / None as "no preview".
"""

import os
import re
import math

# --- Canonical resource palette ---------------------------------------------
# map.bin resource byte (Cameo index) -> RGB. Identical RGBs to
# render_corrected_distribution.RESOURCE_COLORS and the GUI hover/legend map.
#   1 Tiberium(green) 2 BlueTiberium 3 Ore 4 Gems 5 RedTiberium 6 GoldTiberium
INDEX_COLORS = {
    1: (0, 210, 0),
    2: (0, 180, 255),
    3: (150, 95, 40),
    4: (170, 60, 210),
    5: (235, 30, 30),
    6: (255, 205, 0),
}

RESOURCE_COLORS = {
    "Tiberium": (0, 210, 0),
    "BlueTiberium": (0, 180, 255),
    "Ore": (150, 95, 40),
    "Gems": (170, 60, 210),
    "RedTiberium": (235, 30, 30),
    "GoldTiberium": (255, 205, 0),
}

# Background / out-of-data fill, and a fallback terrain colour when a cell's
# terrain can't be resolved (no tileset YAML available, unknown template, etc.).
BG_COLOR = (18, 20, 22)
DEFAULT_TERRAIN_COLOR = (40, 68, 40)   # ~ RA_TEMPERAT "Clear" grass (284428-ish)

# Built-in RA_TEMPERAT terrain->minimap-colour table (fallback when the tileset
# YAML has no parsable Terrain: section). Values per OpenRA RA_TEMPERAT.
DEFAULT_TERRAIN_COLORS = {
    "Clear": (40, 68, 40),
    "Rough": (68, 68, 60),
    "Rock": (68, 68, 60),
    "Road": (88, 116, 116),
    "River": (92, 140, 180),
    "Water": (92, 116, 164),
    "Beach": (176, 156, 120),
    "Bridge": (96, 96, 96),
    "Tree": (28, 32, 36),
    "Wall": (208, 192, 160),
    "Rail": (96, 96, 96),
    "Ore": (148, 128, 96),
    "Gems": (132, 112, 255),
}

SPAWN_MARKER = (255, 255, 255)

# Node actor → resource type mapping (for coloring node markers in the preview)
NODE_ACTOR_TO_RESOURCE = {
    "mine":          "Ore",
    "split2":        "Tiberium",
    "split3":        "Tiberium",
    "splitblue":     "BlueTiberium",
    "splitbluesmall":"BlueTiberium",
    "splitred":      "RedTiberium",
    "splitredsmall": "RedTiberium",
    "splitgold":     "GoldTiberium",
    "splitgoldsmall":"GoldTiberium",
    "gmine":         "Gems",
}

# Slightly brightened versions of resource colors for node markers so they
# stand out clearly from the filled resource cells they sit inside.
NODE_MARKER_COLORS = {
    "Ore":          (220, 160,  70),   # warm amber
    "Tiberium":     ( 80, 255,  80),   # bright green
    "BlueTiberium": ( 80, 210, 255),   # bright sky blue
    "RedTiberium":  (255,  80,  80),   # bright red
    "GoldTiberium": (255, 235,  60),   # bright gold
    "Gems":         (210, 100, 255),   # bright violet
}


# --- tileset parsing --------------------------------------------------------

def _hex_rgb(s):
    s = s.strip()
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            return None
    return None


def load_terrain_colors(yaml_path):
    """Parse the tileset YAML's Terrain: section into {terrain_name: (r,g,b)}.

    Reads each `TerrainType@Name:` block's `Color: RRGGBB`. Returns merged over the
    RA_TEMPERAT defaults so unspecified terrains still resolve."""
    colors = dict(DEFAULT_TERRAIN_COLORS)
    try:
        cur = None
        in_terrain = False
        with open(yaml_path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if not raw.strip():
                    continue
                ind = len(raw) - len(raw.lstrip("\t"))
                s = raw.strip()
                if ind == 0:
                    in_terrain = (s.rstrip(":") == "Terrain")
                    cur = None
                    continue
                if not in_terrain:
                    continue
                if ind == 1 and s.startswith("TerrainType@"):
                    cur = s[len("TerrainType@"):].rstrip(":").strip()
                elif ind >= 2 and cur and s.startswith("Color:"):
                    rgb = _hex_rgb(s.split(":", 1)[1])
                    if rgb:
                        colors[cur] = rgb
    except Exception:
        pass
    return colors


def _candidate_tilesets(script_dir=None):
    """Ordered candidate tileset YAML paths for terrain resolution. Independent of
    the converter's water-crossing path so it can never change conversion output."""
    if script_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(script_dir, "..", ".."))
    return [
        os.path.join(script_dir, "ra_temperat.yaml"),                 # bundled (preferred for exe)
        os.path.join(script_dir, "tilesets", "ra_temperat.yaml"),
        os.path.join(root, "Cameo-mod-playtest-20260614 (source)", "mods", "cameo", "tilesets", "ra_temperat.yaml"),
        os.path.join(root, "Game Sources", "Cameo-mod-playtest-20260614 (source)", "mods", "cameo", "tilesets", "ra_temperat.yaml"),
        os.path.join(root, "Game Sources", "OpenRA-playtest-20260222  (source)", "mods", "ra", "tilesets", "temperat.yaml"),
        os.path.join(root, "Game Sources", "OpenRA-playtest-20260222 (source)", "mods", "ra", "tilesets", "temperat.yaml"),
    ]


def _readable(path):
    """True only if the file can actually be opened+read (beats stale-mount os.path.exists)."""
    try:
        with open(path, "rb") as f:
            return bool(f.read(1))
    except Exception:
        return False


# Cache the (templates_table, terrain_colors, used_path) so we parse the tileset once.
_TERR_CACHE = {}


def get_terrain_tables(script_dir=None):
    """Return (templates_table, terrain_colors). Iterates candidate tileset YAMLs and
    uses the FIRST that is actually readable AND yields a non-empty templates table;
    otherwise falls back to flat default terrain colours.

    templates_table: {template_id: {sub_index: terrain_name}} or None if none load.
    terrain_colors:  {terrain_name: (r,g,b)} (always populated)."""
    if "_" in _TERR_CACHE:
        return _TERR_CACHE["_"]
    templates = None
    colors = dict(DEFAULT_TERRAIN_COLORS)
    used = None
    try:
        from water_crossing_detect import load_tileset_terrain
    except Exception:
        load_tileset_terrain = None
    if load_tileset_terrain is not None:
        for c in _candidate_tilesets(script_dir):
            if not _readable(c):
                continue
            try:
                tpl = load_tileset_terrain(c)
            except Exception:
                tpl = None
            if tpl:                       # non-empty templates table
                templates = tpl
                colors = load_terrain_colors(c)
                used = c
                break
    _TERR_CACHE["_"] = (templates, colors)
    _TERR_CACHE["used"] = used
    return _TERR_CACHE["_"]


def resolve_tileset_yaml(script_dir=None):
    """Return the tileset YAML actually used for terrain (or None). For reporting."""
    if "used" not in _TERR_CACHE:
        get_terrain_tables(script_dir)
    return _TERR_CACHE.get("used")


# --- map.yaml helpers -------------------------------------------------------

def parse_bounds(yaml_text):
    """Return (x, y, w, h) from the map.yaml Bounds rectangle, or None."""
    for ln in yaml_text.split("\n"):
        s = ln.strip()
        if s.startswith("Bounds:"):
            try:
                parts = [int(p) for p in s.split(":", 1)[1].strip().split(",")]
            except ValueError:
                return None
            if len(parts) == 4:
                return tuple(parts)
            if len(parts) == 2:               # width,height only -> origin 0,0
                return (0, 0, parts[0], parts[1])
    return None


def parse_actor_locations(yaml_text):
    """Return [(name, x, y), ...] for placed actors (name lower-cased base)."""
    out = []
    cur = None
    for ln in yaml_text.split("\n"):
        m = re.match(r"\s+Actor\d+:\s*([A-Za-z0-9_.\-]+)", ln)
        if m:
            cur = m.group(1)
            continue
        if cur and "Location:" in ln:
            try:
                x, y = map(int, ln.split("Location:")[1].strip().split(","))
                out.append((cur.split(".")[0].lower(), x, y))
            except ValueError:
                pass
            cur = None
    return out


# --- per-cell terrain -------------------------------------------------------

def _cell_terrain_name(mb, i, templates):
    if templates is None:
        return None
    tid = mb.tile_type(i)
    idx = mb.raw[mb.tiles_off + i * 3 + 2]
    sub = templates.get(tid)
    return sub.get(idx) if sub else None


# --- rendering --------------------------------------------------------------

def _resolved_bounds(mb, yaml_text):
    b = parse_bounds(yaml_text) if yaml_text else None
    if not b:
        return (0, 0, mb.width, mb.height)
    x, y, w, h = b
    # clamp to map just in case
    x = max(0, min(x, mb.width - 1)); y = max(0, min(y, mb.height - 1))
    w = max(1, min(w, mb.width - x)); h = max(1, min(h, mb.height - y))
    return (x, y, w, h)


def terrain_layer(mb, templates, terrain_colors, bounds, scale=1):
    """Render ONLY the terrain base (cacheable; independent of resource knobs)."""
    from PIL import Image
    x0, y0, w, h = bounds
    img = Image.new("RGB", (w * scale, h * scale), BG_COLOR)
    px = img.load()
    H = mb.height
    for cx in range(w):
        col = x0 + cx
        base = col * H
        for cy in range(h):
            row = y0 + cy
            name = _cell_terrain_name(mb, base + row, templates)
            color = terrain_colors.get(name, DEFAULT_TERRAIN_COLOR) if name else DEFAULT_TERRAIN_COLOR
            if scale == 1:
                px[cx, cy] = color
            else:
                for sx in range(scale):
                    for sy in range(scale):
                        px[cx * scale + sx, cy * scale + sy] = color
    return img


def overlay_resources(img, mb, bounds, scale=1):
    """Paint resource cells (by tier colour) over the terrain layer, in place."""
    x0, y0, w, h = bounds
    px = img.load()
    H = mb.height
    roff = mb.res_off
    for cx in range(w):
        col = x0 + cx
        base = col * H
        for cy in range(h):
            row = y0 + cy
            t = mb.raw[roff + (base + row) * 2]
            color = INDEX_COLORS.get(t)
            if color is None:
                continue
            if scale == 1:
                px[cx, cy] = color
            else:
                for sx in range(scale):
                    for sy in range(scale):
                        px[cx * scale + sx, cy * scale + sy] = color


def _dot(px, w, h, cx, cy, color, r):
    """Paint a filled square marker of radius r (side = 2r+1) centred at (cx, cy).

    r=0 → single pixel.  The square is clipped to image bounds so it never writes
    outside the image even when markers are near the edge.
    """
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            x, y = cx + dx, cy + dy
            if 0 <= x < w and 0 <= y < h:
                px[x, y] = color


def _cell_square(px, w, h, col, row, color, scale, border_color=None):
    """Fill the exact scale×scale pixel block for map cell (col, row).

    Optionally draws a 1-px border in border_color around the filled block.
    This is bleed-proof: the fill is strictly confined to the cell's pixel block.
    At scale=1 the border is suppressed — there is no room for a border without
    overwriting the single fill pixel, which would make all markers black.
    """
    x0, y0 = col * scale, row * scale
    for dx in range(scale):
        for dy in range(scale):
            x, y = x0 + dx, y0 + dy
            if 0 <= x < w and 0 <= y < h:
                px[x, y] = color
    if border_color and scale > 1:
        for dx in range(scale):
            for dy in range(scale):
                if dx == 0 or dx == scale - 1 or dy == 0 or dy == scale - 1:
                    x, y = x0 + dx, y0 + dy
                    if 0 <= x < w and 0 <= y < h:
                        px[x, y] = border_color


def overlay_actors(img, actors, bounds, scale=1, draw_spawns=True, draw_nodes=False,
                   node_type_map=None):
    """Draw spawn markers (and optionally resource-node dots) over the image.

    Markers are drawn as exact cell-square fills (bleed-proof): each marker occupies
    precisely the scale×scale pixel block for its map cell, with a contrasting border.
    At scale=1 this degenerates to a single pixel per cell (same as before).

    node_type_map: optional dict of (ax, ay) -> resource_type string.  When provided,
    the drawn marker color for a node is taken from this map instead of the actor name.
    This lets render_preview display the *assigned* tier color (e.g. Tiberium for a mine
    that generates Tiberium) and also applies GUI node-paint overrides.
    """
    x0, y0, w, h = bounds
    W, Hpix = img.size
    px = img.load()
    node_names = set(NODE_ACTOR_TO_RESOURCE.keys())
    for name, ax, ay in actors:
        # Cell coordinates relative to the bounds origin
        col = ax - x0
        row = ay - y0
        if not (0 <= col < w and 0 <= row < h):
            continue
        if name == "mpspawn" and draw_spawns:
            # Spawn: white fill, black border
            _cell_square(px, W, Hpix, col, row, SPAWN_MARKER, scale,
                         border_color=(0, 0, 0))
        elif draw_nodes and name in node_names:
            # Use node_type_map (assigned/overridden tier) when available,
            # otherwise fall back to the actor name's native resource type.
            if node_type_map and (ax, ay) in node_type_map:
                res_type = node_type_map[(ax, ay)]
            else:
                res_type = NODE_ACTOR_TO_RESOURCE[name]
            color = NODE_MARKER_COLORS.get(res_type, (255, 255, 255))
            # Node: resource-colored fill, black border
            _cell_square(px, W, Hpix, col, row, color, scale,
                         border_color=(0, 0, 0))


def render_minimap(mb, yaml_text="", script_dir=None, scale=1,
                   draw_actors=True, draw_nodes=False, terr_tables=None,
                   actors=None, node_type_map=None):
    """Full compose: terrain + resources + (optional) actor markers.

    Returns a PIL.Image sized to the playable Bounds * scale, matching OpenRA's
    map.png. `terr_tables` may be a pre-fetched (templates, colors) tuple (lets the
    GUI cache it); otherwise it is loaded (and cached) via get_terrain_tables().

    node_type_map: Optional dict of (x, y) -> resource_type for node override coloring.
    """
    if terr_tables is None:
        terr_tables = get_terrain_tables(script_dir)
    templates, terrain_colors = terr_tables
    bounds = _resolved_bounds(mb, yaml_text)
    img = terrain_layer(mb, templates, terrain_colors, bounds, scale)
    overlay_resources(img, mb, bounds, scale)
    if draw_actors:
        if actors is None:
            actors = parse_actor_locations(yaml_text) if yaml_text else []
        overlay_actors(img, actors, bounds, scale, draw_spawns=True, draw_nodes=draw_nodes,
                      node_type_map=node_type_map)
    return img


def save_minimap_png(mb, yaml_text, png_path, **kw):
    """Render and save; returns True on success, False if Pillow is missing/error."""
    try:
        img = render_minimap(mb, yaml_text, **kw)
        img.save(png_path)
        return True
    except Exception:
        return False
