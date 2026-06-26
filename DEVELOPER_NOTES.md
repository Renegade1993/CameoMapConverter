# Developer Notes — Cameo Map Converter (v0.6 — post-beta, all algorithms stable)

These are the notes a developer picking up this project should read first. They complement the deeper
references: `CODEBASE_REFERENCE.md` (full system design and tiering math), `README.md` (end-user usage
and release notes), and `DEVELOPMENT_LOG.md` (recent fixes and current state).

It onboards OpenRA / Combined Arms (CA) tournament maps into the Cameo mod: rewrites the map header
(`RequiresMod`, `Tileset`, `Categories`, `Title`, `Author`), strips CA-custom rules/sequences/weapons/
voices/notifications and bundled assets, drops or remaps custom palettes to Cameo's stock palettes,
validates every placed actor against `cameo_actors.txt` (keep / remap via `ACTOR_OVERRIDES` / drop so
the map never crashes on "unknown type"), re-types each contiguous resource field by a symmetry-aware
distance-to-spawn algorithm, regenerates the in-game preview `map.png`, and repackages a clean
`.oramap`.

## Module map

The runtime is a small set of cooperating modules; the GUI and CLI share the same conversion core.

- `cameo_map_converter.py` — the core. `ConverterConfig` (centralized config + YAML/JSON load/save),
  input validators (`validate_oramap_file`, `validate_map_dimensions`, `validate_resource_config`,
  `validate_file_path`), the `.oramap` pipeline (`convert_map`), the `map.bin` reader/writer (`MapBin`),
  the actor matrix, template remapping, water fills, the resource assignment (`assign_resources`), the
  in-process preview API used by the GUI (`build_preview_base`, `render_preview`), and `main()` (CLI).
- `cameo_converter_gui.py` — PyQt5 GUI. `JSONSettings` (settings persistence to `settings.json`),
  `PreviewWorker` / conversion workers (QThreads), the main window, the live preview, and the logging
  menu. Entry point is `main()`.
- `resource_reclassification.py` — Symmetry detection and the nearest-spawn node tiering.
  Public API: `assign_node_tiers_corrected` (single entry point), `assign_node_tiers_debug` (debug
  dict variant), `assign_node_tiers_even` (even cell-count balancer), `_active_tiers` (richness→type
  list), `detect_symmetries`, `build_orbits`, `TIER_ORDER`, `DISTRIBUTION_MODE`, `BALANCE_BIAS`,
  `BALANCE_HOME_RADIUS`. Do not edit the symmetry/orbit logic without explicit sign-off; the balance
  guarantee depends on it.
- `water_crossing_detect.py` — tileset terrain table loader + water-crossing detection/conversion.
- `minimap_render.py` — shared minimap renderer used for both the in-game `map.png` and the GUI preview,
  so a preview is pixel-identical to a full conversion at the same settings.
- `converter_logging.py` — singleton `ConverterLogger`: console handler plus optional per-log-type
  rotating file handlers (`debug.log`, `info.log`, …) under a `log/` directory.

Data files the core reads (bundled into the exe, and shipped in `source/` for run-from-source):
`cameo_actors.txt` (valid Cameo actor names), `actor_matrix.yaml`, `template_matrix.yaml`,
`bi_protocol.yaml`, `converter_config.yaml`.

## Conversion pipeline (order matters)

`convert_map()` runs, roughly: validate `.oramap` → extract → parse `map.yaml` → detect source mod /
tileset / BI version → header rewrites → strip external refs + palettes → apply the actor matrix
(keep/remap/drop) → load `map.bin` → remap templates → remap source resource indices (1:1) → water
crossing detection (if the tileset YAML is found) → fill stray water / grass → `assign_resources`
(symmetry-aware tiering, only when spawns exist and remap is enabled) → regenerate `map.png` →
repackage kept files into a new `.oramap`. `render_preview()` mirrors this up to `assign_resources`
and is cached per (path, mtime), recomputing only tiering when the knobs change.

## Configuration

