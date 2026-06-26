#!/usr/bin/env python3
"""Check specific coordinates in a converted map for tile issues.

CRITICAL COORDINATE SYSTEM DISCOVERY (2026-06-18):
Game/editor coordinates map DIRECTLY to map.bin coordinates.
NO offset conversion needed - use (x, y) as provided.
Column-major cell index: cell = x * height + y
"""

import zipfile
import struct
from pathlib import Path

def get_all_layers_at_coordinate(map_path, x, y):
    """Get all layer data at a specific coordinate from map.bin.
    
    CRITICAL: Game/editor coordinates map DIRECTLY to map.bin coordinates.
    NO offset conversion needed - use (x, y) as provided.
    """
    try:
        with zipfile.ZipFile(map_path, 'r') as zf:
            if 'map.bin' in zf.namelist():
                bin_data = zf.read('map.bin')
                
                fmt = bin_data[0]
                width = struct.unpack_from("<H", bin_data, 1)[0]
                height = struct.unpack_from("<H", bin_data, 3)[0]
                cells = width * height
                
                # Determine offsets based on format
                if fmt == 1:
                    tiles_off = 5
                    heights_off = 0
                    res_off = 5 + cells * 3
                elif fmt == 2:
                    tiles_off = struct.unpack_from("<I", bin_data, 5)[0]
                    heights_off = struct.unpack_from("<I", bin_data, 9)[0]
                    res_off = struct.unpack_from("<I", bin_data, 13)[0]
                else:
                    return None
                
                # Calculate cell index using column-major: cell = col*H + row
                # Use coordinates DIRECTLY as provided (no offset conversion)
                cell_index = x * height + y
                
                # Read tiles layer
                tile_value = struct.unpack_from("<H", bin_data, tiles_off + cell_index * 3)[0]
                tile_index = tile_value & 0xFF
                tile_idx = bin_data[tiles_off + cell_index * 3 + 2]
                
                # Read resource layer
                res_type = bin_data[res_off + cell_index * 2]
                res_density = bin_data[res_off + cell_index * 2 + 1]
                
                # Check if heights layer exists
                height_data = None
                if heights_off > 0 and heights_off + cell_index < len(bin_data):
                    height_data = bin_data[heights_off + cell_index]
                
                return {
                    'format': fmt,
                    'tile_value': tile_value,
                    'tile_index': tile_index,
                    'tile_idx': tile_idx,
                    'res_type': res_type,
                    'res_density': res_density,
                    'height_data': height_data
                }
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == '__main__':
    base_dir = Path(__file__).parent
    original_cow = base_dir / 'maps' / 'Cow_Level_1v1_BI-4.3.oramap'
    
    print("=== COORDINATE SYSTEM VERIFICATION ===")
    print("Using DIRECT coordinate mapping: Game (x,y) -> map.bin (x, y)")
    print("=" * 60)
    
    # Test coordinates the user mentioned
    test_coords = [(80,79), (80,78), (81,78), (82,79)]
    
    print("\nORIGINAL COW MAP:")
    for x, y in test_coords:
        layer_data = get_all_layers_at_coordinate(original_cow, x, y)
        if layer_data:
            print(f"Game ({x},{y}) -> map.bin ({x},{y}): template={layer_data['tile_index']}")
        else:
            print(f"Game ({x},{y}) -> map.bin ({x},{y}): NOT FOUND")