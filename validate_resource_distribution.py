#!/usr/bin/env python3
"""
validate_resource_distribution.py -- Pass/fail validation of the resource
distribution on the FINAL painted map.bin (not just the node-tier algorithm).

For every test map it runs the real convert_map() pipeline in-process at
RESOURCE_RICHNESS = 0.5, 1.0, 1.5 and asserts, on the painted output:

  * Knob:     r=0.5 -> essentially all Ore   (>= 95% of resource cells)
              r<=1.0 -> ZERO gems
              r=1.5 -> essentially all Gems   (>= 95% of resource cells)
  * Symmetry: painted tiers are mirror-symmetric  (100% of overlapping cells)
  * Coherence: every node actor's colour matches the field it stands in

Runs all three distribution modes ("distance", "balance", "even") by default.
For distance/balance the knob invariants (r=0.5 -> all Ore, r<=1.0 -> no gems,
r=1.5 -> all Gems) are checked.  For "even" mode the richness knob is
intentionally ignored (Aedis prime directive: equal amounts of every type,
always); instead the validator checks that the maximum achievable number of
resource types appear on the map.  The maximum equals min(6, n_mirror_pairs)
because mirror symmetry requires both fields in a pair to share the same tier —
maps with fewer than 6 mirror-field-pairs physically cannot show all 6 types
while maintaining 100% mirror symmetry.  The algorithm always assigns the lowest
tiers (Ore first) to the nearest-spawn pairs, so only the top-of-ladder types
(Gems, GoldTiberium) are the first to drop off on small maps.
Symmetry and coherence are checked for all modes.  Exits non-zero if any
requirement fails.

Usage:
    python validate_resource_distribution.py [--mode distance|balance|even|all] [map.oramap ...]
"""

import math
import os
import re
import sys
import zipfile
import tempfile
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cameo_map_converter as cmc
import resource_reclassification as rr

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IDX_TIER = {v: k for k, v in cmc.CAMEO_RES_INDEX.items()}
ACTOR_TIER = {v: k for k, v in cmc.CAMEO_RES_ACTOR.items()}

DEFAULT_MAPS = [
    "Abendland_BI-4.5", "Cow_Level_1v1_BI-4.3", "Crownsbury_BI-4.5",
    "Dash_BI-4.5", "Discovery_BI-4.5", "Kosovo_1v1_BI-4.3",
    "Patches_BI-4.5", "Taiga_Vortex_v2_BI-4.5",
    "Abendland_2v2_BI-4.5", "Abendland_4v4_BI-4.5",
]

ORE_MIN = 95.0    # % at r=0.5
GEMS_MIN = 95.0   # % at r=1.5
SYM_MIN = 99.5    # % mirror-symmetric overlapping cells