`ConverterConfig` holds defaults. A YAML/JSON config can be loaded via `--config FILE` (CLI) or the
GUI. Three attributes are **sets** (`KEEP_NAMES`, `SOURCE_RESOURCE_ACTORS`, `ACTOR_NEVER_DROP`); because
JSON/YAML have no set type, `save_to_file` writes them as sorted lists and `load_from_file` restores
them to sets — keep that invariant if you touch config I/O (there's a round-trip test in
`tests/unit/test_config.py`). After a `--config` load, `main()` re-syncs the uppercase module-global
aliases from the class so the loaded values take effect; explicit CLI knobs are applied afterward so
they still win.

The single resource tuning knob is `--richness` (0.0–2.0; 0.5≈all Ore, 1.0≈balanced/no gems, 1.5≈all
gems). `--distribution` is `balance` (default; richest in the contested centre), `distance` (richest
at the outer edges), or `even` (position-agnostic cell-count equalisation), with `--balance-bias` and
`--balance-home-radius` refining balance mode. `--no-remove-actors` keeps the palette-issue rock/stone/
bush actors instead of dropping them (see `REMOVE_PROBLEMATIC_ACTORS` global and `PALETTE_ISSUE_ACTORS`
frozenset in `cameo_map_converter.py`).

## Build & test

- **Build the exe (Windows only):** `Build Executable.cmd` → runs `py -m PyInstaller build_exe.spec`,
  producing a single-file `CameoMapConverter.exe`. The spec is windowed (`console=False`) and bundles
  all `.py` modules and data files as `datas`, so the exe needs no external files at runtime. Switch
  `console=True` in `build_exe.spec` for a diagnostic build that shows stdout live.
- **pytest suite** (`pytest`): 21 fast unit + integration tests covering config validators and
  basic conversion correctness. Config in `pyproject.toml`; tests under `tests/`. These are fast
  structural checks (< 1 s total) — they do NOT test resource distribution quality.
- **Resource distribution regression harness** (`py validate_resource_distribution.py`): the real
  algorithmic regression suite. Runs all 3 modes × 10 maps × 3 richness values = 90 checks.
  Validates 100% mirror symmetry, tier variety (≥ min(6, n_mirror_pairs) types), and node/field
  coherence. Run this after any change to `resource_reclassification.py` or `assign_resources`.
  Current baseline: 90/90 PASS.
- **Batch convert from a terminal:** run the converter over the `maps/` folder; expect 39/39 maps to
  convert with 0 errors.

## Known issues / gotchas (read before debugging)

