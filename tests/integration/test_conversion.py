"""
test_conversion.py -- Integration tests for the map conversion pipeline
"""

import pytest
import sys
import os
import zipfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.integration
def test_basic_conversion(sample_map_path, test_output_dir):
    """Test basic map conversion with default settings."""
    import cameo_map_converter as cmc
    
    if not os.path.exists(sample_map_path):
        pytest.skip("Sample map file not found")
    
    # Load valid actors
    script_dir = os.path.dirname(os.path.abspath(cmc.__file__))
    valid_actors = cmc.load_valid_actors(script_dir)
    
    # Create output file path
    output_name = os.path.basename(sample_map_path)
    output_path = test_output_dir / output_name
    
    # Perform conversion
    rpt = cmc.Report()
    success = cmc.convert_map(
        sample_map_path,
        output_path,
        rpt,
        keep_palettes=False,
        keep_decorations=False,
        valid=valid_actors,
        dry_run=False,
        remap_resources=True
    )
    
    assert success, "Conversion should succeed"
    
    # Check that output file was created
    assert os.path.exists(output_path), "Output file should exist"
    
    # Verify it's a valid zip file
    assert zipfile.is_zipfile(output_path), "Output should be a valid .oramap (zip) file"
    
    # Check that required files are present
    with zipfile.ZipFile(output_path, 'r') as zf:
        assert 'map.yaml' in zf.namelist(), "map.yaml should be in output"
        assert 'map.bin' in zf.namelist(), "map.bin should be in output"


@pytest.mark.integration
def test_conversion_with_remap_disabled(sample_map_path, test_output_dir):
    """Test conversion with resource remapping disabled."""
    import cameo_map_converter as cmc
    
    if not os.path.exists(sample_map_path):
        pytest.skip("Sample map file not found")
    
    # Load valid actors
    script_dir = os.path.dirname(os.path.abspath(cmc.__file__))
    valid_actors = cmc.load_valid_actors(script_dir)
    
    # Create output file path
    output_name = os.path.basename(sample_map_path)
    output_path = test_output_dir / output_name
    
    # Perform conversion with remap disabled
    rpt = cmc.Report()
    success = cmc.convert_map(
        sample_map_path,
        output_path,
        rpt,
        keep_palettes=False,
        keep_decorations=False,
        valid=valid_actors,
        dry_run=False,
        remap_resources=False
    )
    
    assert success, "Conversion with remap disabled should succeed"
    
    # Check report mentions remap disabled
    report_text = rpt.dump()
    assert "remap resources disabled" in report_text.lower(), \
        "Report should mention remap resources disabled"


@pytest.mark.integration
def test_dry_run(sample_map_path, test_output_dir):
    """Test dry run mode (no output file created)."""
    import cameo_map_converter as cmc
    
    if not os.path.exists(sample_map_path):
        pytest.skip("Sample map file not found")
    
    # Load valid actors
    script_dir = os.path.dirname(os.path.abspath(cmc.__file__))
    valid_actors = cmc.load_valid_actors(script_dir)
    
    # Create output file path
    output_name = os.path.basename(sample_map_path)
    output_path = test_output_dir / output_name
    
    # Perform dry run
    rpt = cmc.Report()
    success = cmc.convert_map(
        sample_map_path,
        output_path,
        rpt,
        keep_palettes=False,
        keep_decorations=False,
        valid=valid_actors,
        dry_run=True,
        remap_resources=True
    )
    
    assert success, "Dry run should succeed"
    
    # Check that output file was NOT created
    assert not os.path.exists(output_path), "Dry run should not create output file"


