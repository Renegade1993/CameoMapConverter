"""
conftest.py -- Pytest configuration and shared fixtures for the Cameo Map Converter test suite.
"""

import os
import sys
import pytest
from pathlib import Path

# Add the parent directory to the path so we can import the converter modules
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def sample_map_path():
    """Fixture providing a path to a sample test map.
    
    This fixture is shared across multiple test files (unit and integration),
    so it belongs in conftest.py per pytest best practices.
    """
    return os.path.join(
        Path(__file__).parent.parent,
        "maps",
        "Cow_Level_1v1_BI-4.3.oramap"
    )


@pytest.fixture
def test_output_dir(tmp_path):
    """Fixture providing a temporary directory for test outputs.
    
    This fixture is shared across multiple test files, so it belongs in conftest.py.
    """
    output_dir = tmp_path / "test_output"
    output_dir.mkdir()
    return output_dir