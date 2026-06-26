#!/usr/bin/env python3
"""
Extract all unique actors from source .oramap files and count frequencies.
Outputs: actor_inventory.json with counts per actor across all maps.
"""

import json
import os
import re
import zipfile
from collections import Counter
from pathlib import Path


def extract_actors_from_map(map_path):
    """Extract actor names from a single .oramap file."""
    actors = []
    try:
        with zipfile.ZipFile(map_path, 'r') as zf:
            if 'map.yaml' in zf.namelist():
                content = zf.read('map.yaml').decode('utf-8', errors='replace')
                # Parse Actors section
                in_actors = False
                for line in content.split('\n'):
                    # Check for Actors: section start
                    if line.strip() == 'Actors:':
                        in_actors = True
                        continue
                    # Check for section end (new top-level key)
                    if in_actors and line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                        in_actors = False
                        continue
                    # Parse actor entry (one level indented, format: Name: Type)
                    if in_actors and line.startswith('\t') and not line.startswith('\t\t'):
                        match = re.match(r'^\t([A-Za-z0-9_\.\-]+):\s*([A-Za-z0-9_\.\-]+)', line)
                        if match:
                            actor_type = match.group(2)
                            actors.append(actor_type)
    except Exception as e:
        print(f"  Error reading {map_path.name}: {e}")
    return actors


def main():
    maps_dir = Path(__file__).parent / 'maps'
    if not maps_dir.exists():
        print(f"Maps directory not found: {maps_dir}")
        return

    # Find all .oramap files
    map_files = list(maps_dir.glob('*.oramap'))
    print(f"Found {len(map_files)} .oramap files")

    # Collect all actors with their source map
    all_actors = Counter()
    actor_sources = {}  # actor -> list of maps

    for map_path in sorted(map_files):
        print(f"Processing: {map_path.name}")
        actors = extract_actors_from_map(map_path)
        for actor in actors:
            all_actors[actor] += 1
            if actor not in actor_sources:
                actor_sources[actor] = []
            actor_sources[actor].append(map_path.name)

    # Build inventory
    inventory = {
        'total_maps': len(map_files),
        'total_actor_placements': sum(all_actors.values()),
        'unique_actors': len(all_actors),
        'actors': {}
    }

    for actor, count in all_actors.most_common():
        inventory['actors'][actor] = {
            'count': count,
            'maps': actor_sources[actor][:5]  # First 5 maps only (keep file small)
        }

    # Write output
    output_path = Path(__file__).parent / 'actor_inventory.json'
    with open(output_path, 'w') as f:
        json.dump(inventory, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Extracted {inventory['total_actor_placements']} actor placements")
    print(f"Found {inventory['unique_actors']} unique actor types")
    print(f"Output written to: {output_path}")

    # Show top 30 actors by frequency
    print(f"\nTop 30 actors by placement count:")
    for actor, count in all_actors.most_common(30):
        print(f"  {actor}: {count}")


if __name__ == '__main__':
    main()
