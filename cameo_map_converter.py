#!/usr/bin/env python3
"""
cameo_map_converter.py  --  OpenRA / Combined Arms -> Cameo map converter  (v40)

Onboards CA tournament maps into Cameo:
  * header rewrites (RequiresMod, Tileset, Categories, LockPreview, Title, Author)
  * strips CA custom rules/sequences/weapons/voices/notifications + bundled files
  * drops custom palettes (default) -> Cameo's stock palettes
  * validates placed actors against cameo_actors.txt: keep / remap (ACTOR_OVERRIDES)
    / drop, so no "unknown type" crash
  * RESOURCES: each contiguous resource blob is given ONE type by its distance
    band from the nearest spawn, and every generation node inside the blob is set
    to match -- so a field is always uniform and matches its node (no tiberium
    next to an ore mine, no mixed patches).
  * reports any tiles using CA-custom templates that Cameo's tileset lacks
  * repackages a clean .oramap

TEMPORARY ROCK WORKAROUND: Rocks dropped due to Cameo mod palette rendering issue.
See ROCK_PALETTE_ISSUE_FOR_DEV_TEAM.md for details. Original rock mappings are
documented in ACTOR_OVERRIDES comments for restoration when Cameo fixes the
palette mismatch between .des files and ra_temperat.pal.

Ship cameo_actors.txt next to this script (regenerate with --dump-actors).
"""

import argparse
import json
import math
import os
import re
import shutil
from converter_logging import setup_logging, get_logger
import struct
import sys
import tempfile
import zipfile
from collections import deque

# ==========================================================================
# CONFIGURATION MANAGEMENT
# ==========================================================================

class ConverterConfig:
    """Centralized configuration for the Cameo Map Converter."""
    
    # Tileset mappings
    TILESET_MAP = {
        "TEMPERAT": "RA_TEMPERAT", "SNOW": "RA_SNOW",
        "DESERT": "RA_DESERT", "INTERIOR": "RA_INTERIOR",
        "RA_TEMPERAT": "RA_TEMPERAT", "RA_SNOW": "RA_SNOW",
        "RA_DESERT": "RA_DESERT", "RA_INTERIOR": "RA_INTERIOR",
    }
    
    # Palette handling
    PALETTE_DEFAULT = "drop"
    PALETTE_OVERRIDES = {}
    
    # BI Protocol Configuration
    BI_PROTOCOL_FILE = "bi_protocol.yaml"
    BI_PROTOCOL = None
    
    # Resource configuration (defaults, can be overridden by CLI/GUI)
    RESOURCE_RICHNESS = 1.0
    WATER_FILL_SAFETY = 60  # don't auto-fill a leaking water blob larger than this
    
    # Cameo resource indices and properties
    CAMEO_RES_INDEX = {"Tiberium": 1, "BlueTiberium": 2, "Ore": 3,
                       "Gems": 4, "RedTiberium": 5, "GoldTiberium": 6}
    CAMEO_RES_MAXDENSITY = {1: 35, 2: 30, 3: 40, 4: 15, 5: 25, 6: 20}
    CAMEO_RES_ACTOR = {"Ore": "mine", "Gems": "gmine", "Tiberium": "split2",
                       "BlueTiberium": "splitblue", "RedTiberium": "splitred",
                       "GoldTiberium": "splitgold"}
    
    # Source resource actors
    SOURCE_RESOURCE_ACTORS = {"mine", "gmine", "MINE", "GMINE"}
    
    # File handling
    KEEP_NAMES = {"map.yaml", "map.bin", "map.png"}
    NEW_CATEGORY = "Tournament"
    CONVERTER_TAG = "Cameo Conversion"
    EXTERNAL_REF_KEYS = ["Rules", "Sequences", "Weapons", "Voices", "Notifications", "FluentMessages"]
    ACTOR_NEVER_DROP = {"mpspawn", "waypoint"}
    ACTORS_FILE = "cameo_actors.txt"
    
    # Source resource remapping
    SOURCE_RES_REMAP = {
        "ra":              {1: 3, 2: 4},   # RA Ore->Ore(3), RA Gems->Gems(4)
        "cnc":             {1: 3, 2: 4},   # C&C same as RA
        "d2k":             {1: 3, 2: 4},   # Dune 2000 same as RA
        "ts":              {1: 3, 2: 4},   # Tiberian Sun same as RA
    }
    
    @classmethod
    def load_from_file(cls, config_path):
        """Load configuration from a YAML or JSON file."""
        if not os.path.exists(config_path):
            print(f"[WARNING] Config file not found: {config_path}, using defaults")
            return
        
        try:
            if config_path.endswith('.yaml') or config_path.endswith('.yml'):
                import yaml
                with open(config_path, 'r') as f:
                    config_data = yaml.safe_load(f)
            elif config_path.endswith('.json'):
                import json
                with open(config_path, 'r') as f:
                    config_data = json.load(f)
            else:
                print(f"[WARNING] Unsupported config file format: {config_path}")
                return
            
            # Apply configuration overrides
            for key, value in config_data.items():
                if hasattr(cls, key):
                    # If the class default is a set but the incoming value is a
                    # list (JSON/YAML have no set type), restore it as a set so
                    # downstream membership tests keep working.
                    if isinstance(getattr(cls, key), set) and isinstance(value, list):
                        value = set(value)
                    setattr(cls, key, value)
                else:
                    print(f"[WARNING] Unknown config key: {key}")
            
            print(f"[INFO] Loaded configuration from: {config_path}")
        except Exception as e:
            print(f"[ERROR] Failed to load config file: {e}")
    
    @classmethod
    def save_to_file(cls, config_path):
        """Save current configuration to a YAML or JSON file."""
        try:
            config_data = {}
            for key in dir(cls):
                if not key.startswith('_') and not callable(getattr(cls, key)):
                    value = getattr(cls, key)
                    if not isinstance(value, classmethod):
                        # Convert sets to sorted lists (JSON/YAML have no set
                        # type); sorting keeps the serialized output deterministic.
                        if isinstance(value, set):
                            value = sorted(value)
                        config_data[key] = value
            
            if config_path.endswith('.yaml') or config_path.endswith('.yml'):
                import yaml
                with open(config_path, 'w') as f:
                    yaml.dump(config_data, f, default_flow_style=False)
            elif config_path.endswith('.json'):
                import json
                with open(config_path, 'w') as f:
                    json.dump(config_data, f, indent=2)
            else:
                raise ValueError("Unsupported config file format. Use .yaml, .yml, or .json")
            
            print(f"[INFO] Saved configuration to: {config_path}")
        except Exception as e:
            print(f"[ERROR] Failed to save config file: {e}")

# Initialize configuration
config = ConverterConfig()

# ==========================================================================
# INPUT VALIDATION
# ==========================================================================

def validate_file_path(file_path, allow_directories=True):
    """Validate file path to prevent directory traversal and ensure it's safe."""
    if not file_path:
        raise ValueError("File path cannot be empty")
    
    # Normalize the path
    normalized = os.path.normpath(file_path)
    
    # Check for directory traversal attempts
    if ".." in normalized:
        raise ValueError(f"Directory traversal not allowed: {file_path}")
    
    # Check if path exists
    if not os.path.exists(normalized):
        raise ValueError(f"Path does not exist: {file_path}")
    
    # Check if it's a file or directory (as allowed)
    if os.path.isfile(normalized):
        return normalized
    elif os.path.isdir(normalized) and allow_directories:
        return normalized
    elif not allow_directories:
        raise ValueError(f"Expected a file, got directory: {file_path}")
    else:
        raise ValueError(f"Path is neither file nor directory: {file_path}")

def validate_oramap_file(file_path):
    """Validate that a file is a valid .oramap file."""
    if not file_path.lower().endswith(".oramap"):
        raise ValueError(f"File must be a .oramap file: {file_path}")
    
    if not os.path.exists(file_path):
        raise ValueError(f"File does not exist: {file_path}")
    
    if not os.path.isfile(file_path):
        raise ValueError(f"Path is not a file: {file_path}")
    
    # Try to open as zip to verify it's a valid oramap
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            # Check for required files
            required_files = {'map.yaml', 'map.bin'}
            actual_files = set(z.namelist())
            missing = required_files - actual_files
            if missing:
                raise ValueError(f"Invalid .oramap: missing required files {missing}")
    except zipfile.BadZipFile:
        raise ValueError(f"File is not a valid zip archive: {file_path}")
    
    return file_path

def validate_map_dimensions(width, height):
    """Validate map.bin dimensions are within reasonable bounds."""
    if not isinstance(width, int) or not isinstance(height, int):
        raise ValueError(f"Map dimensions must be integers: got {width}x{height}")
    
    if width <= 0 or height <= 0:
        raise ValueError(f"Map dimensions must be positive: got {width}x{height}")
    
    if width > 1024 or height > 1024:
        raise ValueError(f"Map dimensions too large: got {width}x{height}, max 1024x1024")
    
    if width < 32 or height < 32:
        raise ValueError(f"Map dimensions too small: got {width}x{height}, min 32x32")
    
    return True

def validate_resource_config(richness, balance_bias, home_radius):
    """Validate resource configuration parameters."""
    if not isinstance(richness, (int, float)):
        raise ValueError(f"RESOURCE_RICHNESS must be numeric: got {richness}")
    
    if richness < 0.0 or richness > 2.0:
        raise ValueError(f"RESOURCE_RICHNESS must be between 0.0 and 2.0: got {richness}")
    
    if not isinstance(balance_bias, (int, float)):
        raise ValueError(f"BALANCE_BIAS must be numeric: got {balance_bias}")
    
    if balance_bias < 0.0 or balance_bias > 10.0:
        raise ValueError(f"BALANCE_BIAS must be between 0.0 and 10.0: got {balance_bias}")
    
    if not isinstance(home_radius, (int, float)):
        raise ValueError(f"BALANCE_HOME_RADIUS must be numeric: got {home_radius}")
    
    if home_radius < 0 or home_radius > 100:
        raise ValueError(f"BALANCE_HOME_RADIUS must be between 0 and 100: got {home_radius}")
    
    return True

# Import water crossing detection module
from water_crossing_detect import load_tileset_terrain, detect_and_convert_crossings
# Import resource reclassification module
from resource_reclassification import assign_node_tiers_corrected, detect_symmetries
import resource_reclassification as _rr
import minimap_render  # shared minimap renderer (Task 1/2); top-level so PyInstaller bundles it

# ==========================================================================
# BACKWARD COMPATIBILITY - Legacy global variables mapped to config
# ==========================================================================

# For backward compatibility with existing code
TILESET_MAP = ConverterConfig.TILESET_MAP
PALETTE_DEFAULT = ConverterConfig.PALETTE_DEFAULT
PALETTE_OVERRIDES = ConverterConfig.PALETTE_OVERRIDES
BI_PROTOCOL_FILE = ConverterConfig.BI_PROTOCOL_FILE
BI_PROTOCOL = ConverterConfig.BI_PROTOCOL

