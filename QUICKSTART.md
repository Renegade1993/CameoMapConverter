# Cameo Map Converter - Quick Start Guide

Get a Balance Iteration 4.3-4.6 OpenRA map into the Cameo mod in a few clicks.

## Run the converter

1. Put your `.oramap` files in the `maps\` folder.
2. Double-click **Convert Maps.cmd** (Windows) or run:
   ```bash
   python cameo_map_converter.py maps/
   ```
3. Converted maps appear in `maps\converted\`.

## Use the GUI

1. Run `CameoMapConverter.exe`.
2. Select the folder containing your `.oramap` files.
3. Adjust the **Richness** slider:
   - `0.5` = mostly Ore
   - `1.0` = balanced, no Gems (default)
   - `1.5` = mostly Gems
4. Choose a **Distribution**:
   - **balance** = richer resources toward the contested middle (default)
   - **distance** = richest resources on the outer edges
   - **even** = equal amounts of every active resource type
5. Click **Convert Maps** or **Convert All**.

## Hand-paint resources

1. Click **Paint Mode** to turn it on.
2. Click a resource type in the legend (e.g., Green Tiberium).
3. Click a resource cell in the preview to repaint that cell (mirrored cells too if symmetry is on).
4. Drag a box to repaint all cells inside the box.
5. Paint overrides are included in the next conversion automatically.

## Density levels

When painting, choose a density:
- **Replace** = keep the source density byte
- **Random** = random level 1-5 for every cell in the stroke
- **1-5** = uniform density across the stroke

Lower levels (1-2) show mostly the brown "oyster" stage; higher levels show more crystals.

## Install converted maps

Copy the contents of `maps\converted\` into:
```
%USERPROFILE%\Documents\OpenRA\maps\cameo\<version>\
```
Delete older copies of the same map there, or the editor may load a stale version.

## Quick CLI examples

```bash
python cameo_map_converter.py map.oramap
python cameo_map_converter.py maps/ -o output/ --richness 1.0
python cameo_map_converter.py maps/ --distribution distance
python cameo_map_converter.py maps/ --keep-decorations
python cameo_map_converter.py maps/ --dry-run
```

## Need more detail?

See `README.md` for the full manual (including release notes).
