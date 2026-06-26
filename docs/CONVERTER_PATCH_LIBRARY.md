# Converter Patch Library

This document serves as a comprehensive library of all patches, fixes, and empirical observations made during the development of the Cameo map converter. Each entry documents the problem, solution, and implications for the conversion matrices.

---

## Template Remapping Patches

### Patch 1: Water Wreckage and Rocky Edge Tiles (157, 166)
**Problem:** Tiles 157 (water wreckage) and 166 (water rocky edge) were incorrectly mapped to water (2), causing water to appear where craggy rocks should be at coordinates like (41,78), (40,78), (40,79), (101,86), etc.

**Solution:** Changed mapping from `157: 2` and `166: 2` to `157: 255` and `166: 255` (clear terrain).

**Implications:**
- These CA-specific water decoration tiles don't have direct RA equivalents
- Mapping to clear terrain is safer than creating water where rocks should be
- Affected 40 cells of tile 157 and 27 cells of tile 166

**Code Location:** `TEMPLATE_REMAP["RA_TEMPERAT"]` lines 458-461

---

### Patch 2: Rocky Water Crossing Tile (221)
**Problem:** Template 221 (1x1 rocky water crossing) cannot safely map to 591 (2x1 water crossing) - only one cell would be set, leaving the adjacent cell with a wrong template.

**Solution:** Map to water (2) instead of 591 to ensure complete rendering.

**Implications:**
- 1x1 tiles cannot safely map to 2x1 tiles due to footprint mismatch
- Water (2) is the safe fallback for water crossing tiles
- Affected 14 placements

**Code Location:** `TEMPLATE_REMAP["RA_TEMPERAT"]` line 466

---

### Patch 3: Hill/Terrain Templates (400-406)
**Problem:** CA custom hill/terrain templates (400-406) don't exist in RA_TEMPERAT tileset.

**Solution:** Map to clear (255) except tile 406 which is preserved as cliff tiles.

**Implications:**
- CA decorative terrain features have no RA equivalents
- Clear terrain is the safe fallback
- Tile 406 (hill07) preserved as it represents actual cliff tiles at specific coordinates (85,55), (85,56)
- Affected 40 cells total

**Code Location:** `TEMPLATE_REMAP["RA_TEMPERAT"]` lines 470-477

---

### Patch 4: Context-Aware Tile 225 Remapping (BI 4.5 Specific)
**Problem:** Maps with BI 4.5 in name use tile 225 for different terrain types:
- Near beach/shore tiles (119, 122) = water crossings
- Near cliff/rock tiles (223, 224, 143, 163) = rocky grass/terrain

**Solution:** Implemented context-aware algorithm:
1. First pass: Identify tile 225 cells adjacent to beach/shore tiles (119, 122)
2. Second pass: Expand to include tile 225 cells adjacent to identified water crossings (handles clusters)
3. Third pass: Map identified water crossings to 591, others to 255

**Implications:**
- This patch is specific to BI 4.5 maps based on empirical testing
- BI (Balance Iteration) is a community balance package, not a mod
- BI version numbers (4.3, 4.4, 4.5) refer to balance ruleset versions
- Maps with BI in name have custom gameplay changes and balance modifications
- Algorithm handles clusters where middle cells don't touch beach/shore directly
- Results in 24 water crossings + 187 rocky grass tiles for Abendland (BI 4.5)
- **Note:** GitHub analysis shows BI has no custom tilesets/templates across versions - this is a mapper convention, not a BI version difference

**Code Location:** `remap_templates()` function lines 532-578

**Empirical Finding (BI 4.5):** Actual water crossings (83,13), (17,88) are already 591 in source map, suggesting BI 4.5 maps use RA water crossing tiles directly where appropriate.

---

## Actor Override Patches

### Patch 1: Tree Color Variants
**Problem:** CA has tree color variants (o=orange, p=pink, r=red, y=yellow, b=blue) that Cameo lacks.

**Solution:** Map all color variants to base tree types.