def load_simple_yaml(file_path):
    """Simple BI protocol parser for VERSION|KEY|FILE1,FILE2,... format."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        result = {"BI_VERSIONS": {}, "DEFAULT_PROTOCOL": {}}
        
        for line in content.split('\n'):
            if not line.strip() or line.strip().startswith('#'):
                continue
            
            # Parse VERSION|KEY|FILE1,FILE2,... format
            parts = line.strip().split('|')
            if len(parts) >= 3:
                version = parts[0].strip()
                key = parts[1].strip()
                files = [f.strip() for f in parts[2].split(',') if f.strip()]
                
                if version == "DEFAULT":
                    if "external_refs" not in result["DEFAULT_PROTOCOL"]:
                        result["DEFAULT_PROTOCOL"]["external_refs"] = {}
                    result["DEFAULT_PROTOCOL"]["external_refs"][key] = files
                else:
                    if version not in result["BI_VERSIONS"]:
                        result["BI_VERSIONS"][version] = {"external_refs": {}}
                    if "external_refs" not in result["BI_VERSIONS"][version]:
                        result["BI_VERSIONS"][version]["external_refs"] = {}
                    result["BI_VERSIONS"][version]["external_refs"][key] = files
        
        return result
    except Exception as e:
        print(f"Warning: Failed to parse BI protocol: {e}")
        return None

def load_bi_protocol(script_dir):
    """Load BI protocol configuration from YAML file."""
    global BI_PROTOCOL
    protocol_path = os.path.join(script_dir, BI_PROTOCOL_FILE)
    if os.path.exists(protocol_path):
        BI_PROTOCOL = load_simple_yaml(protocol_path)
        if BI_PROTOCOL:
            return True
    return False

def get_bi_protocol(bi_version):
    """Get protocol configuration for a specific BI version."""
    if BI_PROTOCOL and "BI_VERSIONS" in BI_PROTOCOL:
        if bi_version in BI_PROTOCOL["BI_VERSIONS"]:
            return BI_PROTOCOL["BI_VERSIONS"][bi_version]
        elif "DEFAULT_PROTOCOL" in BI_PROTOCOL:
            return BI_PROTOCOL["DEFAULT_PROTOCOL"]
    return None

# CA decorations Cameo lacks -> same-footprint Cameo actor. Not listed + not in
# cameo_actors.txt = dropped. (Rocks dropped by default: Cameo rock1-7 render
# wrong on the RA temperate theater. Uncomment to bring them back.)
ACTOR_OVERRIDES = {
    # ============================================================================
    # TREE COLOR VARIANTS -> base tree (o=orange, p=pink, r=red, y=yellow, b=blue)
    # ============================================================================
    "t01o": "t01", "t01p": "t01", "t01r": "t01",
    "t02r": "t02",
    "t03o": "t03", "t03p": "t03", "t03y": "t03",
    "t05o": "t05", "t05p": "t05", "t05r": "t05", "t05y": "t05",
    "t06o": "t06", "t06r": "t06", "t06y": "t06",
    "t07o": "t07", "t07p": "t07", "t07r": "t07", "t07y": "t07",
    "t08b": "t08", "t08o": "t08", "t08p": "t08", "t08r": "t08", "t08y": "t08",
    "t10p": "t10", "t10r": "t10", "t10y": "t10",
    "t11o": "t11", "t11p": "t11", "t11y": "t11",
    "t12o": "t12", "t12p": "t12", "t12y": "t12",
    "t13o": "t13", "t13p": "t13", "t13r": "t13",
    "t14o": "t14", "t14r": "t14", "t14y": "t14",
    "t15o": "t15", "t15p": "t15", "t15y": "t15",
    "t16o": "t16", "t16p": "t16", "t16r": "t16", "t16y": "t16",
    "t17o": "t17", "t17r": "t17",
    "tc01b": "tc01",

    # ============================================================================
    # TREE CLUMPS -> tree clusters (HIGH ROI: 602 placements)
    # ============================================================================
    "tgb": "tc04",           # Tree group B (76 placements)
    "tgb.husk": "tc04",      # Tree group B husk
    "tgc1": "tc03",          # Tree clump 1 (139 placements)
    "tgc1.husk": "tc03",     # Tree clump 1 husk
    "tgc2": "tc04",          # Tree clump 2 (117 placements)
    "tgc2.husk": "tc04",     # Tree clump 2 husk
    "tgc3": "tc03",          # Tree clump 3
    "tgd": "tc05",           # Tree dense (64 placements)
    "tgd2": "tc05",          # Tree dense 2
    "tg1": "tc02",           # Tree group 1 (60 placements)
    "tg1.husk": "tc02",      # Tree group 1 husk
    "tg2": "tc03",           # Tree group 2 (61 placements)

    # ============================================================================
    # ROCK/STONE ACTORS -> DROP (TEMPORARY: Palette issue - see ROCK_PALETTE_ISSUE_FOR_DEV_TEAM.md)
    # CA rock actors would map to Cameo's rock1-7, which all use .des files (desert palette)
    # but render with ra_temperat.pal on RA_TEMPERAT tileset, causing incorrect colors
    # Verified: Cameo rock1-7 all use .des files in decorations.yaml
    # ============================================================================
    "stones1": "drop",      # 150 placements - would map to rock1 (palette issue)
    "stones2": "drop",      # 142 placements - would map to rock1 (palette issue)
    "stones3": "drop",      # 143 placements - would map to rock1 (palette issue)
    "stones4": "drop",      # 88 placements - would map to rock1 (palette issue)
    "stones11": "drop",     # 56 placements - would map to rock1 (palette issue)
    "stones12": "drop",     # 121 placements - would map to rock1 (palette issue)
    "stones13": "drop",     # 82 placements - would map to rock1 (palette issue)
    "stones14": "drop",     # 29 placements - would map to rock1 (palette issue)
    "rocks1": "drop",       # 126 placements - would map to rock1 (palette issue)
    "rocks2": "drop",       # 16 placements - would map to rock1 (palette issue)
    "rocks3": "drop",       # 69 placements - would map to rock1 (palette issue)
    "rocks_1x1_1": "drop",  # would map to rock1 (palette issue)
    "rocks_1x1_2": "drop",  # would map to rock1 (palette issue)
    "rocks_1x1_3": "drop",  # would map to rock1 (palette issue)
    "rocks_1x1_4": "drop",  # would map to rock1 (palette issue)
    "1x1rocks1": "drop",    # would map to rock1 (palette issue)
    "1x1rocks2": "drop",    # would map to rock1 (palette issue)
    "1x1rocks3": "drop",    # would map to rock1 (palette issue)
    "1x1searocks1": "drop", # would map to rock1 (palette issue)
    "1x1searocks2": "drop", # would map to rock1 (palette issue)
    "1x1searocks3": "drop", # would map to rock1 (palette issue)
    "2x1stones1": "drop",    # 18 placements - would map to rock5 (palette issue)
    "2x1stones2": "drop",    # 17 placements - would map to rock5 (palette issue)
    "2x1stones3": "drop",    # 6 placements - would map to rock5 (palette issue)
    "rocks_2x1_3": "drop",   # would map to rock1 (palette issue)
    "rocks_2x1_4": "drop",   # would map to rock1 (palette issue)
    "1x2stones1": "drop",    # 13 placements - would map to rock3 (palette issue)
    "1x2stones2": "drop",    # 16 placements - would map to rock3 (palette issue)
    "1x2stones3": "drop",    # 10 placements - would map to rock3 (palette issue)
    "2x2rocks1": "drop",     # 5 placements - would map to rock6 (palette issue)
    "2x2rocks2": "drop",     # 4 placements - would map to rock6 (palette issue)
    "2x2rocks3": "drop",     # 8 placements - would map to rock6 (palette issue)
    "2x2rocks4": "drop",     # 1 placement - would map to rock6 (palette issue)

    # ============================================================================
    # BUSHES -> DROP (no defensible Cameo equivalent; same footprint unavailable)
    # These are NOT controlled by REMOVE_PROBLEMATIC_ACTORS — they are always
    # dropped because turning them into rocks would place wrong-sized geometry.
    # ============================================================================
    "sbush1": "drop",        # small bush - no equivalent
    "sbush2": "drop",        # small bush - no equivalent
    "sbush3": "drop",        # small bush - no equivalent
    "bush1": "drop",         # bush - no equivalent
    "bush2": "drop",         # bush - no equivalent
    "bush3": "drop",         # bush - no equivalent
    "bush4": "drop",         # bush - no equivalent
    "bush5": "drop",         # bush - no equivalent
    "lbush1": "drop",        # large bush - no equivalent
    "lbush2": "drop",        # large bush - no equivalent

    # ============================================================================
    # CA-SPECIFIC WALLS -> Cameo equivalents
    # ============================================================================
    "swall": "wall",          # 102 placements -> stone wall
}

CAMEO_RES_INDEX = ConverterConfig.CAMEO_RES_INDEX
CAMEO_RES_MAXDENSITY = ConverterConfig.CAMEO_RES_MAXDENSITY
CAMEO_RES_ACTOR = ConverterConfig.CAMEO_RES_ACTOR
# RESOURCE_RICHNESS is the single tuning knob for resource value. The node
# tiering itself lives in resource_reclassification.py (symmetry-aware, based on
# each node's distance to its nearest spawn):
#   0.5 -> essentially all Ore   1.0 -> even Ore..Gold (no gems)   1.5 -> all Gems
# Mirror-paired nodes always receive the same tier (the balance guarantee).
RESOURCE_RICHNESS = ConverterConfig.RESOURCE_RICHNESS
WATER_FILL_SAFETY = ConverterConfig.WATER_FILL_SAFETY

# Actor removal toggle: when False, ACTOR_OVERRIDES entries that are "drop" due to
# the Cameo palette issue (rocks/stones/bushes) are remapped to their Cameo
# equivalents instead of being dropped. When True, they are dropped as before.
# CLI: --no-remove-actors  GUI: "Remove Problematic Actors" checkbox.
# Default True preserves existing behavior (rocks/bushes are dropped).
REMOVE_PROBLEMATIC_ACTORS = True

# Module-level cache: field metadata from the most recent assign_resources call.
# Set to a list of {center, cells, tier} dicts by assign_resources; read by
# render_preview to supply paint-mode field data to the GUI.
_last_assign_fields = []
_last_assign_nodes = []  # Store node information for tooltips

# The set of ACTOR_OVERRIDES keys that are dropped. Most are dropped because of
# the Cameo rock palette issue; a few (bushes) have no defensible Cameo
# equivalent and are always dropped. When REMOVE_PROBLEMATIC_ACTORS is False,
# only the actors listed in PALETTE_ISSUE_REMAPS are remapped to palette-mismatched
# Cameo rock actors (they will render with wrong colors on the RA temperate theater,
# but the rock geometry is preserved). Actors in this set but not in the remap
# (e.g., bushes) are dropped regardless of the toggle.
PALETTE_ISSUE_ACTORS = frozenset(k for k, v in ACTOR_OVERRIDES.items() if v == "drop")

# Palette-issue actor -> Cameo equivalent. Only rock/stone geometry is defensible:
# bushes and other decorative actors have no equivalent footprint in Cameo, so they
# are dropped regardless of the REMOVE_PROBLEMATIC_ACTORS toggle.
PALETTE_ISSUE_REMAPS = {
    # Stones and rock variants -> rock1
    "stones1": "rock1", "stones2": "rock1", "stones3": "rock1", "stones4": "rock1",
    "stones11": "rock1", "stones12": "rock1", "stones13": "rock1", "stones14": "rock1",
    "rocks1": "rock1", "rocks2": "rock1", "rocks3": "rock1",
    "rocks_1x1_1": "rock1", "rocks_1x1_2": "rock1", "rocks_1x1_3": "rock1", "rocks_1x1_4": "rock1",
    "1x1rocks1": "rock1", "1x1rocks2": "rock1", "1x1rocks3": "rock1",
    "1x1searocks1": "rock1", "1x1searocks2": "rock1", "1x1searocks3": "rock1",
    "rocks_2x1_3": "rock1", "rocks_2x1_4": "rock1",
    # 1x2 stones -> rock3
    "1x2stones1": "rock3", "1x2stones2": "rock3", "1x2stones3": "rock3",
    # 2x1 stones -> rock5
    "2x1stones1": "rock5", "2x1stones2": "rock5", "2x1stones3": "rock5",
    # 2x2 rocks -> rock6
    "2x2rocks1": "rock6", "2x2rocks2": "rock6", "2x2rocks3": "rock6", "2x2rocks4": "rock6",
}

# Source actors in CA maps; also include Cameo names in case actor matrix already ran
SOURCE_RESOURCE_ACTORS = ConverterConfig.SOURCE_RESOURCE_ACTORS

# Source resource remapping (kept separate for backward compatibility)
SOURCE_RES_REMAP = ConverterConfig.SOURCE_RES_REMAP

# ==========================================================================

KEEP_NAMES = ConverterConfig.KEEP_NAMES
NEW_CATEGORY = ConverterConfig.NEW_CATEGORY
CONVERTER_TAG = ConverterConfig.CONVERTER_TAG
EXTERNAL_REF_KEYS = ConverterConfig.EXTERNAL_REF_KEYS
ACTOR_NEVER_DROP = ConverterConfig.ACTOR_NEVER_DROP
ACTORS_FILE = ConverterConfig.ACTORS_FILE


def load_valid_actors(script_dir):
    path = os.path.join(script_dir, ACTORS_FILE)
    valid = set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    valid.add(ln.lower())
    return valid


class MapBin:
    def __init__(self, data):
        self.raw = bytearray(data)
        self.fmt = self.raw[0]
        self.width = struct.unpack_from("<H", self.raw, 1)[0]
        self.height = struct.unpack_from("<H", self.raw, 3)[0]
        self.cells = self.width * self.height

        # Validate dimensions
        validate_map_dimensions(self.width, self.height)

        # OpenRA map.bin has two formats:
        # Format 1: 5-byte header, tiles at offset 5, resources at 5 + W*H*3
        # Format 2: 17-byte header, offsets stored explicitly at bytes 5, 9, 13
        if self.fmt == 1:
            self.tiles_off = 5
            self.heights_off = 0
            self.res_off = 5 + self.cells * 3
        elif self.fmt == 2:
            self.tiles_off = struct.unpack_from("<I", self.raw, 5)[0]
            self.heights_off = struct.unpack_from("<I", self.raw, 9)[0]
            self.res_off = struct.unpack_from("<I", self.raw, 13)[0]
        else:
            raise ValueError("Unknown map.bin format byte: %d" % self.fmt)

        if self.res_off + self.cells * 2 > len(self.raw):
            raise ValueError("map.bin too short for %dx%d (fmt=%d)" % (self.width, self.height, self.fmt))

    def tile_type(self, i):
        return struct.unpack_from("<H", self.raw, self.tiles_off + i * 3)[0]

    def set_tile(self, i, t, idx):
        struct.pack_into("<H", self.raw, self.tiles_off + i * 3, t)
        self.raw[self.tiles_off + i * 3 + 2] = idx

    def res_density(self, i):
        return self.raw[self.res_off + i * 2 + 1]

    def set_res(self, i, t, d=None):
        b = self.res_off + i * 2
        self.raw[b] = t
        if d is not None:
            self.raw[b + 1] = d

    def cell_xy(self, i):
        # Column-major layout: cell i = col*H + row
        # col = i // height, row = i % height
        return i // self.height, i % self.height

    def cell_index(self, col, row):
        """Convert (col, row) to cell index using column-major order (matches OpenRA Map.cs)."""
        return col * self.height + row

    def resource_cells(self):
        return [i for i in range(self.cells) if self.raw[self.res_off + i * 2] != 0]

    def bytes(self):
        return bytes(self.raw)


def indent_of(line):
    n = 0
    for ch in line:
        if ch == "\t":
            n += 1
        else:
            break
    return n


def set_scalar(lines, key, value):
    pat = re.compile(r"^" + re.escape(key) + r":")
    for i, ln in enumerate(lines):
        if indent_of(ln) == 0 and pat.match(ln):
            lines[i] = "%s: %s" % (key, value)
            return True
    return False


def remove_scalar(lines, key):
    pat = re.compile(r"^" + re.escape(key) + r":")
    return [ln for ln in lines if not (indent_of(ln) == 0 and pat.match(ln))]


def remove_toplevel_block(lines, key):
    pat = re.compile(r"^" + re.escape(key) + r":(.*)$")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if indent_of(ln) == 0 and pat.match(ln):
            i += 1
            while i < n and (lines[i].strip() == "" or indent_of(lines[i]) > 0):
                if lines[i].strip() != "" and indent_of(lines[i]) == 0:
                    break
                i += 1
            continue
        out.append(ln)
        i += 1
    return out


def extract_palette_blocks(text):
    lines = text.replace("\r\n", "\n").split("\n")
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if "PaletteFromFile@" in ln and ln.strip().endswith(":"):
            base = indent_of(ln)
            block = [ln]
            i += 1
            while i < n and (lines[i].strip() == "" or indent_of(lines[i]) > base):
                block.append(lines[i])
                i += 1
            fname = None
            for b in block:
                m = re.match(r"^\s*Filename:\s*(\S+)", b)
                if m:
                    fname = os.path.basename(m.group(1)).lower()
                    break
            blocks.append({"base": base, "block": block, "filename": fname})
            continue
        i += 1
    return blocks


def parse_actors(map_lines):
    actors = []
    in_actors = False
    cur = None
    for i, ln in enumerate(map_lines):
        if indent_of(ln) == 0:
            in_actors = ln.startswith("Actors:")
            if cur:
                actors.append(cur)
                cur = None
            continue
        if not in_actors:
            continue
        m = re.match(r"^\t([A-Za-z0-9_]+):\s*([A-Za-z0-9_.\-]+)\s*$", ln)
        if m and indent_of(ln) == 1:
            if cur:
                actors.append(cur)
            cur = {"id": m.group(1), "name": m.group(2),
                   "type_line_i": i, "x": None, "y": None}
            continue
        ml = re.match(r"^\t\tLocation:\s*(\d+)\s*,\s*(\d+)", ln)
        if ml and cur:
            cur["x"] = int(ml.group(1))
            cur["y"] = int(ml.group(2))
    if cur:
        actors.append(cur)
    return actors


def nearest_spawn_dist(x, y, spawns):
    best = None
    for sx, sy in spawns:
        d = math.hypot(x - sx, y - sy)
        if best is None or d < best:
            best = d
    return best if best is not None else 0.0


def actor_action(name, valid, autodrop):
    nl = name.lower()
    base = nl.split(".")[0]
    # Check ACTOR_OVERRIDES, but honour REMOVE_PROBLEMATIC_ACTORS toggle:
    # palette-issue actors (rocks/bushes) that would be dropped are kept when
    # the toggle is off.
    for key in (nl, base):
        if key in ACTOR_OVERRIDES:
            action = ACTOR_OVERRIDES[key]
            if action == "drop" and key in PALETTE_ISSUE_ACTORS:
                if not REMOVE_PROBLEMATIC_ACTORS and key in PALETTE_ISSUE_REMAPS:
                    # Toggle is off and the actor has a defensible Cameo
                    # equivalent: remap it (e.g., rocks1 -> rock1). It will render
                    # with wrong colors on the RA temperate theater, but the
                    # geometry is preserved. Return immediately so the autodrop
                    # logic below cannot drop it.
                    return PALETTE_ISSUE_REMAPS[key]
                # Toggle is on, or the actor has no defensible equivalent (e.g.
                # bushes): drop it.
                return "drop"
            return action
    if nl in valid or base in valid or nl in ACTOR_NEVER_DROP:
        return "keep"
    return "drop" if autodrop else "keep"


def apply_actor_matrix(lines, valid, autodrop, rpt):
    out = []
    i = 0
    n = len(lines)
    in_actors = False
    dropped = {}
    remapped = {}
    rock_conversions = {}  # Track rock->barl conversions for restoration
    rock_remaps = {}       # Track rocks remapped to palette-mismatched Cameo actors
    while i < n:
        ln = lines[i]
        if indent_of(ln) == 0:
            in_actors = ln.startswith("Actors:")
            out.append(ln)
            i += 1
            continue
        m = re.match(r"^\t([A-Za-z0-9_]+):\s*([A-Za-z0-9_.\-]+)\s*$", ln) if in_actors else None
        if m and indent_of(ln) == 1:
            name = m.group(2)
            nl = name.lower()
            act = actor_action(name, valid, autodrop)
            # Track rock drops/remaps separately for restoration logging
            is_palette_issue = nl in PALETTE_ISSUE_ACTORS
            if act == "drop":
                if is_palette_issue:
                    rock_conversions[nl] = rock_conversions.get(nl, 0) + 1
                else:
                    dropped[nl] = dropped.get(nl, 0) + 1
                i += 1
                while i < n and (lines[i].strip() == "" or indent_of(lines[i]) >= 2):
                    i += 1
                continue
            if act != "keep":
                ln = re.sub(r"(:\s*)" + re.escape(name) + r"\s*$", r"\g<1>" + act, ln)
                remapped[nl] = remapped.get(nl, 0) + 1
                if is_palette_issue:
                    rock_remaps[nl] = rock_remaps.get(nl, 0) + 1
            out.append(ln)
            i += 1
            continue
        out.append(ln)
        i += 1
    if remapped:
        rpt.add("remapped %d actor placement(s) to Cameo equivalents"
                % sum(remapped.values()))
    if rock_remaps:
        rpt.add("ROCK PALETTE WORKAROUND: %d rock/stone/bush actor(s) kept with palette-mismatched Cameo equivalents (see ROCK_PALETTE_ISSUE_FOR_DEV_TEAM.md for restoration)"
                % sum(rock_remaps.values()))
        rpt.add("Palette-issue actors kept: " + ", ".join(f"{k}->{PALETTE_ISSUE_REMAPS[k]}({v})" for k, v in sorted(rock_remaps.items())))
    if rock_conversions:
        rpt.add("ROCK PALETTE WORKAROUND: %d rock/stone/bush actor(s) dropped due to palette issue (see ROCK_PALETTE_ISSUE_FOR_DEV_TEAM.md for restoration)"
                % sum(rock_conversions.values()))
        rpt.add("Dropped rock types for restoration: " + ", ".join(f"{k}({v})" for k, v in sorted(rock_conversions.items())))
    if dropped:
        rpt.add("dropped %d unmatched actor placement(s), %d type(s)"
                % (sum(dropped.values()), len(dropped)))
    return out


# Stray-water fix: a real water body is fully enclosed by shore (Beach/Rock),
# river, other water, or the map edge. A leftover ford/water patch instead leaks
# straight into plain LAND (Clear/Rough/Road). So: a non-border water blob that
# touches any land template is erroneous -> fill it with grass. Size-independent;
# real lakes/ponds are kept because they never abut bare grass. Per tileset:
#   water template ids | clear (fill) template | land template ids.
TILESET_WATER = {
    "RA_TEMPERAT": {
        "water": frozenset({1, 2}),
        "clear": 255,
        "grass": frozenset({255}),  # Clear template is the fillable grass type
        "beach": frozenset(range(3, 57)),
        "land": frozenset({
            107, 108, 173, 174, 175, 176, 177, 178, 179, 180, 181, 183, 184,
            187, 189, 191, 192, 194, 195, 196, 197, 198, 199, 200, 201, 202,
            203, 204, 205, 206, 207, 208, 209, 210, 211, 212, 214, 215, 221,
            227, 228, 255, 400, 580, 581, 582, 583, 584, 585, 586, 587, 588,
            590, 591, 859, 65535}),
    },
}

# Template remapping: CA custom templates -> RA_TEMPERAT equivalents
# Deterministic mapping based on terrain category - no adjacency heuristics
# Load template remappings from YAML file
def load_template_remap():
    """Load template remappings from template_matrix.yaml."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    yaml_path = os.path.join(script_dir, "template_matrix.yaml")
    
    default_remap = {
        "RA_TEMPERAT": {
            # Water wreckage/debris (CA-specific) -> clear (not water)
            157: 255,  # Water wreckage -> clear (987 placements)
            166: 166,  # Water rocky edge -> keep as-is (718 placements)
            
            # Rocky debris (CA custom -> clear)
            221: 255,  # Rocky debris -> clear (243 placements) - was incorrectly mapped to water
            
            # CA custom hill/terrain templates -> clear (no RA equivalent)
            400: 255,  # hill01 -> clear
            # 401-404: Standard RA cliff tiles (cliffsl1-4) - keep as-is (template 404 exists in Cameo)
            # 405: cliffsw1 (water cliff) - keep as-is
            # Note: Template 406 was previously preserved as cliff tiles at specific coordinates
            
            # Template 0 (invalid) -> clear
            0: 255,
        }
    }
    
    try:
        if os.path.exists(yaml_path):
            with open(yaml_path, 'r') as f:
                content = f.read()
            
            # Simple YAML parser for key-value pairs
            ca_mappings = {}
            in_ca_mappings = False
            
            for line in content.split('\n'):
                original_line = line
                line = line.rstrip()
                
                # Check if we're in the ca_template_mappings section
                if line.strip().startswith('ca_template_mappings:'):
                    in_ca_mappings = True
                    continue
                
                # Exit if we hit another top-level section (not indented)
                if in_ca_mappings and line and not line.startswith(' ') and not line.startswith('\t') and ':' in line:
                    break
                
                # Parse key-value pairs (must be indented)
                if in_ca_mappings and (line.startswith('  ') or line.startswith('\t')) and ':' in line:
                    # Remove comments
                    if '#' in line:
                        line = line[:line.index('#')]
                    
                    # Parse key: value
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key_str = parts[0].strip()
                        value_str = parts[1].strip()
                        
                        try:
                            key = int(key_str)
                            value = int(value_str)
                            ca_mappings[key] = value
                        except ValueError:
                            # Skip non-integer keys
                            pass
            
            if ca_mappings:
                remap = {"RA_TEMPERAT": ca_mappings}
                print(f"Loaded {len(ca_mappings)} template mappings from {yaml_path}")
                return remap
            else:
                print(f"Warning: No ca_template_mappings found in {yaml_path}, using defaults")
                return default_remap
        else:
            print(f"Warning: {yaml_path} not found, using default template remappings")
            return default_remap
    except Exception as e:
        print(f"Error loading template remappings from {yaml_path}: {e}")
        print("Using default template remappings")
        return default_remap

