#!/usr/bin/env python3
"""Analyze resource distribution around spawn points."""

import zipfile
import struct
import re
from pathlib import Path

def analyze_resource_distribution(map_path):
    """Analyze resource distribution around spawn points."""
    try:
        with zipfile.ZipFile(map_path, 'r') as zf:
            if 'map.yaml' in zf.namelist() and 'map.bin' in zf.namelist():
                yaml_content = zf.read('map.yaml').decode('utf-8', errors='replace')
                bin_data = zf.read('map.bin')
                
                # Find spawn points
                spawns = []
                for line in yaml_content.split('\n'):
                    match = re.match(r'\s+([A-Za-z0-9_]+):\s*mpspawn', line)
                    if match:
                        actor_name = match.group(1)
                        # Find Location for this actor
                        pattern = actor_name + ':.*?Location:\\s*(\\d+)\\s*,\\s*(\\d+)'
                        loc_match = re.search(pattern, yaml_content, re.DOTALL)
                        if loc_match:
                            spawns.append((int(loc_match.group(1)), int(loc_match.group(2))))
                
                # Read resource data
                fmt = bin_data[0]
                width = struct.unpack_from("<H", bin_data, 1)[0]
                height = struct.unpack_from("<H", bin_data, 3)[0]
                cells = width * height
                
                if fmt == 1:
                    res_off = 5 + cells * 3
                elif fmt == 2:
                    res_off = struct.unpack_from("<I", bin_data, 13)[0]
                
                # Collect resource locations by type
                resources = {1: [], 2: [], 3: [], 4: [], 5: [], 6: []}  # Different resource types
                
                for i in range(cells):
                    res_type = bin_data[res_off + i * 2]
                    if res_type in resources:
                        col, row = i // height, i % height
                        resources[res_type].append((col, row))
                
                return spawns, resources
    except Exception as e:
        print(f"Error: {e}")
        return [], {}

def calculate_distances(spawns, resources):
    """Calculate distances from spawn points to resources."""
    resource_names = {
        1: "Resource Type 1",
        2: "Resource Type 2", 
        3: "Resource Type 3",
        4: "Resource Type 4",
        5: "Resource Type 5",
        6: "Resource Type 6"
    }
    
    for spawn_idx, (sx, sy) in enumerate(spawns):
        print(f"\n=== Spawn {spawn_idx + 1} at ({sx}, {sy}) ===")
        for res_type, locations in resources.items():
            if locations:
                distances = []
                for (rx, ry) in locations:
                    # Convert to 0-based for distance calc
                    dist = ((rx - (sx-1))**2 + (ry - (sy-1))**2)**0.5
                    distances.append(dist)
                
                if distances:
                    distances.sort()
                    print(f"{resource_names[res_type]}: {len(locations)} instances")
                    print(f"  Closest: {distances[0]:.1f} cells")
                    print(f"  Average: {sum(distances)/len(distances):.1f} cells")
                    print(f"  Farthest: {distances[-1]:.1f} cells")

if __name__ == '__main__':
    base_dir = Path(__file__).parent
    cow_level = base_dir / 'maps' / 'converted' / 'Cow_Level_1v1_BI-4.3.oramap'
    
    print("=== COW LEVEL RESOURCE DISTRIBUTION ANALYSIS ===")
    print("=" * 60)
    
    spawns, resources = analyze_resource_distribution(cow_level)
    
    print(f"\nFound {len(spawns)} spawn points:")
    for i, (sx, sy) in enumerate(spawns):
        print(f"  Spawn {i+1}: ({sx}, {sy})")
    
    print(f"\nResource distribution:")
    for res_type, locations in resources.items():
        if locations:
            print(f"  Type {res_type}: {len(locations)} instances")
    
    calculate_distances(spawns, resources)