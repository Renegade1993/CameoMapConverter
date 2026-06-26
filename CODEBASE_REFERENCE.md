# Cameo Map Converter - Codebase Reference Manual

> Quick-reference for any development session. Last updated: 2026-06-24.
> This manual covers the active project root (`Cameo Map Converter/`). A mirrored copy of the production source lives in `Distribution/source/` and is used for build packaging.

---

## 1. What This Project Does

Converts OpenRA / Combined Arms (CA) tournament maps from the Balance Iteration (BI) 4.3-4.6 era into the Cameo mod format. Each `.oramap` is rewritten so that Cameo can load it without crashing, while preserving the map's geometry and re-tiering its resources for balanced competitive play.

**Long-term vision:** The project is architected toward a universal game-map converter supporting bidirectional conversion between any source and target format. The current CA→Cameo path is the first concrete format-pair implementation.

**Architecture principles:**
- **Format abstraction** — every source/target format exposes its own parser, generator, and protocol rules.
- **Translation matrices** — actor, tile, and resource mappings are data-driven (YAML/JSON) rather than hardcoded.
- **Protocol system** — version-specific conversion rules (like the BI protocol) can be added without changing core code.
- **Pipeline architecture** — conversion is a sequence of discrete stages (parse → transform → generate → validate).
- **Validation system** — every output is checked against format-specific invariants.

**Key source locations for cross-reference:**
- OpenRA engine: `Other Game Sources/OpenRA-playtest-20260222 (source)`
- Cameo mod: `Cameo-mod-playtest-20260614 (source)`
- Installed Cameo maps: `%APPDATA%/OpenRA/maps/cameo/playtest-20260614`

High-level transforms performed on every input map:

1. **Header rewrite** — `RequiresMod: ra` -> `cameo`, `Tileset` -> `RA_*`, `Categories` -> `Tournament`, strip trailing `[BI-x.x]` title tag, remove `LockPreview`.
2. **Strip CA custom assets** — removes CA-specific rules, sequences, weapons, voices, notifications, and bundled files that Cameo does not have.
3. **Palette handling** — drops custom palettes by default; use `--keep-palettes` to retain them.
4. **Actor remapping** — keeps actors that exist in Cameo (`cameo_actors.txt`), remaps known CA variants to same-footprint Cameo actors, and drops the rest (notably rocks/stones due to a Cameo palette bug).
5. **Tile/template remapping** — deterministic remapping of CA-specific template IDs to Cameo RA_TEMPERAT equivalents.
6. **Water-crossing fix** — detects template `225` strips that pinch water and converts them to ford templates `590/591/129`.
7. **Resource re-tiering** — assigns every resource field a single tier based on distance from the nearest spawn and the chosen distribution mode; guarantees mirror symmetry and node/field coherence.
8. **Minimap regeneration** — writes a new `map.png` so the OpenRA map list reflects the converted terrain and resources.

---

## 2. Repository Layout

```
Cameo Map Converter/
├── cameo_map_converter.py          # Main conversion engine (CLI + library API)
├── cameo_converter_gui.py          # PyQt5 GUI wrapper
├── resource_reclassification.py    # Symmetry-aware resource tiering algorithm
├── water_crossing_detect.py      # Per-cell terrain lookup + ford detection
├── minimap_render.py             # Shared terrain/resource/actor minimap renderer
├── validate_resource_distribution.py  # Pass/fail validation on final painted output
├── converter_logging.py          # Centralised logging system
├── render_corrected_distribution.py   # Diagnostic PNG renderer
├── actor_matrix.yaml             # Actor keep/remap/drop rules
├── template_matrix.yaml          # Template ID remapping rules
├── bi_protocol.yaml              # BI-version external-ref handling
├── converter_config.yaml         # Default converter settings
├── cameo_actors.txt              # Valid Cameo actor names (regenerate with --dump-actors)
├── ra_temperat.yaml              # Cameo RA_TEMPERAT tileset terrain table
├── Convert Maps.cmd              # Windows launcher (drag folder or .oramap)
├── Build Executable.cmd          # PyInstaller build launcher
├── Create Distribution.cmd       # Builds Distribution/ folder
├── build_exe.spec                # PyInstaller spec for the single-file EXE
├── pyi_rth_cameo_isolation.py   # PyInstaller runtime hook: isolate bundled Python from system Python
├── maps/                         # Source .oramap files
├── maps/converted/               # Output .oramap files
├── corrected_renders/            # Diagnostic renders from render_corrected_distribution.py
├── dev_tools/                    # Standalone diagnostic scripts
├── tests/                        # pytest suite
├── docs/                         # Additional reference docs
├── Distribution/source/          # Mirror of production source used for packaging
└── Distribution/Release/         # Packaged executable + docs
```


### Key docs already present

- `README.md` — User-facing comprehensive manual and release notes.
- `QUICKSTART.md` — Fast getting-started guide.
- `DEVELOPER_NOTES.md` — Developer onboarding and build/test notes.
- `docs/CONVERTER_PATCH_LIBRARY.md` — Empirical patch data with coordinates and placement counts.
- `docs/REPLACEMENT_GUIDE.md` — Actor replacement tables with placement counts.
- `CLAUDE.md` — Project memory, mandatory read at every session.
- `DEVELOPMENT_LOG.md` — Per-session changelog and current state.
- `CODEBASE_REFERENCE.md` — This manual (primary technical reference; ARCHITECTURE.md, GUI_REQUIREMENTS.md, RESOURCE_ALGORITHM_GUIDE.md, and TROUBLESHOOTING.md content merged here).

---

## 3. Core Concepts & Data Formats

### 3.1 .oramap (ZIP archive)

An `.oramap` is a ZIP file containing at minimum:

| File | Required | Description |
|------|----------|-------------|
| `map.yaml` | yes | Map metadata, actors, rule references |
| `map.bin` | yes | Binary tile + resource data |
| `map.png` | no | Preview thumbnail |
| `*.shp` / `*.pal` / `*.aud` | no | Custom assets (most CA maps carry extra YAMLs/SHPs/PALs that must be removed) |