# Load template remappings at module load time
TEMPLATE_REMAP = load_template_remap()


# Source mod resource indices -> Cameo resource indices
# RA mod: Ore=1, Gems=2
# Cameo:  Tiberium=1, BlueTiberium=2, Ore=3, Gems=4
SOURCE_RES_REMAP = {
    "ra":              {1: 3, 2: 4},   # RA Ore->Ore(3), RA Gems->Gems(4)
    "ca":              {1: 3, 2: 4},   # CA/Combined Arms uses same resource indices
}


def remap_source_resources(mb, src_mod, rpt):
    """Remap source mod resource indices to Cameo indices (always run for 1-1 conversion).

    CA/RA maps use Ore=1, Gems=2.  Cameo uses Ore=3, Gems=4.
    This function always runs to ensure basic 1-1 conversion works correctly.
    When remap_resources is enabled, assign_resources will then re-type fields
    by node distance (distance-based tiering). When disabled, resources stay
    as the 1-1 remapped types.
    """
    if mb is None:
        return
    remap = SOURCE_RES_REMAP.get(src_mod.lower())
    if not remap:
        return
    remapped = 0
    for i in range(mb.cells):
        t = mb.raw[mb.res_off + i * 2]
        if t in remap:
            mb.raw[mb.res_off + i * 2] = remap[t]
            remapped += 1
    if remapped:
        details = ", ".join("%d->%d" % (k, v) for k, v in sorted(remap.items()))
        rpt.add("remapped %d source resource cell(s): %s" % (remapped, details))


def remap_templates(mb, new_ts, rpt, bi_protocol=None):
    """Remap CA-specific templates to RA equivalents using deterministic mapping."""
    remap = TEMPLATE_REMAP.get(new_ts)
    if mb is None or not remap:
        return

    remapped_count = 0
    by_template = {}

    # Get water tile IDs for this tileset
    water_cfg = TILESET_WATER.get(new_ts)
    water_ids = water_cfg["water"] if water_cfg else set()

    # Determine if contextual tile 225 handling should be used
    # Disabled - edge-crawling model not finding water crossings in this map
    # All tile 225 converts to grass to avoid incorrect water crossing placement
    use_contextual_225 = False

    # First pass: identify which tile 225 cells should be water crossings
    # Smart edge-crawling model: crawl water body edges to find grass abutting water
    water_crossing_225 = set()
    if use_contextual_225:
        # Step 1: Identify all water bodies using connected component analysis
        water_cells = set(i for i in range(mb.cells) if mb.tile_type(i) in water_ids)
        water_bodies = []
        visited = set()
        
        for start in water_cells:
            if start in visited:
                continue
            # BFS to find connected water body
            body = set()
            queue = [start]
            visited.add(start)
            while queue:
                cell = queue.pop(0)
                body.add(cell)
                col, row = mb.cell_xy(cell)
                # Check 4 neighbors
                for dc, dr in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    nc, nr = col + dc, row + dr
                    if 0 <= nc < mb.width and 0 <= nr < mb.height:
                        ni = mb.cell_index(nc, nr)
                        if ni in water_cells and ni not in visited:
                            visited.add(ni)
                            queue.append(ni)
            water_bodies.append(body)
        
        # Step 2: Edge-crawling model - find where terrain abuts water
        # For each water body, crawl its edge and find narrow terrain passages
        for body in water_bodies:
            # Find all edge cells (water cells adjacent to non-water)
            edge_cells = set()
            for cell in body:
                col, row = mb.cell_xy(cell)
                for dc, dr in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    nc, nr = col + dc, row + dr
                    if 0 <= nc < mb.width and 0 <= nr < mb.height:
                        ni = mb.cell_index(nc, nr)
                        if ni not in body:
                            edge_cells.add(cell)
                            break
            
            # Step 3: For each edge cell, check if adjacent to grass (valid terrain)
            # and crawl to find narrow passages
            for cell in edge_cells:
                col, row = mb.cell_xy(cell)
                for dc, dr in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    nc, nr = col + dc, row + dr
                    if 0 <= nc < mb.width and 0 <= nr < mb.height:
                        ni = mb.cell_index(nc, nr)
                        tile_t = mb.tile_type(ni)
                        # Check if this is any terrain (not water) - "naked terrain abutting water"
                        if tile_t not in water_ids:  # Any non-water terrain
                            # Step 4: Crawl from this terrain to find if it forms a narrow passage
                            # BFS to find connected terrain cluster
                            terrain_cluster = set()
                            terrain_queue = [ni]
                            terrain_visited = {ni}
                            
                            while terrain_queue:
                                tcell = terrain_queue.pop(0)
                                terrain_cluster.add(tcell)
                                tcol, trow = mb.cell_xy(tcell)
                                
                                # Check 4 neighbors for same terrain type
                                for tdc, tdr in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                                    tnc, tnr = tcol + tdc, trow + tdr
                                    if 0 <= tnc < mb.width and 0 <= tnr < mb.height:
                                        tni = mb.cell_index(tnc, tnr)
                                        if mb.tile_type(tni) == tile_t and tni not in terrain_visited:
                                            terrain_visited.add(tni)
                                            terrain_queue.append(tni)
                            
                            # Step 5: Check if this terrain cluster forms a narrow passage
                            # Count how many water bodies this cluster is adjacent to
                            adjacent_water_count = 0
                            for tcell in terrain_cluster:
                                tcol, trow = mb.cell_xy(tcell)
                                for tdc, tdr in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                                    tnc, tnr = tcol + tdc, trow + tdr
                                    if 0 <= tnc < mb.width and 0 <= tnr < mb.height:
                                        tni = mb.cell_index(tnc, tnr)
                                        if mb.tile_type(tni) in water_ids:
                                            adjacent_water_count += 1
                                            break
                                if adjacent_water_count >= 2:
                                    break
                            
                            # If cluster is adjacent to 2+ water bodies and is small, it's a crossing
                            if adjacent_water_count >= 2 and len(terrain_cluster) <= 12:
                                # Mark all cells in this cluster as water crossings (regardless of tile type)
                                # Then convert tile 225 cells to 591, others keep as-is
                                for tcell in terrain_cluster:
                                    if mb.tile_type(tcell) == 225:
                                        water_crossing_225.add(tcell)

    # Edge-crawling model complete - identified valid water crossing points

    # Third pass: apply remapping
    for i in range(mb.cells):
        tile_t = mb.tile_type(i)
        
        # Special handling for tile 225: context-aware remapping (if enabled)
        if tile_t == 225:
            if use_contextual_225:
                new_t = 591 if i in water_crossing_225 else 255
            else:
                # If contextual handling disabled, use standard remapping or keep as-is
                new_t = remap.get(tile_t, tile_t)
        elif tile_t in remap:
            new_t = remap[tile_t]
        else:
            continue

        idx = mb.raw[mb.tiles_off + i * 3 + 2]  # keep same index
        mb.set_tile(i, new_t, idx)

        remapped_count += 1
        by_template[tile_t] = by_template.get(tile_t, 0) + 1

    if remapped_count:
        details = []
        for t, c in sorted(by_template.items()):
            if t == 225:
                # Special case: tile 225 maps contextually
                water_count = len(water_crossing_225)
                details.append(f"{t}->591({water_count})+255({c-water_count})")
            elif t in remap:
                details.append(f"{t}->{remap[t]}({c})")
            else:
                details.append(f"{t}->?({c})")
        rpt.add(f"remapped {remapped_count} tile(s): {', '.join(details)}")