**Implications:**
- High ROI: Many tree placements use color variants
- Simplifies actor diversity while maintaining tree coverage
- Examples: t01o→t01, t01p→t01, t08b→t08, etc.

**Code Location:** `ACTOR_OVERRIDES` lines 51-68

---

### Patch 2: Tree Clumps
**Problem:** CA has tree clump actors (tgb, tgc1-3, tgd, tg1-2) that Cameo lacks.

**Solution:** Map to Cameo tree cluster actors (tc02-05).

**Implications:**
- Very high ROI: 602 placements affected
- Maintains forest density with appropriate Cameo equivalents
- Examples: tgb→tc04 (76 placements), tgc1→tc03 (139 placements)

**Code Location:** `ACTOR_OVERRIDES` lines 70-84

---

### Patch 3: Stones to Rocks
**Problem:** CA has stone actors (stones1-4, stones11-14) that Cameo lacks.

**Solution:** Map all stones to rock1.

**Implications:**
- Stones and rocks are functionally similar terrain decorations
- rock1 is the default 2x2 rock in Cameo
- High placement count: 150+142+143+88+56+121+82+29 = 711 placements

**Code Location:** `ACTOR_OVERRIDES` lines 86-96

---

### Patch 4: Rock Dimension Mapping
**Problem:** CA has various rock sizes (1x1, 1x2, 2x1, 2x2) that need appropriate Cameo equivalents.

**Solution:** 
- 1x1 rock variants → rock4 (1x1 Cameo rock)
- 1x2 stones → rock1 (default 2x2)
- 2x1 stones → rock5 (elongated 2x1)
- 2x2 rocks → rock1 (default 2x2)

**Implications:**
- Cameo has rock1-7 with different dimensions
- rock4 is the 1x1 variant, rock5 is 2x1, rock3 is 1x2
- Dimension mismatch can cause rendering issues
- Original mapping sent all to rock1, causing visual problems

**Code Location:** `ACTOR_OVERRIDES` lines 107-145

**Testing Result:** Converted map shows rock1, rock2, rock3, rock4 actors, confirming dimension mapping is working.

---

### Patch 5: Bushes to Rocks
**Problem:** CA has bush actors (sbush1-3, bush1-5, lbush1-2) that Cameo lacks.

**Solution:** Map bushes to rocks by size (rock1-5).

**Implications:**
- Cameo lacks bush actors entirely
- Rocks are the terrain decoration stand-in
- Size-based mapping preserves visual footprint

**Code Location:** `ACTOR_OVERRIDES` lines 143-155

---

## Palette Handling Patches

### Patch 1: Default Palette Dropping
**Problem:** CA maps contain custom palettes that may not render correctly in Cameo.

**Solution:** Default behavior is to drop custom palettes (`PALETTE_DEFAULT = "drop"`).

**Implications:**
- Cameo has stock palettes that should work for most cases
- Custom palettes can cause rendering issues if not compatible
- Specific overrides can be added for known good palettes

**Code Location:** Line 43

---

### Patch 2: Palette Override Attempts
**Problem:** Rock palette issues on RA temperate theater.

**Attempted Solutions:**
1. First attempt: Added bushpal.pal, bushpalv1.pal, dartmoorpal.pal, temperat.pal
   - Result: Caused blue tiberium palette issues
2. Second attempt: Added only temperat.pal (terrain palette)
   - Result: Still caused blue tiberium issues
3. Final solution: Removed all palette overrides

**Implications:**
- Rock palette issue appears to be a Cameo mod-level rendering problem
- Not a converter issue - rocks.shp is properly included in converted maps
- Cameo stock palettes work correctly for blue tiberium
- Best to use Cameo stock palettes unless specific compatibility is proven

**Code Location:** `PALETTE_OVERRIDES` line 44 (empty dict)

**Empirical Finding:** Rocks inherit from ^CustomMapDebris with Palette: terrain in source rules, but keeping temperat.pal didn't fix rendering.

