# dev_tools/

Standalone diagnostic and development scripts. None of these are part of the
production converter pipeline — they are not imported by any production module
and are not required to run CameoMapConverter.exe or the CLI.

| Script | Purpose |
|---|---|
| `analyze_resources.py` | Inspect resource node distribution on a source map |
| `check_conversion.py` | Compare actor lists between original and converted maps |
| `check_coordinates.py` | Debug coordinate system alignment issues |
| `detailed_node_check.py` | Verify node actors match their surrounding field resource |
| `extract_actors.py` | Dump actor names/positions from a raw .oramap |
| `render_corrected_distribution.py` | Render resource tier PNGs for visual diagnostics |
| `test_logging.py` | Manual smoke-test for the converter_logging module |
| `test_paint_symmetry.py` | Simulate manual mirror-paint clicks and verify symmetry |
| `test_symmetry.py` | Report detected symmetry transforms and field groups |
| `test_symmetry_all_maps.py` | Run symmetry detection across all maps in `maps/` |

Run from the project root: `py dev_tools/<script>.py ...`