def fill_stray_water(mb, new_ts, rpt, safety=WATER_FILL_SAFETY):
    cfg = TILESET_WATER.get(new_ts)
    if mb is None or not cfg:
        return
    water_ids, clear_id, land = cfg["water"], cfg["clear"], cfg["land"]
    W, H = mb.width, mb.height
    water = set(i for i in range(mb.cells) if mb.tile_type(i) in water_ids)
    if not water:
        return
    seen = set()
    filled = 0
    patches = 0
    flagged = 0
    for s in water:
        if s in seen:
            continue
        comp = []
        dq = deque([s])
        seen.add(s)
        border = False
        leak = False
        while dq:
            c = dq.popleft()
            comp.append(c)
            # Column-major: cell = col*H + row; col = c//H, row = c%H
            col, row = c // H, c % H
            for dcol, drow in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ncol, nrow = col + dcol, row + drow
                if not (0 <= ncol < W and 0 <= nrow < H):
                    border = True
                    continue
                nc = ncol * H + nrow
                if nc in water:
                    if nc not in seen:
                        seen.add(nc)
                        dq.append(nc)
                elif mb.tile_type(nc) in land:
                    leak = True
        if (not border) and leak:
            if len(comp) <= safety:
                for c in comp:
                    mb.set_tile(c, clear_id, 0)
                filled += len(comp)
                patches += 1
            else:
                flagged += 1
    if filled:
        rpt.add("filled %d water cell(s) in %d patch(es) that leaked into grass -> grass"
                % (filled, patches))
    if flagged:
        rpt.add("!! %d large water blob(s) touch grass but exceed safety size -- REVIEW" % flagged)


def fill_grass_in_water(mb, new_ts, rpt):
    """Mirror of fill_stray_water: a grass tile stranded in the shore -- one that
    has at least one WATER neighbour and is otherwise hemmed in by water / beach /
    the map edge (>=3 such of its 8 neighbours) -- is converted to water (copying
    an adjacent water tile so it renders correctly). Straight lake/river banks have
    grass on most sides, so they keep their shoreline; only corners and pockets
    poking into the water are filled."""
    cfg = TILESET_WATER.get(new_ts)
    if mb is None or not cfg or "beach" not in cfg:
        return
    water_ids = cfg["water"]
    grass_ids = cfg.get("grass", frozenset({cfg["clear"]}))
    beach_ids = cfg["beach"]
    W, H = mb.width, mb.height
    targets = []
    for i in range(mb.cells):
        if mb.tile_type(i) not in grass_ids:
            continue
        # Column-major: col = i//H, row = i%H
        col, row = i // H, i % H
        wn = bn = en = 0
        wsrc = None
        for dcol in (-1, 0, 1):
            for drow in (-1, 0, 1):
                if dcol == 0 and drow == 0:
                    continue
                ncol, nrow = col + dcol, row + drow
                if not (0 <= ncol < W and 0 <= nrow < H):
                    en += 1
                    continue
                nc = ncol * H + nrow
                t = mb.tile_type(nc)
                if t in water_ids:
                    wn += 1
                    wsrc = nc
                elif t in beach_ids:
                    bn += 1
        if wn >= 1 and (wn + bn + en) >= 3:
            targets.append((i, wsrc))
    for i, wsrc in targets:
        wt = mb.tile_type(wsrc)
        widx = mb.raw[mb.tiles_off + wsrc * 3 + 2]
        mb.set_tile(i, wt, widx)
    if targets:
        rpt.add("filled %d grass tile(s) stranded in water -> water" % len(targets))