`map.yaml` may also reference external rules/sequences/weapons/voices/music/notifications (`Rules`, `Sequences`, `Weapons`, `Voices`, `Music`, `Notifications`, `FluentMessages`, `ModelSequences`). These are stripped during conversion along with any bundled files they pull in.

### 3.2 map.bin binary format

All CA maps use **Format 2** (byte 0 = `0x02`):

```
[0]      format byte (0x02)
[1-2]    width  (uint16 LE)
[3-4]    height (uint16 LE)
[5-8]    TilesOffset     (uint32 LE, usually 17)
[9-12]   HeightsOffset   (uint32 LE, 0 if none)
[13-16]  ResourcesOffset (uint32 LE, usually 17 + W*H*3)
[17...]  tile data: W*H*3 bytes per cell
[res...] resource data: W*H*2 bytes per cell
```

**Tile cell** (3 bytes): `[template_id (uint16 LE), sub-index (uint8)]`.  
**Resource cell** (2 bytes): `[type (uint8), density (uint8)]`.

**Iteration is COLUMN-MAJOR** (matches OpenRA `Map.cs`):

```python
# cell index for (col=x, row=y)
cell = col * height + row
col = cell // height
row = cell % height
```

This coordinate system is one of the most common sources of bugs. Always use `MapBin.cell_index(col, row)` and `MapBin.cell_xy(i)`.

**Format 1 vs Format 2:** Format 1 has a 5-byte header (no offsets) and is rare today. Format 2 has a 17-byte header with explicit `TilesOffset`, `HeightsOffset`, and `ResourcesOffset`. All CA maps use Format 2. OpenRA also has a special-case loader: if a tile cell's sub-index is `0xFF (255)`, it is replaced with `(col % 4) + (row % 4 * 4)` during loading.

### 3.3 Resource index mapping

Source maps (RA/CA) use:
- `1` = Ore
- `2` = Gems

Cameo uses:

| Name | Index | MaxDensity | Node actor(s) |
|------|-------|------------|---------------|
| Tiberium | 1 | 35 | `split2`, `split3` |
| BlueTiberium | 2 | 30 | `splitblue`, `splitbluesmall` |
| Ore | 3 | 40 | `mine` |
| Gems | 4 | 15 | `gmine` |
| RedTiberium | 5 | 25 | `splitred`, `splitredsmall` |
| GoldTiberium | 6 | 20 | `splitgold`, `splitgoldsmall` |

`remap_source_resources()` converts RA Ore->Cameo Ore (3) and RA Gems->Cameo Gems (4). `assign_resources()` then re-types fields according to the distance/contestedness algorithm.

### 3.4 Key template IDs (RA_TEMPERAT)

| ID | Meaning |
|----|---------|
| 0 | Invalid (remapped to clear) |
| 1, 2 | Water |
| 19-29 | Beach |
| 129 | Large ford (3x3) |
| 156-167 | Cliffs / rocky edges |
| 199-230 | Roads |
| 231-234 | River rocks |
| 255 | Clear (default clear terrain) |
| 590 | Ford vertical (1x2) |
| 591 | Ford horizontal (2x1) |
| 65535 | Void / outside bounds |

Special values: `255` is the default clear terrain (`clear1.tem`); `65535` marks void cells outside the map bounds. Sub-index `0xFF (255)` inside a tile cell is a special loader marker that OpenRA replaces with `(col % 4) + (row % 4 * 4)`.

CA-specific templates > 255 are mapped back to these via `template_matrix.yaml`.

### 3.5 Template remapping caveats

- **Template 221** is a 1x1 CA rocky water-crossing marker. Mapping it to Cameo template `591` (2x1 horizontal ford) is geometrically wrong and should be avoided. The safer targets are `2` (water) or `255` (clear). `water_crossing_detect.py` handles true 225 crossings; 221 is not a reliable crossing signal.
- **Templates 157 and 166** (water wreckage / rocky edges) are mapped to `255` (clear) because they render as water-like debris in Cameo.
- **Templates 400-406** (CA custom hills) do not exist in RA_TEMPERAT and are mapped to `255` except where they need to be preserved as cliffs.

---

## 4. Conversion Pipeline (Step by Step)

The main orchestrator is `convert_map()` in `cameo_map_converter.py`. Steps in order:

1. **Validate & extract** — `validate_oramap_file()`, unzip into a temp directory.
2. **Parse `map.yaml`** — read as a list of lines.
3. **Detect source metadata** — `RequiresMod`, `Tileset`, BI version from `Title`/`Categories`.
4. **Apply BI protocol** — if a `[BI-x.x]` tag is found, load version-specific external refs from `bi_protocol.yaml`.
5. **Rewrite header** — `set_scalar()` for `RequiresMod`, `Tileset`, `Title`, `Author`, `Categories`; remove `LockPreview`.
6. **Remove external refs** — strip `Rules`, `Sequences`, `Weapons`, `Voices`, `Notifications`, `FluentMessages` blocks and their referenced files.
7. **Palette handling** — extract palette blocks from Rules files; keep only palettes listed in `PALETTE_OVERRIDES` or when `--keep-palettes` is passed.
8. **Load `map.bin`** — create `MapBin` object from the binary.
9. **Template remapping** — `remap_templates()` applies `template_matrix.yaml` mappings.
10. **Water crossing detection** — `detect_and_convert_crossings()` from `water_crossing_detect.py` converts pinched template 225 strips into fords.
11. **Stray water fixes** — `fill_stray_water()` and `fill_grass_in_water()` clean up orphaned water/grass cells.
12. **Source resource remap** — `remap_source_resources()` converts RA indices to Cameo indices.
13. **Actor processing** — `parse_actors()` and `apply_actor_matrix()` keep/remap/drop actors based on `cameo_actors.txt` and `actor_matrix.yaml`.
14. **Resource assignment** — `assign_resources()` re-types fields and nodes (see Section 5).
15. **Minimap render** — `minimap_render.py` generates a new `map.png` from the converted terrain/resources.
16. **File filtering** — keep only `map.yaml`, `map.bin`, `map.png`, and allowed asset types (PAL/SHP/AUD if kept).
17. **Repackage** — write the cleaned files to the output `.oramap` as a ZIP.
18. **Cleanup** — delete the temp directory.

