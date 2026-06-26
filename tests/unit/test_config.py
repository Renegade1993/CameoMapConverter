"""
test_config.py -- Unit tests for ConverterConfig save/load round-tripping.

Focuses on the set-valued config attributes (KEEP_NAMES, SOURCE_RESOURCE_ACTORS,
ACTOR_NEVER_DROP), which have no native JSON/YAML representation and must survive
a save -> load cycle as Python sets.
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cameo_map_converter import ConverterConfig

# Config attributes that are stored as sets and must round-trip as sets.
SET_ATTRS = ["KEEP_NAMES", "SOURCE_RESOURCE_ACTORS", "ACTOR_NEVER_DROP"]


@pytest.fixture
def saved_set_defaults():
    """Snapshot the set attrs before a test and restore them afterwards.

    save_to_file / load_from_file mutate class-level attributes, so we must
    restore them so other tests see the original defaults.
    """
    original = {attr: set(getattr(ConverterConfig, attr)) for attr in SET_ATTRS}
    yield original
    for attr, value in original.items():
        setattr(ConverterConfig, attr, set(value))


@pytest.mark.parametrize("ext", [".json", ".yaml"])
def test_set_attrs_round_trip(tmp_path, saved_set_defaults, ext):
    """Set-valued attrs save and load back as sets with identical contents."""
    config_path = str(tmp_path / f"config{ext}")

    # Save current config to disk.
    ConverterConfig.save_to_file(config_path)
    assert Path(config_path).exists(), f"config file was not written: {config_path}"

    # Clobber the in-memory values so a successful load is meaningful.
    for attr in SET_ATTRS:
        setattr(ConverterConfig, attr, set())

    # Load it back.
    ConverterConfig.load_from_file(config_path)

    for attr in SET_ATTRS:
        loaded = getattr(ConverterConfig, attr)
        assert isinstance(loaded, set), (
            f"{attr} loaded from {ext} as {type(loaded).__name__}, expected set"
        )
        assert loaded == saved_set_defaults[attr], (
            f"{attr} contents changed across {ext} round-trip"
        )


@pytest.mark.parametrize("ext", [".json", ".yaml"])
def test_scalar_attr_round_trip(tmp_path, ext):
    """A representative scalar attr survives the round-trip unchanged."""
    config_path = str(tmp_path / f"config{ext}")
    original = ConverterConfig.RESOURCE_RICHNESS
    try:
        ConverterConfig.save_to_file(config_path)
        ConverterConfig.RESOURCE_RICHNESS = -999.0
        ConverterConfig.load_from_file(config_path)
        assert ConverterConfig.RESOURCE_RICHNESS == original
    finally:
        ConverterConfig.RESOURCE_RICHNESS = original


def test_unsupported_extension_raises(tmp_path):
    """save_to_file rejects an unsupported extension via ValueError (caught+logged)."""
    # save_to_file catches the ValueError internally and logs it, so the file
    # simply should not be created.
    bad_path = str(tmp_path / "config.txt")
    ConverterConfig.save_to_file(bad_path)
    assert not Path(bad_path).exists()