@pytest.mark.integration
def test_remap_disabled_preserves_source_resource_types():
    """Regression test: with remap_resources=False, the manual_only pass must
    preserve the original 1-1 converted cell types (e.g., gems must stay gems)
    instead of merging mixed adjacent fields into a single majority type."""
    import cameo_map_converter as cmc
    import struct
    import tempfile
    import zipfile

    W, H = 64, 64
    tiles_off = 17
    res_off = tiles_off + W * H * 3
    total = res_off + W * H * 2
    raw = bytearray(total)
    raw[0] = 2
    struct.pack_into("<H", raw, 1, W)
    struct.pack_into("<H", raw, 3, H)
    struct.pack_into("<I", raw, 5, tiles_off)
    struct.pack_into("<I", raw, 9, 0)
    struct.pack_into("<I", raw, 13, res_off)
    mb = cmc.MapBin(raw)
    # Build a contiguous field that mixes ore and gems, plus a pure gem patch.
    for col in range(20, 30):
        for row in range(20, 30):
            mb.set_res(col * H + row, 1, 12)  # ore-like
    for col in range(25, 32):  # overlaps the ore block -> mixed field
        for row in range(25, 32):
            mb.set_res(col * H + row, 2, 12)  # gem-like (RA index)

    yaml = """MapFormat: 11
RequiresMod: ra
Title: test
Author: test
Tileset: TEMPERAT
MapSize: 64,64
Bounds: 0,0,64,64
Visibility: Lobby
Categories: Conquest
Players:
\tPlayerReference@Neutral:
\t\tName: Neutral
\t\tOwnsWorld: True
\t\tNonCombatant: True
\t\tFaction: Random
Actors:
\tActor0: mpspawn
\t\tOwner: Neutral
\t\tLocation: 10,10
"""
    src = tempfile.mktemp(suffix=".oramap")
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("map.yaml", yaml)
        zf.writestr("map.bin", mb.bytes())

    try:
        settings = {
            "richness": 1.0,
            "distribution": "distance",
            "balance_bias": 0.0,
            "balance_home_radius": 15,
            "remap_resources": False,
            "remove_actors": True,
            "paint_overrides": {},
            "cell_overrides": {},
            "node_overrides": {},
            "density_overrides": {},
            "field_density_overrides": {},
        }
        _, counts = cmc.render_preview(src, settings, scale=1, draw_nodes=True)
        # The base conversion maps RA index 1 -> Ore(3) and 2 -> Gems(4).
        # With remap off, those exact counts must be preserved. 100 ore cells
        # minus the 25-cell overlap overwritten by gems gives 75 ore + 49 gems.
        assert counts["Ore"] == 75, f"Expected 75 ore cells, got {counts['Ore']}"
        assert counts["Gems"] == 49, f"Expected 49 gem cells, got {counts['Gems']}"
    finally:
        os.remove(src)


@pytest.mark.integration
def test_node_paint_does_not_repaint_field_when_independent():
    """Regression test: painting a node (e.g., ore mine -> gems) should not
    repaint the entire surrounding field when node_affects_field_tier=False."""
    import cameo_map_converter as cmc
    import struct
    import tempfile
    import zipfile

    W, H = 64, 64
    tiles_off = 17
    res_off = tiles_off + W * H * 3
    total = res_off + W * H * 2
    raw = bytearray(total)
    raw[0] = 2
    struct.pack_into("<H", raw, 1, W)
    struct.pack_into("<H", raw, 3, H)
    struct.pack_into("<I", raw, 5, tiles_off)
    struct.pack_into("<I", raw, 9, 0)
    struct.pack_into("<I", raw, 13, res_off)
    mb = cmc.MapBin(raw)
    # Build a small ore field and place an ore mine node in the middle.
    for col in range(20, 26):
        for row in range(20, 26):
            mb.set_res(col * H + row, 1, 12)

    yaml = """MapFormat: 11
RequiresMod: ra
Title: test
Author: test
Tileset: TEMPERAT
MapSize: 64,64
Bounds: 0,0,64,64
Visibility: Lobby
Categories: Conquest
Players:
\tPlayerReference@Neutral:
\t\tName: Neutral
\t\tOwnsWorld: True
\t\tNonCombatant: True
\t\tFaction: Random
Actors:
\tActor0: mpspawn
\t\tOwner: Neutral
\t\tLocation: 10,10
\tActor1: mine
\t\tOwner: Neutral
\t\tLocation: 23,23
"""
    src = tempfile.mktemp(suffix=".oramap")
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("map.yaml", yaml)
        zf.writestr("map.bin", mb.bytes())

    try:
        settings = {
            "richness": 1.0,
            "distribution": "distance",
            "balance_bias": 0.0,
            "balance_home_radius": 15,
            "remap_resources": True,
            "remove_actors": True,
            "paint_overrides": {},
            "cell_overrides": {},
            "node_overrides": {"23,23": "Gems"},
            "density_overrides": {},
            "field_density_overrides": {},
            "node_affects_field_tier": False,
        }
        _, counts = cmc.render_preview(src, settings, scale=1, draw_nodes=True)
        # The ore field must remain ore; only the node actor is changed.
        assert counts["Ore"] == 36, f"Expected 36 ore cells, got {counts['Ore']}"
        assert counts["Gems"] == 0, f"Expected 0 gem cells from field repaint, got {counts['Gems']}"
    finally:
        os.remove(src)