---

## 5. Resource Algorithm Reference

The resource tiering lives in `resource_reclassification.py` and is called from `cameo_map_converter.py` via `assign_resources()`.

### 5.1 Tier order

Cheapest to richest:

```
Ore -> Tiberium -> BlueTiberium -> RedTiberium -> GoldTiberium -> Gems
```

### 5.2 The `RESOURCE_RICHNESS` knob

A single boundary-sweep knob that controls how far up the tier ladder the map goes:

| Richness | Result |
|----------|--------|
| `0.5` | Essentially all Ore |
| `1.0` | Even Ore -> GoldTiberium spread, **zero gems** |
| `1.5` | Essentially all Gems |

Gems only appear when `richness > 1.0`. The knob is monotonic and saturates past ~0.5 and ~1.5.

### 5.3 Distribution modes

Set via `--distribution` or the GUI. All three modes preserve 100% symmetry and obey the knob.

| Mode | Value driver | Result | Best for |
|------|--------------|--------|----------|
| `distance` | Nearest-spawn distance | Richest resources on the **outer** edges of the map. | Maps where expansions should be highly rewarded; natural resource pressure toward the edges. |
| `balance` (default) | `dn + BALANCE_BIAS * cn * home_gate` | Richest resources in the **contested centre** between bases; base patches stay Ore. | Standard competitive play; rewards fighting for map control. |
| `even` | Quota-fill by orbit distance | Equal cell counts per active type; ignores richness knob and always spreads all 6 tiers across orbits when possible. | Exhibition/scenario maps where every player must have access to the same total value. |

`balance` mode tuning:
- `BALANCE_BIAS` (default `3`): strength of the contested-centre pull. `0` behaves like `distance`; higher values pull rich tiers harder into the middle.
- `BALANCE_HOME_RADIUS` (default `15` grid cells): safe zone around spawns; resources inside it stay low-tier regardless of contestedness. The home gate is a smooth fall-off near the spawn so that base patches never become high-tier accidentally.

### 5.4 Symmetry guarantee

1. `detect_symmetries()` builds candidate transforms around the spawn centroid: point reflection, vertical/horizontal mirrors, main/anti diagonal mirrors, 90/270 rotations.
2. A transform is accepted if it maps spawns onto themselves (median error <= `SPAWN_MATCH_TOL = 2.5`) and nodes onto nodes (median error <= `NODE_MATCH_TOL = 4.0`).
3. `build_orbits()` groups nodes that map to each other under the accepted transforms.
4. Each orbit is tiered by its **average** distance/value, so every member of an orbit receives the same tier.
5. Fields are then symmetrized in `assign_resources()` using the same transforms, so mirror-paired fields share one tier.

### 5.5 Node vs field coherence

- Every contiguous resource field is assigned a single tier.
- The field's tier comes from the node that owns it (node inside the field, or nearest node within `MERGE_MARGIN = 4` cells; contested blobs take the richest tier).
- After field painting, each node actor is rewritten to match the field it actually stands in, including in `manual_only` mode when `remap_resources=False`.
- The cells occupied by node actors are also painted to match the surrounding field.
- This prevents visual mismatches such as an ore mine sitting in a gold field.

### 5.6 Paint-mode overrides (GUI only)

The GUI supports hand-painted overrides on top of the algorithm:

- **Field override** — click inside a field to repaint the entire field.
- **Cell override** — drag a box to repaint all resource cells (and any nodes) inside the selection.
- **Node override** — click directly on a node actor to repaint just the node (and optionally the field).
- **Mirror paint** — when enabled, every paint action is mirrored through the detected symmetry transforms.
- **Undo/Redo** — diff-based undo stack for all override types.

Overrides are passed into `assign_resources()` via `paint_overrides`, `cell_overrides`, and `node_overrides`. The field metadata returned in `counts["__fields__"]` and `counts["__nodes__"]` drives the GUI's paint tooltips and mirror logic.

### 5.7 Recommended presets

Starting points; tweak richness and bias to taste:

| Preset | CLI | Use case |
|--------|-----|----------|
| Standard Competitive | `--richness 1.0 --distribution balance` | Balanced, no gems, contested centre rewards map control. |
| Expansion Focus | `--richness 1.0 --distribution distance` | Rich outer fields reward expanding away from base. |
| Central Conflict | `--richness 1.0 --distribution balance --balance-bias 5` | Heavily contested middle, very valuable centre. |
| Defensive Play | `--richness 0.7 --distribution balance --balance-home-radius 25` | Base patches stay Ore, only distant fields tier up. |
| High-Stakes | `--richness 1.5 --distribution balance` | Gems appear; very high-value contested fields. |
| Equal Access | `--richness 1.0 --distribution even` | Equal cell counts across all active tiers. |

### 5.8 Tier colors and validation

Preview/render colors used in the GUI and `render_corrected_distribution.py`:

| Tier | Color |
|------|-------|
| Ore | Brown/Orange |
| Tiberium | Green |
| BlueTiberium | Blue |
| RedTiberium | Red |
| GoldTiberium | Gold/Yellow |
| Gems | Purple/Magenta |

**Stability status:** The resource algorithm is considered stable as of 2026-06-22. Any change to symmetry detection, orbit building, or tier assignment must be followed by `validate_resource_distribution.py` (default: 90 checks across 10 maps). Default production values are `richness=1.0`, `distribution=balance`, `balance-bias=3`, `balance-home-radius=15`.

---

## 6. Module Reference

### `cameo_map_converter.py` — conversion engine