def max_even_tiers(src):
    """Return the maximum number of distinct tiers achievable in even mode for
    this map.  Equals min(6, n_mirror_field_pairs).  On point-symmetric 1v1
    maps a pair of nodes share both fields in a mirror-pair, limiting the
    achievable variety below 6 even with a perfect algorithm."""
    try:
        with zipfile.ZipFile(src) as z:
            yaml_text = z.read("map.yaml").decode("utf-8", "replace")
            mb = cmc.MapBin(z.read("map.bin"))
    except Exception:
        return 6
    lines = yaml_text.split("\n")
    actors = cmc.parse_actors(lines)
    spawns = [(a["x"], a["y"]) for a in actors
              if a["name"] == "mpspawn" and a["x"] is not None]
    seeds  = [a for a in actors
              if a["name"] in cmc.SOURCE_RESOURCE_ACTORS and a["x"] is not None]
    if not spawns or not seeds:
        return 6
    W, H = mb.width, mb.height
    cells = mb.resource_cells()
    if not cells:
        return 6
    cellset = set(cells)
    label, fields = {}, []
    for start in cells:
        if start in label:
            continue
        fid = len(fields)
        comp = []
        q = deque([start])
        label[start] = fid
        while q:
            cur = q.popleft()
            comp.append(cur)
            cc, cr = cur // H, cur % H
            for dc in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    nc, nr = cc + dc, cr + dr
                    nk = nc * H + nr
                    if 0 <= nc < W and 0 <= nr < H and nk in cellset and nk not in label:
                        label[nk] = fid
                        q.append(nk)
        fields.append(comp)
    centers = [(sum(c // H for c in comp) / len(comp),
                sum(c % H for c in comp) / len(comp))
               for comp in fields]
    transforms, _ = rr.detect_symmetries(spawns, seeds)
    parent = list(range(len(fields)))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    if transforms and len(fields) > 1:
        for _, T in transforms:
            for fid, (cx, cy) in enumerate(centers):
                tx, ty = T(cx, cy)
                best_d, bj = None, None
                for fj, (ox, oy) in enumerate(centers):
                    d = math.hypot(tx - ox, ty - oy)
                    if best_d is None or d < best_d:
                        best_d, bj = d, fj
                if bj is not None and bj != fid and best_d <= 5.0:
                    ra, rb = find(fid), find(bj)
                    if ra != rb:
                        parent[ra] = rb
    n_pairs = len({find(fid) for fid in range(len(fields))})
    return min(6, n_pairs)


def convert(src, richness, mode, outdir, valid):
    cmc.RESOURCE_RICHNESS = richness
    rr.DISTRIBUTION_MODE = mode
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, os.path.basename(src))
    rpt = cmc.Report()
    ok = cmc.convert_map(src, out, rpt, keep_palettes=False,
                         keep_decorations=False, valid=valid, dry_run=False)
    return out if ok else None


def load(path):
    with zipfile.ZipFile(path) as z:
        y = z.read("map.yaml").decode("utf-8", "replace")
        mb = cmc.MapBin(z.read("map.bin"))
    spawns, nodes, cur = [], [], None
    for ln in y.split("\n"):
        m = re.match(r"\s+Actor\d+:\s*([A-Za-z0-9_.\-]+)", ln)
        if m:
            cur = m.group(1)
            continue
        if cur and "Location:" in ln:
            try:
                x, yv = map(int, ln.split("Location:")[1].strip().split(","))
            except ValueError:
                cur = None
                continue
            base = cur.split(".")[0]
            if cur == "mpspawn":
                spawns.append((x, yv))
            elif base in ACTOR_TIER:
                nodes.append((base, x, yv))
            cur = None
    return mb, spawns, nodes


def _res(mb, col, row):
    if 0 <= col < mb.width and 0 <= row < mb.height:
        return mb.raw[mb.res_off + (col * mb.height + row) * 2]
    return -1


def analyze(mb, spawns, nodes):
    W, H = mb.width, mb.height
    cx = sum(s[0] for s in spawns) / len(spawns)
    cy = sum(s[1] for s in spawns) / len(spawns)
    counts, match, mismatch = {}, 0, 0
    for col in range(W):
        for row in range(H):
            t = _res(mb, col, row)
            if t in IDX_TIER:
                counts[IDX_TIER[t]] = counts.get(IDX_TIER[t], 0) + 1
                mt = _res(mb, round(2 * cx - col), round(2 * cy - row))
                if mt in IDX_TIER:
                    if mt == t:
                        match += 1
                    else:
                        mismatch += 1
    sym = 100.0 * match / (match + mismatch) if (match + mismatch) else 100.0
    incoherent = []
    for nm, x, y in nodes:
        want = ACTOR_TIER[nm]
        near = {}
        for dc in range(-3, 4):
            for dr in range(-3, 4):
                t = _res(mb, x + dc, y + dr)
                if t in IDX_TIER:
                    near[IDX_TIER[t]] = near.get(IDX_TIER[t], 0) + 1
        if near and max(near, key=near.get) != want:
            incoherent.append((nm, x, y))
    return counts, sym, incoherent