@pytest.mark.integration
def test_density_override_disables_resource_recalculation():
    """When field/cell density overrides are used, convert_map must add a map-level
    rule override that disables ResourceLayer's RecalculateResourceDensity so the
    painted density bytes are not overwritten by the engine at load time."""
    import cameo_map_converter as cmc
    import struct
    import tempfile
    import zipfile

    W, H = 64, 64
    tiles_off = 17
    res_off = tiles_off + W * H * 3
    total = res_off + W * H * 2
    raw = bytearray(total)
    raw[0] = 2
    struct.pack_into("<H", raw, 1, W)
    struct.pack_into("<H", raw, 3, H)
    struct.pack_into("<I", raw, 5, tiles_off)
    struct.pack_into("<I", raw, 9, 0)
    struct.pack_into("<I", raw, 13, res_off)
    mb = cmc.MapBin(raw)
    # Small ore field.
    for col in range(20, 26):
        for row in range(20, 26):
            mb.set_res(col * H + row, 3, 12)

    yaml = """MapFormat: 11
RequiresMod: ra
Title: test
Author: test
Tileset: TEMPERAT
MapSize: 64,64
Bounds: 0,0,64,64
Visibility: Lobby
Categories: Conquest
Players:
\tPlayerReference@Neutral:
\t\tName: Neutral
\t\tOwnsWorld: True
\t\tNonCombatant: True
\t\tFaction: Random
Actors:
\tActor0: mpspawn
\t\tOwner: Neutral
\t\tLocation: 10,10
"""
    src = tempfile.mktemp(suffix=".oramap")
    out = tempfile.mktemp(suffix=".oramap")
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("map.yaml", yaml)
        zf.writestr("map.bin", mb.bytes())

    try:
        from cameo_map_converter import convert_map, Report
        rpt = Report()
        ok = convert_map(src, out, rpt, keep_palettes=True, keep_decorations=True,
                          valid=set(), dry_run=False, remap_resources=False,
                          paint_overrides={"22,22": "Tiberium"},
                          cell_overrides={}, node_overrides={},
                          density_overrides={}, field_density_overrides={"22,22": 14})
        assert ok, "convert_map failed"

        with zipfile.ZipFile(out) as zf:
            out_yaml = zf.read("map.yaml").decode("utf-8")
            out_bin = zf.read("map.bin")

        # Verify the map.yaml contains the rule override under the correct actors.
        assert "RecalculateResourceDensity: false" in out_yaml, \
            "Expected ResourceLayer density recalculation override in map.yaml"
        assert "ResourceLayer:" in out_yaml, \
            "Expected ResourceLayer block in map.yaml"
        assert "EditorResourceLayer:" in out_yaml, \
            "Expected EditorResourceLayer block in map.yaml"
        assert "\tWorld:" in out_yaml, \
            "Expected density override on the World actor, not ^BaseWorld"
        assert "\tEditorWorld:" in out_yaml, \
            "Expected density override on the EditorWorld actor"

        # Verify the map.bin has uniform density.
        omb = cmc.MapBin(out_bin)
        tib_idx = cmc.CAMEO_RES_INDEX["Tiberium"]
        densities = [omb.res_density(i) for i in range(omb.cells)
                     if omb.raw[omb.res_off + i * 2] == tib_idx]
        assert set(densities) == {14}, f"Expected uniform density 14, got {set(densities)}"
    finally:
        os.remove(src)
        os.remove(out)