---

## Resource Handling Patches

### Patch 1: Source Resource Index Remapping
**Problem:** CA/RA maps use Ore=1, Gems=2, but Cameo uses Ore=3, Gems=4.

**Solution:** Remap source resource indices before assign_resources runs.

**Implications:**
- Without this, resources appear as Tiberium (1) and BlueTiberium (2)
- assign_resources re-types fields by node distance, but cells with no nearby node keep the remapped type
- Applied to "ra" and "ca" source mods

**Code Location:** `SOURCE_RES_REMAP` lines 488-491, `remap_source_resources()` function

---

### Patch 2: Resource Coherence Algorithm
**Problem:** Resource fields should be uniform and match their generation nodes.

**Solution:** Each contiguous resource blob is given ONE type by its distance band from the nearest spawn. Every generation node inside the blob is set to match.

**Implications:**
- No tiberium next to ore mines, no mixed patches
- BASE_RADIUS_FRAC = 0.16 for base patches (always Ore)
- OUTER_BANDS for tiberium tiers by distance
- BAND_CURVE = 1.0 for linear escalation

**Code Location:** Lines 169-175, resource assignment logic

---

## File Handling Patches

### Patch 1: Custom Rule File Stripping
**Problem:** CA/BI maps contain custom rule files (ERCC refinery, BCC barracks, ACC airfield) that Cameo doesn't provide.

**Solution:** Strip entire Rules/Sequences/Weapons/Voices/Notifications blocks and bundled files.

**Implications:**
- BI (Balance Iteration) is a community balance package
- BI version numbers refer to balance ruleset versions, not engine versions
- Custom rules reference actors/traits that don't exist in Cameo
- Keeping them would cause crashes or undefined behavior

**Code Location:** `EXTERNAL_REF_KEYS` line 185, file filtering logic

---

## Algorithmic Patches

### Patch 1: MapBin Format 2 Header Handling
**Problem:** MapBin class was hardcoding Format 1 offsets, but all source maps use Format 2.

**Solution:** Read format byte and branch on Format 1 vs Format 2 to get correct offsets.

**Implications:**
- Format 1: 5-byte header, tiles at offset 5
- Format 2: 17-byte header, offsets stored explicitly at bytes 5, 9, 13
- Critical fix - was corrupting header bytes when remapping templates

**Code Location:** `MapBin.__init__()` lines 210-222

---

### Patch 2: Column-Major Coordinate System
**Problem:** OpenRA uses column-major layout for map.bin, but initial implementation used row-major.

**Solution:** Updated all coordinate transforms to use column-major: `cell_index = col * height + row`.

**Implications:**
- Critical for correct tile/resource access
- Affects coordinate calculations throughout converter

**Code Location:** `MapBin.cell_xy()`, `MapBin.cell_index()` lines 243-250

---

## Empirical Observations

### Observation 1: BI (Balance Iteration) Understanding
**Finding:** BI refers to "Balance Iteration" - a community balance package, not a mod or engine version.

**Evidence:**
- Maps explicitly state "Balance Iteration 4.3/4.4/4.5" in descriptions
- Custom gameplay changes: ERCC refinery, BCC barracks, ACC airfield
- Large numbers of maps tagged with BI versions on OpenRA Resource Center
- Maps published in 2025 still carry BI version numbers

**Implications:**
- Explains why maps have custom rule files
- Explains consistent version numbering across many maps
- Converter's approach of stripping custom rules is correct

---

### Observation 2: Tile 225 Contextual Usage (BI 4.5 Specific)
**Finding:** Maps with BI 4.5 in name use tile 225 for different terrain types based on neighboring tiles.

**Evidence:**
- Near beach/shore tiles (119, 122) = water crossings
- Near cliff/rock tiles (223, 224, 143, 163) = rocky grass/terrain
- Actual water crossings (83,13), (17,88) are already 591 in source map