| Symbol | Purpose |
|--------|---------|
| `ConverterConfig` | Centralised config; loads `converter_config.yaml` and supports YAML/JSON save/load. |
| `MapBin` | Parses/writes `map.bin` (Format 1/2, column-major). Key methods: `tile_type`, `set_tile`, `set_res`, `cell_xy`, `cell_index`. |
| `validate_*` | Path, `.oramap`, dimension, and resource-config validation. |
| `load_template_remap()` | Loads `template_matrix.yaml`. |
| `remap_templates()` | Applies CA->Cameo template ID mapping. |
| `remap_source_resources()` | RA->Cameo resource index remap. |
| `fill_stray_water()` / `fill_grass_in_water()` | Water cleanup passes. |
| `apply_actor_matrix()` | Keep/remap/drop actors using `actor_matrix.yaml` and `cameo_actors.txt`. |
| `assign_resources()` | Full resource field decomposition + tiering + painting + node reconciliation. |
| `convert_map()` | Main pipeline orchestrator. |
| `render_preview()` | In-process preview for the GUI; returns `(PIL.Image, counts_dict)`. |
| `Report` | Simple message accumulator for the conversion log. |
| `main()` | CLI entry point. |

### `resource_reclassification.py` — tiering algorithm

| Symbol | Purpose |
|--------|---------|
| `TIER_ORDER` | `["Ore", "Tiberium", "BlueTiberium", "RedTiberium", "GoldTiberium", "Gems"]` |
| `RESOURCE_INDICES` | Cameo map.bin resource byte per tier. |
| `RESOURCE_RICHNESS` / `DISTRIBUTION_MODE` / `BALANCE_BIAS` / `BALANCE_HOME_RADIUS` | Module-level knobs that the CLI/GUI mutate at call time. |
| `tier_for_fraction()` | Maps a normalised distance fraction to a tier using the richness knob. |
| `calculate_nearest_spawn_distances()` | Per-node distance to nearest spawn. |
| `detect_symmetries()` | Returns accepted transforms and the map centre. |
| `build_orbits()` | Groups nodes into symmetry orbits via union-find. |
| `node_values()` | Computes the per-node ranking value (`distance` or `balance`). |
| `assign_node_tiers_even()` | Even-mode quota-fill assignment. |
| `assign_node_tiers_corrected()` | Main entry point; calls the above and returns tiers. |
| `assign_node_tiers_debug()` | Returns full working set (distances, orbits, fractions, tiers) for diagnostics. |

### `water_crossing_detect.py` — ford detection

| Symbol | Purpose |
|--------|---------|
| `load_tileset_terrain()` | Parses `ra_temperat.yaml` into `{template_id: {sub_index: terrain_name}}`. |
| `cell_terrain()` | Resolves a single cell to its terrain string using template ID and sub-index. |
| `detect_crossings()` | Scans for template 225 cells/clusters that are pinched by water. |
| `detect_and_convert_crossings()` | Main entry point; rewrites crossings to ford templates. |

### `minimap_render.py` — preview/minimap rendering

| Symbol | Purpose |
|--------|---------|
| `get_terrain_tables()` | Loads `ra_temperat.yaml` and returns `(templates_table, terrain_colors)`. |
| `terrain_layer()` | Renders a base terrain PNG from `map.bin` and tileset colours. |
| `overlay_resources()` | Paints resource cells over the terrain using the canonical `INDEX_COLORS` palette. Always uses Cameo indices regardless of `remap_resources`. |
| `overlay_actors()` | Paints spawn and node markers; at `scale=1` the border is suppressed because a single pixel cannot hold both a fill and a border. |
| `INDEX_COLORS` / `RESOURCE_COLORS` / `NODE_MARKER_COLORS` | Canonical RGB tables shared with the GUI and `render_corrected_distribution.py`. `SOURCE_INDEX_COLORS` was removed in v0.75-beta. |

### `cameo_converter_gui.py` — GUI

| Symbol | Purpose |
|--------|---------|
| `JSONSettings` | JSON-based settings store (`settings.json`). |
| `PreviewWorker` | QThread that calls `render_preview()` in-process. |
| `ConversionWorker` | QThread that runs a single conversion via subprocess. |
| `BatchConversionWorker` | QThread that runs sequential conversions for multiple maps. |
| `CameoConverterGUI` | Main window: directory browser, preview viewer, resource knobs, paint mode, presets, logging menu. |
| Paint handlers | `_handle_field_paint_click`, `_handle_cell_paint_click`, `_handle_node_paint_click`, `_handle_paint_box`, `_mirror_cell_override`, `_mirror_node_override`. |
| Preset handlers | `_load_presets`, `_save_presets`, `_load_preset_by_name`, `_delete_preset_by_name`. |

### `validate_resource_distribution.py` — validation

| Symbol | Purpose |
|--------|---------|
| `max_even_tiers()` | Computes the maximum distinct tiers achievable in `even` mode for a map. |
| `convert()` | Runs the real `convert_map()` pipeline at a given richness/mode. |
| `analyze()` | Returns tier counts, symmetry percentage, and incoherent node list. |
| `main()` | Runs all test maps at `r = 0.5, 1.0, 1.5` across all modes; exits non-zero on failure. |

### `converter_logging.py` — logging

| Symbol | Purpose |
|--------|---------|
| `ConverterLogger` | Singleton logger with console output and per-log-type rotating file handlers. |
| `get_logger()` / `setup_logging()` | Global access and convenience setup. |
| `enable_log_type()` / `disable_log_type()` | Toggle file logging for `DEBUG`/`INFO`/`WARNING`/`ERROR`. |

---

## 7. GUI & Preview System

### 7.1 Layout and controls

The PyQt5 GUI is laid out in three bands:

- **Top:** incoming/outgoing game-type selectors (currently fixed to OpenRA → Cameo) and directory browsers for source and destination maps.
- **Centre:** map preview viewer with left/right arrow buttons to page through the source directory. Previews are rendered to a temporary image and are not written to disk until conversion.
- **Bottom:** settings panel with five parameters and conversion buttons.

**Settings panel parameters:**