@pytest.mark.integration
def test_random_density_override_applies_per_cell():
    """When a field density override is "Random", each cell must get a different
    random density rather than a single uniform value."""
    import cameo_map_converter as cmc
    import struct
    import tempfile
    import zipfile

    W, H = 64, 64
    tiles_off = 17
    res_off = tiles_off + W * H * 3
    total = res_off + W * H * 2
    raw = bytearray(total)
    raw[0] = 2
    struct.pack_into("<H", raw, 1, W)
    struct.pack_into("<H", raw, 3, H)
    struct.pack_into("<I", raw, 5, tiles_off)
    struct.pack_into("<I", raw, 9, 0)
    struct.pack_into("<I", raw, 13, res_off)
    mb = cmc.MapBin(raw)
    # Small tiberium field.
    for col in range(20, 26):
        for row in range(20, 26):
            mb.set_res(col * H + row, 1, 12)

    yaml = """MapFormat: 11
RequiresMod: ra
Title: test
Author: test
Tileset: TEMPERAT
MapSize: 64,64
Bounds: 0,0,64,64
Visibility: Lobby
Categories: Conquest
Players:
\tPlayerReference@Neutral:
\t\tName: Neutral
\t\tOwnsWorld: True
\t\tNonCombatant: True
\t\tFaction: Random
Actors:
\tActor0: mpspawn
\t\tOwner: Neutral
\t\tLocation: 10,10
"""
    src = tempfile.mktemp(suffix=".oramap")
    out = tempfile.mktemp(suffix=".oramap")
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("map.yaml", yaml)
        zf.writestr("map.bin", mb.bytes())

    try:
        from cameo_map_converter import convert_map, Report
        rpt = Report()
        ok = convert_map(src, out, rpt, keep_palettes=True, keep_decorations=True,
                          valid=set(), dry_run=False, remap_resources=False,
                          paint_overrides={"22,22": "Tiberium"},
                          cell_overrides={}, node_overrides={},
                          density_overrides={}, field_density_overrides={"22,22": "Random"})
        assert ok, "convert_map failed"

        with zipfile.ZipFile(out) as zf:
            out_bin = zf.read("map.bin")

        omb = cmc.MapBin(out_bin)
        tib_idx = cmc.CAMEO_RES_INDEX["Tiberium"]
        densities = [omb.res_density(i) for i in range(omb.cells)
                     if omb.raw[omb.res_off + i * 2] == tib_idx]
        assert len(densities) >= 4, f"Expected at least 4 tiberium cells, got {len(densities)}"
        # Random density must produce at least two different values across the field.
        assert len(set(densities)) > 1, \
            f"Expected varied random densities, got uniform {set(densities)}"
        # All densities must be valid Tiberium density steps (1-5 scaled by 35).
        expected = {7, 14, 21, 28, 35}
        assert set(densities) <= expected, f"Unexpected densities {set(densities)}"
        assert all(d >= 1 for d in densities), "Random density must never be 0"
    finally:
        os.remove(src)
        os.remove(out)


@pytest.mark.integration
def test_manual_only_field_paint_updates_node_actor_and_tooltip_metadata():
    """Regression test: with remap_resources=False, painting a whole field to a new
    tier must also update the resource node inside that field, and the tooltip
    metadata (_last_assign_nodes / _last_assign_fields) must reflect the painted
    tier instead of the original ore actor."""
    import cameo_map_converter as cmc
    import struct
    import tempfile
    import zipfile

    W, H = 64, 64
    tiles_off = 17
    res_off = tiles_off + W * H * 3
    total = res_off + W * H * 2
    raw = bytearray(total)
    raw[0] = 2
    struct.pack_into("<H", raw, 1, W)
    struct.pack_into("<H", raw, 3, H)
    struct.pack_into("<I", raw, 5, tiles_off)
    struct.pack_into("<I", raw, 9, 0)
    struct.pack_into("<I", raw, 13, res_off)
    mb = cmc.MapBin(raw)
    # 6x6 ore field centered at (22,22), with an ore mine node at its center.
    for col in range(20, 26):
        for row in range(20, 26):
            mb.set_res(col * H + row, 3, 12)

    yaml = """MapFormat: 11
RequiresMod: ra
Title: test
Author: test
Tileset: TEMPERAT
MapSize: 64,64
Bounds: 0,0,64,64
Visibility: Lobby
Categories: Conquest
Players:
\tPlayerReference@Neutral:
\t\tName: Neutral
\t\tOwnsWorld: True
\t\tNonCombatant: True
\t\tFaction: Random
Actors:
\tActor0: mpspawn
\t\tOwner: Neutral
\t\tLocation: 10,10
\tActor1: mine
\t\tOwner: Neutral
\t\tLocation: 22,22
"""
    src = tempfile.mktemp(suffix=".oramap")
    out = tempfile.mktemp(suffix=".oramap")
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("map.yaml", yaml)
        zf.writestr("map.bin", mb.bytes())

    try:
        # Preview path: field paint override must update node metadata.
        settings = {
            "richness": 1.0,
            "distribution": "distance",
            "balance_bias": 0.0,
            "balance_home_radius": 15,
            "remap_resources": False,
            "remove_actors": True,
            "paint_overrides": {"22,22": "Tiberium"},
            "cell_overrides": {},
            "node_overrides": {},
            "density_overrides": {},
            "field_density_overrides": {},
        }
        _, counts = cmc.render_preview(src, settings, scale=1, draw_nodes=True)
        fields = counts.get("__fields__", [])
        nodes = counts.get("__nodes__", [])
        assert fields, "Expected field metadata in preview counts"
        assert fields[0]["tier"] == "Tiberium", \
            f"Painted field tier should be Tiberium, got {fields[0]['tier']}"
        assert len(nodes) == 1, f"Expected one node metadata entry, got {len(nodes)}"
        assert nodes[0]["resource"] == "Tiberium", \
            f"Node in painted field should be Tiberium, got {nodes[0]['resource']}"

        # Convert path: the node actor name must be rewritten to the tiberium tree.
        rpt = cmc.Report()
        ok = cmc.convert_map(src, out, rpt, keep_palettes=False, keep_decorations=False,
                              valid=set(), dry_run=False, remap_resources=False,
                              paint_overrides={"22,22": "Tiberium"},
                              cell_overrides={}, node_overrides={},
                              density_overrides={}, field_density_overrides={})
        assert ok, "convert_map failed"
        with zipfile.ZipFile(out) as zf:
            out_yaml = zf.read("map.yaml").decode("utf-8")
        assert "Actor1: split2" in out_yaml, \
            "Ore mine node should be renamed to split2 (Tiberium) in output map.yaml"
    finally:
        os.remove(src)
        os.remove(out)


