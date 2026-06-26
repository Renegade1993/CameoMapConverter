#!/usr/bin/env python3
"""
Test symmetry detection and field metadata for manual painting.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cameo_map_converter as cmc


def test_symmetry(map_path, distribution="even"):
    """Run symmetry detection and report field metadata."""
    settings = {
        "richness": 1.0,
        "distribution": distribution,
        "remap_resources": True,
        "node_affects_field_tier": True,
    }
    img, counts = cmc.render_preview(map_path, settings, scale=4, draw_nodes=True)

    fields = counts.get("__fields__", [])
    nodes = counts.get("__nodes__", [])
    print(f"Map: {map_path}")
    print(f"Distribution: {distribution}")
    print(f"Fields: {len(fields)}")
    print(f"Nodes: {len(nodes)}")

    if not fields:
        print("No fields found!")
        return

    # Check first field structure
    f0 = fields[0]
    print(f"\nFirst field keys: {list(f0.keys())}")
    print(f"First field nodes: {len(f0.get('nodes', []))}")
    print(f"First field transforms: {len(f0.get('transforms', []))}")
    print(f"First field mirror_keys: {len(f0.get('mirror_keys', []))}")

    if f0.get("transforms"):
        for name, T in f0["transforms"]:
            print(f"  Transform: {name}")

    # Check that all nodes are assigned to some field
    field_nodes = sum(len(f.get("nodes", [])) for f in fields)
    print(f"\nTotal field nodes assigned: {field_nodes} / {len(nodes)}")

    # Check symmetry groups
    sym_groups = set()
    for f in fields:
        sym_groups.add(tuple(sorted(f.get("mirror_keys", []))))
    print(f"\nSymmetry groups: {len(sym_groups)}")
    for i, grp in enumerate(sym_groups):
        print(f"  Group {i}: {len(grp)} fields")

    # Test a transform on a field center
    if f0.get("transforms"):
        cx, cy = f0["center"]
        print(f"\nField center: ({cx:.1f}, {cy:.1f})")
        for name, T in f0["transforms"]:
            tx, ty = T(cx, cy)
            print(f"  {name}: ({tx:.1f}, {ty:.1f})")

    # Check that transforms are consistent across all fields
    print("\nTransform consistency:")
    for f in fields:
        if f.get("transforms"):
            names = [name for name, _ in f["transforms"]]
            print(f"  Field @({f['center'][0]:.1f},{f['center'][1]:.1f}): {names}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_symmetry.py <oramap_path> [distribution]")
        sys.exit(1)
    map_path = sys.argv[1]
    distribution = sys.argv[2] if len(sys.argv) > 2 else "even"
    test_symmetry(map_path, distribution)
