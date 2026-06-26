"""Quick test for the density override pipeline."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cameo_map_converter as cmc


def _make_mb(w, h):
    """Create a tiny MapBin with all ore resources at varying densities."""
    # Minimal fmt=2 header: 17 bytes + tiles + resources
    tiles_off = 17
    res_off = tiles_off + w * h * 3
    total = res_off + w * h * 2
    raw = bytearray(total)
    raw[0] = 2  # fmt
    # fmt=2 header: fmt(1) + width(2) + height(2) + tiles_off(4) + heights_off(4) + res_off(4)
    import struct
    struct.pack_into("<H", raw, 1, w)
    struct.pack_into("<H", raw, 3, h)
    struct.pack_into("<I", raw, 5, tiles_off)
    struct.pack_into("<I", raw, 9, 0)
    struct.pack_into("<I", raw, 13, res_off)
    mb = cmc.MapBin(raw)
    for i in range(w * h):
        mb.set_res(i, cmc.CAMEO_RES_INDEX["Ore"], (i % 40) + 1)
    return mb


def _set_density(mb, col, row, density):
    H = mb.height
    mb.raw[mb.res_off + (col * H + row) * 2 + 1] = density


def test_density_override():
    mb = _make_mb(32, 32)
    H = mb.height
    # Set explicit original densities so Replace behavior is predictable.
    _set_density(mb, 0, 0, 10)
    _set_density(mb, 1, 0, 10)
    _set_density(mb, 2, 0, 10)
    _set_density(mb, 3, 0, 25)
    cell_overrides = {
        "0,0": "Tiberium",
        "1,0": "Tiberium",
        "2,0": "Tiberium",
        "3,0": "Tiberium",
    }
    density_overrides = {
        "0,0": "1",
        "1,0": "3",
        "2,0": "5",
        "3,0": "Replace",
    }
    lines = []
    actors = []
    spawns = []
    rpt = cmc.Report()
    cmc.assign_resources(lines, actors, mb, spawns, rpt,
                         cell_overrides=cell_overrides,
                         density_overrides=density_overrides,
                         manual_only=True)
    # Tiberium cap = 35, level 1 => 7, level 3 => 21, level 5 => 35, Replace => keep existing
    assert mb.raw[mb.res_off + (0 * H + 0) * 2 + 1] == 7, "level 1 Tiberium should be 7"
    assert mb.raw[mb.res_off + (1 * H + 0) * 2 + 1] == 21, "level 3 Tiberium should be 21"
    assert mb.raw[mb.res_off + (2 * H + 0) * 2 + 1] == 35, "level 5 Tiberium should be 35"
    assert mb.raw[mb.res_off + (3 * H + 0) * 2 + 1] == 25, "Replace should keep original density 25"
    print("Density override backend test PASSED")


if __name__ == "__main__":
    test_density_override()
