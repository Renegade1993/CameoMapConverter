#!/usr/bin/env python3
"""
Detailed verification of node cells vs surrounding field types.
"""
import sys
import zipfile
import struct

# Cameo resource indices
CAMEO_RES_INDEX = {
    "Tiberium": 1,
    "BlueTiberium": 2,
    "Ore": 3,
    "Gems": 4,
    "RedTiberium": 5,
    "GoldTiberium": 6,
}

def detailed_node_check(oramap_path):
    """Check node cells vs surrounding field types in detail."""
    with zipfile.ZipFile(oramap_path) as z:
        # Read map.yaml
        with z.open("map.yaml") as f:
            map_yaml = f.read().decode('utf-8')
        
        # Parse node positions
        import re
        seeds = []
        lines = map_yaml.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('Actor') and ':' in line:
                actor_name = line.split(':')[1].strip().lower()
                if any(x in actor_name for x in ['mine', 'split', 'gmine']):
                    # Look for Location
                    j = i + 1
                    while j < len(lines) and j < i + 10:
                        if 'Location:' in lines[j]:
                            loc_match = re.search(r'Location:\s*(\d+),(\d+)', lines[j])
                            if loc_match:
                                x = int(loc_match.group(1))
                                y = int(loc_match.group(2))
                                seeds.append({
                                    "name": actor_name,
                                    "x": x,
                                    "y": y,
                                })
                            break
                        j += 1
            i += 1
        
        # Read map.bin
        with z.open("map.bin") as f:
            map_bin = f.read()
        
        # Parse header
        width = struct.unpack('<H', map_bin[1:3])[0]
        height = struct.unpack('<H', map_bin[3:5])[0]
        resources_offset = 17 + width * height * 3  # Format 2
        
        print(f"Map size: {width}x{height}")
        print(f"Found {len(seeds)} resource nodes\n")
        
        # Check each node
        RES_BY_IDX = {v: k for k, v in CAMEO_RES_INDEX.items()}
        mismatches = []
        
        for node in seeds:
            x, y = node["x"], node["y"]
            cell = x * height + y
            res_offset = resources_offset + cell * 2
            node_res_type = map_bin[res_offset]
            node_res_name = RES_BY_IDX.get(node_res_type, "Unknown")
            
            # Find surrounding field type
            best = None
            bres = None
            for dcol in range(-5, 6):
                for drow in range(-5, 6):
                    if dcol == 0 and drow == 0:
                        continue
                    ncol, nrow = x + dcol, y + drow
                    if 0 <= ncol < width and 0 <= nrow < height:
                        ncell = ncol * height + nrow
                        nres_offset = resources_offset + ncell * 2
                        nidx = map_bin[nres_offset]
                        if nidx in RES_BY_IDX:
                            d = dcol * dcol + drow * drow
                            if best is None or d < best:
                                best, bres = d, RES_BY_IDX[nidx]
            
            field_res_name = bres if bres else "Unknown"
            
            match = "OK" if node_res_name == field_res_name else "BAD"
            print(f"{match} {node['name']:15} at ({x:3},{y:3}): node={node_res_name:15} field={field_res_name:15}")
            
            if node_res_name != field_res_name:
                mismatches.append(node)
        
        print(f"\nMismatches: {len(mismatches)}/{len(seeds)}")
        return len(mismatches) == 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python detailed_node_check.py <oramap_path>")
        sys.exit(1)
    
    oramap_path = sys.argv[1]
    success = detailed_node_check(oramap_path)
    sys.exit(0 if success else 1)