@pytest.mark.integration
def test_remove_actors_false_remaps_rocks_and_stones_only():
    """Regression test: the "Remove Problematic Actors" checkbox (remove_actors=False)
    remaps only rock/stone actors to their palette-mismatched Cameo equivalents
    (e.g., stones1 -> rock1). Bushes and other decorative actors with no
    defensible equivalent are dropped regardless of the toggle."""
    import cameo_map_converter as cmc
    import struct
    import tempfile
    import zipfile

    W, H = 32, 32
    tiles_off = 17
    res_off = tiles_off + W * H * 3
    total = res_off + W * H * 2
    raw = bytearray(total)
    raw[0] = 2
    struct.pack_into("<H", raw, 1, W)
    struct.pack_into("<H", raw, 3, H)
    struct.pack_into("<I", raw, 5, tiles_off)
    struct.pack_into("<I", raw, 9, 0)
    struct.pack_into("<I", raw, 13, res_off)
    mb = cmc.MapBin(raw)

    yaml = """MapFormat: 11
RequiresMod: ra
Title: test
Author: test
Tileset: TEMPERAT
MapSize: 32,32
Bounds: 0,0,32,32
Visibility: Lobby
Categories: Conquest
Players:
\tPlayerReference@Neutral:
\t\tName: Neutral
\t\tOwnsWorld: True
\t\tNonCombatant: True
\t\tFaction: Random
Actors:
\tActor0: mpspawn
\t\tOwner: Neutral
\t\tLocation: 10,10
\tActor1: stones1
\t\tOwner: Neutral
\t\tLocation: 15,15
\tActor2: bush2
\t\tOwner: Neutral
\t\tLocation: 16,16
"""
    src = tempfile.mktemp(suffix=".oramap")
    out_keep = tempfile.mktemp(suffix=".oramap")
    out_drop = tempfile.mktemp(suffix=".oramap")
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("map.yaml", yaml)
        zf.writestr("map.bin", mb.bytes())

    try:
        # remove_actors=False -> rocks/stones are remapped; bushes are still dropped.
        rpt = cmc.Report()
        ok = cmc.convert_map(src, out_keep, rpt, keep_palettes=False,
                              keep_decorations=False, valid=set(), dry_run=False,
                              remap_resources=True, remove_actors=False)
        assert ok, "convert_map with remove_actors=False failed"
        with zipfile.ZipFile(out_keep) as zf:
            out_yaml = zf.read("map.yaml").decode("utf-8")
        assert "stones1" not in out_yaml, \
            "Source actor stones1 should be remapped, not kept as-is"
        assert "Actor1: rock1" in out_yaml, \
            "stones1 should be remapped to rock1 when remove_actors=False"
        assert "bush2" not in out_yaml and "Actor2" not in out_yaml, \
            "bush2 has no defensible Cameo equivalent and should be dropped even when remove_actors=False"

        # remove_actors=True (default) -> both rocks and bushes are dropped.
        rpt = cmc.Report()
        ok = cmc.convert_map(src, out_drop, rpt, keep_palettes=False,
                              keep_decorations=False, valid=set(), dry_run=False,
                              remap_resources=True, remove_actors=True)
        assert ok, "convert_map with remove_actors=True failed"
        with zipfile.ZipFile(out_drop) as zf:
            out_yaml = zf.read("map.yaml").decode("utf-8")
        assert "stones1" not in out_yaml and "rock1" not in out_yaml, \
            "Palette-issue actor stones1 should be dropped when remove_actors=True"
        assert "bush2" not in out_yaml, \
            "Palette-issue actor bush2 should be dropped when remove_actors=True"
    finally:
        os.remove(src)
        os.remove(out_keep)
        os.remove(out_drop)