def _density_for_type(tier, density_setting=None):
    """Convert a density level (1-5, "Random", "Replace"/None) to a byte value.

    None or "Replace" => keep existing density (return None).
    """
    if density_setting is None or density_setting == "Replace":
        return None
    caps = {
        "Tiberium": 35, "BlueTiberium": 30, "Ore": 40,
        "Gems": 15, "RedTiberium": 25, "GoldTiberium": 20,
    }
    cap = caps.get(tier, 40)
    if density_setting == "Random":
        import random
        level = random.randint(1, 5)
        return max(1, (cap * level) // 5)
    try:
        level = int(density_setting)
    except (ValueError, TypeError):
        return None
    if 1 <= level <= 5:
        return max(1, (cap * level) // 5)
    return cap


def _apply_density_for_override(mb, cell_idx, tier, density_override, cap):
    """Return the density byte to write for a cell override.

    density_override may be None (use existing), an int (use it, capped), or a
    string (1-5 / "Random" / "Replace") that needs conversion.
    """
    if density_override is None or density_override == "Replace":
        dens = mb.res_density(cell_idx)
        return cap if (dens == 0 or dens > cap) else dens
    if isinstance(density_override, int):
        return min(density_override, cap)
    # String setting (legacy GUI storage)
    converted = _density_for_type(tier, density_override)
    if converted is None:
        dens = mb.res_density(cell_idx)
        return cap if (dens == 0 or dens > cap) else dens
    return min(converted, cap)


def assign_resources(lines, actors, mb, spawns, rpt, paint_overrides=None, cell_overrides=None, node_overrides=None, node_affects_field_tier=True, manual_only=False, density_overrides=None, field_density_overrides=None):
    """Resource fields and nodes (rebuilt 2026-06-19).

    Single source of truth, symmetry-safe:
      * Node tiers come from the symmetry-aware nearest-spawn algorithm
        (assign_node_tiers_corrected); mirror-paired nodes already share a tier.
      * Each contiguous resource field is owned by the node inside it (or the
        nearest node) and painted with that node's tier.
      * Field tiers are then symmetrized: mirror-paired fields are forced to a
        single tier, so the painted map stays balanced even where field ownership
        is slightly asymmetric on a human-built map.
      * Each node actor is finally set to the resource it actually stands in, so a
        node's colour always matches its field (no "red node in an ore field").
    """
    global _last_assign_fields, _last_assign_nodes
    seeds = [a for a in actors
             if a["name"] in SOURCE_RESOURCE_ACTORS and a["x"] is not None]
    if mb is None:
        return
    W, H = mb.width, mb.height
    cells = mb.resource_cells()

    # Manual-only mode: skip automatic tier assignment, only apply overrides
    if manual_only:
        # Build paint-mode field decomposition from the current map state so painting
        # works even when remap_resources is disabled.
        fields = []
        if cells:
            cellset = set(cells)
            label = {}
            for start in cells:
                if start in label:
                    continue
                fid = len(fields)
                comp = []
                dq = deque([start])
                label[start] = fid
                while dq:
                    cur = dq.popleft()
                    comp.append(cur)
                    ccol, crow = cur // H, cur % H
                    for dcol in (-1, 0, 1):
                        for drow in (-1, 0, 1):
                            ncol, nrow = ccol + dcol, crow + drow
                            nc = ncol * H + nrow
                            if 0 <= ncol < W and 0 <= nrow < H and nc in cellset and nc not in label:
                                label[nc] = fid
                                dq.append(nc)
                fields.append(comp)

        def field_center(comp):
            return (sum(c // H for c in comp) / len(comp),
                    sum(c % H for c in comp) / len(comp))

        centers = [field_center(comp) for comp in fields]
        transforms, _center = detect_symmetries(spawns, seeds)
        _map_center = tuple(_center)
        _transforms = transforms

        RES_BY_IDX = {v: k for k, v in CAMEO_RES_INDEX.items()}
        field_tier = {}
        for fid, comp in enumerate(fields):
            type_counts = {}
            for c in comp:
                t = RES_BY_IDX.get(mb.raw[mb.res_off + c * 2])
                if t:
                    type_counts[t] = type_counts.get(t, 0) + 1
            field_tier[fid] = max(type_counts, key=type_counts.get) if type_counts else "Ore"

        # Apply field-level paint overrides (hand-painted whole fields).
        if paint_overrides:
            for fid, (cx, cy) in enumerate(centers):
                key = "%d,%d" % (round(cx), round(cy))
                if key in paint_overrides and paint_overrides[key] in CAMEO_RES_INDEX:
                    field_tier[fid] = paint_overrides[key]

        # Apply field-level density overrides and normalize densities.
        # In manual-only mode, preserve each cell's original type unless the field
        # has an explicit paint override; this prevents adjacent mixed-type fields
        # from being merged into a single majority type.
        for fid, comp in enumerate(fields):
            key = "%d,%d" % (round(centers[fid][0]), round(centers[fid][1]))
            field_res_override = paint_overrides.get(key) if paint_overrides else None
            field_density = field_density_overrides.get(key) if field_density_overrides else None
            for c in comp:
                if field_res_override in CAMEO_RES_INDEX:
                    res = field_res_override
                else:
                    res = RES_BY_IDX.get(mb.raw[mb.res_off + c * 2])
                    if res is None:
                        continue
                idx = CAMEO_RES_INDEX[res]
                cap = CAMEO_RES_MAXDENSITY[idx]
                dens = _apply_density_for_override(mb, c, res, field_density, cap)
                mb.set_res(c, idx, dens)

        # Apply cell overrides on top of the field paint.
        if cell_overrides:
            for cell_key, tier in cell_overrides.items():
                if tier in CAMEO_RES_INDEX:
                    col, row = map(int, cell_key.split(','))
                    cell_idx = col * H + row
                    if 0 <= cell_idx < mb.cells:
                        idx = CAMEO_RES_INDEX[tier]
                        cap = CAMEO_RES_MAXDENSITY[idx]
                        density_override = density_overrides.get(cell_key) if density_overrides else None
                        dens = _apply_density_for_override(mb, cell_idx, tier, density_override, cap)
                        mb.set_res(cell_idx, idx, dens)

        # Recompute field_tier and density from the *final* painted map.bin so
        # tooltips and the GUI metadata match what is actually written.
        if cells:
            for fid, comp in enumerate(fields):
                type_counts = {}
                for c in comp:
                    t = RES_BY_IDX.get(mb.raw[mb.res_off + c * 2])
                    if t:
                        type_counts[t] = type_counts.get(t, 0) + 1
                field_tier[fid] = max(type_counts, key=type_counts.get) if type_counts else "Ore"

            _sym_parent = list(range(len(fields)))
            def _sym_find(a):
                while _sym_parent[a] != a:
                    _sym_parent[a] = _sym_parent[_sym_parent[a]]
                    a = _sym_parent[a]
                return a
            def _sym_union(a, b):
                ra, rb = _sym_find(a), _sym_find(b)
                if ra != rb:
                    _sym_parent[ra] = rb

            FTOL = 5.0
            if transforms and len(fields) > 1:
                for _name, T in transforms:
                    for fid, (cx, cy) in enumerate(centers):
                        tx, ty = T(cx, cy)
                        best_d = None
                        bj = None
                        for fj, (ox, oy) in enumerate(centers):
                            d = math.hypot(tx - ox, ty - oy)
                            if best_d is None or d < best_d:
                                best_d, bj = d, fj
                        if bj is not None and bj != fid and best_d <= FTOL:
                            _sym_union(fid, bj)

            sym_groups = {}
            for fid in range(len(fields)):
                sym_groups.setdefault(_sym_find(fid), []).append(fid)

            fid_mirror_keys = {}
            for grp in sym_groups.values():
                keys = ["%d,%d" % (round(centers[fid][0]), round(centers[fid][1])) for fid in grp]
                for fid in grp:
                    fid_mirror_keys[fid] = keys

            _last_assign_fields = [
                {
                    "center": centers[fid],
                    "cells": set(fields[fid]),
                    "cell_count": len(fields[fid]),
                    "tier": field_tier[fid],
                    "map_height": H,
                    "mirror_keys": fid_mirror_keys.get(fid, [
                        "%d,%d" % (round(centers[fid][0]), round(centers[fid][1]))
                    ]),
                    "map_center": _map_center,
                    "transforms": _transforms,
                    "density": {c: mb.res_density(c) for c in fields[fid]},
                    "nodes": [],
                }
                for fid in range(len(fields))
            ]

            # Assign each resource node to its closest field.
            for s in seeds:
                ccol, crow = s['x'], s['y']
                best_fid = None
                best_dist = float("inf")
                for fid, comp in enumerate(fields):
                    if not comp:
                        continue
                    for c in comp:
                        fcol = c // H
                        frow = c % H
                        dist = ((ccol - fcol) ** 2 + (crow - frow) ** 2) ** 0.5
                        if dist < best_dist:
                            best_dist = dist
                            best_fid = fid
                if best_fid is not None:
                    _last_assign_fields[best_fid]["nodes"].append((ccol, crow))

            # Build node -> field lookup so each node can inherit the tier of the
            # field it actually sits in. Explicit node overrides win; isolated nodes
            # (not inside any field) fall back to their current actor name.
            NODE_ACTOR_TO_RES = {
                "mine": "Ore", "gmine": "Gems",
                "split2": "Tiberium", "split3": "Tiberium",
                "splitblue": "BlueTiberium", "splitbluesmall": "BlueTiberium",
                "splitred": "RedTiberium", "splitredsmall": "RedTiberium",
                "splitgold": "GoldTiberium", "splitgoldsmall": "GoldTiberium",
            }
            node_to_field = {}
            for fid, f in enumerate(_last_assign_fields):
                for (nx, ny) in f.get("nodes", []):
                    node_to_field[(nx, ny)] = fid

            _last_assign_nodes = []
            for s in seeds:
                node_key = f"{s['x']},{s['y']}"
                if node_overrides and node_key in node_overrides:
                    res = node_overrides[node_key]
                else:
                    fid = node_to_field.get((s['x'], s['y']))
                    if fid is not None:
                        res = field_tier[fid]
                    else:
                        res = NODE_ACTOR_TO_RES.get(s["name"], "Unknown")
                _last_assign_nodes.append({"x": s['x'], "y": s['y'], "resource": res})
                # Ensure the actor name reflects the effective node resource type.
                na = CAMEO_RES_ACTOR.get(res)
                if na:
                    # The line may already have been renamed by a previous pass; match
                    # the current actor token at the end of the line.
                    old_line = lines[s["type_line_i"]]
                    match = re.search(r":\s*([A-Za-z0-9_]+)\s*$", old_line)
                    if match and match.group(1) != na:
                        lines[s["type_line_i"]] = re.sub(
                            r"(:\s*)" + re.escape(match.group(1)) + r"\s*$",
                            r"\g<1>" + na, old_line)

        rpt.add("manual overrides applied (no automatic tiering)")
        return

    # node tier by the symmetry-aware nearest-spawn algorithm.
    # For "even" mode we need field cell counts first, so we defer final tier
    # assignment until after field decomposition (see below).
    is_even_mode = (_rr.DISTRIBUTION_MODE == "even")
    if is_even_mode:
        # Temporary tier assignment via "distance" to establish field ownership.
        node_res = assign_node_tiers_corrected(seeds, spawns, RESOURCE_RICHNESS, mode="distance")
    else:
        node_res = assign_node_tiers_corrected(seeds, spawns, RESOURCE_RICHNESS)

    # Apply node overrides (hand-paint mode) before field ownership and node actor
    # typing are computed, so the painted node type flows into both the field tier
    # and the actor rendered in the preview.
    # When node_affects_field_tier=False, node overrides only affect the actor rendering,
    # not the field tier calculation (allows independent node painting).
    if node_overrides and node_affects_field_tier:
        for i, s in enumerate(seeds):
            node_key = f"{s['x']},{s['y']}"
            if node_key in node_overrides and node_overrides[node_key] in CAMEO_RES_INDEX:
                node_res[i] = node_overrides[node_key]

    if not cells:
        # no resource fields: type the node actors purely by distance
        if is_even_mode:
            # For even mode with no cells, fall back to distance assignment.
            node_res = assign_node_tiers_corrected(seeds, spawns, RESOURCE_RICHNESS, mode="distance")
            # Re-apply node overrides after the fallback assignment.
            if node_overrides:
                for i, s in enumerate(seeds):
                    node_key = f"{s['x']},{s['y']}"
                    if node_key in node_overrides and node_overrides[node_key] in CAMEO_RES_INDEX:
                        node_res[i] = node_overrides[node_key]
        ac = {}
        for i, s in enumerate(seeds):
            na = CAMEO_RES_ACTOR[node_res[i]]
            if na != s["name"]:
                lines[s["type_line_i"]] = re.sub(
                    r"(:\s*)" + re.escape(s["name"]) + r"\s*$",
                    r"\g<1>" + na, lines[s["type_line_i"]])
            ac[na] = ac.get(na, 0) + 1
        rpt.add("nodes (by distance) -> "
                + ", ".join("%s:%d" % (k, v) for k, v in sorted(ac.items())))
        return

    # contiguous resource fields (8-connected); column-major cell = col*H + row
    cellset = set(cells)
    label = {}
    fields = []
    for start in cells:
        if start in label:
            continue
        fid = len(fields)
        comp = []
        dq = deque([start])
        label[start] = fid
        while dq:
            cur = dq.popleft()
            comp.append(cur)
            ccol, crow = cur // H, cur % H
            for dcol in (-1, 0, 1):
                for drow in (-1, 0, 1):
                    ncol, nrow = ccol + dcol, crow + drow
                    nc = ncol * H + nrow
                    if 0 <= ncol < W and 0 <= nrow < H and nc in cellset and nc not in label:
                        label[nc] = fid
                        dq.append(nc)
        fields.append(comp)

    cell_to_field = {c: fid for fid, comp in enumerate(fields) for c in comp}

    def field_center(comp):
        return (sum(c // H for c in comp) / len(comp),
                sum(c % H for c in comp) / len(comp))

    # Assign each field to its owner node and set the field's tier.
    #
    # distance/balance modes — RICHEST-WINS with merge margin:
    #   Each field takes the richest tier among nodes tied for closest.  Nodes
    #   within MERGE_MARGIN of the closest are co-owners; richest wins so a
    #   contested-centre gold blob keeps its tier instead of being lost to an
    #   arbitrary neighbour.
    #
    # even mode — MIRROR-PAIR-FIRST tier assignment:
    #   The correct unit of assignment for even mode is the mirror-field-pair,
    #   not the individual field or seed orbit.  The sym pass groups mirror
    #   fields into pairs; we sort those pairs by nearest-spawn distance and
    #   distribute TIER_ORDER[0:6] across the pairs with quota-fill — exactly
    #   as assign_node_tiers_even does for orbits.  This guarantees:
    #     * 100% symmetry: pairs are the assignment unit, no sym-pass conflicts.
    #     * Maximum variety: min(6, n_pairs) distinct types — Ore always appears
    #       (nearest pair gets lowest tier), Gems only if >=6 pairs exist.
    #     * Equal cell-count distribution: quota-fill based on pair cell counts.
    MERGE_MARGIN = 4.0
    _RANK = {t: i for i, t in enumerate(_rr.TIER_ORDER)}

    field_owner = {}
    field_tier = {}

    # Build mirror-field groups (shared by both modes; used directly for even).
    centers = [field_center(comp) for comp in fields]
    transforms, _center = detect_symmetries(spawns, seeds)
    # Stash the map center and transforms for the GUI's mirror-paint math.
    _map_center = tuple(_center)
    _transforms = transforms
    _sym_parent = list(range(len(fields)))

    def _sym_find(a):
        while _sym_parent[a] != a:
            _sym_parent[a] = _sym_parent[_sym_parent[a]]
            a = _sym_parent[a]
        return a

    def _sym_union(a, b):
        ra, rb = _sym_find(a), _sym_find(b)
        if ra != rb:
            _sym_parent[ra] = rb

    FTOL = 5.0
    if transforms and len(fields) > 1:
        for _name, T in transforms:
            for fid, (cx, cy) in enumerate(centers):
                tx, ty = T(cx, cy)
                best_d = None
                bj = None
                for fj, (ox, oy) in enumerate(centers):
                    d = math.hypot(tx - ox, ty - oy)
                    if best_d is None or d < best_d:
                        best_d, bj = d, fj
                if bj is not None and bj != fid and best_d <= FTOL:
                    _sym_union(fid, bj)

    sym_groups: dict[int, list[int]] = {}
    for fid in range(len(fields)):
        sym_groups.setdefault(_sym_find(fid), []).append(fid)

    if is_even_mode and seeds:
        # ── EVEN MODE: mirror-pair-first tier assignment ──────────────────
        # Sort mirror-field groups by the minimum nearest-spawn distance of
        # any cell in the group (closest to base = lowest tier = Ore).
        _ev_group_list = list(sym_groups.values())
        _ev_group_dist = []
        for grp in _ev_group_list:
            all_cells = [c for fid in grp for c in fields[fid]]
            dist = min(
                min(math.hypot(c // H - sx, c % H - sy) for sx, sy in spawns)
                for c in all_cells
            ) if spawns else 0.0
            _ev_group_dist.append(dist)
        _ev_order = sorted(range(len(_ev_group_list)),
                           key=lambda k: _ev_group_dist[k])

        # Quota-fill: distribute TIER_ORDER[0:6] across groups.
        ladder = _rr.TIER_ORDER
        n_tiers = len(ladder)
        n_ev_groups = len(_ev_group_list)
        if n_ev_groups <= n_tiers:
            _ev_rank_to_tier_idx = list(range(n_ev_groups))
        else:
            base = n_ev_groups // n_tiers
            extra = n_ev_groups % n_tiers
            _ev_rank_to_tier_idx = []
            for t in range(n_tiers):
                count = base + (1 if t < extra else 0)
                _ev_rank_to_tier_idx.extend([t] * count)

        for rank, k in enumerate(_ev_order):
            tier = ladder[_ev_rank_to_tier_idx[rank]]
            for fid in _ev_group_list[k]:
                field_tier[fid] = tier
                d2 = [min(((c // H) - s["x"]) ** 2 + ((c % H) - s["y"]) ** 2
                          for c in fields[fid]) for s in seeds]
                field_owner[fid] = min(range(len(seeds)), key=lambda i: d2[i])
        
        # FIX: Update node_res to match the field tiers they end up in
        # This ensures consistency between node tiers and field tiers in even mode
        for i, s in enumerate(seeds):
            ccol, crow = s["x"], s["y"]
            # Find which field this node belongs to (closest field, since node cell is not in field comp)
            node_field = None
            best_dist = float('inf')
            for fid, comp in enumerate(fields):
                if not comp:
                    continue
                # Find closest cell in this field to the node
                for c in comp:
                    fcol = c // H
                    frow = c % H
                    dist = ((ccol - fcol) ** 2 + (crow - frow) ** 2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
                        node_field = fid
            if node_field is not None:
                node_res[i] = field_tier[node_field]

    else:
        # ── DISTANCE/BALANCE MODE ─────────────────────────────────────────
        for fid, comp in enumerate(fields):
            if not seeds:
                field_tier[fid] = "Ore"
                continue
            d2 = [min(((c // H) - s["x"]) ** 2 + ((c % H) - s["y"]) ** 2
                      for c in comp) for s in seeds]
            dmin = min(d2) ** 0.5
            cands = [i for i in range(len(seeds)) if d2[i] ** 0.5 <= dmin + MERGE_MARGIN]
            best = max(cands, key=lambda i: _RANK[node_res[i]])
            field_owner[fid] = best
            field_tier[fid] = node_res[best]

        # --- symmetry guarantee for distance/balance: nearest-spawn canon ---
        for grp in sym_groups.values():
            if len(grp) < 2:
                continue
            canon = min(grp, key=lambda fid: nearest_spawn_dist(
                centers[fid][0], centers[fid][1], spawns))
            t = field_tier[canon]
            for fid in grp:
                field_tier[fid] = t
        
        # FIX: Update node_res to match field tiers after symmetry pass
        # This ensures consistency when symmetry overrides field tiers
        for i, s in enumerate(seeds):
            ccol, crow = s["x"], s["y"]
            # Find which field this node belongs to (closest field, since node cell is not in field comp)
            node_field = None
            best_dist = float('inf')
            for fid, comp in enumerate(fields):
                if not comp:
                    continue
                # Find closest cell in this field to the node
                for c in comp:
                    fcol = c // H
                    frow = c % H
                    dist = ((ccol - fcol) ** 2 + (crow - frow) ** 2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
                        node_field = fid
            if node_field is not None:
                node_res[i] = field_tier[node_field]

    # Build symmetry group lookup: fid -> list of all fid keys in the same group.
    # Used by the GUI's mirror-paint feature.  When no transforms were found every
    # field is its own group (list of one).
    if transforms and len(fields) > 1:
        # sym_groups / _sym_find / centers are in scope from the block above.
        root_to_keys = {}
        for fid, (cx, cy) in enumerate(centers):
            key = "%d,%d" % (round(cx), round(cy))
            root_to_keys.setdefault(_sym_find(fid), []).append(key)
        fid_mirror_keys = {
            fid: root_to_keys[_sym_find(fid)]
            for fid, (cx, cy) in enumerate(centers)
        }
    else:
        fid_mirror_keys = {
            fid: ["%d,%d" % (round(cx), round(cy))]
            for fid, (cx, cy) in enumerate(centers)
        }

    # apply paint overrides (hand-paint mode): field-centre key -> tier string
    # Keys are (round(center_col), round(center_row)) tuples serialised as "col,row".
    if paint_overrides:
        centers = [field_center(comp) for comp in fields]
        available_keys = ["%d,%d" % (round(cx), round(cy)) for (cx, cy) in centers]
        matched = []
        for fid, (cx, cy) in enumerate(centers):
            key = "%d,%d" % (round(cx), round(cy))
            if key in paint_overrides and paint_overrides[key] in CAMEO_RES_INDEX:
                field_tier[fid] = paint_overrides[key]
                matched.append(key)

    # apply cell overrides (individual cell painting): "col,row" -> tier string
    # These override the field tier for specific cells only
    cell_override_map = {}
    if cell_overrides:
        for cell_key, tier in cell_overrides.items():
            if tier in CAMEO_RES_INDEX:
                col, row = map(int, cell_key.split(','))
                cell_idx = col * H + row
                density_override = density_overrides.get(cell_key) if density_overrides else None
                cell_override_map[cell_idx] = (tier, density_override)


    # Build field metadata for callers that need it (paint mode, diagnostics).
    # Stored as a list of dicts: {center, cells, tier}.  Returned alongside counts
    # via the global _last_assign_fields (reset each call).
    RES_BY_IDX = {v: k for k, v in CAMEO_RES_INDEX.items()}
    _last_assign_fields = [
        {
            "center": field_center(comp),
            "cells": comp,
            "cell_count": len(comp),           # explicit size for GUI size-compat checks
            "tier": field_tier[fid],
            "map_height": H,                   # map height for cell index calculations
            # All field-center keys in the same symmetry group (including self).
            # The GUI mirror-paint feature uses this to paint all mirrors at once.
            "mirror_keys": fid_mirror_keys.get(fid, [
                "%d,%d" % (round(field_center(comp)[0]), round(field_center(comp)[1]))
            ]),
            "map_center": _map_center,         # map symmetry center for mirror transforms
            "transforms": _transforms,         # [(name, lambda), ...] symmetry transforms
            "nodes": [],                       # populated below
        }
        for fid, comp in enumerate(fields)
    ]

    # Assign nodes to their closest field (needed for GUI mirror-paint symmetry)
    for s in seeds:
        ccol, crow = s["x"], s["y"]
        best_fid = None
        best_dist = float('inf')
        for fid, comp in enumerate(fields):
            if not comp:
                continue
            for c in comp:
                fcol = c // H
                frow = c % H
                dist = ((ccol - fcol) ** 2 + (crow - frow) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_fid = fid
        if best_fid is not None:
            _last_assign_fields[best_fid]["nodes"].append((ccol, crow))
    
    # Store node information for tooltips
    # FIX: Use the actual resource type that will be applied (field tier), not the algorithm result
    # This ensures tooltips match the visual representation
    _last_assign_nodes = []
    for i, s in enumerate(seeds):
        ccol, crow = s["x"], s["y"]
        # Find which field this node belongs to (closest field, since node cell is not in field comp)
        node_field = None
        best_dist = float('inf')
        for fid, comp in enumerate(fields):
            if not comp:
                continue
            # Find closest cell in this field to the node
            for c in comp:
                fcol = c // H
                frow = c % H
                dist = ((ccol - fcol) ** 2 + (crow - frow) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    node_field = fid
        # Use the field tier if the node is in a field, otherwise fall back to node_res
        if node_field is not None:
            actual_res = field_tier[node_field]
        else:
            actual_res = node_res[i] if i < len(node_res) else "Unknown"
        _last_assign_nodes.append({
            "x": s["x"],
            "y": s["y"],
            "resource": actual_res
        })

    # Attach per-cell density to the field cache for tooltip level reporting.
    for f in _last_assign_fields:
        f["density"] = {c: mb.res_density(c) for c in f.get("cells", [])}

    # paint every field cell to its (symmetrized) tier
    counts = {}
    for fid, comp in enumerate(fields):
        res = field_tier[fid]
        idx = CAMEO_RES_INDEX[res]
        cap = CAMEO_RES_MAXDENSITY[idx]
        key = "%d,%d" % (round(centers[fid][0]), round(centers[fid][1]))
        field_density = field_density_overrides.get(key) if field_density_overrides else None
        for c in comp:
            # Check if this cell has a cell override
            if c in cell_override_map:
                override_res, override_density = cell_override_map[c]
                override_idx = CAMEO_RES_INDEX[override_res]
                override_cap = CAMEO_RES_MAXDENSITY[override_idx]
                dens = _apply_density_for_override(mb, c, override_res, override_density, override_cap)
                mb.set_res(c, override_idx, dens)
                counts[override_res] = counts.get(override_res, 0) + 1
            else:
                dens = _apply_density_for_override(mb, c, res, field_density, cap)
                mb.set_res(c, idx, dens)
                counts[res] = counts.get(res, 0) + 1

    # Paint node cells to match their surrounding field type
    # (node cells may be Empty in source maps and not included in field sets)
    for i, s in enumerate(seeds):
        ccol, crow = s["x"], s["y"]
        cell = ccol * H + crow
        # Find the resource type of the field this node sits in
        best = None
        bres = None
        for dcol in range(-3, 4):
            for drow in range(-3, 4):
                ncol, nrow = ccol + dcol, crow + drow
                if 0 <= ncol < W and 0 <= nrow < H:
                    ncell = ncol * H + nrow
                    idx = mb.raw[mb.res_off + ncell * 2]
                    if idx in RES_BY_IDX:
                        d = dcol * dcol + drow * drow
                        if best is None or d < best:
                            best, bres = d, RES_BY_IDX[idx]
        if bres is not None:
            res = bres
            idx = CAMEO_RES_INDEX[res]
            cap = CAMEO_RES_MAXDENSITY[idx]
            dens = mb.res_density(cell)
            mb.set_res(cell, idx, cap if (dens == 0 or dens > cap) else dens)
            counts[res] = counts.get(res, 0) + 1

    # node actors conform to the resource field they sit in (colour == field)
    RES_BY_IDX = {v: k for k, v in CAMEO_RES_INDEX.items()}
    ac = {}
    for i, s in enumerate(seeds):
        ccol, crow = s["x"], s["y"]
        best = None
        bres = None
        for dcol in range(-3, 4):
            for drow in range(-3, 4):
                ncol, nrow = ccol + dcol, crow + drow
                if 0 <= ncol < W and 0 <= nrow < H:
                    cell = ncol * H + nrow
                    idx = mb.raw[mb.res_off + cell * 2]
                    if idx in RES_BY_IDX:
                        d = dcol * dcol + drow * drow
                        if best is None or d < best:
                            best, bres = d, RES_BY_IDX[idx]
        res = bres if bres is not None else node_res[i]
        na = CAMEO_RES_ACTOR[res]
        if na != s["name"]:
            lines[s["type_line_i"]] = re.sub(
                r"(:\s*)" + re.escape(s["name"]) + r"\s*$",
                r"\g<1>" + na, lines[s["type_line_i"]])
        ac[na] = ac.get(na, 0) + 1
    if counts:
        rpt.add("fields -> node resource: "
                + ", ".join("%s:%d" % (k, v) for k, v in sorted(counts.items())))
    rpt.add("nodes -> " + ", ".join("%s:%d" % (k, v) for k, v in sorted(ac.items())))


class Report:
    def __init__(self):
        self.lines = []

    def add(self, m):
        self.lines.append(m)

    def dump(self, prefix="  "):
        return "\n".join(prefix + l for l in self.lines)


def convert_map(src, out_oramap, rpt, keep_palettes, keep_decorations,
                valid, dry_run=False, remap_resources=True, paint_overrides=None, cell_overrides=None, node_overrides=None, node_affects_field_tier=True,
                density_overrides=None, field_density_overrides=None, remove_actors=True):
    from converter_logging import get_logger

    # Honour the remove-actors toggle for this conversion regardless of the
    # module-level default (set by CLI/GUI/workers before entry).
    globals()["REMOVE_PROBLEMATIC_ACTORS"] = bool(remove_actors)

    logger = get_logger()
    logger.info(f"convert_map: Starting conversion for {src}")
    logger.debug(f"convert_map: Output path={out_oramap}, dry_run={dry_run}, remap_resources={remap_resources}, remove_actors={remove_actors}")

    # Defensive guard: reject anything that isn't a valid .oramap before we
    # spend work on it (matches the existing skip pattern).
    try:
        validate_oramap_file(src)
    except ValueError as e:
        rpt.add("!! invalid .oramap: %s -- skipped" % e)
        logger.error("convert_map: invalid .oramap (%s), skipping conversion" % e)
        return False

    tmp = tempfile.mkdtemp(prefix="oramap_")
    logger.debug(f"convert_map: Created temp directory {tmp}")
    
    try:
        with zipfile.ZipFile(src) as z:
            names = z.namelist()
            logger.debug(f"convert_map: Extracted {len(names)} files from oramap")
            z.extractall(tmp)
        myp = os.path.join(tmp, "map.yaml")
        mbp = os.path.join(tmp, "map.bin")
        if not os.path.exists(myp):
            rpt.add("!! no map.yaml -- skipped")
            logger.error("convert_map: No map.yaml found, skipping conversion")
            return False
        with open(myp, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().replace("\r\n", "\n").split("\n")
        logger.debug(f"convert_map: Read {len(lines)} lines from map.yaml")

        src_mod = next((l.split(":", 1)[1].strip() for l in lines
                        if indent_of(l) == 0 and l.startswith("RequiresMod:")), "?")
        src_ts = next((l.split(":", 1)[1].strip() for l in lines
                       if indent_of(l) == 0 and l.startswith("Tileset:")), "?")
        
        # Detect BI version from title or categories
        bi_version = None
        for l in lines:
            if indent_of(l) == 0 and l.startswith("Title:"):
                title = l.split(":", 1)[1].strip()
                match = re.search(r"\[BI-([0-9.]+)\]", title)
                if match:
                    bi_version = match.group(1)
                    break
        if not bi_version:
            for l in lines:
                if indent_of(l) == 0 and l.startswith("Categories:"):
                    cats = l.split(":", 1)[1].strip()
                    match = re.search(r"\[BI-([0-9.]+)\]", cats)
                    if match:
                        bi_version = match.group(1)
                        break
        
        # Apply BI protocol if detected
        bi_protocol = None
        if bi_version:
            logger.debug(f"convert_map: Detected BI version {bi_version}")
            bi_protocol = get_bi_protocol(bi_version)
            if bi_protocol:
                rpt.add("detected BI version %s, applying BI protocol" % bi_version)
                logger.info(f"convert_map: Applying BI protocol for version {bi_version}")
            else:
                rpt.add("detected BI version %s, no protocol found, using default handling" % bi_version)
                logger.warning(f"convert_map: No protocol found for BI version {bi_version}, using default handling")
        
        rpt.add("source mod=%s  tileset=%s" % (src_mod, src_ts))
        logger.info(f"convert_map: Source mod={src_mod}, tileset={src_ts}")

        set_scalar(lines, "RequiresMod", "cameo")
        logger.debug("convert_map: Set RequiresMod to cameo")
        new_ts = TILESET_MAP.get(src_ts)
        if new_ts:
            set_scalar(lines, "Tileset", new_ts)
            logger.debug(f"convert_map: Mapped tileset {src_ts} -> {new_ts}")
        else:
            rpt.add("!! unknown tileset '%s' -- left unchanged (REVIEW)" % src_ts)
            logger.warning(f"convert_map: Unknown tileset {src_ts}, left unchanged")
            new_ts = src_ts

        for i, ln in enumerate(lines):
            if indent_of(ln) == 0 and ln.startswith("Title:"):
                t = re.sub(r"\s*\[[^\]]*\]\s*$", "", ln.split(":", 1)[1].strip()).strip()
                lines[i] = "Title: %s" % t
                logger.debug(f"convert_map: Cleaned title: {t}")
                break
        if CONVERTER_TAG:
            for i, ln in enumerate(lines):
                if indent_of(ln) == 0 and ln.startswith("Author:"):
                    a = ln.split(":", 1)[1].strip()
                    if CONVERTER_TAG not in a:
                        lines[i] = "Author: %s, %s" % (a, CONVERTER_TAG)
                        logger.debug(f"convert_map: Added converter tag to author: {CONVERTER_TAG}")
                    break
        if not set_scalar(lines, "Categories", NEW_CATEGORY):
            for i, ln in enumerate(lines):
                if indent_of(ln) == 0 and ln.startswith("Author:"):
                    lines.insert(i + 1, "Categories: %s" % NEW_CATEGORY)
                    logger.debug(f"convert_map: Added category: {NEW_CATEGORY}")
                    break
        lines = remove_scalar(lines, "LockPreview")
        logger.debug("convert_map: Removed LockPreview")

        palette_blocks = []
        # Determine which external reference keys to process
        ref_keys_to_process = EXTERNAL_REF_KEYS
        if bi_protocol and "external_refs" in bi_protocol:
            # Use BI protocol's external reference keys
            ref_keys_to_process = list(bi_protocol["external_refs"].keys())
            # Ensure FluentMessages is included if it's in the protocol
            if "FluentMessages" in bi_protocol["external_refs"] and "FluentMessages" not in ref_keys_to_process:
                ref_keys_to_process.append("FluentMessages")
        logger.debug(f"convert_map: Processing external refs: {ref_keys_to_process}")
        
        for key in ref_keys_to_process:
            ref_files = []
            for ln in lines:
                if indent_of(ln) == 0 and ln.startswith(key + ":"):
                    v = ln.split(":", 1)[1].strip()
                    if v:
                        ref_files = [p.strip() for p in v.split(",") if p.strip()]
                    break
            logger.debug(f"convert_map: Processing {key} with files: {ref_files}")
            if key == "Rules":
                for rf in ref_files:
                    rp = os.path.join(tmp, rf)
                    if os.path.exists(rp):
                        with open(rp, "r", encoding="utf-8", errors="replace") as f:
                            palette_blocks += extract_palette_blocks(f.read())
                            logger.debug(f"convert_map: Extracted palette blocks from {rf}")
            lines = remove_toplevel_block(lines, key)
            logger.debug(f"convert_map: Removed {key} block from map.yaml")

        bundled_pals = set(fn.lower() for fn in os.listdir(tmp)
                           if fn.lower().endswith(".pal"))

        def pal_action(pf):
            if pf in PALETTE_OVERRIDES:
                return PALETTE_OVERRIDES[pf]
            return "keep" if keep_palettes else PALETTE_DEFAULT

        keep_pb = [pb for pb in palette_blocks if pb["filename"] in bundled_pals
                   and pal_action(pb["filename"]) == "keep"]
        keep_pal_files = set(pb["filename"] for pb in keep_pb)
        logger.debug(f"convert_map: Keeping {len(keep_pb)} custom palettes")

        # When the user has painted explicit density overrides, the Cameo mod's default
        # RecalculateResourceDensity:true would throw them away and recompute density from
        # neighbor count. Emit a map-level rule override so the painted density bytes win.
        has_density_overrides = bool(density_overrides or field_density_overrides)
        if has_density_overrides:
            logger.debug(f"convert_map: Density overrides present ({len(density_overrides or {})} cell, {len(field_density_overrides or {})} field) - will disable density recalculation")

        if keep_pb or has_density_overrides:
            block = ["Rules:"]
            if has_density_overrides:
                block.extend([
                    "\tWorld:",
                    "\t\tResourceLayer:",
                    "\t\t\tRecalculateResourceDensity: false",
                    "\tEditorWorld:",
                    "\t\tEditorResourceLayer:",
                    "\t\t\tRecalculateResourceDensity: false",
                ])
            if keep_pb:
                block.append("\t^Palettes:")
                for pb in keep_pb:
                    for bln in pb["block"]:
                        if bln.strip() == "":
                            block.append("")
                            continue
                        rel = indent_of(bln) - pb["base"]
                        body = bln.lstrip("\t")
                        if re.match(r"^Tileset:\s*\S+", body):
                            body = "Tileset: %s" % new_ts
                        block.append(("\t\t" + "\t" * rel) + body)
            while lines and lines[-1].strip() == "":
                lines.pop()
            lines.append("")
            lines += block
            if keep_pb:
                rpt.add("kept %d custom palette(s)" % len(keep_pb))
                logger.info(f"convert_map: Kept {len(keep_pb)} custom palette(s)")
            if has_density_overrides:
                rpt.add("disabled ResourceLayer density recalculation so painted densities are preserved")
                logger.info(f"convert_map: Disabled ResourceLayer density recalculation")
        elif palette_blocks:
            rpt.add("dropped %d custom palette ref(s) -- Cameo stock palettes"
                    % len(palette_blocks))
            logger.info(f"convert_map: Dropped {len(palette_blocks)} custom palette ref(s)")

        autodrop = (not keep_decorations) and len(valid) > 0
        logger.debug(f"convert_map: Autodrop unknown actors={autodrop}, valid actors={len(valid)}")
        if not valid:
            rpt.add("!! cameo_actors.txt not found -- unknown actors NOT dropped (may crash)")
            logger.warning("convert_map: cameo_actors.txt not found, unknown actors NOT dropped")
        lines = apply_actor_matrix(lines, valid, autodrop, rpt)
        logger.debug("convert_map: Applied actor matrix")

        actors = parse_actors(lines)
        spawns = [(a["x"], a["y"]) for a in actors
                  if a["name"] == "mpspawn" and a["x"] is not None]
        rpt.add("%d spawn point(s)" % len(spawns))
        logger.info(f"convert_map: Found {len(spawns)} spawn point(s)")
        mb = None
        if os.path.exists(mbp):
            with open(mbp, "rb") as f:
                mb = MapBin(f.read())
            logger.debug(f"convert_map: Loaded map.bin, size={mb.width}x{mb.height}")
        remap_templates(mb, new_ts, rpt, bi_protocol)
        logger.debug("convert_map: Remapped templates")
        # Always remap source resource indices to Cameo equivalents (1-1 conversion)
        remap_source_resources(mb, src_mod, rpt)
        logger.debug("convert_map: Remapped source resources")
        
        # Water crossing detection using proper terrain resolution
        # Load tileset terrain table for RA_TEMPERAT from bundled data
        script_dir = os.path.dirname(os.path.abspath(__file__))
        tileset_yaml = os.path.join(script_dir, "ra_temperat.yaml")
        logger.debug(f"convert_map: Looking for tileset YAML at {tileset_yaml}")
        if os.path.exists(tileset_yaml):
            terr = load_tileset_terrain(tileset_yaml)
            detect_and_convert_crossings(mb, terr, rpt, maxwidth=2)
            logger.debug("convert_map: Water crossing detection complete")
        else:
            rpt.add("!! tileset YAML not found at %s -- water crossing detection skipped" % tileset_yaml)
            logger.warning(f"convert_map: Tileset YAML not found at {tileset_yaml}, water crossing detection skipped")
        
        fill_stray_water(mb, new_ts, rpt)
        logger.debug("convert_map: Filled stray water")
        fill_grass_in_water(mb, new_ts, rpt)
        logger.debug("convert_map: Filled grass in water")
        if spawns and remap_resources:
            logger.debug("convert_map: Applying Cameo resource algorithm")
            assign_resources(lines, actors, mb, spawns, rpt, paint_overrides=paint_overrides, cell_overrides=cell_overrides, node_overrides=node_overrides, node_affects_field_tier=node_affects_field_tier,
                             density_overrides=density_overrides, field_density_overrides=field_density_overrides)
            rpt.add("remap resources enabled - applied Cameo resource algorithm (distance-based tiering)")
            logger.info("convert_map: Applied Cameo resource algorithm (distance-based tiering)")
        elif spawns:
            # Non-remap mode: still run assign_resources so the paint-mode field
            # and node metadata are populated. manual_only=True keeps the existing
            # 1-1 converted resources and only applies any paint overrides.
            logger.debug("convert_map: Applying manual paint mode metadata pass (remap_resources disabled)")
            assign_resources(lines, actors, mb, spawns, rpt, paint_overrides=paint_overrides, cell_overrides=cell_overrides, node_overrides=node_overrides, node_affects_field_tier=node_affects_field_tier, manual_only=True,
                             density_overrides=density_overrides, field_density_overrides=field_density_overrides)
            rpt.add("remap resources disabled - resources pass through 1-1 conversion; paint metadata built")
            logger.info("convert_map: Remap resources disabled - resources pass through 1-1 conversion; paint metadata built")
        else:
            rpt.add("!! no spawns -- resources left unchanged (REVIEW)")
            logger.warning("convert_map: No spawns found, resources left unchanged")

        # Regenerate the in-game preview map.png from the CONVERTED terrain+resources so
        # OpenRA's map-list minimap reflects the conversion (not the stale CA map.png).
        # The keep-list already keeps "map.png"; we overwrite tmp/map.png here. If we
        # cannot render (e.g. Pillow missing), DROP the stale source map.png so OpenRA
        # rebuilds the preview on open+save (handoff fallback option b).
        map_png_path = os.path.join(tmp, "map.png")
        png_ok = False
        logger.debug("convert_map: Regenerating in-game preview map.png")
        if mb is not None:
            try:
                import minimap_render as _mmr
                from PIL import Image
                import io

                # Try to use source map.png terrain layer for high-fidelity base
                source_terrain = None
                try:
                    with zipfile.ZipFile(src) as z:
                        if "map.png" in z.namelist():
                            map_png_data = z.read("map.png")
                            source_terrain = Image.open(io.BytesIO(map_png_data))
                            logger.debug("convert_map: Loaded source map.png terrain layer")
                except Exception as e:
                    logger.debug(f"convert_map: Could not load source map.png: {e}")

                # Generate map.png using source terrain if available, otherwise generate from scratch
                if source_terrain is not None:
                    # Use source terrain as base, overlay converted resources
                    bounds = _mmr._resolved_bounds(mb, "\n".join(lines))
                    expected_size = (bounds[2], bounds[3])
                    if source_terrain.size == expected_size:
                        # Overlay resources on source terrain
                        _mmr.overlay_resources(source_terrain, mb, bounds, scale=1)
                        # Overlay actors
                        actors = _mmr.parse_actor_locations("\n".join(lines))
                        # Build node_type_map from node overrides and assigned nodes
                        node_type_map = {}
                        if node_overrides:
                            for node_key, tier in node_overrides.items():
                                col, row = map(int, node_key.split(','))
                                node_type_map[(col, row)] = tier
                        # Include assigned node tiers from _last_assign_nodes
                        for node in _last_assign_nodes:
                            if (node["x"], node["y"]) not in node_type_map:
                                node_type_map[(node["x"], node["y"])] = node["resource"]
                        _mmr.overlay_actors(source_terrain, actors, bounds, scale=1, draw_spawns=True, draw_nodes=True,
                                           node_type_map=node_type_map)
                        source_terrain.save(map_png_path)
                        png_ok = True
                        logger.debug("convert_map: Generated map.png using source terrain layer")
                    else:
                        logger.debug(f"convert_map: Source map.png size mismatch, regenerating from scratch")
                        source_terrain = None

                if not png_ok:
                    # Fallback: generate from scratch
                    # Build node_type_map for node override support
                    node_type_map = {}
                    if node_overrides:
                        for node_key, tier in node_overrides.items():
                            col, row = map(int, node_key.split(','))
                            node_type_map[(col, row)] = tier
                    # Include assigned node tiers from _last_assign_nodes
                    for node in _last_assign_nodes:
                        if (node["x"], node["y"]) not in node_type_map:
                            node_type_map[(node["x"], node["y"])] = node["resource"]
                    
                    png_ok = _mmr.save_minimap_png(
                        mb, "\n".join(lines), map_png_path,
                        script_dir=script_dir, scale=1, draw_actors=True,
                        draw_nodes=True,
                        node_type_map=node_type_map)
                    logger.debug("convert_map: map.png regeneration from scratch successful")
            except Exception as e:
                logger.error(f"convert_map: Failed to regenerate map.png: {e}")
                print(f"[ERROR] Failed to regenerate map.png: {e}")
                import traceback
                traceback.print_exc()
                png_ok = False
        if png_ok:
            rpt.add("regenerated in-game preview map.png (converted terrain+resources)")
            logger.info("convert_map: Regenerated in-game preview map.png")
        else:
            try:
                os.remove(map_png_path)
                rpt.add("map.png not regenerated -- dropped stale preview so OpenRA rebuilds it")
                logger.info("convert_map: Dropped stale map.png so OpenRA rebuilds it")
            except OSError:
                logger.debug("convert_map: No stale map.png to remove")
                pass

        kept = []
        logger.debug("convert_map: Filtering files to keep")
        for root, _, files in os.walk(tmp):
            for fn in files:
                low = fn.lower()
                # Keep essential files only
                if fn in KEEP_NAMES:
                    kept.append(os.path.relpath(os.path.join(root, fn), tmp))
                elif low.endswith(".pal") and low in keep_pal_files:
                    kept.append(os.path.relpath(os.path.join(root, fn), tmp))
                elif low.endswith(".shp"):
                    kept.append(os.path.relpath(os.path.join(root, fn), tmp))
                elif low.endswith(".aud"):
                    kept.append(os.path.relpath(os.path.join(root, fn), tmp))
                # NOTE: CA-specific YAMLs are now dropped (rules, sequences, etc.)
                # Only map.yaml is kept via KEEP_NAMES
        logger.debug(f"convert_map: Keeping {len(kept)} files")
        kb = set(os.path.basename(k) for k in kept)
        df = [n for n in names if not n.endswith("/") and os.path.basename(n) not in kb]
        if df:
            rpt.add("dropped %d asset file(s)" % len(df))
            logger.info(f"convert_map: Dropped {len(df)} asset file(s)")

        if dry_run:
            rpt.add("(dry-run: nothing written)")
            logger.info("convert_map: Dry run - nothing written")
            return True
        
        logger.debug("convert_map: Writing converted files")
        with open(myp, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines).rstrip("\n") + "\n")
            logger.debug("convert_map: Wrote map.yaml")
        if mb:
            with open(mbp, "wb") as f:
                f.write(mb.bytes())
                logger.debug("convert_map: Wrote map.bin")
        od = os.path.dirname(out_oramap)
        if od:
            os.makedirs(od, exist_ok=True)
            logger.debug(f"convert_map: Created output directory {od}")
        with zipfile.ZipFile(out_oramap, "w", zipfile.ZIP_DEFLATED) as z:
            for rel in kept:
                z.write(os.path.join(tmp, rel), rel)
            # Add missing critical assets for Cameo compatibility - DISABLED due to SHP bug
            # add_missing_cameo_assets(z, kb, tmp, rpt)
        logger.info(f"convert_map: Wrote converted oramap to {out_oramap}")
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        logger.debug(f"convert_map: Cleaned up temp directory {tmp}")
        logger.info(f"convert_map: Conversion complete for {src}")


def add_missing_cameo_assets(zf, kept_basenames, tmp_dir, rpt):
    """Add missing SHP assets that Cameo requires but CA maps don't have."""
    
    # Critical assets that Cameo mod requires
    CRITICAL_ASSETS = [
        'harvicon.shp',    # Harvester icon
        'procdead.shp',    # Processor dead sprite
        'procicon.shp',    # Processor icon
    ]
    
    # Find a template SHP file in the source
    template_shp = None
    template_name = None
    for root, _, files in os.walk(tmp_dir):
        for fn in files:
            if fn.endswith('.shp') and fn not in kept_basenames:
                try:
                    with open(os.path.join(root, fn), 'rb') as f:
                        data = f.read()
                        if len(data) > 100:  # Valid SHP has reasonable size
                            template_shp = data
                            template_name = fn
                            break
                except (OSError, IOError) as e:
                    print(f"[WARNING] Failed to read {fn}: {e}")
                    continue
        if template_shp:
            break
    
    # Prefer gpssactiveicon.shp if available
    gpss_path = os.path.join(tmp_dir, 'gpssactiveicon.shp')
    if os.path.exists(gpss_path):
        try:
            with open(gpss_path, 'rb') as f:
                template_shp = f.read()
                template_name = 'gpssactiveicon.shp'
        except (OSError, IOError) as e:
            print(f"[WARNING] Failed to read gpssactiveicon.shp: {e}")
            pass
    
    added = 0
    for asset in CRITICAL_ASSETS:
        if asset not in kept_basenames:
            if template_shp:
                zf.writestr(asset, template_shp)
                added += 1
            else:
                # Create minimal valid SHP as fallback
                zf.writestr(asset, create_minimal_shp())
                added += 1
    
    if added > 0:
        rpt.add("added %d missing asset(s) for Cameo compatibility" % added)


def create_minimal_shp():
    """Create a minimal valid 1x1 SHP file."""
    import struct
    # SHP header: 1 image, 0 offset, 0,0 position, 1x1 size
    header = struct.pack('<HHHHHH', 1, 0, 0, 0, 1, 1)
    offset_and_format = struct.pack('<IH', 14, 0)
    pixel_data = bytes([0])  # Transparent pixel
    return header + offset_and_format + pixel_data


def dump_actors(rules_dir):
    out = {}
    for fn in os.listdir(rules_dir):
        if not fn.endswith(".yaml"):
            continue
        for ln in open(os.path.join(rules_dir, fn), encoding="utf-8",
                       errors="replace").read().replace("\r\n", "\n").split("\n"):
            m = re.match(r"^([A-Za-z0-9][\w.\-]*):\s*$", ln)
            if m and not ln.startswith("\t"):
                k = m.group(1).lower()
                if k not in ("world", "player"):
                    out[k] = True
    print("# Valid Cameo actor names (generated from %s)" % rules_dir)
    for a in sorted(out):
        print(a)


# ---------------------------------------------------------------------------
# In-process preview API (used by the GUI for fast, LOSSLESS previews).
#
# Rendering uses the SAME minimap_render path as the in-game map.png, and resource
# tiering uses the SAME assign_resources() pipeline as convert_map(), so a preview is
# pixel-identical to a full conversion at the same settings (verified). Terrain + the
# base resource-cell set are knob-INDEPENDENT and cached per map; only resource TIERING
# is recomputed when richness/bias/home-radius/distribution change.
#
# NOTE: build_preview_base() MUST mirror convert_map()'s map.bin transform (the steps
# before assign_resources). The preview==convert regression check guards against drift.
# ---------------------------------------------------------------------------

# Preview cache (path, mtime, remap_resources -> cache entry)
_PREVIEW_CACHE = {}

def clear_preview_cache():
    """Clear the preview cache (call when source file changes)."""
    global _PREVIEW_CACHE
    _PREVIEW_CACHE = {}


def _yaml_scalar(lines, key, default="?"):
    for l in lines:
        if indent_of(l) == 0 and l.startswith(key + ":"):
            return l.split(":", 1)[1].strip()
    return default


def build_preview_base(src, remap_resources=True):
    """Extract + transform a source map's TERRAIN and base resource cells once
    (knob-independent), returning a cache entry. Mirrors convert_map()'s map.bin
    transform up to (but not including) assign_resources(). Cached by (path, mtime)."""
    mtime = os.path.getmtime(src)
    cache_key = (src, mtime)
    ent = _PREVIEW_CACHE.get(cache_key)
    if ent is not None:
        return ent

    if BI_PROTOCOL is None:
        load_bi_protocol(os.path.dirname(os.path.abspath(__file__)))

    with zipfile.ZipFile(src) as z:
        yaml_bytes = z.read("map.yaml")
        bin_bytes = z.read("map.bin")
    lines = yaml_bytes.decode("utf-8", "replace").replace("\r\n", "\n").split("\n")

    src_mod = _yaml_scalar(lines, "RequiresMod")
    src_ts = _yaml_scalar(lines, "Tileset")
    new_ts = TILESET_MAP.get(src_ts, src_ts)

    bi_version = None
    for key in ("Title", "Categories"):
        val = _yaml_scalar(lines, key, "")
        m = re.search(r"\[BI-([0-9.]+)\]", val or "")
        if m:
            bi_version = m.group(1)
            break
    bi_protocol = get_bi_protocol(bi_version) if bi_version else None

    actors = parse_actors(lines)
    spawns = [(a["x"], a["y"]) for a in actors
              if a["name"] == "mpspawn" and a["x"] is not None]

    rpt = Report()
    mb = MapBin(bin_bytes)
    remap_templates(mb, new_ts, rpt, bi_protocol)
    # Always remap source resource indices to Cameo equivalents (1-1 conversion)
    remap_source_resources(mb, src_mod, rpt)
    # Water-crossing detection: mirror convert_map() exactly (skipped when the tileset
    # YAML isn't found, so conversion output is unchanged).
    script_dir = os.path.dirname(os.path.abspath(__file__))
    tileset_yaml = os.path.join(script_dir, "ra_temperat.yaml")
    if os.path.exists(tileset_yaml):
        try:
            terr = load_tileset_terrain(tileset_yaml)
            detect_and_convert_crossings(mb, terr, rpt, maxwidth=2)
        except Exception:
            pass
    fill_stray_water(mb, new_ts, rpt)
    fill_grass_in_water(mb, new_ts, rpt)

    ent = {
        "mtime": mtime,
        "base_bytes": mb.bytes(),
        "lines": lines,
        "yaml_txt": "\n".join(lines),
        "actors": actors,
        "spawns": spawns,
        "bounds": None,     # filled lazily (knob-independent)
        "terrain": {},      # scale -> PIL terrain layer (knob-independent cache)
    }
    _PREVIEW_CACHE[cache_key] = ent
    return ent


def count_resource_tiers(mb):
    """Count resource cells per tier name from a (converted) map.bin."""
    counts = {t: 0 for t in _rr.TIER_ORDER}
    idx_tier = {v: k for k, v in CAMEO_RES_INDEX.items()}
    roff, raw = mb.res_off, mb.raw
    for i in range(mb.cells):
        name = idx_tier.get(raw[roff + i * 2])
        if name:
            counts[name] += 1
    return counts


def render_preview(src, settings, scale=4, draw_nodes=True):
    """Fast, LOSSLESS in-process preview. Returns (PIL.Image, counts_dict).

    Reuses the cached knob-independent terrain layer + base resource cells; re-runs
    ONLY resource tiering (assign_resources) for the current knobs, then overlays via
    the shared minimap_render path. Output is identical to convert_map() at the same
    settings (same pipeline + renderer).

    NOTE: mutates module knob globals (RESOURCE_RICHNESS, resource_reclassification.*),
    so callers must serialize concurrent calls. The GUI does (it terminate()+wait()s the
    previous preview worker before starting the next), as does the CLI."""
    import minimap_render as _mmr
    from converter_logging import get_logger
    
    logger = get_logger()
    logger.debug(f"render_preview: Starting preview for {src}")
    
    remap_resources = settings.get("remap_resources", True)
    remove_actors = settings.get("remove_actors", True)
    globals()["REMOVE_PROBLEMATIC_ACTORS"] = bool(remove_actors)
    logger.debug(f"render_preview: remap_resources={remap_resources}, remove_actors={remove_actors}")

    paint_overrides = settings.get("paint_overrides") or {}
    cell_overrides = settings.get("cell_overrides") or {}
    node_overrides = settings.get("node_overrides") or {}
    density_overrides = settings.get("density_overrides") or {}
    field_density_overrides = settings.get("field_density_overrides") or {}
    
    ent = build_preview_base(src, remap_resources)
    logger.debug(f"render_preview: Built preview base, spawns={len(ent['spawns']) if ent['spawns'] else 0}")
    
    mb = MapBin(ent["base_bytes"])               # cheap deep copy per render
    logger.debug(f"render_preview: Created MapBin, size={mb.width}x{mb.height}")

    global RESOURCE_RICHNESS
    if settings.get("richness") is not None:
        RESOURCE_RICHNESS = float(settings["richness"])
        logger.debug(f"render_preview: Set RESOURCE_RICHNESS={RESOURCE_RICHNESS}")
    _rr.DISTRIBUTION_MODE = settings.get("distribution", _rr.DISTRIBUTION_MODE)
    logger.debug(f"render_preview: Set DISTRIBUTION_MODE={_rr.DISTRIBUTION_MODE}")
    if settings.get("balance_bias") is not None:
        _rr.BALANCE_BIAS = max(0.0, float(settings["balance_bias"]))
        logger.debug(f"render_preview: Set BALANCE_BIAS={_rr.BALANCE_BIAS}")
    if settings.get("balance_home_radius") is not None:
        _rr.BALANCE_HOME_RADIUS = max(1.0, float(settings["balance_home_radius"]))
        logger.debug(f"render_preview: Set BALANCE_HOME_RADIUS={_rr.BALANCE_HOME_RADIUS}")

    if ent["spawns"] and remap_resources:
        logger.debug("render_preview: Applying resource assignment")
        if paint_overrides:
            logger.debug(f"render_preview: paint_overrides={paint_overrides}")
        if cell_overrides:
            logger.debug(f"render_preview: cell_overrides={cell_overrides}")
        if node_overrides:
            logger.debug(f"render_preview: node_overrides={node_overrides}")
        assign_resources(list(ent["lines"]), ent["actors"], mb, ent["spawns"], Report(),
                         paint_overrides=paint_overrides, cell_overrides=cell_overrides, node_overrides=node_overrides, node_affects_field_tier=settings.get('node_affects_field_tier', True),
                         density_overrides=density_overrides, field_density_overrides=field_density_overrides)
        logger.debug("render_preview: Resource assignment complete")
    elif ent["spawns"]:
        # Non-remap mode: still run assign_resources so the paint-mode field
        # and node metadata are populated. manual_only=True preserves the 1-1
        # converted resources and only applies any paint overrides.
        logger.debug("render_preview: Applying paint-mode metadata pass (remap_resources disabled)")
        assign_resources(list(ent["lines"]), ent["actors"], mb, ent["spawns"], Report(),
                         paint_overrides=paint_overrides, cell_overrides=cell_overrides, node_overrides=node_overrides, node_affects_field_tier=settings.get('node_affects_field_tier', True), manual_only=True,
                         density_overrides=density_overrides, field_density_overrides=field_density_overrides)
        logger.debug("render_preview: Paint-mode metadata pass complete")

    if ent["bounds"] is None:
        ent["bounds"] = _mmr._resolved_bounds(mb, ent["yaml_txt"])
        logger.debug(f"render_preview: Resolved bounds={ent['bounds']}")
    bounds = ent["bounds"]

    # Try to load the source map.png from the oramap as a HIGH-FIDELITY terrain base.
    # When remap_resources is False:  map.png has unconverted resources — use it as-is
    #   (the resource overlay below will paint over whatever is there anyway when remap is on,
    #    but with remap off we want the source colors so we use it directly).
    # When remap_resources is True:  map.png terrain detail is still useful as the base —
    #   we load it, then overlay_resources paints the remapped (converted) resources on top.
    #   This matches what convert_map() does and gives the same high-fidelity appearance
    #   for both generated and not-yet-generated maps.
    img = None
    img = None
    try:
        import zipfile as _zf
        from PIL import Image as _PILImage
        import io as _io

        logger.debug("render_preview: Attempting to load map.png from oramap as terrain base")
        with _zf.ZipFile(src) as z:
            if "map.png" in z.namelist():
                map_png_data = z.read("map.png")
                loaded_img = _PILImage.open(_io.BytesIO(map_png_data)).convert("RGB")
                # map.png is 1-px-per-cell; expected size matches bounds (w, h)
                expected_size = (bounds[2], bounds[3])
                if loaded_img.size == expected_size:
                    # Use map.png as terrain base in all cases — resource overlay
                    # is always applied below with INDEX_COLORS so colors match
                    # the primary preview regardless of remap_resources setting.
                    if scale > 1:
                        img = loaded_img.resize(
                            (loaded_img.size[0] * scale, loaded_img.size[1] * scale),
                            _PILImage.NEAREST)
                    else:
                        img = loaded_img.copy()
                    logger.debug("render_preview: Using map.png as terrain base")
                else:
                    logger.warning(
                        f"render_preview: map.png size {loaded_img.size} != bounds {expected_size}, "
                        f"falling back to terrain_layer()")
            else:
                logger.debug("render_preview: map.png not in oramap, falling back to terrain_layer()")
    except Exception as e:
        logger.warning(f"render_preview: Failed to load map.png: {e}, falling back to terrain_layer()")
        img = None

    # If map.png loading failed or dimensions don't match, generate terrain from scratch
    if img is None:
        logger.debug("render_preview: Generating terrain layer from scratch")
        tt = _mmr.get_terrain_tables(os.path.dirname(os.path.abspath(__file__)))
        layer = ent["terrain"].get(scale)
        if layer is None:
            layer = _mmr.terrain_layer(mb, tt[0], tt[1], bounds, scale)
            ent["terrain"][scale] = layer
            logger.debug(f"render_preview: Generated terrain layer at scale {scale}")
        img = layer.copy()
        logger.debug(f"render_preview: Copied terrain layer, img size={img.size}")

    # Apply resource overlay with canonical INDEX_COLORS — identical path for both
    # remap=on and remap=off so colors always match the primary preview palette.
    logger.debug("render_preview: Applying resource overlay")
    _mmr.overlay_resources(img, mb, bounds, scale)
    logger.debug("render_preview: Resource overlay complete")

    # Apply actor overlay
    logger.debug("render_preview: Applying actor overlay")
    # Build node_type_map from assigned nodes and overrides
    node_type_map = {}
    if node_overrides:
        for node_key, tier in node_overrides.items():
            col, row = map(int, node_key.split(','))
            node_type_map[(col, row)] = tier
    # Also include assigned node tiers from _last_assign_nodes
    for node in _last_assign_nodes:
        if (node["x"], node["y"]) not in node_type_map:
            node_type_map[(node["x"], node["y"])] = node["resource"]
    
    _mmr.overlay_actors(img, _mmr.parse_actor_locations(ent["yaml_txt"]),
                        bounds, scale, draw_spawns=True, draw_nodes=draw_nodes,
                        node_type_map=node_type_map)
    logger.debug("render_preview: Actor overlay complete")

    counts = count_resource_tiers(mb)
    # Expose the field metadata from the most recent assign_resources call so
    # the GUI can power the hand-paint mode without a separate analysis pass.
    counts["__fields__"] = list(_last_assign_fields)
    # Expose node information for tooltips
    counts["__nodes__"] = list(_last_assign_nodes)
    logger.debug(f"render_preview: Resource counts={counts}")
    logger.debug("render_preview: Preview generation complete")
    
    return img, counts

def main():
    ap = argparse.ArgumentParser(description="Convert OpenRA/CA maps to Cameo.")
    ap.add_argument("input", nargs="?", help="a .oramap file or a folder of them")
    ap.add_argument("-o", "--outdir")
    ap.add_argument("--keep-palettes", action="store_true")
    ap.add_argument("--keep-decorations", action="store_true",
                    help="don't drop actors Cameo lacks (may crash on load)")
    ap.add_argument("--dump-actors", metavar="RULES_DIR",
                    help="print valid Cameo actor names from a rules dir and exit")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--richness", type=float, default=None,
                    help="RESOURCE_RICHNESS knob: 0.5=all ore, 1.0=balanced/no gems, 1.5=all gems")
    ap.add_argument("--distribution", choices=["distance", "balance", "even"], default="balance",
                    help="resource value metric: 'distance'=richest at the outer edges "
                         "(farthest from any base); 'balance'=richest in the contested centre; "
                         "'even'=equal cell counts for every active resource type")
    ap.add_argument("--balance-bias", type=float, default=None,
                    help="(balance mode) how hard to pull rich resources into the contested "
                         "middle. 0=acts like 'distance'; 3=default; higher=stronger.")
    ap.add_argument("--balance-home-radius", type=float, default=None,
                    help="(balance mode) home/expansion safe zone in GRID CELLS; resources within "
                         "it stay low-tier no matter how contested. Default 15.")
    ap.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO",
                    help="logging level (default: INFO)")
    ap.add_argument("--log-file", metavar="PATH",
                    help="enable file logging to specified path")
    ap.add_argument("--no-remap-resources", dest="remap_resources", action="store_false",
                    help="disable Cameo resource algorithm (distance-based tiering) - resources "
                         "pass through 1-1 conversion only (algorithm is enabled by default)")
    ap.set_defaults(remap_resources=True)
    ap.add_argument("--no-remove-actors", dest="remove_problematic_actors", action="store_false",
                    help="keep rock/stone/bush actors even though they render with wrong colors "
                         "in Cameo's RA_TEMPERAT tileset (palette issue). By default these actors "
                         "are dropped to prevent visual corruption.")
    ap.set_defaults(remove_problematic_actors=True)
    ap.add_argument("--config", metavar="CONFIG_FILE",
                    help="load configuration from a YAML or JSON file")
    ap.add_argument("--paint-overrides", metavar="JSON",
                    help="JSON string of field paint overrides (format: {\"x,y\": \"resource_type\"})")
    ap.add_argument("--cell-overrides", metavar="JSON",
                    help="JSON string of cell paint overrides (format: {\"x,y\": \"resource_type\"})")
    ap.add_argument("--node-overrides", metavar="JSON",
                    help="JSON string of node paint overrides (format: {\"ax,ay\": \"resource_type\"})")
    ap.add_argument("--density-overrides", metavar="JSON",
                    help="JSON string of cell density overrides (format: {\"x,y\": 7})")
    ap.add_argument("--field-density-overrides", metavar="JSON",
                    help="JSON string of field density overrides (format: {\"x,y\": 7})")
    ap.add_argument("--node-affects-field-tier", dest="node_affects_field_tier", action="store_true",
                    help="when painting a node, also change the field tier (default: True)")
    ap.add_argument("--node-affects-field-tier=false", dest="node_affects_field_tier", action="store_false",
                    help="when painting a node, only change the node actor, not the field tier")
    ap.set_defaults(node_affects_field_tier=True)
    args = ap.parse_args()
    
    # Setup logging
    setup_logging(
        log_file=args.log_file,
        level=args.log_level,
        enable_file=args.log_file is not None
    )
    logger = get_logger()

    # Load configuration file if specified. Loaded first so explicit CLI knob
    # overrides below still win. After loading, re-sync the module-global aliases
    # (e.g. KEEP_NAMES, RESOURCE_RICHNESS) so the loaded values actually take
    # effect for code that reads the globals rather than ConverterConfig.
    if args.config:
        ConverterConfig.load_from_file(args.config)
        g = globals()
        for k in list(g):
            if not k.startswith('_') and k.isupper() and hasattr(ConverterConfig, k):
                g[k] = getattr(ConverterConfig, k)

    if args.richness is not None:
        globals()["RESOURCE_RICHNESS"] = args.richness
    _rr.DISTRIBUTION_MODE = args.distribution
    if args.balance_bias is not None:
        _rr.BALANCE_BIAS = max(0.0, args.balance_bias)
    globals()["REMOVE_PROBLEMATIC_ACTORS"] = args.remove_problematic_actors
    
    # Parse override JSON strings if provided
    paint_overrides = None
    cell_overrides = None
    node_overrides = None
    density_overrides = None
    field_density_overrides = None
    if args.paint_overrides:
        try:
            paint_overrides = json.loads(args.paint_overrides)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON in --paint-overrides: {e}")
            return 1
    if args.cell_overrides:
        try:
            cell_overrides = json.loads(args.cell_overrides)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON in --cell-overrides: {e}")
            return 1
    if args.node_overrides:
        try:
            node_overrides = json.loads(args.node_overrides)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON in --node-overrides: {e}")
            return 1
    if args.density_overrides:
        try:
            density_overrides = json.loads(args.density_overrides)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON in --density-overrides: {e}")
            return 1
    if args.field_density_overrides:
        try:
            field_density_overrides = json.loads(args.field_density_overrides)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON in --field-density-overrides: {e}")
            return 1
    if args.balance_home_radius is not None:
        _rr.BALANCE_HOME_RADIUS = max(1.0, args.balance_home_radius)
    
    # Validate resource configuration
    try:
        validate_resource_config(RESOURCE_RICHNESS, _rr.BALANCE_BIAS, _rr.BALANCE_HOME_RADIUS)
    except ValueError as e:
        print(f"[ERROR] Invalid resource configuration: {e}")
        return 1

    if args.dump_actors:
        dump_actors(args.dump_actors)
        return 0
    if not args.input:
        ap.error("input is required")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    valid = load_valid_actors(script_dir)
    
    # Load BI protocol configuration
    load_bi_protocol(script_dir)

    # Validate input path
    try:
        inp = validate_file_path(args.input, allow_directories=True)
    except ValueError as e:
        print(f"[ERROR] Invalid input path: {e}")
        return 1
    
    if os.path.isdir(inp):
        maps = []
        for f in sorted(os.listdir(inp)):
            if f.lower().endswith(".oramap"):
                try:
                    map_path = validate_oramap_file(os.path.join(inp, f))
                    maps.append(map_path)
                except ValueError as e:
                    print(f"[WARNING] Skipping invalid .oramap file {f}: {e}")
        base = inp
    elif inp.lower().endswith(".oramap"):
        try:
            maps = [validate_oramap_file(inp)]
        except ValueError as e:
            print(f"[ERROR] Invalid .oramap file: {e}")
            return 1
        base = os.path.dirname(inp) or "."
    else:
        print("Input must be a .oramap file or a folder of them.")
        return 2
    outdir = args.outdir or os.path.join(base, "converted")
    if not maps:
        print("No .oramap files found.")
        return 1
    print("Found %d map(s). valid-actors=%d  Output -> %s\n"
          % (len(maps), len(valid), outdir))
    _bal = ("  balance-bias=%s  home-radius=%s" % (_rr.BALANCE_BIAS, _rr.BALANCE_HOME_RADIUS)) if _rr.DISTRIBUTION_MODE == "balance" else ""
    print("RESOURCE_RICHNESS = %s   distribution = %s%s\n" % (RESOURCE_RICHNESS, _rr.DISTRIBUTION_MODE, _bal))
    ok = 0
    for m in maps:
        name = os.path.basename(m)
        rpt = Report()
        print("== %s" % name)
        try:
            if convert_map(m, os.path.join(outdir, name), rpt,
                           args.keep_palettes, args.keep_decorations, valid, args.dry_run,
                           args.remap_resources, paint_overrides, cell_overrides, node_overrides, args.node_affects_field_tier,
                           density_overrides, field_density_overrides, args.remove_problematic_actors):
                ok += 1
            print(rpt.dump())
        except Exception as e:
            print("  !! ERROR: %s" % e)
        print()
    print("Done: %d/%d converted." % (ok, len(maps)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