- **Cowork stale-mount bug (#38993).** Inside the Cowork desktop app, the bash sandbox reads a stale
  virtiofs→FUSE mirror of the project. Treat the file tools (Read/Write/Edit/Grep) as ground truth and
  use bash only to *run* code. As of this beta, `cameo_map_converter.py` is stuck stale in the sandbox
  (bash sees a truncated copy; the host file is correct). This is why the distribution is assembled by
  the Windows packager script, never by copying inside the sandbox. A plain terminal (no VM mount) is
  unaffected. See `CLAUDE.md` for the full protocol.
- **GUI logging — wrapped but not root-caused.** `save_logging_settings` crash was fixed (`setValue`
  instead of dict item-assignment). A second silent failure on the first `enable_log_type` call was
  never fully reproduced. `toggle_log_type` is now wrapped so it cannot hard-crash the GUI, and
  `main()` installs `sys.excepthook` + `faulthandler` that write `gui_crash_log.txt` next to the exe.
  If a logging crash reappears: rebuild the exe, reproduce, read `gui_crash_log.txt`. Not a blocker.
- **Water-crossing detection depends on an external tileset YAML** two levels up from the script
  (`../../Cameo-mod-playtest-…/mods/cameo/tilesets/ra_temperat.yaml`). If absent (as in a standalone
  distribution), detection is skipped gracefully — conversion still succeeds; crossings can be added in
  the map editor.
- **Rocks are dropped by default** (open Cameo mod issue): Cameo's rock1–7 use `.des` (desert)
  palettes that render wrong on RA temperate. This is a mod-side palette issue, not a converter bug.
  The 43 palette-issue actors are listed in `PALETTE_ISSUE_ACTORS` (auto-derived from
  `ACTOR_OVERRIDES`). `REMOVE_PROBLEMATIC_ACTORS = True` (default) drops them; `--no-remove-actors`
  sets it False so they pass through. Restore the mappings when/if the Cameo mod fixes the palette
  — the toggle will then be redundant. Status as of 2026-06-22: still unfixed in mod.
- **`resource_reclassification.py` — symmetry/orbit logic is sensitive.** The balance guarantee lives
  in `build_orbits` and `detect_symmetries`. `assign_node_tiers_even` and `assign_node_tiers_debug`
  are safe to extend; do not alter the orbit-building path without running the full validator suite.

## Diagnostic / dev tools (`dev_tools/`)

Standalone scripts not part of the production pipeline. Run from the project root:
- `dev_tools/analyze_resources.py` — inspect resource node distribution on a source map
- `dev_tools/check_conversion.py` — compare actor lists between original and converted maps
- `dev_tools/check_coordinates.py` — debug coordinate alignment issues
- `dev_tools/extract_actors.py` — dump actor names/positions from a raw .oramap
- `dev_tools/render_corrected_distribution.py` — render resource tier PNGs for visual diagnostics
- `dev_tools/test_logging.py` — manual smoke-test for the converter_logging module

None are imported at runtime; none are required for builds or tests.

## Extension points

Actor handling is data-driven via `cameo_actors.txt` (regenerate with `--dump-actors RULES_DIR`) and
`ACTOR_OVERRIDES` / `actor_matrix.yaml`. Tileset/template handling is in `template_matrix.yaml` and
`TILESET_WATER`. New source mods need an entry in `SOURCE_RES_REMAP`. Logging types are centralized in
`converter_logging.py`. Keep the GUI preview and `convert_map` in lockstep — `build_preview_base` must
mirror `convert_map`'s `map.bin` transform up to `assign_resources`, or previews will drift from output.

## Paint mode backend (v0.6)

The hand-paint override path flows through:

1. `assign_resources(…, paint_overrides=None)` — accepts `{"col,row": tier}` dict. After the
   symmetry-unification step, iterates field centers and applies any matching override. Field-center
   key format: `"%d,%d" % (round(cx), round(cy))`.
2. `_last_assign_fields` (module global in `cameo_map_converter.py`) — populated by `assign_resources`
   on every call with a list of `{center: (cx,cy), cells: [...], tier: "..."}` dicts. Reset each call.
3. `render_preview` — passes `settings.get("paint_overrides", {})` into `assign_resources`, then
   injects `_last_assign_fields` into the returned counts dict as `counts["__fields__"]`.
4. `on_preview_counts` (GUI) — pops `__fields__` from counts, stores it in `self._paint_field_cache`
   for the click handler; strips it before passing the dict to `update_resource_counts`.
5. `_handle_paint_click` — translates pixel position → map cell (via `_pixel_to_map_cell`), finds
   the nearest field center (via `_find_field_for_cell`), records an undo diff, updates
   `self._paint_overrides`, then calls `schedule_preview_refresh()`.
6. `get_current_settings` — includes `paint_overrides` so `PreviewWorker` picks it up automatically.

**Undo/redo stacks** (`_paint_undo_stack` / `_paint_redo_stack`) hold per-click diffs of the form
`{field_key: old_tier}`. Undo pops from undo, pushes to redo (with new_tier), and vice-versa.

## Preset storage (v0.6)

Presets are stored in `presets.json` adjacent to `settings.json` (the JSONSettings path). Structure:

```json
{
  "My preset": {
    "richness": 1.2,
    "distribution": "balance",
    "balance_bias": 3.0,
    "balance_home_radius": 15.0,
    "remap_resources": true,
    "remove_actors": true
  }
}
```

Methods: `_presets_path`, `_load_presets`, `_save_presets`, `_refresh_preset_combo`,
`save_current_as_preset`, `load_selected_preset`, `delete_selected_preset`.