| Control | CLI flag | Purpose |
|---------|----------|---------|
| Resource Richness | `--richness` | 0.5≈all Ore, 1.0=balanced/no gems, 1.5≈all Gems |
| Distribution Mode | `--distribution` | `distance` (rich at edges) / `balance` (rich in centre) / `even` (equal tier counts) |
| Balance Bias | `--balance-bias` | Strength of contested-centre pull; 0 acts like distance, default 3 |
| Balance Home Radius | `--balance-home-radius` | Safe zone around spawns in grid cells; default 15 |
| Curve | `--curve` | Historical BAND_CURVE parameter; kept in UI for compatibility |

**Conversion controls:**
- **Convert Map** — convert the currently-previewed map.
- **Convert All** — batch-convert every map in the source directory.
- Status indicator light shows whether a map has already been converted. When lit, **Hold to Preview Converted** shows the saved output while the mouse button is held. The converted preview is rendered at the same 4× scale and with the same marker borders as the live preview.

### 7.2 Dependencies and launch

- Runtime: `PyQt5 >= 5.15.0` (or PySide2 as fallback).
- Launch from source: `py cameo_converter_gui.py`
- Launch standalone: `CameoMapConverter.exe` (built by `Build Executable.cmd`).

### 7.3 Preview flow

1. The GUI caches the terrain layer and base resource cells once per map.
2. When a knob changes, `PreviewWorker` calls `cameo_map_converter.render_preview()` in-process.
3. `render_preview()` mutates the module-level `RESOURCE_RICHNESS` and `resource_reclassification.*` globals, runs `assign_resources()`, and uses `minimap_render` to overlay terrain, resources, and actor markers.
4. The `map.png` from the source `.oramap` is loaded as a terrain base when dimensions match. Resources are always repainted with the canonical `INDEX_COLORS` palette; the `remap_resources` flag only affects which indices are in `map.bin`, not the preview colors.
5. The returned `counts` dict includes `__fields__` and `__nodes__` metadata for paint mode and tooltips.
6. The GUI displays the PNG and updates the legend/counts. The previous worker is terminated before a new one starts to avoid concurrent global mutation.
7. **Converted preview**: when the user holds **Preview Converted**, the baked 1px/cell `map.png` from the output `.oramap` is extracted, upscaled 4×, and `overlay_actors()` is run again so spawn and node markers match the live preview style.

### 7.4 Paint mode

- Toggle **Paint Mode: ON** and select a resource type.
- Click a field, cell, or node to override its tier.
- Use the **Density** dropdown to set the density level for the next paint stroke:
  - **Replace** keeps the existing density byte.
  - **Random** picks a level 1-5 uniformly.
  - **1-5** writes a density proportional to the tier's `MaxDensity` (e.g., level 1 Tiberium = 7/35, level 5 = 35/35).
- **Mirror Paint** is on by default; symmetry partners are painted automatically using the transforms stored in `_last_assign_fields`.
- **Undo / Redo / Clear Overrides** are available and restore both tier and density.
- Overrides persist across preview refreshes but are **not** saved to the output file until you press **Convert**.
- The paint override settings passed to `render_preview()` and `convert_map()` include:
  - `paint_overrides` / `cell_overrides` / `node_overrides` for tier.
  - `density_overrides` / `field_density_overrides` for density bytes.
- When `convert_map()` receives any density overrides, it emits a `Rules:` block in the output `map.yaml` that sets `RecalculateResourceDensity: false` on `^BaseWorld.ResourceLayer` and `EditorWorld.EditorResourceLayer`. Without this, the Cameo/OpenRA engine would throw away the painted density bytes and recompute them from neighbor count.

### 7.5 Presets

Presets save the current knob state (richness, distribution, balance bias, home radius, remap resources, remove actors) to `presets.json` next to the executable. They are managed from the **Presets** menu.

### 7.6 Future GUI enhancements

Planned but not implemented:
- Support for additional game types beyond OpenRA → Cameo.
- Map browser with thumbnails.
- Resource distribution visualization tools.
- Validation reports (symmetry, coherence checks).
- Side-by-side before/after comparison.
- Visual editor for BI protocols and translation matrices.
- Template/actor remapping interface.
- Performance optimizations: cached preview generation, incremental updates, background pre-loading.

---

## 8. Tests & Validation

### 8.1 pytest suite

```bash
pytest                      # all tests
pytest tests/unit/          # unit tests only
pytest tests/integration/   # integration tests only
pytest -v                   # verbose
```

- `conftest.py` — shared fixtures (`sample_map_path`, `test_output_dir`).
- `tests/unit/test_config.py` — `ConverterConfig` YAML/JSON round-trip for set-valued attrs.
- `tests/unit/test_validators.py` — validation of richness, bias, home radius, file paths, `.oramap` structure.
- `tests/integration/test_conversion.py` — full conversion, remap-disabled conversion, dry-run.

### 8.2 Validation script

```bash
python validate_resource_distribution.py
python validate_resource_distribution.py --mode all
python validate_resource_distribution.py --mode balance path/to/map.oramap
```

Checks on the final painted `map.bin`:
- **Knob invariants** (distance/balance): `r=0.5` >= 95% Ore; `r<=1.0` zero gems; `r=1.5` >= 95% Gems.
- **Even mode**: maximum achievable distinct tiers appear.
- **Symmetry**: >= 99.5% of overlapping resource cells are mirror-symmetric.
- **Coherence**: zero nodes whose field type does not match their actor.

### 8.3 Diagnostic renders

```bash
python render_corrected_distribution.py          # default 12 test maps, r=0.5/1.0/1.5
python render_corrected_distribution.py Map1 Map2
```

Produces `corrected_renders/<Map>_richness_<r>.png` showing tier-coloured fields, node markers, spawns, symmetry centre, and live stats.

### 8.4 Build & distribution

```bash
Build Executable.cmd          # creates CameoMapConverter.exe via PyInstaller
Create Distribution.cmd       # assembles Distribution\Release\ and Distribution\source\
```

