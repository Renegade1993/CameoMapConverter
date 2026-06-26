"""
test_validators.py -- Unit tests for validator functions in cameo_map_converter.py
"""

import pytest
import sys
import os
import zipfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cameo_map_converter import (
    validate_resource_config,
    validate_file_path,
    validate_oramap_file
)


class TestValidateResourceConfig:
    """Tests for validate_resource_config function."""
    
    def test_valid_config(self):
        """Test that valid resource configuration passes."""
        # Should not raise any exception
        validate_resource_config(1.0, 3.0, 15.0)
    
    def test_invalid_richness_negative(self):
        """Test that negative richness raises ValueError."""
        with pytest.raises(ValueError, match="RESOURCE_RICHNESS"):
            validate_resource_config(-0.5, 3.0, 15.0)
    
    def test_invalid_richness_too_high(self):
        """Test that richness > 2.0 raises ValueError."""
        with pytest.raises(ValueError, match="RESOURCE_RICHNESS"):
            validate_resource_config(3.0, 3.0, 15.0)
    
    def test_invalid_bias_negative(self):
        """Test that negative balance bias raises ValueError."""
        with pytest.raises(ValueError, match="BALANCE_BIAS"):
            validate_resource_config(1.0, -1.0, 15.0)
    
    def test_invalid_home_radius_negative(self):
        """Test that negative home radius raises ValueError."""
        with pytest.raises(ValueError, match="BALANCE_HOME_RADIUS"):
            validate_resource_config(1.0, 3.0, -5.0)
    
    def test_invalid_home_radius_too_high(self):
        """Test that home radius > 100 raises ValueError."""
        with pytest.raises(ValueError, match="BALANCE_HOME_RADIUS"):
            validate_resource_config(1.0, 3.0, 150.0)
    
    def test_extreme_but_valid_values(self):
        """Test that extreme but valid values pass."""
        # These should be valid even if unusual
        validate_resource_config(2.0, 10.0, 100.0)


class TestValidateFilePath:
    """Tests for validate_file_path function."""
    
    def test_valid_file_path(self, tmp_path):
        """Test that valid file path passes."""
        test_file = tmp_path / "test.oramap"
        test_file.write_text("test content")
        result = validate_file_path(str(test_file))
        assert result == str(test_file)
    
    def test_nonexistent_file(self):
        """Test that nonexistent file raises ValueError."""
        with pytest.raises(ValueError, match="does not exist"):
            validate_file_path("/nonexistent/path/file.oramap")
    
    def test_directory_instead_of_file(self, tmp_path):
        """Test that directory instead of file raises ValueError."""
        with pytest.raises(ValueError, match="Expected a file, got directory"):
            validate_file_path(str(tmp_path), allow_directories=False)


class TestValidateOramapFile:
    """Tests for validate_oramap_file function."""
    
    def test_valid_oramap(self, sample_map_path):
        """Test that valid .oramap file passes."""
        if os.path.exists(sample_map_path):
            result = validate_oramap_file(sample_map_path)
            assert result == sample_map_path
        else:
            pytest.skip("Sample map file not found")
    
    def test_wrong_extension(self, tmp_path):
        """Test that non-.oramap file raises ValueError."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        
        with pytest.raises(ValueError, match="must be a .oramap file"):
            validate_oramap_file(str(test_file))
    
    def test_invalid_zip_file(self, tmp_path):
        """Test that invalid zip file raises ValueError."""
        test_file = tmp_path / "fake.oramap"
        test_file.write_text("not a zip file")
        
        with pytest.raises(ValueError, match="not a valid zip"):
            validate_oramap_file(str(test_file))