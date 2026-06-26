#!/usr/bin/env python3
"""
render_corrected_distribution.py -- Visual diagnostic for the resource
distribution produced by the Cameo map converter.

For each test map it runs the REAL convert_map() pipeline IN-PROCESS at a set of
RESOURCE_RICHNESS values (no subprocess -- so the knob actually takes effect),
then renders the painted map.bin with:

  * resource cells coloured by tier
  * node markers (white-outlined) coloured by the tier of the field they sit in
  * spawn markers (white X) and the symmetry centre (cyan +)
  * a stats panel: per-tier CELL counts, per-tier NODE counts, painted mirror
    symmetry %, node/field coherence, and the detected symmetry.

Output: corrected_renders/<Map>_richness_<r>.png
"""

import os
import re
import sys
import zipfile

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cameo_map_converter as cmc
from resource_reclassification import TIER_ORDER
import resource_reclassification as rr

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IDX_TIER = {v: k for k, v in cmc.CAMEO_RES_INDEX.items()}
ACTOR_TIER = {v: k for k, v in cmc.CAMEO_RES_ACTOR.items()}

RESOURCE_COLORS = {
    "Ore": (150, 95, 40),
    "Tiberium": (0, 210, 0),
    "BlueTiberium": (0, 180, 255),
    "RedTiberium": (235, 30, 30),
    "GoldTiberium": (255, 205, 0),
    "Gems": (170, 60, 210),
}
SCALE = 4
PANEL_H = 104
RICHNESS_VALUES = [0.5, 1.0, 1.5]

MAPS = [
    "Abendland_BI-4.5", "Cow_Level_1v1_BI-4.3", "Crownsbury_BI-4.5",
    "Dash_BI-4.5", "Discovery_BI-4.5", "Downgrade_BI-4.4",
    "Kosovo_1v1_BI-4.3", "Patches_BI-4.5", "River_Crossing_2023_v2_BI-4.5",
    "Fairyland_BI-4.5", "Taiga_Vortex_v2_BI-4.5",
    "Abendland_2v2_BI-4.5", "Abendland_4v4_BI-4.5",
]


def _font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
              "C:\\Windows\\Fonts\\arial.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def convert(src, richness, outdir, valid):
    cmc.RESOURCE_RICHNESS = richness
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, os.path.basename(src))
    rpt = cmc.Report()
    ok = cmc.convert_map(src, out, rpt, curve=cmc.BAND_CURVE, keep_palettes=False,
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


def render(src, name, richness, outdir, valid):
    out = convert(src, richness, "/tmp/render_conv", valid)
    if not out:
        print("  convert failed: %s r=%s" % (name, richness))
        return
    mb, spawns, nodes = load(out)
    sym_names = "+".join(n for n, _ in cmc.detect_symmetries(
        spawns, [{"x": x, "y": y} for _, x, y in nodes])[0]) or "none"
    W, H = mb.width, mb.height
    img = Image.new("RGB", (W * SCALE, H * SCALE + PANEL_H), (12, 12, 14))
    d = ImageDraw.Draw(img)

    cell_counts = {}
    cx = sum(s[0] for s in spawns) / len(spawns) if spawns else W / 2
    cy = sum(s[1] for s in spawns) / len(spawns) if spawns else H / 2
    match = mismatch = 0
    for col in range(W):
        for row in range(H):
            t = _res(mb, col, row)
            if t in IDX_TIER:
                tier = IDX_TIER[t]
                cell_counts[tier] = cell_counts.get(tier, 0) + 1
                d.rectangle([col * SCALE, row * SCALE,
                             col * SCALE + SCALE - 1, row * SCALE + SCALE - 1],
                            fill=RESOURCE_COLORS[tier])
                mt = _res(mb, round(2 * cx - col), round(2 * cy - row))
                if mt in IDX_TIER:
                    match += (mt == t)
                    mismatch += (mt != t)
    sym = 100.0 * match / (match + mismatch) if (match + mismatch) else 100.0

    # node markers coloured by the field tier they sit in
    node_counts = {}
    incoherent = 0
    for nm, x, y in nodes:
        want = ACTOR_TIER[nm]
        near = {}
        for dc in range(-3, 4):
            for dr in range(-3, 4):
                t = _res(mb, x + dc, y + dr)
                if t in IDX_TIER:
                    near[IDX_TIER[t]] = near.get(IDX_TIER[t], 0) + 1
        shown = max(near, key=near.get) if near else want
        if near and shown != want:
            incoherent += 1
        node_counts[want] = node_counts.get(want, 0) + 1
        px, py = x * SCALE, y * SCALE
        d.rectangle([px - 3, py - 3, px + 3, py + 3],
                    fill=RESOURCE_COLORS[shown], outline=(255, 255, 255))

    # spawns + symmetry centre
    for sx, sy in spawns:
        px, py = sx * SCALE, sy * SCALE
        d.line([px - 4, py - 4, px + 4, py + 4], fill=(255, 255, 255), width=2)
        d.line([px - 4, py + 4, px + 4, py - 4], fill=(255, 255, 255), width=2)
    pcx, pcy = int(cx * SCALE), int(cy * SCALE)
    d.line([pcx - 5, pcy, pcx + 5, pcy], fill=(0, 230, 230), width=1)
    d.line([pcx, pcy - 5, pcx, pcy + 5], fill=(0, 230, 230), width=1)

    # legend (top-left)
    f = _font(13)
    ly = 6
    for tier in TIER_ORDER:
        d.rectangle([6, ly, 22, ly + 11], fill=RESOURCE_COLORS[tier])
        d.text((26, ly - 1), tier, fill=(235, 235, 235), font=f)
        ly += 15

    # stats panel
    y0 = H * SCALE + 6
    cellmix = ", ".join("%s:%d" % (t, cell_counts[t]) for t in TIER_ORDER if t in cell_counts) or "none"
    nodemix = ", ".join("%s:%d" % (t, node_counts[t]) for t in TIER_ORDER if t in node_counts) or "none"
    d.text((8, y0), "%s   RESOURCE_RICHNESS = %s   [%s]" % (name, richness, rr.DISTRIBUTION_MODE), fill=(255, 255, 255), font=_font(15))
    d.text((8, y0 + 22), "cells  " + cellmix, fill=(210, 210, 210), font=f)
    d.text((8, y0 + 40), "nodes  " + nodemix, fill=(210, 210, 210), font=f)
    sym_col = (120, 230, 120) if sym >= 99.5 else (240, 110, 110)
    d.text((8, y0 + 60),
           "symmetry %.1f%%   node-coherence %d/%d   detected: %s" %
           (sym, len(nodes) - incoherent, len(nodes), sym_names),
           fill=sym_col, font=f)

    os.makedirs(outdir, exist_ok=True)
    safe = name.replace(" ", "_")
    img.save(os.path.join(outdir, "%s_richness_%s.png" % (safe, richness)))


def main():
    valid = cmc.load_valid_actors(SCRIPT_DIR)
    outdir = os.path.join(SCRIPT_DIR, "corrected_renders")
    names = sys.argv[1:] or MAPS
    for mp in names:
        src = mp if mp.endswith(".oramap") else os.path.join(SCRIPT_DIR, "maps", mp + ".oramap")
        if not os.path.exists(src):
            print("(skip) %s" % src)
            continue
        label = os.path.basename(src).replace(".oramap", "")
        for r in RICHNESS_VALUES:
            render(src, label, r, outdir, valid)
            print("rendered %s r=%s" % (label, r))


if __name__ == "__main__":
    main()