- `build_exe.spec` packages the GUI, converter modules, YAML/TXT configs, and docs into a single windowed executable (`console=False`). Set `console=True` for diagnostic builds.
- `pyi_rth_cameo_isolation.py` is a PyInstaller runtime hook that runs before the main script. It clears `PYTHONPATH`, `PYTHONHOME`, and all other `PYTHON*`/`PY_*` environment variables, disables user site-packages, and resets `sys.path` to the PyInstaller bundle directory (`sys._MEIPASS`). This prevents the bundled Python 3.12 runtime from accidentally importing a system Python 3.13/3.14 stdlib on end-user machines (new Python Install Manager / Microsoft Store installs use `%LOCALAPPDATA%\Python\pythoncore-X.Y-64`), which would otherwise cause `ImportError: Module use of python312.dll conflicts with this version of Python`.
- `build_exe.spec` also disables UPX (`upx=False`) and adds explicit `hiddenimports` for `socket`, `_socket`, and `logging.handlers` to improve reliability on newer Windows/Python combinations.
- `cameo_converter_gui.py` contains a dispatch guard in `main()`: when the frozen EXE is re-executed with the bundled `cameo_map_converter.py` as the first argument, it dispatches to that script via `runpy.run_path()` instead of launching the GUI. This lets the conversion subprocess use the bundled Python 3.12 interpreter rather than searching for a system Python interpreter (which might be Python 3.14 and would load conflicting PyInstaller 3.12 C extension modules from the `_MEI` directory).
- `ConversionWorker` and `BatchConversionWorker` use `sys.executable` for the conversion subprocess in both frozen and script modes, relying on the EXE dispatch above when frozen.
- `Create Distribution.cmd` produces both:
  - A release zip: `Distribution\CameoMapConverter_vX.Y.Z.zip` (portable folder: `CameoMapConverter.exe`, `README.md`, `QUICKSTART.md`).
  - A source zip: `Distribution\CameoMapConverter_vX.Y.Z_source.zip` (mirror of `Distribution\source\`). The source zip must be created alongside every release zip.
- `Distribution\source\` is a mirror of the production source used for build packaging. The project root should remain the single source of truth; update the build script instead of maintaining the mirror manually.

---

## 9. Dev Tools Catalog

All in `dev_tools/`. Run from the project root: `py dev_tools/<script>.py ...`

| Script | Purpose |
|--------|---------|
| `analyze_resources.py` | Inspect resource node distribution around spawns. |
| `check_conversion.py` | Compare actor lists between original and converted maps. |
| `check_coordinates.py` | Debug coordinate alignment (game vs map.bin). |
| `detailed_node_check.py` | Verify node actors match their surrounding field. |
| `extract_actors.py` | Dump all unique actors from `maps/` with counts to `actor_inventory.json`. |
| `render_corrected_distribution.py` | Render diagnostic tier PNGs. |
| `test_logging.py` | Smoke-test the logging module. |
| `test_paint_symmetry.py` | Simulate mirror-paint clicks and verify symmetry. |
| `test_symmetry.py` | Report detected symmetry transforms and field groups for a map. |
| `test_symmetry_all_maps.py` | Run symmetry detection across all maps in `maps/`. |

---

## 10. Configuration Files

### `converter_config.yaml`

Default values for the `ConverterConfig` class. Edits here change CLI/GUI defaults. Key keys:
- `RESOURCE_RICHNESS`, `WATER_FILL_SAFETY`
- `PALETTE_DEFAULT`, `PALETTE_OVERRIDES`
- `KEEP_NAMES`, `NEW_CATEGORY`, `CONVERTER_TAG`
- `EXTERNAL_REF_KEYS`
- `ACTOR_NEVER_DROP`, `ACTORS_FILE`
- `BI_PROTOCOL_FILE`
- `TILESET_MAP`
- `LOGGING` (directory, per-type enable flags, rotation)

### `actor_matrix.yaml`

Three-layer translation:
- `exact_matches` — actors that pass through unchanged.
- `pattern_rules` — regex-based remapping (e.g. strip tree colour suffixes).
- `explicit_remaps` — specific source_actor -> target_actor or `drop`.

Rocks/stones are currently dropped by default due to the Cameo palette issue.

### `template_matrix.yaml`

- `ca_template_mappings` — CA template ID -> Cameo template ID.
- `ra_temperat_categories` — category metadata for validation.

### `bi_protocol.yaml`

Simple line format: `VERSION|KEY|FILE1,FILE2,...`. Defines version-specific external-reference files for BI 4.3-4.6 and a DEFAULT fallback.

### `cameo_actors.txt`

Plain list of valid Cameo actor names, one per line. Regenerate with:

```bash
python cameo_map_converter.py --dump-actors <path_to_cameo_rules_dir>
```

---

## 11. Common Tasks & Gotchas

### Coordinate system

Game/editor `(x,y)` maps directly to `(col,row)` in `map.bin`. Cell index = `col * height + row`. **Never** use `row * width + col`.

### Format 2 map.bin bug

Older code hard-coded Format 1 offsets. All CA maps use Format 2. Always use `MapBin.tiles_off` and `MapBin.res_off`.

### Rock palette issue

Cameo rock actors render with the wrong palette on `RA_TEMPERAT`. They are dropped by default. To restore, edit `actor_matrix.yaml` or `ACTOR_OVERRIDES` in `cameo_map_converter.py`.

### Tile 225

Template `225` is **rocky debris**, not a water crossing. The water-crossing detector only converts `225` strips that are actually pinched by water into fords (`590/591/129`). Bare `225` in open land is remapped to clear.

### Stale bash mount (Cowork)

In the Cowork environment, bash reads can be stale. Use the Read/Edit/Grep file tools for ground truth; use bash only to run code. Canary before running: `python -m py_compile <modules>`.

### Running from source

```bash
python cameo_map_converter.py maps/ --richness 1.0 --distribution balance
python cameo_map_converter.py maps/ --distribution even
```

Output goes to `maps/converted/` by default, or `-o <outdir>`.

### CLI flags

```
-o, --outdir DIR              Output directory (default: <input>/converted)
--richness FLOAT              0.0-2.0 (default 1.0)
--distribution MODE           distance | balance (default) | even
--balance-bias FLOAT          Default 3; higher = more contested-centre pull
--balance-home-radius FLOAT   Default 15 cells
--no-remove-actors            Keep rocks/stones/bushes despite palette bug
--keep-palettes               Preserve custom palettes
--keep-decorations            Keep all CA decoration actors (may fail in Cameo)
--dry-run                     Run conversion without writing output
--no-render                   Skip map.png preview regeneration
--no-remap-resources          Leave source resource indices unchanged
--config FILE                 Load ConverterConfig from YAML or JSON
--dump-actors DIR             Generate cameo_actors.txt from a Cameo rules dir
--log-level LEVEL             DEBUG | INFO | WARNING | ERROR
--log-file FILE               Write log to file
```

### Common errors and quick fixes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `python` / `python3` not found | Python not in PATH | Use `py` on Windows, or install python.org and check "Add Python to PATH" |
| `ModuleNotFoundError: No module named 'yaml'` / `'PIL'` | Missing dependencies | `py -m pip install pyyaml pillow PyQt5` |
| `PermissionError: [Errno 13]` | Output dir protected | Run from a writable directory; do not convert inside `Program Files` |
| `ValueError: Unknown map.bin format byte` | Format 1 or corrupt map.bin | Verify the source map opens in OpenRA; all CA maps are Format 2 |
| `ValueError: File must be a .oramap file` | Wrong extension or nested ZIP | Ensure the file has `.oramap` extension and contains `map.yaml` + `map.bin` |
| Rocks render as black/purple | Cameo palette bug | Expected: rocks are dropped by default. Use `--no-remove-actors` only if the mod fixes the palette. |
| Preview does not update | GUI worker debounce | Wait 500ms after changing a knob, or click **Refresh Preview** |
| GUI crashes silently | Check `gui_crash_log.txt` next to the executable | Re-run with `console=True` in `build_exe.spec` to see stderr |
| Conversion output looks wrong | Mix of knob settings | Start with `--richness 1.0 --distribution balance`, then tweak |
| Asymmetric resources | Source map itself is asymmetric | `validate_resource_distribution.py` will flag this; use paint mode or pick a more symmetric source map |
| High-value resources in base area | `balance-home-radius` too small | Increase to 20-25, or use `distance` mode |

### Advanced debugging

1. Capture verbose output: `py cameo_map_converter.py maps/ --log-level DEBUG --log-file debug.log`
2. Run validation: `py validate_resource_distribution.py --mode all`
3. Generate diagnostic renders: `py render_corrected_distribution.py MapName`
4. Check symmetry: `py dev_tools/test_symmetry.py maps/MapName.oramap`
5. Check node/field coherence: `py dev_tools/detailed_node_check.py maps/converted/MapName.oramap`

---

## 12. Baseline Improvement Recommendations

> Established during the 2026-06-24 reference-manual session. Current baseline: all 21 pytest tests pass and `validate_resource_distribution.py` reports `ALL CHECKS PASSED` across distance/balance/even modes on the default test maps.

These recommendations are grouped by priority. They are intended to be addressed incrementally; they do not need to be done in one session.

### 12.1 High Priority

| # | Issue | Why it matters | Suggested approach |
|---|-------|----------------|-------------------|
| 1 | **Global mutable state** in `cameo_map_converter.py` (`RESOURCE_RICHNESS`, `_PREVIEW_CACHE`, `TEMPLATE_REMAP`, `SOURCE_RES_REMAP`, etc.) and `resource_reclassification.py` (`DISTRIBUTION_MODE`, `BALANCE_BIAS`, `BALANCE_HOME_RADIUS`). | Prevents concurrent use, makes tests depend on import order, and forces the GUI to serialise preview workers. | Introduce a `ConverterContext`/`ConverterSettings` object that is created once per conversion/preview call and passed down. Keep module-level constants as defaults only. |
| 2 | **Monolithic files** — `cameo_map_converter.py` (2633 lines), `cameo_converter_gui.py` (3512 lines), and `assign_resources()` (~550 lines). | Hard to test, hard to navigate, changes in one area risk another. | Split `cameo_map_converter.py` into focused modules (e.g., `parsers/`, `transformers/`, `preview/`, `cli.py`). Extract `PaintManager`, `CoordinateTransformer`, and `ResourceCounter` from the GUI. |
| 3 | **Duplicated core logic** — field decomposition (BFS), resource-cell access, and symmetry grouping each appear in 3+ files. | Bug fixes must be applied in multiple places; divergent copies are likely. | Create shared utilities: `decompose_resource_fields()`, `MapBin.get_resource(col,row)`, `group_symmetric_fields()`. Add unit tests for each. |
| 4 | **No unit tests for the core algorithm** — `tier_for_fraction`, `detect_symmetries`, `build_orbits`, `assign_node_tiers_even`, `node_values` are untested. | Algorithm changes can silently break the balance guarantee or knob behaviour. | Create `tests/unit/test_resource_reclassification.py` with synthetic maps and known symmetries. |
| 5 | **Inconsistent logging** — many `print()` calls remain in `cameo_map_converter.py` and `ConverterConfig`, and bare `except Exception:` blocks silently swallow errors. | Silent failures hide bugs; inconsistent output makes debugging harder. | Replace all `print()` with the existing `ConverterLogger`; replace bare `except` with specific exception types and log/raise. |
| 6 | **Root / `Distribution/source` duplication** — the same source/config/test files are maintained in two places. | Every edit risks the two copies diverging. | Either generate `Distribution/source` automatically from the root (e.g., a single `copy_files` list in `Create Distribution.cmd`), or make the build script copy from root so only one source of truth exists. |

### 12.2 Medium Priority

| # | Issue | Why it matters | Suggested approach |
|---|-------|----------------|-------------------|
| 7 | **Universal-converter vision is blocked** — tileset, resource indices, actor mappings, and source-resource remaps are hardcoded to the CA→Cameo path. | The project vision is bidirectional, multi-format conversion, but the current code cannot support that without large rewrites. | Design a `Format` abstraction and a conversion-pipeline registry. Move CA-specific and Cameo-specific rules into format plugin files (e.g., `formats/source/combined_arms.yaml`, `formats/target/cameo.yaml`). |
| 8 | **O(n²) neighbour searches** in symmetry detection and field grouping. | Performance degrades on large maps (>100 nodes/fields). | Use spatial indexing (KD-tree or grid binning) for nearest-match lookups, or add early-exit when tolerance is reached. |
| 9 | **Dev tools scripts are hardcoded** to specific map paths or the `maps/` directory. | They cannot be reused on different maps or in CI. | Add `argparse` to every `dev_tools/*.py` script for `--maps-dir`, `--output-dir`, and specific map names. |
| 10 | **Thin integration tests** — only basic conversion, remap-disabled, and dry-run are covered. | Core behaviours (distribution modes, richness values, paint mode, symmetry) are not exercised in CI. | Expand `tests/integration/test_conversion.py` with parametrized tests for modes, richness values, and multiple maps. Add a paint-mode integration test. |
| 11 | **Resource/tier constants scattered** across `cameo_map_converter.py`, `resource_reclassification.py`, `minimap_render.py`, `validate_resource_distribution.py`, and the GUI. | Risk of inconsistency; updates require touching many files. | Create a single `constants.py` or export from `resource_reclassification.py` as the canonical source of truth. |
| 12 | **Magic tolerance values** (`SPAWN_MATCH_TOL=2.5`, `NODE_MATCH_TOL=4.0`, `FTOL=5.0`, `MERGE_MARGIN=4.0`) are undocumented and not centralised. | Hard to tune and easy to break during refactors. | Group into a `SymmetryConfig`/`ResourceConfig` class with docstrings explaining the empirical basis. |

### 12.3 Low Priority

| # | Issue | Why it matters | Suggested approach |
|---|-------|----------------|-------------------|
| 13 | **No performance benchmarks** for resource algorithm or symmetry detection. | Cannot detect regressions when optimising. | Add `tests/performance/bench_resource_algorithm.py` with synthetic maps of varying sizes. |
| 14 | **No dedicated paint-mode documentation** beyond the tooltip/legend. | Users and contributors must discover behaviour by trial and error. | Create `docs/PAINT_MODE_GUIDE.md` with workflow, symmetry, density, and undo/redo details. |
| 15 | **Singleton `ConverterLogger` implementation** is more complex than needed. | Minor readability issue. | Simplify to a module-level instance or use `logging.getLogger("CameoConverter")` directly. |
| 16 | **No property-based tests** for symmetry invariants (e.g., transforms are involutions, orbit members share tiers). | Edge cases may be missed. | Add Hypothesis-based tests if the dependency is acceptable. |
| 17 | **Windows-specific Python paths** in `cameo_converter_gui.py` (lines ~289, ~451). | Fails on non-Windows or non-default Python installs. | Use `where py` / `sys.executable` / `py` launcher lookup instead of hardcoded usernames and versions. |

---

## 13. How to Update This Manual

At the end of every session that changes architecture, adds modules, or renames files:

1. Update the relevant section(s) in this file.
2. Refresh the `Last updated` date at the top.
3. Add a note to `DEVELOPMENT_LOG.md` that the manual was updated.
4. If a concept is now permanently part of project memory, also add/refresh it in `CLAUDE.md`.

When in doubt, keep the manual shorter than the full docs and longer than the README; it should answer "which file does what?" and "what is the data flow?" in under 10 minutes.

---

## 14. Document Archive

During the 2026-06-24 reference-manual consolidation, the following documents were reviewed and moved to the project archive (`Cameo Work\to delete\Cameo Map Converter docs archive 2026-06-24\`) because their essential content was merged into this manual or they were no longer needed in the active project root:

### Archived
- `USER_MANUAL.md` — content merged into `README.md`.
- `RELEASE_NOTES.txt` — content merged into `README.md`.
- `DISTRIBUTION_README.md` — distribution-specific copy; only needed inside `Distribution\Release\`.
- `LOGGING.md` — developer-facing logging reference; merged into Section 11 and the module reference.
- `docs/EditorResourceBrush.patch.md` — external OpenRA engine patch, not converter-specific.
- `docs/OPENRA_MAP_REFERENCE_PART1_TILESET.md` — exhaustive tileset reference; essential details are in Section 3.
- `docs/OPENRA_MAP_REFERENCE_PART2_GENERATION.md` — OpenRA procedural generation reference, not used by the converter.
- `docs/OPENRA_MAP_REFERENCE_PART3_ENGINE_RULES.md` — exhaustive engine rules reference; essential details are in Section 3.
- `docs/ROCK_PALETTE_ISSUE_FOR_DEV_TEAM.md` — external Cameo mod issue; the converter workaround is documented in Section 11.
- `ARCHITECTURE.md` — deep .oramap/map.bin/RA_TEMPERAT reference; content into Sections 1, 3, and 11.
- `GUI_REQUIREMENTS.md` — PyQt5 GUI requirements; content merged into Section 7.
- `RESOURCE_ALGORITHM_GUIDE.md` — resource algorithm user/dev guide; content merged into Section 5.
- `TROUBLESHOOTING.md` — detailed troubleshooting guide; content merged into Section 11.

### Retained in active project
- `README.md` — public landing page / comprehensive manual / release notes.
- `QUICKSTART.md` — fast getting-started guide.
- `DEVELOPER_NOTES.md` — developer onboarding and build/test notes.
- `docs/CONVERTER_PATCH_LIBRARY.md` — empirical patch data with coordinates and placement counts.
- `docs/REPLACEMENT_GUIDE.md` — actor replacement tables with placement counts.
- `CLAUDE.md` — project memory and session protocol.
- `DEVELOPMENT_LOG.md` — running session notes.
- `CODEBASE_REFERENCE.md` — this manual.
