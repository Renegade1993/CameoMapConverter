# Test Suite for Cameo Map Converter

This directory contains the test suite for the Cameo Map Converter using pytest.

## Installation

First, install pytest (added to requirements.txt):
```bash
pip install -r requirements.txt
```

## Running Tests

### Run all tests:
```bash
pytest
```

### Run only unit tests (fast):
```bash
pytest tests/unit/
```

### Run only integration tests:
```bash
pytest tests/integration/
```

### Run with verbose output:
```bash
pytest -v
```

### Run specific test file:
```bash
pytest tests/unit/test_validators.py
```

### Run specific test function:
```bash
pytest tests/unit/test_validators.py::TestValidateResourceConfig::test_valid_config
```

### Run tests excluding slow tests:
```bash
pytest -m "not slow"
```

## Test Structure

- `conftest.py` - Shared fixtures and configuration
- `unit/` - Fast unit tests for individual functions
- `integration/` - Integration tests for the full conversion pipeline

## Test Markers

- `@pytest.mark.unit` - Fast unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.slow` - Slow tests (for future use)
- `@pytest.mark.gui` - GUI-related tests (for future use)

## Adding New Tests

1. Unit tests go in `tests/unit/`
2. Integration tests go in `tests/integration/`
3. Use appropriate fixtures from `conftest.py`
4. Mark tests with appropriate decorators
5. Follow naming convention: `test_<functionality>`

## Current Test Coverage

- Validator functions (resource config, file paths, oramap files)
- Basic conversion pipeline
- Conversion with remap disabled
- Dry run mode

## Future Test Areas

- Resource algorithm correctness
- MapBin binary format handling
- Template remapping
- Actor validation and remapping
- GUI functionality
- Error handling and edge cases