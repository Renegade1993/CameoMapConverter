# CLAUDE.md - Cameo Map Converter Project

**MANDATORY:** Read this file at the start of EVERY session working on this project.

## Standard Session Opening Briefing

Before doing any analysis or implementation in a new session, follow this checklist. It is also the template for any handoff/briefing delivered at the start of a session.

### 1. Mandatory Ingestion (do this first)

1. **Ingest all global and project instructions**
   - `C:\Users\Kmoney\AppData\Roaming\Devin\SESSION_START_PROTOCOL.md`
   - `C:\Users\Kmoney\.claude\CLAUDE.md` (global)
   - `C:\Users\Kmoney\Documents\AI Projects\Cameo Work\CLAUDE.md` (workspace)
   - This file (`Cameo Map Converter\CLAUDE.md`) — project-specific memory and rules.

2. **Familiarize yourself with the reference manual**
   - `Cameo Map Converter\CODEBASE_REFERENCE.md` (primary technical reference).
   - Focus on sections 2-3 (layout/formats), 4 (pipeline), 5 (resource algorithm), 7 (GUI), 11 (troubleshooting), and 12 (baseline recommendations).

3. **Read the current state**
   - `Cameo Map Converter\DEVELOPMENT_LOG.md` — most recent entry at the top.

### 2. Session Opening Structure

When starting a session, deliver a short briefing covering:

- **Session ID:** `SID-YYYYMMDD-xxxxxx`
- **Goal:** One-sentence description of what this session will accomplish.
- **Current baseline:** Last completed work, known open issues, test status.
- **Scope & user intent:** What is in scope and what is out of scope.
- **Work plan:** First step, verification step, documentation update step.
- **Key references:** Files/sections that will matter most.

### 3. Session End Checklist

Before marking a session complete:

- [ ] Tests pass (`pytest`, `validate_resource_distribution.py`, `py -m py_compile`)
- [ ] `DEVELOPMENT_LOG.md` updated with the session entry
- [ ] `CODEBASE_REFERENCE.md` updated if architecture/files changed
- [ ] `CLAUDE.md` memory section updated if new patterns discovered
- [ ] Distribution or build artifacts regenerated if needed
- [ ] **Source zip created alongside every release zip** (`Distribution\CameoMapConverter_vX.Y.Z_source.zip` from `Distribution\source\`)
- [ ] Handoff delivered in chat if user requested one

## ⚠️ Known Environment Bug — Cowork bash mount is STALE (do NOT re-investigate each session)

The Linux **bash** sandbox reads files through a virtiofs→FUSE mount that **caches stale content AND
metadata** and only refreshes when Cowork itself writes a file. External writes (a prior session, the
Claude Code tab, Notepad/VS Code/Excel, sync tools) never reach it; `cat`/`wc`/`stat`/`ls -la` silently
report the OLD size/content with no error. This is a confirmed **open Anthropic bug**
(github.com/anthropics/claude-code/issues/38993; see also #45433), NOT file corruption. It survives
session restarts AND full app reinstalls, so do not spend calls re-diagnosing it — follow the rules below.

**Ground rules (cheap + reliable):**
1. **File tools (Read/Write/Edit/Grep) = ground truth.** In this build they hit the real host files
   directly, not the cache. Trust them over bash for every file's contents. (Verified: `requirements.txt`
   reads 4 lines via Read, 2 lines via bash, same instant.)
2. **bash is for RUNNING code only**, never for reading source you care about.
3. **Refresh-through:** a file is reliable in the VM only after Cowork writes it via the file tools. Files
   you Edit this session are auto-refreshed; to refresh an un-edited module, re-write it identically with
   the file tools. (Verified: a file written via Write appears correctly in bash; writes are one-way VM→host.)
4. **Canary before trusting a run:** `python -m py_compile <all modules>` — a stale/truncated module fails
   to compile and names itself; refresh it, then run.

## Session Notes Protocol (MANDATORY)

Keep session notes procedurally — do not wait until the end:

1. **At the start of every session**, generate a UNIQUE SESSION ID — format `SID-YYYYMMDD-xxxxxx` (xxxxxx
   = random hex / unique suffix) — and create a new entry at the TOP of `DEVELOPMENT_LOG.md` headed with
   that ID, the goal, an `[IN PROGRESS]` marker, and a `last edited: YYYY-MM-DD HH:MM TZ` line. Keep the
   SAME ID for the whole session.
2. **Every time you update that entry during the session, MOVE THE WHOLE ENTRY BACK TO THE TOP** of the
   log (above all other sessions) and refresh its `last edited:` date + timestamp. The most-recently-
   touched session is always first in the file.
3. **As findings emerge**, append them to that entry immediately (diagnosis, evidence, root causes,
   decisions made with the user, plan). Treat the log as a live scratchpad, not a closing summary.
4. **Record evidence, not conclusions only** — include the actual measurements/commands that prove a
   claim (e.g. "pixel-diff: identical", "painted symmetry = 84%"), so later sessions can trust it.
5. **When the user makes a design decision**, write it down verbatim under that entry the same turn.
6. **At session end** (or when told we're switching sessions), drop the `[IN PROGRESS]` marker and add a
   short Status/Next-Steps block. (Handoffs: see Handoff Protocol — produced only when the user asks, and
   delivered as a markdown copy box in chat, never written to a file unless told.)

## Project Overview

**Current Scope:** Converts Combined Arms (CA/Balance Iteration) tournament maps to Cameo mod format. Python-based converter that transforms .oramap files (ZIP archives containing map.yaml, map.bin, assets) from CA format to Cameo-compatible format.

**Long-term Vision:** Universal game map converter supporting bidirectional conversion between any game format. The system should be architected to handle:
- Any source game format → Any target game format
- Bidirectional conversion (A→B and B→A)
- Format-specific protocol libraries (like the current BI protocol system)
- Extensible architecture for adding new game formats

**Current Implementation:** Combined Arms → Cameo conversion for OpenRA/CA tournament maps from the Balance Iteration (BI) 4.3-4.6 era.

**Current Status:** Resource distribution REBUILT and verified (2026-06-19) — aggressive RESOURCE_RICHNESS
knob (0.5≈all ore, 1.0=balanced/no gems, 1.5≈all gems) with guaranteed mirror symmetry and node/field
coherence; 100% on all 10 test maps. Remaining before distribution: a few map *translation* fixes.

## Quick Reference — Where to Look

**`CODEBASE_REFERENCE.md`** is the first-stop technical reference for any session: repository layout, data formats, pipeline steps, module responsibilities, resource algorithm, GUI notes, tests, dev tools, and common gotchas. It is kept up to date at the end of each session.

- For **start-of-session ingestion and briefing structure**: `CLAUDE.md` section *Standard Session Opening Briefing*.
- For **file layout and data formats**: `CODEBASE_REFERENCE.md` sections 2-3.
- For **conversion pipeline details**: `CODEBASE_REFERENCE.md` section 4.
- For **resource algorithm**: `CODEBASE_REFERENCE.md` section 5.
- For **GUI and paint mode**: `CODEBASE_REFERENCE.md` section 7.
- For **recent fixes and current state**: `DEVELOPMENT_LOG.md` (most recent entry at the top).
- For **baseline improvement recommendations**: `CODEBASE_REFERENCE.md` section 12 (prioritised High/Medium/Low).
- For **which documents were archived and why**: `CODEBASE_REFERENCE.md` section 14.

## Resource Re-classification Algorithm (IMPLEMENTED 2026-06-19 — see resource_reclassification.py)

> The spec below is the original design brief. The shipped implementation refines it: the knob is an
> aggressive boundary-sweep (0.5≈all ore / 1.5≈all gems) and symmetry is enforced via node **orbits**
> tiered by average distance, not via subrange thresholds. See "Current Resource Algorithm" further down.

### Problem
Current implementation has wrong math resulting in all resources becoming gems. Need to implement proper distance-based tier assignment.

### Algorithm Specification

**Resource Tier Order:**
Ore → green tiberium → blue tiberium → red tiberium → Gold tiberium → gems (extreme cases or with RESOURCE_RICHNESS knob over 1.0)

**Core Algorithm:**
1. For each resource node, calculate its distance to the nearest spawn (this is the node's "distance to nearest spawn")
2. Find the minimum distance-to-nearest-spawn across all nodes (probably 8-20)
3. Find the maximum distance-to-nearest-spawn across all nodes (probably 40-80 on smaller maps)
4. This establishes the total range: [min_distance, max_distance]
5. Divide the total range into subranges for each resource tier
6. For each node, check which subrange its distance-to-nearest-spawn falls into
7. Assign the corresponding resource tier to that node
8. Change all resources around each node to match the node's assigned tier

**RESOURCE_RICHNESS Knob Behavior:**
- If RESOURCE_RICHNESS < 1.0 (turned down): Gems become impossible (gem subrange = 0), gold's subrange shrinks, ore's subrange expands
- If RESOURCE_RICHNESS > 1.0 (turned up): Gold's subrange share goes down (gold shifts to shorter distances), gems subrange share grows
- If RESOURCE_RICHNESS = 1.0 (default): Equal or balanced distribution of subranges

**Key Insight:** Each node is evaluated only against its nearest spawn, not all spawns. This prevents one player's base ore from being factored as another player's furthest ore.

### Implementation Plan

**Phase 1: Nearest-Spawn Distance Calculation (1 hour)**
- For each node, calculate distance to each spawn, find minimum
- Store as node's distance value

**Phase 2: Global Range Calculation (30 minutes)**
- Find min/max of node-to-nearest-spawn distances across all nodes
- Establish global range [min_dist, max_dist]

**Phase 3: Subrange Division (1 hour)**
- Divide total range into subranges based on RESOURCE_RICHNESS
- Handle knob behavior (< 1.0, = 1.0, > 1.0)

**Phase 4: Tier Assignment (1 hour)**
- For each node, check which subrange its distance falls into
- Assign corresponding tier

**Phase 5: Resource Field Update (1 hour)**
- Change resources around nodes to match assigned tier
- Update map.bin with new resource types

**Total: 4.5 hours**

### Testing Requirements

- Test on Abendland 1v1 map
- Test on Cow Level map
- Test with RESOURCE_RICHNESS = 1.0 (balanced)
- Test with RESOURCE_RICHNESS = 0.5 (gems impossible)
- Test with RESOURCE_RICHNESS = 1.5 (gems enabled)
- Print test cases showing distance distributions and tier assignments

## Key Technical Context

### Coordinate System (CRITICAL)
- **Game/editor coordinates map directly to map.bin coordinates** - NO OFFSET NEEDED
- Game (x,y) -> map.bin (x, y) directly
- Column-major cell index: `cell = x * height + y`
- No 1-based to 0-based conversion needed
- Verified on Cow Level map: Game (80,79) -> map.bin (80,79): template=225 ✓

### map.bin Binary Format
- **Format 2** (all CA maps use this): 17-byte header with offsets
- TilesOffset: always 17 for these maps
- ResourcesOffset: always 17 + W*H*3
- Tile data: W*H*3 bytes (template 2 bytes + index 1 byte)
- Resource data: W*H*2 bytes (type 1 byte + density 1 byte)
- Column-major iteration: `for i in range(width): for j in range(height): cell = i * height + j`

### Resource System
**Cameo Resource Indices:**
- 1: Tiberium (MaxDensity: 35, Node: SPLIT2, SPLIT3)
- 2: BlueTiberium (MaxDensity: 30, Node: SPLITBLUE, SPLITBLUESMALL)
- 3: Ore (MaxDensity: 40, Node: MINE)
- 4: Gems (MaxDensity: 15, Node: GMINE)
- 5: RedTiberium (MaxDensity: 25, Node: SPLITRED, SPLITREDSMALL)
- 6: GoldTiberium (MaxDensity: 20, Node: SPLITGOLD, SPLITGOLDSMALL)

**RA Source Indices:**
- 1: Ore (MaxDensity: 12)
- 2: Gems (MaxDensity: 12)

**Conversion:** RA index 1 (Ore) → Cameo index 3 (Ore), RA index 2 (Gems) → Cameo index 4 (Gems)

### Current Resource Algorithm (rebuilt 2026-06-19, in `resource_reclassification.py`)
- **Nearest-spawn distance** per node (not per-spawn normalization).
- **Symmetry orbits:** `detect_symmetries()` finds the map's point/mirror symmetry from spawns+nodes;
  `build_orbits()` groups mirror/rotational nodes. Each orbit is tiered by its **average** distance →
  mirror-paired nodes ALWAYS get the same tier (the balance guarantee).
- **Aggressive boundary-sweep knob** (`tier_for_fraction`): 0.5≈all ore, 1.0=even Ore→Gold (0 gems),
  1.5≈all gems; monotonic, saturating past ~0.5/~1.5; gems only when richness>1.0.
- **Painting** (`assign_resources`): field tier = owner node tier; mirror field-pairs canonicalized to
  one tier; node actors conform to the field they sit in. Validated: painted symmetry 100%, 0 incoherent.

- **Distribution mode** (`--distribution`, global `DISTRIBUTION_MODE` in resource_reclassification):
  `balance` (DEFAULT) = **distance-gated contestedness**. Per node: `dn` = normalized nearest-spawn
  distance; `cn` = normalized contestedness (each spawn = linear falloff over R=2·mean(spawn→centroid);
  contest = summed influence minus the dominant spawn's); and `home_gate = clamp((d-HOME)/HOME, 0, 1)`,
  which is 0 inside the home zone and 1 by 2·HOME. Node value is the **additive, home-gated** form
  `value = dn + BALANCE_BIAS·cn·home_gate`, so contestedness can't light up next to a base. Gradient:
  ore at base → green/blue tiberium mid-ground → gold on the far contested strips.
  `BALANCE_BIAS` (`--balance-bias`, default `3`) = contest pull strength: `0` acts like `distance`,
  higher = stronger (can over-pull). `BALANCE_HOME_RADIUS` (`--balance-home-radius`, default `15` grid
  cells) = the safe home zone; resources within it stay low-tier no matter how contested.
  `distance` = richest at the outer edges (value = nearest-spawn distance). Both keep 100% symmetry and
  obey the richness knob. Field tiering: a field takes the richest tier among nodes within
  MERGE_MARGIN(=4) of being its closest, so contested blobs keep their top tier (`assign_resources`).

- **Symmetry detection (expanded 2026-06-24):** `detect_symmetries()` in `resource_reclassification.py`
  deduces the map's symmetry from the spawn and resource-node geometry. It tests point reflection,
  vertical/horizontal mirrors, both diagonal mirrors, and 90°/270° rotations. A transform is accepted
  if the median mapping error is within tolerance, so imperfect human-built maps still work. The set of
  detected transforms is stored in `_last_assign_fields` and drives the GUI's mirror-paint feature.

**Knob source of truth:** the converter's module global `RESOURCE_RICHNESS` (set by `--richness`), read at
call time by `assign_resources`. Validate with `validate_resource_distribution.py` (tests both modes).

**LIMITATION (unchanged):** source maps have clustered node placement, so at r=1.0 the *count* per tier
is uneven (boundaries are even by distance, but few nodes sit in the mid bands). This is map data, not the
algorithm — the knob extremes and symmetry are exact regardless.

## Recent Critical Fixes (2026-06-24)

1. **Node/field tooltip consistency** - `_last_assign_nodes` now stores the actual field tier via
   closest-field lookup, not the algorithm result. Preview and tooltips match the converted map.
2. **Even mode node/field mismatch** - `node_res[i]` is reconciled against the final field tier after
   even-mode quota assignment and after the symmetry pass.
3. **Node cell painting** - The cells occupied by resource node actors are now painted to match the
   surrounding field tier.
4. **Symmetry painting rewrite** - Manual mirror-paint uses the detected transforms from field metadata
   instead of fragile node-displacement inference. Works for point, mirror, diagonal, and rotational
   symmetries. Added self-mapping skip and target deduplication.
5. **Expanded symmetry detection** - `detect_symmetries()` now tests diagonal mirrors and 90°/270°
   rotations, with median-error tolerance for imperfect maps.
6. **Legend labels** - Resource legend/count labels now show plain resource names (Ore, Gems, etc.)
   without "Mine", "Field", or "Tree" suffixes.

## Recent Critical Fixes (2026-06-18)

1. **Format 2 map.bin header bug** - Was hardcoding Format 1 offsets (tile data at byte 5), but all source maps use Format 2 (tile data at byte 17). Fixed by reading fmt byte and branching.
2. **Column-major coordinate system** - All functions now use correct `cell = col*H + row`
3. **Template 221→591 (2x1)** - Changed to 221→2 (water, 1x1) to prevent partial rendering
4. **assign_resources coordinate transform** - Was 180° rotation, now direct col=x, row=y
5. **rbase hardcode** - Was `5 + W*H*3` (Format 1), now `mb.res_off`
6. **Raw tile index access** - Was `5 + i*3+2`, now `mb.tiles_off + i*3+2`
7. **Source resource remap** - New `remap_source_resources()` converts RA→Cameo indices
8. **Water fill functions** - Re-enabled with correct column-major neighbor calculation

## Known Issues & Limitations

### Rock Palette Issue
- Rock sequences use `.des` files (desert palette format) but render with `staticterrain` palette (ra_temperat.pal) on RA_TEMPERAT tileset
- This is a Cameo mod-level rendering problem, not a converter issue
- Workaround: Drop rock actors entirely to avoid palette rendering issues
- Historical deep-dive archived to `Cameo Work\to delete\Cameo Map Converter docs archive 2026-06-24\ROCK_PALETTE_ISSUE_FOR_DEV_TEAM.md`; current behaviour is in `CODEBASE_REFERENCE.md` Section 11

### Water Crossing Detection
- **RESOLVED (2026-06-19):** `water_crossing_detect.py` implements correct sub-cell terrain lookup
  using the per-cell Terrain: field from `ra_temperat.yaml`, not template-level guessing.
- Algorithm: 225 strips pinched by Water/River on opposite sides → ford template (590/591 orientation).
  225 strips in open land = decoration, left alone.
- Integrated in `convert_map()` after `remap_templates()`, before `fill_stray_water()`.
- Tile 225 in open land → Clear (was grass, unchanged behavior for non-crossing use).

### BI Version Architecture
- BI refers to "Balance Iteration" - community balance package versions (4.3, 4.4, 4.5)
- BI has NO custom tilesets/templates across any versions
- Only gameplay/mechanic changes (unit stats, faction bonuses, etc.)
- Tile 225 issue is a mapper convention, not a BI version feature
- Decision: Single base translation matrix with optional version-specific overrides

## File Structure

```
Cameo Map Converter/
├── cameo_map_converter.py             # Main converter script (CLI, --richness, --distribution)
├── resource_reclassification.py       # Symmetry-aware resource tiering (the knob)
├── water_crossing_detect.py           # Water-crossing detection module (ford detection)
├── minimap_render.py                  # In-process minimap renderer
├── cameo_converter_gui.py             # PyQt5 GUI wrapper
├── converter_logging.py               # Logging config
├── validate_resource_distribution.py  # Painted-map pass/fail validator (90/90 baseline)
├── cameo_actors.txt                   # Valid Cameo actor names
├── actor_matrix.yaml                  # Actor translation rules
├── template_matrix.yaml               # Tile template translation rules
├── bi_protocol.yaml                   # BI version external-ref rules (custom pipe format, not std YAML)
├── ra_temperat.yaml                   # RA_TEMPERAT tileset terrain table (tab-indented OpenRA format)
├── converter_config.yaml              # CLI config knobs (standard YAML, all keys consumed)
├── Convert Maps.cmd / Build Executable.cmd / Create Distribution.cmd  # Windows launchers
├── maps/                              # Source .oramap files (CA format)
├── dev_tools/                         # Debug/diagnostic scripts (not part of production)
│   ├── analyze_resources.py / check_conversion.py / check_coordinates.py
│   ├── extract_actors.py / render_corrected_distribution.py / test_logging.py
├── tests/                             # pytest suites (21 tests, unit + integration)
├── docs/                              # CONVERTER_PATCH_LIBRARY, REPLACEMENT_GUIDE, patch notes
├── README.md / QUICKSTART.md / DEVELOPER_NOTES.md / CLAUDE.md / DEVELOPMENT_LOG.md
├── CODEBASE_REFERENCE.md              # consolidated technical reference
```

Regenerable outputs (`maps/converted*`), superseded plans, and old tests were moved to `Cameo Work/to delete/` during the 2026-06-19 cleanup. A full pre-change backup is in `Cameo Work/Backups/`.

## Backup and Cleanup Locations

Before any destructive or disruptive work, take a timestamped full-project backup under:
- `C:\Users\Kmoney\Documents\AI Projects\Cameo Work\Backups\Cameo_Map_Converter_YYYY-MM-DD_HH-MM-SS`

During cleanup, move files to the appropriate location instead of deleting them:
- **Disposable/cache files** (e.g. `__pycache__`, `.pytest_cache`, `log` output, debug renders) →
  `C:\Users\Kmoney\Documents\AI Projects\Cameo Work\to delete\`
- **Files that might be useful later** (old crash logs, archived dev logs, pre-beta reports, superseded guides) →
  `C:\Users\Kmoney\Documents\AI Projects\Cameo Work\Backups\Archived\`

Never delete project files directly; always relocate them to `to delete\` first.

## Project Hygiene Checklist (apply every session)

Keep the project root clean and tidy as a default state, not a one-time event:

1. **Remove regenerable artifacts before finishing**
   - `__pycache__` / `.pytest_cache` / `build` / `dist` / `log` / debug PNGs / crash logs
   - Move them to `Cameo Work\to delete\` (never delete directly).

2. **Keep only current deliverables in the root**
   - One current `CameoMapConverter.exe`.
   - One current `Distribution\` package containing:
     - Release zip: `CameoMapConverter_vX.Y.Z.zip`
     - Source zip: `CameoMapConverter_vX.Y.Z_source.zip` (must be created alongside every release zip)
   - No stale backups, archived logs, or old reports in the root.

3. **Archive or delete superseded documentation**
   - Old revert guides, pre-beta reports, archived dev logs → `Cameo Work\Backups\Archived\`.
   - Disposable drafts → `Cameo Work\to delete\`.

4. **Verify after every build/test run**
   - `py -m py_compile` on all changed `.py` files.
   - `py -m pytest tests` passes.
   - `py validate_resource_distribution.py` passes.
   - Sweep any cache the tools regenerate.

5. **Leave the workspace cleaner than you found it**
   - If a session generates temporary files, remove them before ending.

## Handoff Protocol

When the user requests a handoff (e.g., "stop work and hand the session off"), produce a handoff summary in the following markdown format and deliver it as a copy box in chat (do not write it to a file unless explicitly told):

```markdown
# Handoff — Cameo Map Converter Session

## Current state
- Project path: `C:\Users\Kmoney\Documents\AI Projects\Cameo Work\Maps and Solutions Scripts work 06-15-2026\Cameo Map Converter`
- Code compiles: `py -m py_compile cameo_converter_gui.py cameo_map_converter.py` ✅
- Tests pass: `py -m pytest tests` → 21/21 ✅
- Last validator run: `py validate_resource_distribution.py` → ALL CHECKS PASSED ✅

## What was done this session
[Brief summary of work completed this session]

## Still pending / open
[Unresolved issues, blockers, or work that needs to continue next session]

## Recent backups
[Location of any backups created this session]

## Files changed
[List of files modified this session]

## Debug data available
[Any debug files or logs that may be useful for next session]
```

**Key points:**
- HANDOFF.md is retired — do not create, read, or maintain it
- Session record lives in `DEVELOPMENT_LOG.md` (see Session Notes Protocol)
- Only produce a handoff when the user explicitly asks for one
- Deliver as a markdown copy box in chat, not written to a file (unless user specifically says to)
   - If a file might be useful later, archive it; if it is disposable, move it to `to delete\`.

## Claude MCP Server Status

The Claude Code MCP server is currently **unavailable** unless explicitly re-enabled by the user. Deep code review and analysis in this project is performed by the Devin agent directly rather than via the MCP dispatch. Update this note if the MCP server is re-enabled.

## Source Code Locations

- OpenRA engine: `C:\Users\Kmoney\Documents\AI Projects\Cameo Work\Other Game Sources\OpenRA-playtest-20260222 (source)`
- Cameo mod: `C:\Users\Kmoney\Documents\AI Projects\Cameo Work\Cameo-mod-playtest-20260614 (source)`
- Installed mod: `C:\Users\Kmoney\AppData\Roaming\OpenRA\maps\cameo\playtest-20260614`

## Conversion Pipeline

1. Unzip source map to temp directory
2. Parse and transform map.yaml (RequiresMod, Tileset, Categories, remove CA YAMLs)
3. Transform map.bin (remap templates, fill water, assign resources)
4. File filtering (keep map.yaml, map.bin, map.png, SHPs, PALs, AUDs; drop CA YAMLs)
5. Repackage as ZIP

## Testing Protocol

**NEVER manually copy individual maps for testing. Always go through the systemic converter.**

Run batch conversion via wrapper, then test specific maps in OpenRA.

## Current Status (as of 2026-06-25)

The project is **production-ready** for CA→Cameo conversion:
- Resource distribution: 3 modes (balance/distance/even), mirror-symmetry guaranteed, 90/90 validated
- Water crossings: ford detection live (`water_crossing_detect.py`)
- GUI: PyQt5 launcher with live preview and hand-paint override
- Build: single-file exe via PyInstaller; distribution package via `Create Distribution.cmd`
- Build isolation: `pyi_rth_cameo_isolation.py` runtime hook clears `PYTHONPATH`/`PYTHONHOME` and locks `sys.path` to the bundle; `cameo_converter_gui.py` dispatches to the bundled `cameo_map_converter.py` when the frozen EXE is re-executed as a conversion subprocess. Both prevent the bundled Python 3.12 runtime from mixing with a system Python 3.13/3.14 on end-user machines.
- Tests: 27 pytest (unit + integration) + 90-check resource regression harness

**Next development priorities (when resumed):**
- Verify the Aedis Python 3.14 DLL conflict is fully resolved with the new dispatch fix; capture any remaining traceback if not
- Map *translation* quality: remaining actor/template edge-cases flagged in DEVELOPMENT_LOG
- Potential: node repositioning / advanced distribution patterns (post-production backlog)

## Important Conventions

- **Column-major iteration only** - All map.bin operations must use `cell = col*H + row`
- **Direct coordinate mapping** - No offset conversion between game and map.bin coordinates
- **Format 2 header** - All CA maps use Format 2 with 17-byte header
- **Resource index remapping** - Always convert RA indices to Cameo indices before assignment
- **File filtering** - Only keep map.yaml, map.bin, map.png, SHPs, PALs, AUDs; drop CA YAMLs

## Handoff Protocol

**The HANDOFF.md standard is retired. Never create, read, or maintain a HANDOFF.md file** (there is no
longer one in this project). Do not treat "read/update the handoff" as a routine session step.

**Do NOT produce a handoff unless the user explicitly asks for one.** The user does not want unprompted
handoffs written to any file.

**When the user DOES ask for a handoff:** deliver it in the chat as a **copy box** — a single fenced
```` ```markdown ```` code block the user can copy-paste — NOT as a file. Do not write it to any file
unless the user specifically says to.

**Always** keep the running session record in DEVELOPMENT_LOG.md (see Session Notes Protocol above) — that
is the canonical memory future sessions read from, independent of any handoff request.

## Discord Release Announcement Template

Use this markdown template for quick CMC release/hotfix announcements in Discord. The Google Drive link is stable and should not change.

### Template

```markdown
Hey Cameo Map Converter Users— quick heads up:

<problem description>. <root cause in one sentence>.

**<version/name>** <one-line fix summary>.

**[Download](https://drive.google.com/drive/folders/1lnB7vb8N97Hk-CPfSffOl41_PlQnrNdT?usp=drive_link)**

No other functionality changed — just unzip and run as usual. If anyone still hits <issue> after this <release/hotfix>, ping me with the error.
```

### Example: v0.76-beta-hotfix1

```markdown
Hey Cameo Map Converter Users— quick heads up:

If you installed the latest Python from python.org (Python 3.14) and CMC crashed when you pressed **Convert**, that's now fixed. The bundled EXE was accidentally using your system Python for the conversion step, which caused a Python DLL mismatch.

**Hotfix 1** keeps the conversion inside the bundled runtime, so it works regardless of what Python you have installed.

**[Download](https://drive.google.com/drive/folders/1lnB7vb8N97Hk-CPfSffOl41_PlQnrNdT?usp=drive_link)**

No other functionality changed — just unzip and run as usual. If anyone still hits the crash after this hotfix, ping me with the error.
```

## Memory

- GitHub repository: `https://github.com/Renegade1993/CameoMapConverter`
- Latest release: `https://github.com/Renegade1993/CameoMapConverter/releases/tag/v0.76-beta-hotfix1`
- License: pending — Kmoney prefers a permissive license (e.g., MIT) that retains minimal rights to him and belongs to the community.
- The compiled EXE and distribution zips are **GitHub Release assets**, not files in the git repo.