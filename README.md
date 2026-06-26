<p align="center">
  <img src="Icon/cmc.png" alt="Cameo Map Converter icon" width="128" height="128">
</p>

# Cameo Map Converter

Automates onboarding OpenRA maps from the **Balance Iteration 4.3-4.6 era** into the Cameo mod.
Each `.oramap` is rewritten to load cleanly in Cameo; originals are never modified.

> **New to the tool?** See `QUICKSTART.md` for the fast getting-started guide.
> **Scope:** This tool is specifically designed for maps from the Balance Iteration 4.3-4.6 era of OpenRA.
> It may not work correctly with maps from other eras or different mod configurations.

## Quick start

Windows: drop maps into `maps\` and double-click **Convert Maps.cmd** (output in `maps\converted`),
or drag a `.oramap` / folder onto it.

```bash
python cameo_map_converter.py <file-or-folder>
python cameo_map_converter.py <folder> -o <out> --richness 1.0
python cameo_map_converter.py <folder> --distribution distance   # richest on the outer edges
python cameo_map_converter.py <folder> --distribution even       # equal cell counts per active type
python cameo_map_converter.py <folder> --balance-bias 0.5        # ease rich resources back toward edges
python cameo_map_converter.py <folder> --no-remove-actors        # keep rocks/stones (wrong colors, preserved geometry)
python cameo_map_converter.py <folder> --keep-decorations        # don't drop/remap actors
python cameo_map_converter.py <folder> --keep-palettes
python cameo_map_converter.py <folder> --dry-run
```

## Installation

The release package is self-contained: double-click `CameoMapConverter.exe` or `Convert Maps.cmd`.

For the source version:

- Python 3.7 or higher
- Required packages (install via pip):
  - `PyYAML` — configuration file support
  - `Pillow` — preview rendering (optional)
- Ensure `cameo_actors.txt` is in the same directory as the scripts.
- Optional: `pip install pyyaml pillow`

## What the converter does to each .oramap

1. **Header** — `RequiresMod` ra→cameo; tileset remapped (TEMPERAT→RA_TEMPERAT, etc.);
   `Categories`→Tournament; removes `LockPreview`; strips a trailing `[BI-x.x]` title tag.
2. **Strips** BI custom rules/sequences/weapons/voices/notifications and bundled files.
3. **Palettes** — drops custom palettes by default (Cameo already defines the standard ones;
   re-defining them crashes the game). `--keep-palettes` to keep them.
4. **Actors** — every placed actor is checked against Cameo's actor list (`cameo_actors.txt`).
   Actors Cameo has are KEPT; actors it lacks are REMAPPED to a same-footprint
   Cameo actor when one exists, else DROPPED. This eliminates the "Actor … of unknown type" crash.
   Edit `ACTOR_OVERRIDES` in `cameo_map_converter.py` to override, or inspect `actor_matrix.yaml`
   for the current translation rules.
5. **Resources** — re-tiered by distance from the nearest spawn, with a single `--richness` knob,
   and guaranteed symmetric across the map's mirror axis (see below).
6. **Repackages** a clean `.oramap` with a fresh `map.png` preview.

## Resource configuration

### The RESOURCE_RICHNESS knob

Resource value is driven by each node's distance to its **nearest** spawn (so one player's base ore is
never weighed against another player's rim). Tier order, cheapest → richest:
**Ore → Tiberium → BlueTiberium → RedTiberium → GoldTiberium → Gems.**

`--richness` (default `1.0`) is the one tuning knob:

| richness | result |
|----------|--------|
| **0.5**  | essentially all Ore |
| **1.0**  | even spread Ore → GoldTiberium, **zero gems** |
| **1.5**  | essentially all Gems |

Smooth and monotonic between; it saturates past ~0.5 and ~1.5. Gems only appear above 1.0.

**Symmetry is guaranteed.** The converter detects the map's symmetry from the spawn/node geometry,
groups mirror-paired (and rotational) nodes into orbits, and tiers each orbit by its *average*
distance — so mirror-paired resource fields always get the **same** tier even on a hand-built,
slightly-imperfect map. Each field is painted one tier, and each node actor conforms to the field it
sits in (an ore mine is always in ore, a gem mine always in gems).

## Distribution mode (`--distribution distance | balance | even`)

Three philosophies for *where* the value sits — all fully symmetric, all obeying the richness knob:

- **`balance`** (default): value = **distance-gated contestedness**. Each spawn projects an influence
  heatmap (linear falloff over a radius scaled to the map); a node's contestedness is the *overlap* of
  those zones (high in the space **between** bases). That contest term is *added on top of* the plain
  distance baseline but **gated by a home zone**, so it can't light up right next to a spawn:
  `value = dn + balance-bias · contest · home_gate`, where `dn` is the normalized nearest-spawn distance
  and `home_gate` ramps 0→1 from the home radius out to twice it. The result is a gradient: ore at base →
  green/blue tiberium through the mid ground → gold reserved for the far contested strips you must leave
  base to reach.
  `--balance-bias` (default `3`) sets the contest pull strength: `0` acts like plain `distance`, higher
  pulls the rich tiers harder into the contested middle. `--balance-home-radius` (default `15` grid cells)
  sizes the safe home zone; resources inside it stay low-tier no matter how contested.
- **`distance`**: value rises with distance from the nearest spawn, so the richest resources land on
  the **outer** parts of the map (farthest from any base).
- **`even`**: position-agnostic. Resource types are assigned to node orbits (symmetry-aware) so that
  every active type accounts for roughly **equal cell counts** across the whole map. Large fields and
  small fields are balanced against each other. The richness knob still controls which types are active
  (r=0.5 → all Ore, r=1.5 → all Gems). Good for maps where strategic positioning should not affect
  which resources you encounter.

Contiguous resource fields are kept a single type; when several nodes are tied for closest to one
field the **richest** wins, so a contested blob keeps its top tier. The node tiering lives in
`resource_reclassification.py`.

## Advanced configuration

You can customize behaviour with a configuration file:

```bash
python cameo_map_converter.py maps/ --config converter_config.yaml
```

Supported formats: YAML (.yaml, .yml) and JSON (.json). See `converter_config.yaml` for all available
options: resource settings, palette handling, file handling, actor handling, tileset mappings, and logging.

### Command-line options

```
python cameo_map_converter.py <input> [options]