**Implications:**
- This observation is specific to BI 4.5 maps based on empirical testing
- Same tile ID used in different contexts by BI 4.5 mappers
- Requires context-aware remapping algorithm
- Not all tile 225 instances should be water crossings
- **Note:** GitHub analysis shows BI has no custom tilesets/templates across versions - this is a mapper convention, not a BI version difference

---

### Observation 3: Rock Palette Rendering Issue
**Finding:** Rock palette issue persists despite converter fixes.

**Evidence:**
- Rocks.shp is properly included in converted map
- Palette overrides don't fix the issue
- Rock actors use correct Cameo types (rock1-4)

**Implications:**
- Likely a Cameo mod-level rendering problem on RA temperate theater
- Not a converter issue
- May require Cameo game file changes to resolve

---

## Testing Results

### Abendland Testing Summary
**Map:** Abendland_BI-4.5.oramap

**Final State (2026-06-18):**
- ✅ Water crossings: 6-grid areas correctly map to 591
- ✅ Rock dimension mapping: rock1, rock2, rock3, rock4 actors present
- ✅ Blue tiberium: Using Cameo stock palettes correctly
- ✅ River corner: 84,11 area correct (no protrusion)
- ✅ Cliff tiles: (85,55), (85,56) preserved as tile 406
- ✅ Water wreckage: Tiles 157, 166 map to clear (255)
- ⚠️ Rock palette: Still rendering incorrectly (Cameo mod issue)

**Converter Output:**
```
remapped 332 tile(s): 157->255(40), 166->255(27), 221->2(14), 225->591(24)+255(187), 401->255(16), 402->255(6), 403->255(8), 404->255(10)
remapped 220 actor placement(s) to Cameo equivalents
remapped 458 source resource cell(s): 1->3, 2->4
```

---

## Conversion Matrix Implications

### Template Matrix (TEMPLATE_REMAP)
**Current State:** Handles CA-specific templates with deterministic mapping.

**Key Decisions:**
- Water decorations → clear (safer than water)
- Rocky water crossing → water (footprint safety)
- Hill/terrain → clear (no RA equivalent)
- Tile 225 → context-aware (BI-specific behavior)

**Future Considerations:**
- May need additional entries for other CA custom templates
- Context-aware remapping could be extended to other tiles if needed

---

### Actor Matrix (ACTOR_OVERRIDES)
**Current State:** Comprehensive mapping of CA actors to Cameo equivalents.

**Key Decisions:**
- Tree color variants → base trees (simplification)
- Tree clumps → Cameo tree clusters (high ROI)
- Stones → rock1 (functional equivalence)
- Rock dimension mapping → size-appropriate Cameo rocks
- Bushes → rocks (no bush actors in Cameo)

**Future Considerations:**
- May need additional mappings for newly discovered CA actors
- Dimension mapping could be refined if rendering issues persist

---

### Palette Matrix (PALETTE_OVERRIDES)
**Current State:** Empty (use Cameo stock palettes).

**Key Decision:** Removed all palette overrides after causing blue tiberium issues.

**Future Considerations:**
- Could add specific palette overrides if proven safe
- Current approach: rely on Cameo stock palettes

---

## Directory Cleanliness Protocol

**Protocol:** ALWAYS keep directories clean and tidy
- Move temporary/unnecessary files to `to delete` folder
- Remove placeholder/duplicate files
- Maintain organized directory structure
- Clean up after each session

**Implementation:**
- Session notes kept in DEVELOPMENT_LOG.md (no HANDOFF.md)
- Temporary files and duplicates cleaned up
- Project structure maintained

---

## Session Handoff Protocol

**Protocol:** No HANDOFF.md — that standard is retired. All session information is logged in
DEVELOPMENT_LOG.md, the canonical memory. A handoff is produced only when the user explicitly asks, and is
delivered as a chat copy box, never written to a file unless the user says so.

---

*This library is maintained as part of the Cameo Map Converter project to document the evolution of conversion logic and provide reference for future maintenance and debugging.*