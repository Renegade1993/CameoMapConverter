#!/usr/bin/env python3
"""
Test symmetry detection on all available maps.
"""
import sys
import os
import glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cameo_map_converter as cmc


def test_all_maps(maps_dir="maps", distribution="even"):
    """Run symmetry detection and report for all maps."""
    pattern = os.path.join(maps_dir, "*.oramap")
    maps = sorted(glob.glob(pattern))
    
    for map_path in maps:
        if "converted" in map_path:
            continue
        try:
            settings = {
                "richness": 1.0,
                "distribution": distribution,
                "remap_resources": True,
                "node_affects_field_tier": True,
            }
            img, counts = cmc.render_preview(map_path, settings, scale=4, draw_nodes=True)
            
            fields = counts.get("__fields__", [])
            nodes = counts.get("__nodes__", [])
            
            # Get unique transform names
            transform_names = set()
            for f in fields:
                for name, _ in f.get("transforms", []):
                    transform_names.add(name)
            
            # Symmetry groups
            sym_groups = set()
            for f in fields:
                sym_groups.add(tuple(sorted(f.get("mirror_keys", []))))
            
            map_name = os.path.basename(map_path)
            print(f"{map_name}: {len(fields)} fields, {len(nodes)} nodes, transforms={sorted(transform_names)}, groups={len(sym_groups)}")
        except Exception as e:
            print(f"{os.path.basename(map_path)}: ERROR - {e}")


if __name__ == "__main__":
    distribution = sys.argv[1] if len(sys.argv) > 1 else "even"
    test_all_maps(distribution=distribution)