Arguments:
  input              .oramap file or folder of .oramap files

Options:
  -o, --outdir DIR      Output directory (default: input/converted)
  --richness FLOAT      RESOURCE_RICHNESS knob (0.0-2.0, default: 1.0)
  --distribution MODE   Resource distribution: distance, balance, or even (default: balance)
  --balance-bias FLOAT  Balance mode contest pull strength (default: 3)
  --balance-home-radius FLOAT  Balance mode home zone radius (default: 15)
  --no-remove-actors    Keep rock/stone actors (wrong colors, but geometry preserved)
  --keep-palettes       Keep custom palettes instead of dropping them
  --keep-decorations    Don't drop/remap actors Cameo lacks
  --dry-run             Show what would be done without writing files
  --no-render           Don't write resource-preview PNG files
  --no-remap-resources  Pass resources through 1:1 without the tiering algorithm
  --config FILE         Load configuration from YAML or JSON file
  --dump-actors DIR     Print valid Cameo actor names from rules directory
```

## Actor removal toggle

By default the converter **drops** rock and stone actors because Cameo's rock assets use `.des`
(desert) palette files that render incorrectly on the RA temperate tileset. Pass
`--no-remove-actors` (or uncheck **"Remove Problematic Actors"** in the GUI) to keep them — the
geometry is preserved but the colors will be wrong until the Cameo team fixes the palette mismatch.

Bushes and other decorative actors with no defensible Cameo equivalent are **always dropped**,
regardless of the toggle. The GUI exposes this as the **"Remove Problematic Actors"** checkbox
(on by default).

## GUI-only features

The GUI has three features not available from the CLI:

- **Preset save/load** — save the current resource settings as a named preset (`Save Preset…`), recall
  it later from the dropdown. Presets survive restarts and are stored in `presets.json` next to the exe.
  To delete, select the preset and click `Delete`.
- **Hand-paint mode** — click **Paint Mode: ON**, select a resource type, then click any resource cell on the
  live preview to override it. Undo/Redo and Clear Overrides are supported. Overrides persist
  across preview refreshes and are applied on top of the algorithmic assignment. They are **not**
  saved to the output file automatically — use the convert button after painting to bake the result.
  - A single click paints the cell under the cursor (and its symmetry mirrors, if enabled).
  - Drag a box to repaint all cells inside the box.
  - Use the **Density** dropdown next to the paint controls to set the resource density for the next stroke:
    - **Replace** keeps the existing density byte.
    - **Random** assigns a random level 1–5 independently to every cell in the stroke.
    - **1–5** writes a uniform density proportional to the tier's maximum.
  - When you paint with any density other than **Replace**, the converter automatically adds a map rule
    that disables OpenRA/Cameo's `ResourceLayer` density recalculation, so the painted density is preserved.
  - Paint overrides reset when you navigate to a different map or restart the GUI.
  - Mirror painting is enabled by default: when you click a cell or node, the converter detects the map's
    symmetry and paints the corresponding mirror partners at the same time.

## Output files

- **Converted maps** — `maps/converted/` (or the specified output directory), `.oramap` ZIP archives
  containing transformed `map.yaml`, `map.bin`, fresh `map.png`, and essential assets.
- **Conversion reports** — printed to console and GUI, showing spawn points, resource field counts,
  template/actor remapping statistics, and warnings/errors.
:
- **Logs** — written to `log/` next to the converter only when you enable them in the GUI or with
  `--log-file` / `--log-level` on the CLI. File names are `all.log`, `debug.log`, `info.log`, `warning.log`,
  `error.log`. Logs rotate at 10 MB with up to 5 backups per type. All file logging is OFF by default.

## Validate + visualize

```bash
python validate_resource_distribution.py        # pass/fail on the painted map.bin across test maps
python render_corrected_distribution.py          # PNGs in corrected_renders/ (knob sweep + symmetry)
```

`validate_resource_distribution.py` asserts, on the final painted output: the knob targets, 100%
mirror symmetry of painted tiers, and node/field colour coherence. The renderer converts in-process at
richness 0.5 / 1.0 / 1.5 and overlays tier-coloured node markers, spawns, the symmetry centre, and live
stats.

## Install converted maps

- After converting, copy `maps\converted\` into Cameo's maps folder
  (`%USERPROFILE%\Documents\OpenRA\maps\cameo\<version>\`) and delete older copies of the same maps,
  or the editor may load a stale version.
- `cameo_actors.txt` MUST sit next to the script — it is Cameo's actor list. Regenerate when Cameo
  updates: `python cameo_map_converter.py --dump-actors <…>\mods\cameo\rules > cameo_actors.txt`

## Troubleshooting

### "Actor … of unknown type" crash in OpenRA

**Cause:** Map contains actors not defined in Cameo's rules.

**Solution:**
1. Ensure `cameo_actors.txt` is up to date.
2. Regenerate with: `python cameo_map_converter.py --dump-actors <cameo-rules-dir> > cameo_actors.txt`
3. Check `ACTOR_OVERRIDES` in `cameo_map_converter.py` for custom mappings.

### Map loads but looks wrong (missing terrain, wrong colors)

**Cause:** Tileset template remapping issues.

**Solution:**
1. Check the conversion report for template remapping statistics.
2. Verify `template_matrix.yaml` exists and is valid.
3. Some CA-specific templates may not have direct Cameo equivalents.

### Resources not appearing as expected

**Solution:**
1. Try different `--richness` values.
2. Use the GUI preview to see the actual distribution.
3. Verify the source map has resource nodes (mines/gmines).
4. Try different distribution modes (`distance` vs `balance`).

### Need to collect diagnostic logs

1. Enable logging via the **Logging** menu (enable INFO and ERROR at minimum).
2. Reproduce the issue.
3. Click **Logging → Open Log Directory**.
4. Zip the relevant log files.
5. Include the zip with your support request.
6. Disable logging afterward to prevent disk bloat.

### "Python not found" error (Windows)

**Cause:** Python not in system PATH or using the Windows Store alias.

**Solution:** Install Python from python.org, add it to PATH during installation, or use the
compiled executable instead.

### GUI won't start

**Cause:** Missing PyQt5.

**Solution:** `pip install PyQt5` — or use the compiled executable, which bundles it.

### Conversion fails with "map.bin too short"

**Cause:** Corrupted or invalid map.bin.

**Solution:**
1. Verify the source `.oramap` opens in the OpenRA map editor.
2. Re-download the map if it may be corrupted.
3. Ensure the map uses a supported map.bin format (Format 1 or 2).

## Best practices

1. Always back up original maps before conversion.
2. Test converted maps in OpenRA before distribution.
3. Use the GUI preview to verify distribution before batch conversion.
4. Start with default settings (richness=1.0, distribution=balance).
5. Keep `cameo_actors.txt` updated when the Cameo mod updates.
6. Use configuration files for consistent settings across projects.

## Repository layout

```
cameo_map_converter.py            main converter (CLI)
cameo_converter_gui.py              PyQt5 GUI wrapper
resource_reclassification.py        symmetry-aware resource tiering
water_crossing_detect.py            water-crossing detection
validate_resource_distribution.py   painted-map pass/fail validator
render_corrected_distribution.py    visual diagnostic renderer
minimap_render.py                   in-process minimap renderer
actor_matrix.yaml / template_matrix.yaml / cameo_actors.txt        data
Convert Maps.cmd                    Windows launcher
maps/                               source .oramap files
corrected_renders/                  rendered distribution previews
docs/                               CODEBASE_REFERENCE.md, DEVELOPER_NOTES.md
README.md                           this comprehensive manual (includes release notes)
QUICKSTART.md                       fast getting-started guide
```

## Version information

- Converter Version: v0.76-beta-hotfix1
- Resource Algorithm: v14 (locked, do not modify)
- Supported Map Formats: OpenRA .oramap (Format 1 and 2)
- Target Mod: Cameo playtest-20260614 and later

## License and distribution

This converter is provided as-is for use with the Cameo mod. Ensure you have appropriate rights to
convert and distribute any maps you process.

## Credits

**Cameo Map Converter** was built by and for the OpenRA/Cameo community.

| Role | Name |
|------|------|
| Tool author | **Kmoney** — designed and built CMC using [Devin AI](https://devin.ai) and [Claude](https://claude.ai) (Anthropic) as AI development partners |
| Inspiration & design input | **Aedis** — whose tournament maps and resource-balance vision drove the core design; the "even distribution" mode is directly his prime directive |
| Application icon | **zhall** — created and donated the official CMC icon (`Icon/cmc.ico`) |

> Icon (`Icon/cmc.ico`) © zhall — used with permission. All rights reserved by the original author.

---

# Release Notes

## Cameo Map Converter v0.76-beta-hotfix1 — Internal Beta Hotfix

Release date: 2026-06-25

### Fixes in v0.76-beta-hotfix1

- Fixed a Python DLL conflict when running the bundled executable on machines with a newer system Python installed (e.g. Python 3.14 from the new Python Install Manager). The conversion subprocess now stays inside the bundled Python 3.12 runtime instead of launching a system Python interpreter that would load incompatible PyInstaller C extension modules from the `_MEI` temp directory.
- Added a PyInstaller runtime hook (`pyi_rth_cameo_isolation.py`) that clears `PYTHONPATH`, `PYTHONHOME`, and other Python environment variables and locks `sys.path` to the bundle directory, preventing the bundled runtime from accidentally picking up a system Python stdlib.
- Added a dispatch guard in the GUI entry point so the frozen executable can re-run the bundled `cameo_map_converter.py` script as a subprocess without launching the GUI again.
- Disabled UPX compression in the PyInstaller build for improved DLL reliability on newer Windows/Python combinations.

## Cameo Map Converter v0.76-beta — Internal Beta

Release date: 2026-06-24

### Highlights

- Converts OpenRA maps from Balance Iteration 4.3-4.6 era to the Cameo mod format
- Symmetry-aware resource tiering with a balance guarantee
- Configurable richness (0.5-1.5) and distribution mode (balance/distance/even)
- GUI with live preview, converted-preview, plus command-line and batch modes
- Unified console + GUI logging (optional, off by default; writes to `log/` when enabled)
- Hand-paint resource cells, fields, and nodes with automatic symmetry mirroring
- Density levels (Replace/Random/1-5) for hand-painted resources
- Self-contained: no external dependencies or installation required

### Fixes in v0.76-beta

- Density dropdown is now fully wired through the paint pipeline: painted cells and fields write the selected density level to `map.bin` instead of preserving the source map's varying densities.
- Tooltips on previously-converted maps (`remap_resources` off) now report the painted resource type, not the original source type.
- Field-level paint overrides are now applied even when `remap_resources` is disabled.
- Window title now displays the application version so users can easily identify which build they are running.
- Gems and other non-majority resources are preserved in the remap=off preview instead of being merged into the field's majority type.
- Converted-map preview now uses the same stable display size as the primary preview so it no longer appears larger/smaller when holding Preview Converted.
- Hover tooltips now re-appear reliably when pausing over a field again; no click or large mouse movement required.
- Painting a node in the live preview no longer repaints the entire surrounding field; the GUI's `node_affects_field_tier=False` setting is now passed through to the in-process preview worker.
- Painted density overrides are now preserved in-game: the converter emits a map-level rule override that disables OpenRA/Cameo's `ResourceLayer` density recalculation.
- Paint Mode single-click now paints the individual cell under the cursor (with symmetry mirroring), rather than the entire resource field.
- In remap=off mode, painted fields now correctly update their internal resource node actor to match the painted tier.
- Fixed a crash when opening converted maps in the editor caused by the density recalculation rule being placed on `^BaseWorld`; it now correctly targets the `World` actor.
- "Remove Problematic Actors" checkbox now works correctly: unchecking it keeps rock/stone actors by remapping them to palette-mismatched Cameo equivalents (`rock1`-`rock6`) instead of silently dropping them.
- Bushes and other decorative actors with no defensible Cameo equivalent are now always dropped instead of being turned into rocks.
- **Random** density in paint mode now assigns a per-cell random level, not a single uniform value for the entire stroke.

### Packaging changes in v0.76-beta

- Release package now ships only end-user documents: `README.md` and `QUICKSTART.md`.
- Developer docs (`CODEBASE_REFERENCE.md`, `DEVELOPER_NOTES.md`) moved to the source distribution under `docs/`.

### Fixes in v0.75-beta

- Resource palette is now identical for all preview modes and remap settings.
- Converted-map preview now renders spawn and node markers with the same colored fill + black border as the live preview.
- Node painting mirror works correctly even when `remap_resources` is disabled.
- Box, cell, and node mirroring all align transformed source fields to the actual partner field centre for reliable symmetry.

### Known limitations

- Rock/stone decorations use a desert palette that may render with wrong colors on the RA temperate tileset.
- Maps with unusual node placement may have uneven tier counts.
