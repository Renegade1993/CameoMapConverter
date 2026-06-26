#!/usr/bin/env python3
"""Compare actors in original vs converted map."""

import zipfile
import re
from collections import Counter
from pathlib import Path

def extract_actors(map_path):
    """Extract actor types from an oramap file."""
    actors = Counter()
    try:
        with zipfile.ZipFile(map_path, 'r') as zf:
            if 'map.yaml' in zf.namelist():
                content = zf.read('map.yaml').decode('utf-8', errors='replace')
                # Parse Actors section
                in_actors = False
                for line in content.split('\n'):
                    if line.strip() == 'Actors:':
                        in_actors = True
                        continue
                    if in_actors and line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                        in_actors = False
                        continue
                    if in_actors and line.startswith('\t') and not line.startswith('\t\t'):
                        match = re.match(r'^\t([A-Za-z0-9_\.\-]+):\s*([A-Za-z0-9_\.\-]+)', line)
                        if match:
                            actors[match.group(2)] += 1
    except Exception as e:
        print(f"Error: {e}")
    return actors

base_dir = Path(__file__).parent
original = base_dir / 'maps' / 'Dash_BI-4.5.oramap'
converted = base_dir / 'maps' / 'converted_test' / 'Dash_BI-4.5.oramap'

print("=" * 60)
print("DASH_BI-4.5 Actor Comparison")
print("=" * 60)

orig_actors = extract_actors(original)
conv_actors = extract_actors(converted)

print(f"\nOriginal: {sum(orig_actors.values())} placements, {len(orig_actors)} unique")
print(f"Converted: {sum(conv_actors.values())} placements, {len(conv_actors)} unique")

print("\n--- Top 20 actors in ORIGINAL ---")
for actor, count in orig_actors.most_common(20):
    print(f"  {actor}: {count}")

print("\n--- Top 20 actors in CONVERTED ---")
for actor, count in conv_actors.most_common(20):
    print(f"  {actor}: {count}")

print("\n--- Actors that CHANGED ---")
all_actors = set(orig_actors.keys()) | set(conv_actors.keys())
changes = []
for actor in sorted(all_actors):
    orig_count = orig_actors.get(actor, 0)
    conv_count = conv_actors.get(actor, 0)
    if orig_count != conv_count:
        changes.append((actor, orig_count, conv_count))

for actor, orig, conv in changes[:30]:
    if orig == 0:
        print(f"  + ADDED: {actor}: {conv}")
    elif conv == 0:
        print(f"  - DROPPED: {actor}: {orig}")
    else:
        print(f"  ~ CHANGED: {actor}: {orig} -> {conv}")

if len(changes) > 30:
    print(f"  ... and {len(changes) - 30} more changes")