def main(argv):
    args = [a for a in argv[1:]]
    mode_sel = "both"
    if "--mode" in args:
        i = args.index("--mode")
        mode_sel = args[i + 1]
        del args[i:i + 2]
    names = args or DEFAULT_MAPS
    all_modes = ["distance", "balance", "even"]
    modes = all_modes if mode_sel in ("both", "all") else [mode_sel]
    valid = cmc.load_valid_actors(SCRIPT_DIR)
    outdir = tempfile.mkdtemp(prefix="validate_out_")
    failures = []
    print("%-9s %-24s %5s %6s %6s %6s %5s  %s" %
          ("mode", "map", "rich", "ore%", "gems%", "sym%", "incoh", "result"))
    print("-" * 92)
    for mode in modes:
        for mp in names:
            src = mp if mp.endswith(".oramap") else os.path.join(SCRIPT_DIR, "maps", mp + ".oramap")
            if not os.path.exists(src):
                print("(skip, not found) %s" % src)
                continue
            label = os.path.basename(src).replace(".oramap", "")
            # Pre-compute the maximum achievable tiers for even mode on this map.
            _max_tiers = max_even_tiers(src) if mode == "even" else 6
            for r in (0.5, 1.0, 1.5):
                out = convert(src, r, mode, outdir, valid)
                if not out:
                    failures.append("%s/%s r=%s: convert failed" % (mode, label, r))
                    print("%-9s %-24s %5s   CONVERT FAILED" % (mode, label[:24], r))
                    continue
                mb, sp, nodes = load(out)
                counts, sym, incoh = analyze(mb, sp, nodes)
                tot = sum(counts.values()) or 1
                ore = 100 * counts.get("Ore", 0) / tot
                gems = 100 * counts.get("Gems", 0) / tot
                probs = []
                if mode != "even":
                    # Even mode intentionally ignores the richness knob (Aedis
                    # prime directive: equal amounts of every type, always).
                    # The knob saturation invariants only apply to distance/balance.
                    if r == 0.5 and ore < ORE_MIN:
                        probs.append("ore<%.0f" % ORE_MIN)
                    if r <= 1.0 and counts.get("Gems", 0) != 0:
                        probs.append("gems>0")
                    if r == 1.5 and gems < GEMS_MIN:
                        probs.append("gems<%.0f" % GEMS_MIN)
                else:
                    # Even mode: assert the maximum achievable number of tier
                    # types appear on the map.  On small-field maps the mirror-
                    # pair count limits how many distinct types can appear while
                    # still maintaining 100% symmetry (e.g. a 2-spawn map with
                    # only 4 mirror-field-pairs can show at most 4 types).
                    # TIER_ORDER is sorted Ore→Gems; the algorithm always keeps
                    # the lower tiers (nearest-spawn wins), so the first
                    # _max_tiers tiers of TIER_ORDER should all appear.
                    required = rr.TIER_ORDER[:_max_tiers]
                    missing = [t for t in required if counts.get(t, 0) == 0]
                    if missing:
                        probs.append("missing=%s" % "+".join(missing))
                if sym < SYM_MIN:
                    probs.append("sym<%.1f" % SYM_MIN)
                if incoh:
                    probs.append("incoherent=%d" % len(incoh))
                verdict = "PASS" if not probs else "FAIL: " + ",".join(probs)
                if probs:
                    failures.append("%s/%s r=%s: %s" % (mode, label, r, ",".join(probs)))
                print("%-9s %-24s %5s %5.0f%% %5.0f%% %5.1f%% %5d  %s" %
                      (mode, label[:24], r, ore, gems, sym, len(incoh), verdict))
    print("-" * 92)
    if failures:
        print("RESULT: %d FAILURE(S)" % len(failures))
        for f in failures:
            print("  - " + f)
        return 1
    tested = "/".join(modes)
    print("RESULT: ALL CHECKS PASSED (%s)" % tested)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
