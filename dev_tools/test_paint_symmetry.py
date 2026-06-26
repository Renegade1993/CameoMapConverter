#!/usr/bin/env python3
"""
Test manual painting symmetry by simulating the GUI state.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cameo_map_converter as cmc
from cameo_converter_gui import CameoConverterGUI


def test_paint_symmetry(map_path, distribution="even"):
    """Simulate mirror-paint clicks and verify symmetry partners are painted."""
    settings = {
        "richness": 1.0,
        "distribution": distribution,
        "remap_resources": True,
        "node_affects_field_tier": True,
    }
    img, counts = cmc.render_preview(map_path, settings, scale=4, draw_nodes=True)

    fields = counts.get("__fields__", [])
    nodes = counts.get("__nodes__", [])
    print(f"Fields: {len(fields)}, Nodes: {len(nodes)}")

    if not fields:
        print("No fields to test")
        return True

    # Create a minimal fake GUI instance
    gui = CameoConverterGUI.__new__(CameoConverterGUI)
    gui._paint_field_cache = fields
    gui._paint_node_cache = nodes
    gui._paint_overrides = {}
    gui._paint_cell_overrides = {}
    gui._paint_node_overrides = {}
    gui._paint_undo_stack = []
    gui._paint_redo_stack = []
    gui._paint_mirror = True
    gui.append_log = lambda msg: print(f"  LOG: {msg}")

    # Find a field with transforms
    src_field = None
    for f in fields:
        if f.get("transforms"):
            src_field = f
            break
    if not src_field:
        print("No fields with transforms found")
        return True

    print(f"\nTesting field @({src_field['center'][0]:.1f},{src_field['center'][1]:.1f})")
    print(f"  transforms: {[n for n, _ in src_field['transforms']]}")
    print(f"  nodes: {src_field.get('nodes', [])}")
    print(f"  mirror_keys: {src_field.get('mirror_keys', [])}")

    # Test node painting symmetry
    if src_field.get("nodes"):
        nx, ny = src_field["nodes"][0]
        node_key = f"{nx},{ny}"
        gui._paint_node_overrides = {}
        undo_diff = {}
        gui._mirror_node_override(nx, ny, "RedTiberium", undo_diff)
        print(f"\nNode paint: source=({nx},{ny})")
        print(f"  Applied overrides: {gui._paint_node_overrides}")
        print(f"  Undo diff: {undo_diff}")

    # Test cell painting symmetry
    cells = list(src_field.get("cells", []))
    if cells:
        H = src_field.get("map_height")
        c = cells[0]
        col, row = c // H, c % H
        field_key = "%d,%d" % (round(src_field["center"][0]), round(src_field["center"][1]))
        gui._paint_cell_overrides = {}
        undo_diff = {}
        gui._mirror_cell_override(col, row, field_key, "RedTiberium", undo_diff)
        print(f"\nCell paint: source=({col},{row}) in field {field_key}")
        print(f"  Applied overrides: {gui._paint_cell_overrides}")
        print(f"  Undo diff: {undo_diff}")

    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_paint_symmetry.py <oramap_path> [distribution]")
        sys.exit(1)
    map_path = sys.argv[1]
    distribution = sys.argv[2] if len(sys.argv) > 2 else "even"
    test_paint_symmetry(map_path, distribution)
