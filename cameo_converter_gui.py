#!/usr/bin/env python3
"""
Cameo Map Converter GUI - PyQt/PySide Desktop Interface

Provides a user-friendly desktop interface for the Cameo Map Converter.
Features live preview rendering, map navigation, and batch conversion capabilities.

Preview rendering is IN-PROCESS via cameo_map_converter.render_preview() (the shared
minimap_render code path), so previews are sub-second and identical to a full conversion.
"""

APP_VERSION = "v0.76-beta-hotfix1"

import sys
import os
import runpy
import subprocess
import tempfile
import shutil
import json
from converter_logging import get_logger

# Use the existing ConverterLogger system for all logging
_logger = get_logger()


class JSONSettings:
    """JSON-based settings manager to replace QSettings."""
    
    def __init__(self, app_name, filename="settings.json"):
        self.app_name = app_name
        # Store settings in the same directory as the executable/script
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller executable - use executable's directory
            script_dir = os.path.dirname(sys.executable)
        else:
            # Running as script - use script's directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
        
        self.settings_file = os.path.join(script_dir, filename)
        self.settings = {}
        self.load()
    
    def load(self):
        """Load settings from JSON file."""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    self.settings = json.load(f)
        except Exception as e:
            _logger.error(f"Error loading settings: {e}")
            self.settings = {}
    
    def save(self):
        """Save settings to JSON file."""
        try:
            # Ensure directory exists
            settings_dir = os.path.dirname(self.settings_file)
            if settings_dir and not os.path.exists(settings_dir):
                os.makedirs(settings_dir)
            
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            _logger.error(f"Error saving settings: {e}")
    
    def get(self, key, default=None):
        """Get a setting value, with default if key doesn't exist."""
        return self.settings.get(key, default)
    
    def value(self, key, default=None, type=None):
        """Get a setting value."""
        value = self.settings.get(key, default)
        if type is not None and value is not None:
            try:
                return type(value)
            except (ValueError, TypeError):
                return default
        return value
    
    def setValue(self, key, value):
        """Set a setting value."""
        self.settings[key] = value
    
    def sync(self):
        """Sync settings to disk."""
        self.save()

try:
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                                 QProgressBar, QGroupBox, QSlider, QComboBox, 
                                 QCheckBox, QGridLayout, QScrollArea, QSizePolicy, 
                                 QStyleFactory, QFrame, QButtonGroup, QRadioButton, QTextEdit, QToolTip,
                                 QMenuBar, QMenu, QAction, QInputDialog, QMessageBox, QRubberBand)
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QEvent, QPoint, QRect, QSize
    from PyQt5.QtGui import QIcon, QFont, QPixmap, QImage, QPalette, QColor
    PYQT_VERSION = "PyQt5"
except ImportError:
    try:
        from PySide2.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                       QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                                       QProgressBar, QGroupBox, QSlider, QComboBox, 
                                       QCheckBox, QGridLayout, QScrollArea, QSizePolicy, 
                                       QStyleFactory, QFrame, QButtonGroup, QRadioButton, QTextEdit, QToolTip,
                                       QMenuBar, QMenu, QAction, QInputDialog, QMessageBox, QRubberBand)
        from PySide2.QtCore import Qt, QThread, Signal as pyqtSignal, QTimer, QRect, QSize
        from PySide2.QtGui import QIcon, QFont, QPixmap, QImage, QPalette, QColor
        PYQT_VERSION = "PySide2"
    except ImportError:
        print("Error: Neither PyQt5 nor PySide2 is installed.")
        print("Install with: pip install PyQt5")
        sys.exit(1)


def resource_path(relative_path):
    """Return the absolute path to a bundled resource.

    Works both when running as a plain script and when frozen by PyInstaller
    (where files land in sys._MEIPASS at startup).
    """
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


def _app_icon():
    """Return a QIcon for the CMC application icon, or an empty QIcon if missing."""
    ico_path = resource_path(os.path.join("Icon", "cmc.ico"))
    if os.path.exists(ico_path):
        return QIcon(ico_path)
    return QIcon()


class PreviewWorker(QThread):
    """Worker thread for generating map previews without blocking the GUI."""
    
    preview_ready = pyqtSignal(str, str)  # temp_file_path, map_name
    preview_failed = pyqtSignal(str, str)  # error_message, map_name
    counts_ready = pyqtSignal(dict, str)   # resource counts, map_name (in-process preview)
    log_output = pyqtSignal(str)
    
    def __init__(self, converter_script, input_map, output_dir, settings, parent=None):
        super().__init__(parent)
        self.converter_script = converter_script
        self.input_map = input_map
        self.output_dir = output_dir
        self.settings = settings
        self.temp_dir = tempfile.mkdtemp(prefix="cameo_preview_")
        self.process = None  # legacy subprocess handle (in-process preview no longer uses it)
        self.parent_gui = parent  # Reference to parent GUI for subprocess tracking
        self.resource_counts = {}
        
    def run(self):
        """Generate a preview IN-PROCESS (no subprocess) -- fast and lossless.

        Uses cameo_map_converter.render_preview(), which reuses a cached, knob-
        independent terrain layer + base resource cells and only re-runs resource
        tiering for the current settings, rendering via the shared minimap_render
        path. Output is identical to a full conversion at the same settings. Keeps the
        preview_ready(png_path, map_name) contract and also emits counts_ready(counts,
        map_name) so the resource counts always match the previewed settings."""
        name = os.path.basename(self.input_map)
        try:
            self.log_output.emit(f"Generating preview for {name}...")
            # Make the converter package importable (script run + frozen exe).
            if self.converter_script:
                conv_dir = os.path.dirname(os.path.abspath(self.converter_script))
                if conv_dir and conv_dir not in sys.path:
                    sys.path.insert(0, conv_dir)
            import cameo_map_converter as cmc

            settings = {
                "richness": self.settings.get("richness"),
                "distribution": self.settings.get("distribution", "balance"),
                "balance_bias": self.settings.get("balance_bias"),
                "balance_home_radius": self.settings.get("balance_home_radius"),
                "remap_resources": self.settings.get("remap_resources", True),
                "remove_actors": self.settings.get("remove_actors", True),
                "paint_overrides": self.settings.get("paint_overrides", {}),
                "cell_overrides": self.settings.get("cell_overrides", {}),
                "node_overrides": self.settings.get("node_overrides", {}),
                "density_overrides": self.settings.get("density_overrides", {}),
                "field_density_overrides": self.settings.get("field_density_overrides", {}),
                "node_affects_field_tier": self.settings.get("node_affects_field_tier", False),
            }
            img, counts = cmc.render_preview(self.input_map, settings,
                                             scale=4, draw_nodes=True)
            preview_path = os.path.join(
                self.temp_dir, os.path.splitext(name)[0] + ".preview.png")
            img.save(preview_path)
            self.resource_counts = counts
            self.counts_ready.emit(counts, name)
            self.preview_ready.emit(preview_path, name)
        except Exception as e:
            import traceback
            self.preview_failed.emit("%s\n%s" % (e, traceback.format_exc()), name)
            
    def cleanup(self):
        """Clean up temporary files and subprocess."""
        # Kill subprocess if running
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(1000)  # Wait up to 1 second
                if self.process.poll() is None:
                    self.process.kill()  # Force kill if terminate didn't work
            except Exception as e:
                _logger.warning(f"Error killing subprocess: {e}")
        
        # Clean up temp directory
        try:
            if os.path.exists(self.temp_dir):
                # Try multiple times to handle Windows file locking issues
                for attempt in range(3):
                    try:
                        shutil.rmtree(self.temp_dir)
                        return
                    except Exception as e:
                        _logger.warning(f"Cleanup attempt {attempt + 1} failed: {e}")
                        if attempt < 2:
                            import time
                            time.sleep(0.5)  # Wait before retry
                _logger.warning(f"Failed to clean up temp directory after 3 attempts")
        except Exception as e:
            _logger.warning(f"Error in cleanup: {e}")


class ConversionWorker(QThread):
    """Worker thread for running actual map conversions."""
    
    conversion_complete = pyqtSignal(bool, str, str)  # success, message, map_name
    log_output = pyqtSignal(str)
    progress_updated = pyqtSignal(str, str)  # message, map_name
    
    def __init__(self, converter_script, input_map, output_dir, settings, parent=None):
        super().__init__(parent)
        self.converter_script = converter_script
        self.input_map = input_map
        self.output_dir = output_dir
        self.settings = settings
        self.parent_gui = parent  # Reference to parent GUI for subprocess tracking
    
    def run(self):
        """Execute single map conversion."""
        try:
            self.log_output.emit(f"Converting {os.path.basename(self.input_map)}...")
            
            # Determine Python executable to use
            # Always use the current interpreter / frozen EXE.  The frozen EXE now
            # dispatches to the bundled cameo_map_converter.py when it is passed as the
            # first argument, so we avoid loading PyInstaller 3.12 extension modules
            # into a system Python 3.13/3.14 interpreter.
            python_exe = sys.executable
            
            # Build command arguments
            cmd = [python_exe, self.converter_script, str(self.input_map)]
            
            if self.output_dir:
                cmd.extend(["-o", self.output_dir])
            
            # Apply current settings
            if self.settings.get('richness') is not None:
                cmd.extend(["--richness", str(self.settings['richness'])])
            
            if self.settings.get('distribution'):
                cmd.extend(["--distribution", self.settings['distribution']])
            
            if self.settings.get('balance_bias') is not None:
                cmd.extend(["--balance-bias", str(self.settings['balance_bias'])])
            
            if self.settings.get('balance_home_radius') is not None:
                cmd.extend(["--balance-home-radius", str(self.settings['balance_home_radius'])])
            
            if not self.settings.get('remap_resources', True):
                cmd.append("--no-remap-resources")

            if not self.settings.get('remove_actors', True):
                cmd.append("--no-remove-actors")
            
            # Add paint, cell, node, and density overrides as JSON strings
            if self.settings.get('paint_overrides'):
                import json
                cmd.extend(["--paint-overrides", json.dumps(self.settings['paint_overrides'])])
            if self.settings.get('cell_overrides'):
                import json
                cmd.extend(["--cell-overrides", json.dumps(self.settings['cell_overrides'])])
            if self.settings.get('node_overrides'):
                import json
                cmd.extend(["--node-overrides", json.dumps(self.settings['node_overrides'])])
            if self.settings.get('density_overrides'):
                import json
                cmd.extend(["--density-overrides", json.dumps(self.settings['density_overrides'])])
            if self.settings.get('field_density_overrides'):
                import json
                cmd.extend(["--field-density-overrides", json.dumps(self.settings['field_density_overrides'])])

            # Add node_affects_field_tier flag (GUI default is False: node painting
            # only changes the node actor, not the surrounding field tier).
            if not self.settings.get('node_affects_field_tier', False):
                cmd.append("--node-affects-field-tier=false")

            # Run the conversion
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            # Add comprehensive window suppression flags
            creation_flags = 0
            creation_flags |= subprocess.CREATE_NO_WINDOW
            creation_flags |= 0x08000000  # CREATE_NO_WINDOW equivalent for some cases
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=os.path.dirname(self.converter_script),
                startupinfo=startupinfo,
                creationflags=creation_flags,
                stdin=subprocess.DEVNULL  # Also suppress stdin
            )
            
            # Track subprocess in parent GUI for cleanup
            if self.parent_gui:
                self.parent_gui.subprocesses.append(process)
            
            # Stream output
            for line in process.stdout:
                line = line.strip()
                if line:
                    self.log_output.emit(line)
            
            process.wait()
            
            if process.returncode == 0:
                self.conversion_complete.emit(True, f"Successfully converted {os.path.basename(self.input_map)}", os.path.basename(self.input_map))
            else:
                self.conversion_complete.emit(False, f"Failed to convert {os.path.basename(self.input_map)}", os.path.basename(self.input_map))
            
        except Exception as e:
            self.log_output.emit(f"Error during conversion: {str(e)}")
            self.conversion_complete.emit(False, str(e), os.path.basename(self.input_map))


class BatchConversionWorker(QThread):
    """Worker thread for batch converting multiple maps."""
    
    batch_progress = pyqtSignal(int, int, str)  # current, total, map_name
    batch_complete = pyqtSignal(int)  # success_count
    log_output = pyqtSignal(str)
    
    def __init__(self, converter_script, map_files, output_dir, settings, parent=None):
        super().__init__(parent)
        self.converter_script = converter_script
        self.map_files = map_files
        self.output_dir = output_dir
        self.settings = settings
        self.parent_gui = parent  # Reference to parent GUI for subprocess tracking
        
    def run(self):
        """Execute batch conversion."""
        success_count = 0
        
        # Determine Python executable to use
        # Always use the current interpreter / frozen EXE.  The frozen EXE now
        # dispatches to the bundled cameo_map_converter.py when it is passed as the
        # first argument, so we avoid loading PyInstaller 3.12 extension modules
        # into a system Python 3.13/3.14 interpreter.
        python_exe = sys.executable
        
        for i, map_file in enumerate(self.map_files):
            map_name = os.path.basename(map_file)
            self.batch_progress.emit(i + 1, len(self.map_files), map_name)
            
            # Build command arguments
            cmd = [python_exe, self.converter_script, str(map_file)]
            
            if self.output_dir:
                cmd.extend(["-o", self.output_dir])
            
            # Apply current settings
            if self.settings.get('richness') is not None:
                cmd.extend(["--richness", str(self.settings['richness'])])
            
            if self.settings.get('distribution'):
                cmd.extend(["--distribution", self.settings['distribution']])
            
            if self.settings.get('balance_bias') is not None:
                cmd.extend(["--balance-bias", str(self.settings['balance_bias'])])
            
            if self.settings.get('balance_home_radius') is not None:
                cmd.extend(["--balance-home-radius", str(self.settings['balance_home_radius'])])
            
            if not self.settings.get('remap_resources', True):
                cmd.append("--no-remap-resources")

            if not self.settings.get('remove_actors', True):
                cmd.append("--no-remove-actors")
            
            # Add paint, cell, node, and density overrides as JSON strings
            if self.settings.get('paint_overrides'):
                import json
                cmd.extend(["--paint-overrides", json.dumps(self.settings['paint_overrides'])])
            if self.settings.get('cell_overrides'):
                import json
                cmd.extend(["--cell-overrides", json.dumps(self.settings['cell_overrides'])])
            if self.settings.get('node_overrides'):
                import json
                cmd.extend(["--node-overrides", json.dumps(self.settings['node_overrides'])])
            if self.settings.get('density_overrides'):
                import json
                cmd.extend(["--density-overrides", json.dumps(self.settings['density_overrides'])])
            if self.settings.get('field_density_overrides'):
                import json
                cmd.extend(["--field-density-overrides", json.dumps(self.settings['field_density_overrides'])])

            # Add node_affects_field_tier flag (GUI default is False: node painting
            # only changes the node actor, not the surrounding field tier).
            if not self.settings.get('node_affects_field_tier', False):
                cmd.append("--node-affects-field-tier=false")

            # Run the conversion
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            # Add comprehensive window suppression flags
            creation_flags = 0
            creation_flags |= subprocess.CREATE_NO_WINDOW
            creation_flags |= 0x08000000  # CREATE_NO_WINDOW equivalent for some cases
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=os.path.dirname(self.converter_script),
                startupinfo=startupinfo,
                creationflags=creation_flags,
                stdin=subprocess.DEVNULL  # Also suppress stdin
            )
            
            # Track subprocess in parent GUI for cleanup
            if self.parent_gui:
                self.parent_gui.subprocesses.append(process)
            
            # Stream output
            for line in process.stdout:
                line = line.strip()
                if line:
                    self.log_output.emit(line)
            
            process.wait()
            
            if process.returncode == 0:
                success_count += 1
                self.log_output.emit(f"✓ Successfully converted {map_name}")
            else:
                self.log_output.emit(f"✗ Failed to convert {map_name}")
        
        self.batch_complete.emit(success_count)


class CameoConverterGUI(QMainWindow):
    """Main GUI window for the Cameo Map Converter."""
    
    def __init__(self):
        super().__init__()
        self.setWindowIcon(_app_icon())
        self.converter_script = self.find_converter_script()
        self.incoming_dir = ""
        self.outgoing_dir = ""
        self.map_files = []
        self.current_map_index = 0
        self.converted_maps = set()
        self.current_preview_path = None
        self.preview_worker = None
        self.preview_refresh_pending = False
        self.navigation_debounce_timer = None
        self.conversion_worker = None
        self.batch_worker = None
        self._preview_display_size = None   # QSize used to keep preview scaling stable
        
        # Application settings - using JSON instead of QSettings to avoid window multiplication
        self.settings = JSONSettings("CameoMapConverter", "settings.json")

        # Hand-paint mode state
        self.paint_mode = False                # True when paint overlay is active
        self._paint_mirror = True              # True → paint all symmetry partners at once
        self._paint_density = "Replace"        # Density setting: "Replace", "Random", "1", "2", "3", "4", "5"
        self._paint_overrides = {}             # "col,row" -> tier (field-center key)
        self._paint_cell_overrides = {}        # "col,row" -> tier (individual cell overrides)
        self._paint_node_overrides = {}        # "ax,ay" -> resource type (node-paint overrides)
        self._paint_density_overrides = {}     # "col,row" -> density setting (None/"Random"/int)
        self._paint_field_density_overrides = {}  # "col,row" -> density setting for field-level paints
        self._paint_undo_stack = []            # list of {key: old_tier} diffs
        self._paint_redo_stack = []            # list of {key: new_tier} diffs
        self._paint_field_cache = []           # list of {center, cells, tier, mirror_keys} from last render
        self._paint_node_cache = []            # list of {x, y, resource} from last render (for hover + paint)
        self._active_paint_map = None          # map name for which current overrides are valid
        self._MIRROR_MAX_DIST = 3.0            # cells: farthest a mirrored cell may drift for count parity
        self.tooltips_enabled = True
        
        # Box-select drag state
        self._drag_origin = None               # QPoint where drag started (viewer coords)
        self._rubber_band = None               # QRubberBand overlay while dragging
        
        # Initialize logging system
        self.logger = get_logger()
        self.init_logging_from_settings()
        
        # Track preview locked state (must be initialized before init_ui)
        self.preview_locked = False
        
        # Track navigation in progress to prevent spamming
        self.navigation_in_progress = False
        
        # Track subprocess processes for cleanup
        self.subprocesses = []

        # Temp directory for preview extraction
        self.temp_dir = tempfile.mkdtemp(prefix="cameo_gui_")

        # Hover functionality for resource type display
        self.hover_timer = QTimer()
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self.show_hover_resource_type)
        self.last_hover_position = None
        self.hover_enabled = True
        
        # Resource color mapping for hover detection (matching render_corrected_distribution.py)
        self.resource_color_map = {
            "#965F28": "Ore",           # (150, 95, 40)
            "#00D200": "Tiberium",     # (0, 210, 0)
            "#00B4FF": "BlueTiberium", # (0, 180, 255)
            "#EB1E1E": "RedTiberium",  # (235, 30, 30)
            "#FFCD00": "GoldTiberium", # (255, 205, 0)
            "#AA3CD2": "Gems",         # (170, 60, 210)
            # Common background colors
            "#121416": "Background",   # Dark gray background
            "#707070": "Background",   # UI background color
            "#000000": "Background",   # Black
            "#1A1A1A": "Background",   # Dark gray
        }
        
        # Display names for resource types in the legend and resource counts.
        self.resource_display_names = {
            "Ore": "Ore",
            "Tiberium": "Green Tiberium",
            "BlueTiberium": "Blue Tiberium",
            "RedTiberium": "Red Tiberium",
            "GoldTiberium": "Gold Tiberium",
            "Gems": "Gems"
        }

        # Tooltip names: nodes are the actor/miner, fields are just the resource.
        self.resource_node_names = {
            "Ore": "Ore Mine",
            "Tiberium": "Green Tiberium Tree",
            "BlueTiberium": "Blue Tiberium Tree",
            "RedTiberium": "Red Tiberium Tree",
            "GoldTiberium": "Gold Tiberium Tree",
            "Gems": "Gem Mine"
        }
        self.resource_field_names = {
            "Ore": "Ore",
            "Tiberium": "Green Tiberium",
            "BlueTiberium": "Blue Tiberium",
            "RedTiberium": "Red Tiberium",
            "GoldTiberium": "Gold Tiberium",
            "Gems": "Gems"
        }

        # Cameo max densities per tier, used to scale a cell's raw density to a 1-5 level.
        self._tier_max_density = {
            "Ore": 40, "Tiberium": 35, "BlueTiberium": 30,
            "RedTiberium": 25, "GoldTiberium": 20, "Gems": 15
        }

        self.init_ui()
        self.init_menu_bar()
        self.apply_system_theme()
        self.setWindowTitle(f"Cameo Map Converter {APP_VERSION}")
        self.setMinimumSize(1366, 850)
        self.resize(1600, 950)
        
    def find_converter_script(self):
        """Find the cameo_map_converter.py script location."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(script_dir, "cameo_map_converter.py")
        if os.path.exists(script_path):
            return script_path
        return ""
    
    def init_logging_from_settings(self):
        """Initialize logging from saved settings."""
        # Get logging settings from JSON (default all OFF for production)
        logging_settings = self.settings.get("logging", {
            "DEBUG": False,  # Verbose logging OFF by default
            "INFO": False,
            "WARNING": False,
            "ERROR": False
        })
        
        # Setup logging directory to log subfolder
        # Handle both script and exe environments
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller exe
            base_dir = os.path.dirname(sys.executable)
        else:
            # Running as script
            base_dir = os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(base_dir, "log")
        self.logger.setup_file_logging(log_dir=log_dir)
        
        # Always write a unified log file so console/print output is easy to share
        self.logger.enable_all_file_logging()
        # Capture stdout/stderr so every print() also lands in the log files
        self.logger.capture_stdout()
        
        # Enable only the log types that are enabled in settings
        for log_type, enabled in logging_settings.items():
            if enabled:
                self.logger.enable_log_type(log_type)
    
    def init_menu_bar(self):
        """Initialize the menu bar with logging controls and presets."""
        menubar = self.menuBar()

        # Presets menu — dynamically rebuilt each time it's shown
        self.presets_menu = menubar.addMenu("Presets")
        self.presets_menu.aboutToShow.connect(self._rebuild_presets_menu)

        # Logging menu
        logging_menu = menubar.addMenu("Logging")
        
        # Add log type toggles
        self.log_actions = {}
        for log_type in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            action = QAction(log_type, self)
            action.setCheckable(True)
            
            # Check if this log type is currently enabled
            if self.logger.is_log_type_enabled(log_type):
                action.setChecked(True)
            
            # Connect to toggle function
            action.triggered.connect(lambda checked, lt=log_type: self.toggle_log_type(lt, checked))
            
            self.log_actions[log_type] = action
            logging_menu.addAction(action)
        
        logging_menu.addSeparator()
        
        # Add "Open Log Directory" action
        open_logs_action = QAction("Open Log Directory", self)
        open_logs_action.triggered.connect(self.open_log_directory)
        logging_menu.addAction(open_logs_action)
    
    def toggle_log_type(self, log_type, enabled):
        """Toggle a specific log type on/off.
        
        Args:
            log_type: One of 'DEBUG', 'INFO', 'WARNING', 'ERROR'
            enabled: True to enable, False to disable
        """
        try:
            if enabled:
                self.logger.enable_log_type(log_type)
            else:
                self.logger.disable_log_type(log_type)

            # Save to settings
            self.save_logging_settings()
        except Exception as e:
            # Never let a logging toggle hard-crash the GUI. Record the full
            # traceback to gui_crash_log.txt, revert the menu check state, and
            # print the error so it is diagnosable.
            import traceback
            tb = traceback.format_exc()
            try:
                with open(_crash_log_path(), "a", encoding="utf-8") as f:
                    f.write(f"\n===== toggle_log_type({log_type}, {enabled}) FAILED =====\n{tb}\n")
            except Exception:
                pass
            action = getattr(self, "log_actions", {}).get(log_type)
            if action is not None:
                action.setChecked(not enabled)
    
    def save_logging_settings(self):
        """Save current logging settings to JSON."""
        logging_settings = {}
        for log_type in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            logging_settings[log_type] = self.logger.is_log_type_enabled(log_type)
        
        self.settings.setValue("logging", logging_settings)
        self.settings.save()
    
    def open_log_directory(self):
        """Open the log directory in the system file explorer."""
        import subprocess
        import platform
        
        # Get log directory
        if self.logger._log_dir:
            log_dir = self.logger._log_dir
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(script_dir, "log")
        
        # Ensure directory exists
        os.makedirs(log_dir, exist_ok=True)
        
        # Open in file explorer
        if platform.system() == "Windows":
            os.startfile(log_dir)
        elif platform.system() == "Darwin":  # macOS
            subprocess.run(["open", log_dir])
        else:  # Linux
            subprocess.run(["xdg-open", log_dir])
    
    def resizeEvent(self, event):
        """Re-display the current preview when the window is resized.

        This updates the stable target size so the preview fills the available
        viewer space while keeping the next refresh at the same size.
        """
        if self.map_viewer and self.current_preview_path:
            self._preview_display_size = QSize(self.map_viewer.size())
            self.display_preview(self.current_preview_path, os.path.basename(self.map_files[self.current_map_index]))
        super().resizeEvent(event)

    def closeEvent(self, event):
        """Handle window close event - clean up all processes."""
        
        # Cancel timers
        self.preview_timer.stop()
        self.navigation_debounce_timer.stop()
        self.hover_timer.stop()
        
        # Terminate preview worker
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.cleanup()
            self.preview_worker.terminate()
            self.preview_worker.wait(3000)  # Wait up to 3 seconds
        
        # Terminate conversion worker
        if self.conversion_worker and self.conversion_worker.isRunning():
            self.conversion_worker.terminate()
            self.conversion_worker.wait(2000)
        
        # Terminate batch worker
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.terminate()
            self.batch_worker.wait(2000)
        
        # Kill all tracked subprocesses
        for proc in self.subprocesses:
            try:
                if proc.poll() is None:  # Process is still running
                    proc.terminate()
                    proc.wait(1000)  # Wait up to 1 second
                    if proc.poll() is None:
                        proc.kill()  # Force kill if terminate didn't work
            except Exception as e:
                _logger.warning(f"Error killing subprocess: {e}")
        
        # Save settings before closing
        self.save_settings()

        # Clean up temp directory
        try:
            if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            _logger.warning(f"Error cleaning up temp directory: {e}")

        event.accept()
        
    def apply_system_theme(self):
        """Apply system dark/light mode preference."""
        # Try to detect system theme
        if sys.platform == "win32":
            # Windows 10/11 dark mode detection
            import winreg
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                                   r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                winreg.CloseKey(key)
                if value == 0:
                    # Dark mode
                    app = QApplication.instance()
                    app.setStyle("Fusion")
                    palette = QPalette()
                    palette.setColor(QPalette.Window, QColor(53, 53, 53))
                    palette.setColor(QPalette.WindowText, Qt.white)
                    palette.setColor(QPalette.Base, QColor(25, 25, 25))
                    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
                    palette.setColor(QPalette.ToolTipBase, Qt.white)
                    palette.setColor(QPalette.ToolTipText, Qt.white)
                    palette.setColor(QPalette.Text, Qt.white)
                    palette.setColor(QPalette.Button, QColor(53, 53, 53))
                    palette.setColor(QPalette.ButtonText, Qt.white)
                    palette.setColor(QPalette.BrightText, Qt.red)
                    palette.setColor(QPalette.Link, QColor(42, 130, 218))
                    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
                    palette.setColor(QPalette.HighlightedText, Qt.black)
                    app.setPalette(palette)
            except Exception:
                pass
        
    def init_ui(self):
        """Initialize the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        
        # Top section: Game types and directories
        top_layout = QHBoxLayout()
        
        # Left side: Incoming
        incoming_group = QGroupBox("Incoming")
        incoming_layout = QVBoxLayout()
        
        incoming_game_layout = QHBoxLayout()
        incoming_game_layout.addWidget(QLabel("Game Type:"))
        self.incoming_game_label = QLabel("OpenRA")
        self.incoming_game_label.setStyleSheet("font-weight: bold; color: #2196F3;")
        incoming_game_layout.addWidget(self.incoming_game_label)
        incoming_game_layout.addStretch()
        incoming_layout.addLayout(incoming_game_layout)
        
        incoming_dir_layout = QHBoxLayout()
        self.incoming_dir_label = QLabel("No directory selected")
        self.incoming_dir_label.setWordWrap(True)
        self.incoming_dir_label.setStyleSheet("color: gray;")
        incoming_dir_layout.addWidget(self.incoming_dir_label)
        self.incoming_dir_btn = QPushButton("Browse...")
        self.incoming_dir_btn.clicked.connect(self.select_incoming_dir)
        incoming_dir_layout.addWidget(self.incoming_dir_btn)
        incoming_layout.addLayout(incoming_dir_layout)
        
        incoming_group.setLayout(incoming_layout)
        top_layout.addWidget(incoming_group, 1)
        
        # Right side: Outgoing
        outgoing_group = QGroupBox("Outgoing")
        outgoing_layout = QVBoxLayout()
        
        outgoing_game_layout = QHBoxLayout()
        outgoing_game_layout.addWidget(QLabel("Game Type:"))
        self.outgoing_game_label = QLabel("Cameo")
        self.outgoing_game_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
        outgoing_game_layout.addWidget(self.outgoing_game_label)
        outgoing_game_layout.addStretch()
        outgoing_layout.addLayout(outgoing_game_layout)
        
        outgoing_dir_layout = QHBoxLayout()
        self.outgoing_dir_label = QLabel("No directory selected")
        self.outgoing_dir_label.setWordWrap(True)
        self.outgoing_dir_label.setStyleSheet("color: gray;")
        outgoing_dir_layout.addWidget(self.outgoing_dir_label)
        self.outgoing_dir_btn = QPushButton("Browse...")
        self.outgoing_dir_btn.clicked.connect(self.select_outgoing_dir)
        outgoing_dir_layout.addWidget(self.outgoing_dir_btn)
        outgoing_layout.addLayout(outgoing_dir_layout)
        
        outgoing_group.setLayout(outgoing_layout)
        top_layout.addWidget(outgoing_group, 1)
        
        main_layout.addLayout(top_layout)
        
        # Center section: Map viewer with navigation
        viewer_layout = QHBoxLayout()
        
        # Left navigation arrow
        self.left_arrow = QPushButton("◀")
        self.left_arrow.setFixedSize(40, 60)
        self.left_arrow.clicked.connect(self.navigate_previous)
        self.left_arrow.setEnabled(False)
        viewer_layout.addWidget(self.left_arrow)
        
        # Map viewer
        viewer_container = QWidget()
        viewer_layout_inner = QHBoxLayout(viewer_container)
        
        # Resource type colors (matching render_corrected_distribution.py)
        resource_colors = {
            "Ore": "#965F28",
            "Tiberium": "#00D200",
            "BlueTiberium": "#00B4FF",
            "RedTiberium": "#EB1E1E",
            "GoldTiberium": "#FFCD00",
            "Gems": "#AA3CD2",
        }
        self._legend_colors = resource_colors

        # ── Legend + paint controls panel ─────────────────────────────────────
        left_panel = QWidget()
        left_panel.setMinimumWidth(160)
        left_panel.setMaximumWidth(200)
        left_panel.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(4)
        left_layout.setContentsMargins(4, 0, 4, 0)

        left_layout.addSpacing(4)
        left_layout.addWidget(QLabel("<b>Resource Legend:</b>"))

        # Current paint-type tracking (used by legend click handlers)
        self._paint_type = "Ore"
        self._legend_widgets = {}

        for resource, color in resource_colors.items():
            # The highlight container: only wraps the swatch + label, not full width.
            # We use a QWidget as a tight container with no stretch so the border
            # never extends beyond the text.
            row_outer = QHBoxLayout()
            row_outer.setContentsMargins(0, 0, 0, 0)
            row_outer.setSpacing(0)

            resource_item = QWidget()
            resource_item.setObjectName(f"legend_{resource}")
            resource_item_layout = QHBoxLayout(resource_item)
            resource_item_layout.setContentsMargins(2, 1, 2, 1)
            resource_item_layout.setSpacing(4)
            resource_item.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

            color_box = QLabel()
            color_box.setFixedSize(14, 14)
            color_box.setStyleSheet(f"background-color: {color}; border: 1px solid #333;")
            resource_item_layout.addWidget(color_box)

            display_name = self.resource_display_names.get(resource, resource)
            resource_label = QLabel(display_name)
            resource_label.setStyleSheet("font-size: 10px;")
            resource_item_layout.addWidget(resource_label)

            # Install event filter for hover + click in paint mode
            resource_item.installEventFilter(self)
            resource_item.setProperty("legend_resource", resource)
            resource_item.setMouseTracking(True)

            row_outer.addWidget(resource_item)
            row_outer.addStretch()

            row_wrapper = QWidget()
            row_wrapper.setLayout(row_outer)
            left_layout.addWidget(row_wrapper)

            self._legend_widgets[resource] = {
                "item_widget": resource_item,
                "color_box": color_box,
                "label": resource_label,
            }

        # Paint controls under the legend
        left_layout.addSpacing(8)
        left_layout.addWidget(QLabel("<b>Paint Controls:</b>"))

        # Paint Mode button (moved from top of legend)
        self.paint_mode_btn = QPushButton("Paint Mode")
        self.paint_mode_btn.setCheckable(True)
        self.paint_mode_btn.setToolTip(
            "Toggle hand-paint mode.\n"
            "When ON: click any legend entry to select that resource type,\n"
            "then click a resource cell on the preview map to override it.\n"
            "Drag a box to repaint all cells inside the box.\n"
            "Legend entries highlight when hovered — click to pick the paint type."
        )
        self.paint_mode_btn.setStyleSheet(
            "QPushButton { font-size: 12px; font-weight: bold; background-color: #8B0000; color: white; min-height: 34px; }"
            "QPushButton:checked { background-color: #CD5C5C; color: white; }"
        )
        self.paint_mode_btn.toggled.connect(self.on_paint_mode_toggled)
        left_layout.addWidget(self.paint_mode_btn)
        left_layout.addSpacing(4)

        # Symmetrical Paint Mode button (moved from top of legend)
        self.paint_mirror_btn = QPushButton("Symmetry Mode")
        self.paint_mirror_btn.setCheckable(True)
        self.paint_mirror_btn.setChecked(True)   # ON by default
        self.paint_mirror_btn.setToolTip(
            "When ON, painting a resource cell automatically paints all\n"
            "symmetry-mirrored partner cells to the same type.\n"
            "Turn OFF to paint individual cells without affecting their mirrors."
        )
        self.paint_mirror_btn.setStyleSheet("QPushButton { min-height: 30px; }")
        self.paint_mirror_btn.toggled.connect(self._on_paint_mirror_toggled)
        left_layout.addWidget(self.paint_mirror_btn)
        left_layout.addSpacing(6)

        # Resource Density dropdown
        left_layout.addWidget(QLabel("<b>Density:</b>"))
        self.paint_density_combo = QComboBox()
        self.paint_density_combo.addItems(["Replace", "Random", "1", "2", "3", "4", "5"])
        self.paint_density_combo.setCurrentIndex(0)  # Default to "Replace"
        self.paint_density_combo.setToolTip(
            "Resource density/saturation level for painting:\n"
            "Replace: Keep existing density (only for existing resources)\n"
            "Random: Random density 1-5\n"
            "1-5: Specific density level"
        )
        self.paint_density_combo.currentIndexChanged.connect(self._on_density_changed)
        left_layout.addWidget(self.paint_density_combo)

        self.paint_undo_btn = QPushButton("Undo")
        self.paint_undo_btn.setToolTip("Undo the last paint stroke")
        self.paint_undo_btn.setEnabled(False)
        self.paint_undo_btn.clicked.connect(self.paint_undo)
        left_layout.addWidget(self.paint_undo_btn)

        self.paint_redo_btn = QPushButton("Redo")
        self.paint_redo_btn.setToolTip("Redo the last undone paint stroke")
        self.paint_redo_btn.setEnabled(False)
        self.paint_redo_btn.clicked.connect(self.paint_redo)
        left_layout.addWidget(self.paint_redo_btn)

        self.paint_clear_btn = QPushButton("Clear")
        self.paint_clear_btn.setToolTip("Remove all paint overrides and restore algorithmic assignment")
        self.paint_clear_btn.clicked.connect(self.paint_clear)
        left_layout.addWidget(self.paint_clear_btn)

        left_layout.addStretch()
        viewer_layout_inner.addWidget(left_panel)

        # Center: Map viewer
        viewer_center = QWidget()
        viewer_center.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        viewer_center_layout = QVBoxLayout(viewer_center)

        self.map_viewer = QLabel()
        self.map_viewer.setAlignment(Qt.AlignCenter)
        self.map_viewer.setMinimumSize(480, 360)
        self.map_viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.map_viewer.setMouseTracking(True)  # Enable mouse tracking for hover events
        self.map_viewer.installEventFilter(self)  # Install event filter for mouse events
        self.map_viewer.setStyleSheet("""
            QLabel {
                border: 2px solid #666;
                border-radius: 8px;
                background-color: #000000;
                color: #ccc;
                font-size: 14px;
            }
        """)
        self.map_viewer.setText("Waiting for map directory...")
        viewer_center_layout.addWidget(self.map_viewer)
        
        # Map name display
        self.current_map_label = QLabel("")
        self.current_map_label.setAlignment(Qt.AlignCenter)
        self.current_map_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        viewer_center_layout.addWidget(self.current_map_label)
        
        viewer_layout_inner.addWidget(viewer_center, 1)
        
        viewer_layout.addWidget(viewer_container, 1)
        
        # Right side panel: Status, resource counts, and hold button
        right_panel = QWidget()
        right_panel.setMinimumWidth(140)
        right_panel.setMaximumWidth(170)
        right_panel.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
        right_panel_layout = QVBoxLayout(right_panel)

        # Status indicator with label
        status_layout = QVBoxLayout()
        status_label = QLabel("Conversion Status:")
        status_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        status_layout.addWidget(status_label)

        status_indicator_layout = QHBoxLayout()
        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(20, 20)
        self.status_indicator.setStyleSheet("""
            QLabel {
                border-radius: 10px;
                background-color: #ccc;
            }
        """)
        status_indicator_layout.addWidget(self.status_indicator)
        status_indicator_layout.addStretch()
        status_layout.addLayout(status_indicator_layout)

        right_panel_layout.addLayout(status_layout)
        right_panel_layout.addSpacing(12)

        # Resource counts moved to the right panel
        right_panel_layout.addWidget(QLabel("<b>Resource Counts:</b>"))
        self.resource_counts = {}
        for resource in resource_colors.keys():
            display_name = self.resource_display_names.get(resource, resource)
            count_label = QLabel(f"{display_name}: 0")
            count_label.setStyleSheet("font-size: 10px;")
            self.resource_counts[resource] = count_label
            right_panel_layout.addWidget(count_label)

        right_panel_layout.addStretch()

        # Preview converted button with dual functionality
        self.preview_converted_btn = QPushButton("Preview\nConverted")
        self.preview_converted_btn.setEnabled(False)
        self.preview_converted_btn.pressed.connect(self.preview_converted_map)
        self.preview_converted_btn.released.connect(self.restore_current_preview)
        self.preview_converted_btn.setMaximumWidth(120)
        self.preview_converted_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.preview_converted_btn.customContextMenuRequested.connect(self.toggle_preview_lock)
        right_panel_layout.addWidget(self.preview_converted_btn)

        viewer_layout.addWidget(right_panel)
        
        # Right navigation arrow
        self.right_arrow = QPushButton("▶")
        self.right_arrow.setFixedSize(40, 60)
        self.right_arrow.clicked.connect(self.navigate_next)
        self.right_arrow.setEnabled(False)
        viewer_layout.addWidget(self.right_arrow)

        # Give the viewer layout the majority of the vertical space.
        main_layout.addLayout(viewer_layout, stretch=1)
        
        # Settings section
        settings_group = QGroupBox("Resource Settings")
        settings_layout = QGridLayout()
        
        # Remap resources checkbox (top left)
        self.remap_resources_checkbox = QCheckBox("Remap Resources")
        self.remap_resources_checkbox.setChecked(True)
        self.remap_resources_checkbox.setToolTip(
            "When enabled, applies Cameo's resource algorithm (distance-based tiering: "
            "ore→tiberium→blue→red→gold→gems). When disabled, resources pass through "
            "1-1 conversion only (RA Ore→Cameo Ore, RA Gems→Cameo Gems)."
        )
        self.remap_resources_checkbox.stateChanged.connect(self.on_remap_resources_changed)
        settings_layout.addWidget(self.remap_resources_checkbox, 0, 0)

        # Remove problematic actors checkbox (row 0, col 1)
        self.remove_actors_checkbox = QCheckBox("Remove Problematic Actors")
        self.remove_actors_checkbox.setChecked(True)
        self.remove_actors_checkbox.setToolTip(
            "When enabled (default), drops rock/stone/bush actors that render with "
            "incorrect colors in Cameo's RA_TEMPERAT tileset due to a palette mismatch "
            "(.des files rendered with ra_temperat.pal). Disable to keep them if you "
            "accept the visual artifacts."
        )
        self.remove_actors_checkbox.stateChanged.connect(self.on_setting_changed)
        settings_layout.addWidget(self.remove_actors_checkbox, 0, 1)
        
        # Reset button (top right)
        self.reset_settings_btn = QPushButton("Reset to Defaults")
        self.reset_settings_btn.clicked.connect(self.reset_resource_settings)
        settings_layout.addWidget(self.reset_settings_btn, 0, 2)
        
        # 1. Resource Richness (distance threshold knob)
        self._richness_label_widget = QLabel("Resource Richness:")
        settings_layout.addWidget(self._richness_label_widget, 1, 0)
        self.richness_slider = QSlider(Qt.Horizontal)
        self.richness_slider.setRange(500, 1500)  # 0.5 to 1.5 with .01 precision
        self.richness_slider.setValue(1000)  # 1.0 default
        self.richness_slider.setSingleStep(10)  # Snap to 0.01 increments (10/1000 = 0.01)
        self.richness_slider.setPageStep(50)  # Page step in 0.05 increments
        self.richness_slider.valueChanged.connect(self.update_richness_label)
        settings_layout.addWidget(self.richness_slider, 1, 1)
        self.richness_label = QLabel("1.00 (balanced)")
        settings_layout.addWidget(self.richness_label, 1, 2)
        
        # 2. Distribution Mode (balance/distance toggle)
        settings_layout.addWidget(QLabel("Distribution Mode:"), 2, 0)
        self.dist_button_group = QButtonGroup()
        self.balance_radio = QRadioButton("Balance")
        self.distance_radio = QRadioButton("Distance")
        self.even_radio = QRadioButton("Even")
        self.balance_radio.setChecked(True)
        self.dist_button_group.addButton(self.balance_radio)
        self.dist_button_group.addButton(self.distance_radio)
        self.dist_button_group.addButton(self.even_radio)
        dist_layout = QHBoxLayout()
        dist_layout.addWidget(self.balance_radio)
        dist_layout.addWidget(self.distance_radio)
        dist_layout.addWidget(self.even_radio)
        dist_layout.addStretch()
        settings_layout.addLayout(dist_layout, 2, 1, 1, 2)
        
        # 3. Balance Bias (balance threshold knob)
        self._bias_label_widget = QLabel("Balance Bias:")
        settings_layout.addWidget(self._bias_label_widget, 3, 0)
        self.balance_bias_slider = QSlider(Qt.Horizontal)
        self.balance_bias_slider.setRange(0, 100)  # 0.0 to 10.0
        self.balance_bias_slider.setValue(30)  # 3.0 default
        self.balance_bias_slider.setSingleStep(1)  # Snap to 0.1 increments (1/10 = 0.1)
        self.balance_bias_slider.setPageStep(5)  # Page step in 0.5 increments
        self.balance_bias_slider.valueChanged.connect(self.update_balance_bias_label)
        settings_layout.addWidget(self.balance_bias_slider, 3, 1)
        self.balance_bias_label = QLabel("3.0")
        settings_layout.addWidget(self.balance_bias_label, 3, 2)
        
        # 4. Home Radius (base spawn distance / proximity suppressor)
        self._radius_label_widget = QLabel("Home Radius:")
        settings_layout.addWidget(self._radius_label_widget, 4, 0)
        self.home_radius_slider = QSlider(Qt.Horizontal)
        self.home_radius_slider.setRange(0, 50)  # 0 to 50
        self.home_radius_slider.setValue(15)  # 15 default
        self.home_radius_slider.valueChanged.connect(self.update_home_radius_label)
        settings_layout.addWidget(self.home_radius_slider, 4, 1)
        self.home_radius_label = QLabel("15")
        settings_layout.addWidget(self.home_radius_label, 4, 2)
        
        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)

        # Convert buttons
        control_layout = QHBoxLayout()
        
        self.convert_map_btn = QPushButton("Convert Map")
        self.convert_map_btn.clicked.connect(self.convert_current_map)
        self.convert_map_btn.setEnabled(False)
        control_layout.addWidget(self.convert_map_btn)
        
        self.convert_all_btn = QPushButton("Convert All")
        self.convert_all_btn.clicked.connect(self.convert_all_maps)
        self.convert_all_btn.setEnabled(False)
        control_layout.addWidget(self.convert_all_btn)
        
        control_layout.addStretch()
        main_layout.addLayout(control_layout)
        
        # Log output
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(100)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)
        
        # Status bar with tooltips checkbox
        status_bar_layout = QHBoxLayout()
        status_bar_layout.setContentsMargins(0, 0, 0, 0)
        
        # Status message
        self.status_label = QLabel("Ready")
        status_bar_layout.addWidget(self.status_label)
        status_bar_layout.addStretch()
        
        # Tooltips checkbox
        self.tooltips_cb = QCheckBox("Enable Tooltips")
        self.tooltips_cb.setChecked(True)
        self.tooltips_cb.toggled.connect(self.toggle_tooltips)
        status_bar_layout.addWidget(self.tooltips_cb)
        
        # Add status bar layout to main layout
        main_layout.addLayout(status_bar_layout)
        
        # Timer for auto-refreshing preview on settings change
        self.preview_timer = QTimer()
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.refresh_preview)
        
        # Timer for debouncing navigation to prevent multiple preview requests
        self.navigation_debounce_timer = QTimer()
        self.navigation_debounce_timer.setSingleShot(True)
        self.navigation_debounce_timer.timeout.connect(self.refresh_preview)
        
        # Flag to prevent concurrent preview generation
        self.preview_in_progress = False
        
        # Connect settings changes to preview refresh and save
        self.richness_slider.valueChanged.connect(self.on_setting_changed)
        self.balance_radio.toggled.connect(self.on_setting_changed)
        self.distance_radio.toggled.connect(self.on_setting_changed)
        self.even_radio.toggled.connect(self.on_setting_changed)
        self.balance_radio.toggled.connect(self._update_settings_visibility)
        self.distance_radio.toggled.connect(self._update_settings_visibility)
        self.even_radio.toggled.connect(self._update_settings_visibility)
        self.balance_bias_slider.valueChanged.connect(self.on_setting_changed)
        self.home_radius_slider.valueChanged.connect(self.on_setting_changed)
        
        # Load saved settings (after signal connections are established)
        self.load_settings()

        # Apply initial settings-row visibility based on loaded/default mode
        self._update_settings_visibility()

        # Apply tooltips
        self.apply_tooltips()
        
    def select_incoming_dir(self):
        """Select incoming directory containing source maps."""
        folder = QFileDialog.getExistingDirectory(self, "Select Incoming Map Directory")
        if folder:
            self.incoming_dir = folder
            self.incoming_dir_label.setText(folder)
            self.incoming_dir_label.setStyleSheet("color: black;")
            self.settings.setValue("incoming_dir", folder)
            self.settings.sync()  # Immediately persist to disk
            self.load_map_files()
            self.update_convert_buttons()
            
    def select_outgoing_dir(self):
        """Select outgoing directory for converted maps."""
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.outgoing_dir = folder
            self.outgoing_dir_label.setText(folder)
            self.outgoing_dir_label.setStyleSheet("color: black;")
            self.settings.setValue("outgoing_dir", folder)
            self.settings.sync()  # Immediately persist to disk
            self.check_converted_maps()
            self.update_convert_buttons()
            
    def load_map_files(self):
        """Load all .oramap files from the incoming directory."""
        if not self.incoming_dir:
            return
            
        self.map_files = []
        for root, dirs, files in os.walk(self.incoming_dir):
            for file in files:
                if file.endswith('.oramap'):
                    self.map_files.append(os.path.join(root, file))
        
        self.map_files.sort()
        self.current_map_index = 0
        
        if self.map_files:
            self.log_text.append(f"Loaded {len(self.map_files)} map(s) from {self.incoming_dir}")
            self.update_navigation_buttons()
            self.update_convert_buttons()
            self.load_current_map()
        else:
            self.log_text.append(f"No .oramap files found in {self.incoming_dir}")
            self.map_viewer.setText("No .oramap files found in directory")
            self.current_map_label.setText("")
            
    def load_current_map(self):
        """Load and display the current map."""
        if not self.map_files or self.current_map_index >= len(self.map_files):
            return

        current_map = self.map_files[self.current_map_index]
        map_name = os.path.basename(current_map)

        # Reset paint overrides when the active map changes so edits from a
        # previous map do not leak into the current one.
        if self._active_paint_map != map_name:
            self._clear_paint_overrides()
            self._active_paint_map = map_name

        self.current_map_label.setText(map_name)
        self.update_status_indicator()

        # Clear current preview to prevent showing stale image
        self.current_preview_path = None
        self.map_viewer.setText("Loading preview...")
        
        # Cancel any existing navigation debounce timer
        self.navigation_debounce_timer.stop()
        
        # Cancel any existing preview worker
        if self.preview_worker:
            if self.preview_worker.isRunning():
                self.preview_worker.cleanup()
                self.preview_worker.terminate()
                self.preview_worker.wait()
            try:
                self.preview_worker.preview_ready.disconnect(self.display_preview)
                self.preview_worker.preview_failed.disconnect(self.preview_failed)
                self.preview_worker.log_output.disconnect(self.append_log)
            except Exception:
                pass
        
        # If preview is locked, show converted version immediately
        if self.preview_locked:
            self.preview_converted_map()
        else:
            # Start debounce timer to prevent multiple rapid requests
            self.navigation_debounce_timer.start(300)  # 300ms debounce
        
    def navigate_previous(self):
        """Navigate to the previous map."""
        try:
            if self.navigation_in_progress:
                return
            if self.current_map_index > 0:
                self.navigation_in_progress = True
                self.current_map_index -= 1
                self.load_current_map()
                self.update_navigation_buttons()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.navigation_in_progress = False
            
    def navigate_next(self):
        """Navigate to the next map."""
        try:
            if self.navigation_in_progress:
                return
            if self.current_map_index < len(self.map_files) - 1:
                self.navigation_in_progress = True
                self.current_map_index += 1
                self.load_current_map()
                self.update_navigation_buttons()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.navigation_in_progress = False
            
    def update_navigation_buttons(self):
        """Update navigation button states."""
        self.left_arrow.setEnabled(self.current_map_index > 0)
        self.right_arrow.setEnabled(self.current_map_index < len(self.map_files) - 1)
        
    def update_convert_buttons(self):
        """Update convert button states."""
        has_maps = len(self.map_files) > 0
        has_outgoing = bool(self.outgoing_dir)
        self.convert_map_btn.setEnabled(has_maps and has_outgoing)
        self.convert_all_btn.setEnabled(has_maps and has_outgoing)
        
    def update_status_indicator(self):
        """Update the status indicator for the current map."""
        if not self.map_files:
            self.status_indicator.setStyleSheet("""
                QLabel {
                    border-radius: 10px;
                    background-color: #ccc;
                }
            """)
            self.preview_converted_btn.setEnabled(False)
            return
            
        current_map = self.map_files[self.current_map_index]
        map_name = os.path.basename(current_map)
        
        if map_name in self.converted_maps:
            self.status_indicator.setStyleSheet("""
                QLabel {
                    border-radius: 10px;
                    background-color: #4CAF50;
                }
            """)
            self.preview_converted_btn.setEnabled(True)
        else:
            self.status_indicator.setStyleSheet("""
                QLabel {
                    border-radius: 10px;
                    background-color: #ccc;
                }
            """)
            self.preview_converted_btn.setEnabled(False)
            
    def check_converted_maps(self):
        """Check which maps have already been converted."""
        if not self.outgoing_dir or not self.map_files:
            return
            
        self.converted_maps = set()
        for map_file in self.map_files:
            map_name = os.path.basename(map_file)
            output_path = os.path.join(self.outgoing_dir, map_name)
            if os.path.exists(output_path):
                self.converted_maps.add(map_name)
        
        self.update_status_indicator()
    
    def update_resource_counts(self, resource_data):
        """Update the resource counts display based on converter output."""
        # resource_data should be a dict with resource types and counts
        # For now, this is a placeholder - would need to parse converter output
        if resource_data:
            for resource, count_label in self.resource_counts.items():
                count = resource_data.get(resource, 0)
                display_name = self.resource_display_names.get(resource, resource)
                count_label.setText(f"{display_name}: {count}")
        else:
            # Reset to zeros
            for resource, count_label in self.resource_counts.items():
                display_name = self.resource_display_names.get(resource, resource)
                count_label.setText(f"{display_name}: 0")
    
    def count_resources_from_map(self, map_path):
        """Count resources directly from the converted map.bin file.
        
        This avoids parsing converter output and reads the binary data directly.
        Returns a dict with resource type names and their cell counts.
        """
        import struct
        import zipfile
        
        resource_data = {
            "Ore": 0,
            "Tiberium": 0, 
            "BlueTiberium": 0,
            "RedTiberium": 0,
            "GoldTiberium": 0,
            "Gems": 0
        }
        
        # Cameo resource indices from converter
        CAMEO_RES_INDEX = {
            "Ore": 3,
            "Tiberium": 1,
            "BlueTiberium": 2,
            "RedTiberium": 5,
            "GoldTiberium": 6,
            "Gems": 4,
        }
        
        # Reverse mapping for counting
        IDX_TO_RESOURCE = {v: k for k, v in CAMEO_RES_INDEX.items()}
        
        try:
            with zipfile.ZipFile(map_path, 'r') as zf:
                # Read map.bin from the zip
                with zf.open('map.bin') as f:
                    # Read header to determine format
                    header = f.read(17)
                    if len(header) < 17:
                        return resource_data
                    
                    # Parse format byte (byte 0)
                    fmt = header[0]
                    
                    # Parse width and height (bytes 1-2 and 3-4)
                    width = struct.unpack('<H', header[1:3])[0]
                    height = struct.unpack('<H', header[3:5])[0]
                    
                    # Parse offsets based on format
                    if fmt == 1:
                        # Format 1: 5-byte header, tiles at offset 5, resources at 5 + W*H*3
                        tiles_offset = 5
                        resources_offset = 5 + width * height * 3
                    elif fmt == 2:
                        # Format 2: 17-byte header, offsets stored explicitly at bytes 5, 9, 13
                        tiles_offset = struct.unpack('<I', header[5:9])[0]
                        resources_offset = struct.unpack('<I', header[13:17])[0]
                    else:
                        return resource_data
                    
                    # Read resource data
                    f.seek(resources_offset)
                    resource_data_size = width * height * 2
                    resource_bytes = f.read(resource_data_size)
                    
                    # Count each resource type
                    for i in range(0, len(resource_bytes), 2):
                        res_type = resource_bytes[i]
                        if res_type in IDX_TO_RESOURCE:
                            resource_name = IDX_TO_RESOURCE[res_type]
                            resource_data[resource_name] += 1
                            
        except Exception as e:
            import traceback
            traceback.print_exc()
        
        return resource_data
        
    def get_current_settings(self):
        """Get current settings values."""
        if self.balance_radio.isChecked():
            distribution = "balance"
        elif self.distance_radio.isChecked():
            distribution = "distance"
        else:
            distribution = "even"
        return {
            'richness': self.richness_slider.value() / 1000.0,
            'distribution': distribution,
            'balance_bias': self.balance_bias_slider.value() / 10.0,
            'balance_home_radius': float(self.home_radius_slider.value()),
            'remap_resources': self.remap_resources_checkbox.isChecked(),
            'remove_actors': self.remove_actors_checkbox.isChecked(),
            'paint_overrides': dict(self._paint_overrides),        # field-paint overrides
            'cell_overrides': dict(self._paint_cell_overrides),    # cell-paint overrides
            'node_overrides':  dict(self._paint_node_overrides),   # node-paint overrides
            'density_overrides': dict(self._paint_density_overrides),  # cell-level density settings
            'field_density_overrides': dict(self._paint_field_density_overrides),  # field-level density settings
            'node_affects_field_tier': False,  # Node painting independent of field tier
        }
        
    def schedule_preview_refresh(self):
        """Schedule a preview refresh after settings change."""
        try:
            self.preview_refresh_pending = True
            # Stop and restart timer to ensure it fires with fresh delay
            self.preview_timer.stop()
            self.preview_timer.start(500)  # 500ms delay
        except Exception as e:
            import traceback
            traceback.print_exc()
        
    def refresh_preview(self):
        """Generate a preview for the current map with current settings."""
        try:
            # Prevent concurrent preview generation
            if self.preview_in_progress:
                if self.preview_worker and self.preview_worker.isRunning():
                    try:
                        self.preview_worker.cleanup()
                        self.preview_worker.terminate()
                        self.preview_worker.wait(1000)  # Wait up to 1 second
                    except Exception as e:
                        _logger.warning(f"Error terminating preview worker: {e}")
                self.preview_in_progress = False
            
            if not self.map_files or not self.converter_script:
                return
                
            current_map = self.map_files[self.current_map_index]
            
            # Set flag to prevent concurrent generation
            self.preview_in_progress = True
            
            # Cancel any existing preview worker and disconnect signals
            if self.preview_worker:
                if self.preview_worker.isRunning():
                    try:
                        self.preview_worker.cleanup()
                        self.preview_worker.terminate()
                        self.preview_worker.wait(1000)  # Wait up to 1 second
                    except Exception as e:
                        _logger.warning(f"Error terminating preview worker: {e}")
                # Disconnect old signals to prevent multiple handlers
                try:
                    self.preview_worker.preview_ready.disconnect(self.display_preview)
                    self.preview_worker.preview_failed.disconnect(self.preview_failed)
                    self.preview_worker.log_output.disconnect(self.append_log)
                    self.preview_worker.counts_ready.disconnect(self.on_preview_counts)
                except Exception:
                    pass  # Signals may already be disconnected
            
            # Start new preview worker
            try:
                self.preview_worker = PreviewWorker(
                    self.converter_script,
                    current_map,
                    self.outgoing_dir if self.outgoing_dir else "",
                    self.get_current_settings(),
                    parent=self
                )
                self.preview_worker.preview_ready.connect(self.display_preview)
                self.preview_worker.preview_failed.connect(self.preview_failed)
                self.preview_worker.log_output.connect(self.append_log)
                self.preview_worker.counts_ready.connect(self.on_preview_counts)
                self.preview_worker.start()
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.preview_in_progress = False
                return
            
            # Reset pending flag
            self.preview_refresh_pending = False
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.preview_refresh_pending = False
            self.preview_in_progress = False
        
    def on_preview_counts(self, counts, map_name):
        """Update resource counts from the in-process preview (matches its settings)."""
        if self.map_files and self.current_map_index < len(self.map_files):
            if map_name != os.path.basename(self.map_files[self.current_map_index]):
                return  # stale (counts for a different map)
        # Extract field metadata (for paint mode) and node metadata (for tooltips)
        if "__fields__" in counts:
            self._paint_field_cache = counts["__fields__"]
            counts = {k: v for k, v in counts.items() if k != "__fields__"}
        if "__nodes__" in counts:
            self._paint_node_cache = counts["__nodes__"]
            counts = {k: v for k, v in counts.items() if k != "__nodes__"}
        self.update_resource_counts(counts)

    def display_preview(self, preview_path, map_name):
        """Display the generated preview image.

        The displayed pixmap is scaled to a stable target size so the preview does
        not jump slightly larger/smaller each time it is refreshed. The target size
        updates on window resize.
        """
        # Clear the in-progress flag
        self.preview_in_progress = False

        # Verify this preview is for the current map (prevent stale images)
        if self.map_files and self.current_map_index < len(self.map_files):
            current_map_name = os.path.basename(self.map_files[self.current_map_index])
            if map_name != current_map_name:
                # This preview is for a different map, ignore it
                return

        # Save this as the source preview path (for restoration after viewing converted)
        self.source_preview_path = preview_path
        self.current_preview_path = preview_path
        pixmap = QPixmap(preview_path)
        if not pixmap.isNull():
            # Use a stable target size. Initialise from the current viewer size, then
            # reuse it for subsequent refreshes so the pixmap does not change size.
            if self._preview_display_size is None:
                self._preview_display_size = QSize(self.map_viewer.size())
            target_size = self._preview_display_size
            scaled_pixmap = pixmap.scaled(
                target_size,
                Qt.KeepAspectRatio,
                Qt.FastTransformation
            )
            self.map_viewer.setPixmap(scaled_pixmap)
        else:
            self.map_viewer.setText("Failed to load preview")

        # Resource counts arrive via the in-process preview's counts_ready signal
        # (on_preview_counts), so they always match the previewed settings exactly.

        # Reset navigation in progress flag
        self.navigation_in_progress = False
    
    def eventFilter(self, obj, event):
        """Event filter for mouse events on the map viewer."""
        try:
            if not hasattr(self, 'map_viewer'):
                return False
            
            # Paint mode: handle mouse move during drag (must come before hover logic)
            if (obj == self.map_viewer
                    and event.type() == QEvent.MouseMove
                    and self.paint_mode
                    and self._drag_origin is not None
                    and self._rubber_band):
                # Update rubber band
                current_pos = event.pos()
                self._rubber_band.setGeometry(QRect(self._drag_origin, current_pos).normalized())
                return True  # Consume the event
            
            if obj == self.map_viewer and event.type() == QEvent.MouseMove:
                # Guard against unsafe states
                if self.preview_in_progress:
                    return False
                
                if not self.current_preview_path:
                    return False
                
                # Get the mouse position relative to the map viewer
                viewer_pos = event.pos()
                
                # Start/restart the hover timer (1 second delay)
                self.last_hover_position = viewer_pos
                self.hover_timer.start(1000)  # 1 second delay
                
                # Hide any visible tooltip so it can be re-shown after the hover
                # delay when the cursor stops. This is much cheaper than recomputing
                # the tooltip text on every mouse move.
                QToolTip.hideText()
                # Don't handle the event - let it pass through normally
                return False

            # Paint mode: handle left mouse button clicks and drags on the preview
            if (obj == self.map_viewer
                    and event.type() == QEvent.MouseButtonPress
                    and event.button() == Qt.LeftButton
                    and self.paint_mode):
                # Start box-select drag
                self._drag_origin = event.pos()
                if self._rubber_band:
                    self._rubber_band.deleteLater()
                self._rubber_band = QRubberBand(QRubberBand.Rectangle, self.map_viewer)
                self._rubber_band.setGeometry(QRect(self._drag_origin, QSize()))
                self._rubber_band.show()
                return True  # Consume the event

            # Paint mode: handle mouse release to complete box-select
            if (obj == self.map_viewer
                    and event.type() == QEvent.MouseButtonRelease
                    and event.button() == Qt.LeftButton
                    and self.paint_mode
                    and self._drag_origin is not None):
                # Complete box-select
                if self._rubber_band:
                    self._rubber_band.hide()
                    self._rubber_band.deleteLater()
                    self._rubber_band = None
                
                drag_end = event.pos()
                selection_rect = QRect(self._drag_origin, drag_end).normalized()
                self._drag_origin = None
                
                # If the box is very small, treat as a single click
                if selection_rect.width() < 5 and selection_rect.height() < 5:
                    self._handle_paint_click(drag_end)
                else:
                    self._handle_paint_box(selection_rect)
                
                return True  # Consume the event

            # Legend entry events (hover highlight + click to select paint type)
            resource = obj.property("legend_resource") if hasattr(obj, "property") else None
            if resource and resource in getattr(self, "_legend_widgets", {}):
                if event.type() == QEvent.Enter and self.paint_mode:
                    self._on_legend_hover_enter(resource)
                    return False
                if event.type() == QEvent.Leave and self.paint_mode:
                    self._on_legend_hover_leave(resource)
                    return False
                if event.type() == QEvent.MouseButtonPress and self.paint_mode:
                    if event.button() == Qt.LeftButton:
                        self._on_legend_clicked(resource)
                        return True

            # Let all other events pass through normally
            return super().eventFilter(obj, event)
        except Exception as e:
            # Prevent crashes from event filter errors
            import traceback
            traceback.print_exc()
            return False  # Let event pass through even if there's an error
    
    def mouseMoveEvent(self, event):
        """Handle mouse move events for hover functionality."""
        try:
            # Guard against unsafe states
            if self.preview_in_progress:
                return  # Skip hover during preview generation
            
            if not self.current_preview_path:
                return  # Skip hover if no preview
            
            # Check if the mouse is over the map viewer
            if self.map_viewer.underMouse():
                # Get the mouse position relative to the map viewer
                viewer_pos = self.map_viewer.mapFrom(self, event.pos())
                
                # Start/restart the hover timer (1 second delay)
                self.last_hover_position = viewer_pos
                self.hover_timer.start(1000)  # 1 second delay
                
                # Hide any visible tooltip so it can be re-shown after the hover
                # delay when the cursor stops. This is much cheaper than recomputing
                # the tooltip text on every mouse move.
                QToolTip.hideText()
                
                # Debug: show that mouse move is being detected
                self.hover_status_label.setText(f"Hovering... (timer started)")
            else:
                # Mouse left the map viewer, cancel hover timer
                self.hover_timer.stop()
                self.last_hover_position = None
                self.hover_status_label.setText("Hover over preview for resource info")
            
            # Call parent class method
            super().mouseMoveEvent(event)
        except Exception as e:
            import traceback
            traceback.print_exc()
    
    def _density_level(self, density_value, tier):
        """Convert a raw density byte to a 1-5 level relative to the tier's max."""
        if density_value is None or tier is None:
            return "?"
        if density_value <= 0:
            return "0"
        max_density = self._tier_max_density.get(tier, 255)
        # Scale the density as a fraction of the tier's max density to 1-5.
        level = min(5, max(1, int(round((density_value / max_density) * 5))))
        return str(level)

    def _show_hover_tooltip(self, text):
        """Hide any existing tooltip and show a new one at the last hover position."""
        if not self.last_hover_position:
            return
        global_pos = self.map_viewer.mapToGlobal(self.last_hover_position)
        QToolTip.hideText()
        QToolTip.showText(global_pos, text, self.map_viewer)

    def _find_node_at_cell(self, col, row):
        """Return the node dict at (col, row), or None.

        Node coordinates from the YAML/actor parser may be floats, so we round
        to the nearest integer cell before comparing. Uses a small tolerance
        to handle coordinate precision issues.
        """
        import math
        if not self._paint_node_cache:
            return None
        TOL = 1.0  # cells: handle coordinate precision issues
        for node in self._paint_node_cache:
            if math.hypot(round(node["x"]) - col, round(node["y"]) - row) <= TOL:
                return node
        return None

    def show_hover_resource_type(self):
        """Show the resource type at the hovered position after 1-second delay.

        Uses the map cell under the cursor, not pixel color, so node markers and
        field cells are identified correctly regardless of brightened marker colors.
        """
        try:
            # Guard against running during unsafe states
            if not self.hover_enabled or not self.last_hover_position:
                return
            if not self.current_preview_path:
                return
            if self.preview_in_progress:
                return
            if not os.path.exists(self.current_preview_path):
                return
            if not self._paint_field_cache:
                return

            cell = self._pixel_to_map_cell(self.last_hover_position)
            if cell is None:
                return
            col, row = cell

            # Check for an exact node match first.
            node = self._find_node_at_cell(col, row)
            if node:
                node_key = f"{node['x']},{node['y']}"
                node_res = self._paint_node_overrides.get(node_key, node.get("resource", "Unknown"))
                node_display = self.resource_node_names.get(node_res, node_res)
                tooltip_text = node_display
                self._show_hover_tooltip(tooltip_text)
                return

            # Otherwise check for an exact field cell.
            import math
            CELL_TOL = 1.0  # cells: handle coordinate precision issues ("screendoor effect")
            for f in self._paint_field_cache:
                H = f.get("map_height")
                if H is None:
                    continue
                cell_index = col * H + row
                if cell_index in f.get("cells", set()):
                    cx, cy = f["center"]
                    field_key = "%d,%d" % (round(cx), round(cy))
                    tier = self._paint_overrides.get(field_key, f["tier"])
                    # Apply any cell override.
                    cell_key = f"{col},{row}"
                    tier = self._paint_cell_overrides.get(cell_key, tier)
                    display = self.resource_field_names.get(tier, tier)
                    # Debug: log if tier not found in dictionary
                    if display == tier and tier not in self.resource_field_names:
                        self.append_log(f"Tooltip debug: tier '{tier}' not in resource_field_names dict")
                    # Report density level scaled by the tier's max density.
                    density = self._effective_cell_density(col, row, f, tier)
                    level = self._density_level(density, tier)
                    tooltip_text = f"{display} (Level {level})"
                    self._show_hover_tooltip(tooltip_text)
                    return

            # Fallback: check if near a field cell (handles coordinate precision issues)
            for f in self._paint_field_cache:
                H = f.get("map_height")
                if H is None:
                    continue
                for cell_index in f.get("cells", set()):
                    p_col = cell_index // H
                    p_row = cell_index % H
                    if math.hypot(p_col - col, p_row - row) <= CELL_TOL:
                        cx, cy = f["center"]
                        field_key = "%d,%d" % (round(cx), round(cy))
                        tier = self._paint_overrides.get(field_key, f["tier"])
                        # Apply any cell override.
                        cell_key = f"{p_col},{p_row}"
                        tier = self._paint_cell_overrides.get(cell_key, tier)
                        display = self.resource_field_names.get(tier, tier)
                        # Report density level scaled by the tier's max density.
                        density = self._effective_cell_density(p_col, p_row, f, tier)
                        level = self._density_level(density, tier)
                        tooltip_text = f"{display} (Level {level})"
                        self._show_hover_tooltip(tooltip_text)
                        return

            # Not a resource.
            self._show_hover_tooltip("Background area")

        except Exception as e:
            # Prevent crashes from hover processing errors
            import traceback
            traceback.print_exc()
            
    def preview_failed(self, error_message, map_name):
        """Handle preview generation failure."""
        # Clear the in-progress flag
        self.preview_in_progress = False
        
        # Verify this failure is for the current map (prevent stale error messages)
        if self.map_files and self.current_map_index < len(self.map_files):
            current_map_name = os.path.basename(self.map_files[self.current_map_index])
            if map_name != current_map_name:
                # This failure is for a different map, ignore it
                return
        
        self.map_viewer.setText(f"Preview failed: {error_message}")
        self.append_log(f"Preview failed for {map_name}: {error_message}")
        
        # Reset navigation in progress flag
        self.navigation_in_progress = False
        
    def restore_current_preview(self):
        """Restore the current preview when hold-to-preview is released."""
        # Don't restore if preview is locked
        if self.preview_locked:
            return

        # Restore the source preview if we have it saved
        if hasattr(self, 'source_preview_path') and self.source_preview_path and os.path.exists(self.source_preview_path):
            self.display_preview(self.source_preview_path, os.path.basename(self.map_files[self.current_map_index]))
            self.current_preview_path = self.source_preview_path
        elif self.current_preview_path and os.path.exists(self.current_preview_path):
            self.display_preview(self.current_preview_path, os.path.basename(self.map_files[self.current_map_index]))
        else:
            self.refresh_preview()
    
    def toggle_preview_lock(self, position):
        """Toggle the preview lock state (right-click)."""
        self.preview_locked = not self.preview_locked

        if self.preview_locked:
            self.preview_converted_btn.setText("Preview\nLocked")
            self.preview_converted_btn.setStyleSheet("background-color: #4CAF50; color: white;")
            self.append_log("Preview locked - showing converted version")
            # Show converted preview immediately
            self.preview_converted_map()
        else:
            self.preview_converted_btn.setText("Preview\nConverted")
            self.preview_converted_btn.setStyleSheet("")
            self.append_log("Preview unlocked - showing live preview")
            # Restore source preview
            if hasattr(self, 'source_preview_path') and self.source_preview_path and os.path.exists(self.source_preview_path):
                self.display_preview(self.source_preview_path, os.path.basename(self.map_files[self.current_map_index]))
                self.current_preview_path = self.source_preview_path
            else:
                self.refresh_preview()
            
    def preview_converted_map(self):
        """Preview the already-converted version of the current map.

        The baked map.png is 1px per cell, which leaves no room for marker borders.
        We upscale by 4 (matching the primary preview) and re-run overlay_actors
        so spawns and nodes get the same colored fill + black border as the live preview.
        """
        if not self.outgoing_dir or not self.map_files:
            return

        current_map = self.map_files[self.current_map_index]
        map_name = os.path.basename(current_map)
        # Normalize the path to handle mixed slashes
        output_path = os.path.normpath(os.path.join(self.outgoing_dir, map_name))

        # Check if the converted file exists
        if not os.path.exists(output_path):
            self.append_log(f"Converted map not found: {output_path}")
            return

        # Save the original source preview path before switching
        if not hasattr(self, 'source_preview_path'):
            self.source_preview_path = self.current_preview_path

        try:
            import zipfile
            import io
            from PIL import Image
            import minimap_render as _mmr

            with zipfile.ZipFile(output_path, 'r') as zf:
                if 'map.png' not in zf.namelist() or 'map.yaml' not in zf.namelist():
                    if 'map.png' not in zf.namelist():
                        self.append_log(f"No map.png found in converted .oramap for {map_name}")
                    else:
                        self.append_log(f"No map.yaml found in converted .oramap for {map_name}")
                    return

                # Load map.png directly into a PIL Image
                png_data = zf.read('map.png')
                img = Image.open(io.BytesIO(png_data)).convert('RGB')

                # Read map.yaml for bounds and actor locations
                yaml_text = zf.read('map.yaml').decode('utf-8', errors='replace')
                bounds = _mmr.parse_bounds(yaml_text)
                if bounds is None:
                    bounds = (0, 0, img.size[0], img.size[1])
                actors = _mmr.parse_actor_locations(yaml_text)

                # Upscale 1px/cell -> 4px/cell (identical to primary preview scale)
                PREVIEW_SCALE = 4
                if PREVIEW_SCALE > 1:
                    img = img.resize(
                        (img.size[0] * PREVIEW_SCALE, img.size[1] * PREVIEW_SCALE),
                        Image.NEAREST)

                # Build node_type_map from current node overrides + any known node assignments
                node_type_map = {}
                node_overrides = self.settings.get("node_overrides") or {}
                for node_key, tier in node_overrides.items():
                    col, row = map(int, node_key.split(','))
                    node_type_map[(col, row)] = tier
                # Try to enrich with recently-assigned node metadata from the primary preview
                try:
                    if getattr(self, 'resource_counts', None) and self.resource_counts.get('__nodes__'):
                        for node in self.resource_counts['__nodes__']:
                            key = (node['x'], node['y'])
                            if key not in node_type_map:
                                node_type_map[key] = node['resource']
                except Exception:
                    pass

                # Overlay spawns/nodes with borders at the upscaled resolution
                _mmr.overlay_actors(img, actors, bounds, PREVIEW_SCALE,
                                    draw_spawns=True, draw_nodes=True,
                                    node_type_map=node_type_map)

                # Save to a temp file and display
                temp_preview = os.path.join(self.temp_dir, f"{os.path.splitext(map_name)[0]}_converted_preview.png")
                img.save(temp_preview)

                pixmap = QPixmap(temp_preview)
                if not pixmap.isNull():
                    # Use the same stable target size as the primary preview so
                    # the converted preview appears at the identical size and the
                    # hover coordinate mapping stays consistent.
                    if self._preview_display_size is None:
                        self._preview_display_size = QSize(self.map_viewer.size())
                    target_size = self._preview_display_size
                    scaled_pixmap = pixmap.scaled(
                        target_size,
                        Qt.KeepAspectRatio,
                        Qt.FastTransformation
                    )
                    self.map_viewer.setPixmap(scaled_pixmap)
                    self.current_preview_path = temp_preview
                    self.append_log(f"Showing converted preview for {map_name}")
                else:
                    self.append_log(f"Failed to load converted preview for {map_name}")
        except Exception as e:
            self.append_log(f"Error rendering converted preview for {map_name}: {e}")
            import traceback
            traceback.print_exc()
            
    def convert_current_map(self):
        """Convert the current map."""
        if not self.map_files or not self.outgoing_dir:
            return
            
        current_map = self.map_files[self.current_map_index]
        
        self.conversion_worker = ConversionWorker(
            self.converter_script,
            current_map,
            self.outgoing_dir,
            self.get_current_settings(),
            parent=self
        )
        self.conversion_worker.conversion_complete.connect(self.conversion_finished)
        self.conversion_worker.log_output.connect(self.append_log)
        self.conversion_worker.progress_updated.connect(self.update_progress)
        self.conversion_worker.start()
        
    def convert_all_maps(self):
        """Convert all maps in the incoming directory."""
        if not self.map_files or not self.outgoing_dir:
            return
        
        self.log_text.append("Starting batch conversion...")
        self.convert_all_btn.setEnabled(False)
        self.convert_map_btn.setEnabled(False)
        
        # Start batch conversion in a separate thread
        self.batch_worker = BatchConversionWorker(
            self.converter_script,
            self.map_files,
            self.outgoing_dir,
            self.get_current_settings(),
            parent=self
        )
        self.batch_worker.batch_progress.connect(self.batch_conversion_progress)
        self.batch_worker.batch_complete.connect(self.batch_conversion_complete)
        self.batch_worker.log_output.connect(self.append_log)
        self.batch_worker.start()
        
    def conversion_finished(self, success, message, map_name):
        """Handle single map conversion completion."""
        if success:
            self.converted_maps.add(map_name)
            self.update_status_indicator()
            self.append_log(f"✓ {message}")
        else:
            self.append_log(f"✗ {message}")
            
    def batch_conversion_progress(self, current, total, map_name):
        """Handle batch conversion progress updates."""
        self.status_label.setText(f"Converting [{current}/{total}]: {map_name}")
        
    def batch_conversion_complete(self, success_count):
        """Handle batch conversion completion."""
        self.convert_all_btn.setEnabled(True)
        self.convert_map_btn.setEnabled(True)
        self.status_label.setText(f"Batch conversion complete: {success_count}/{len(self.map_files)} successful")
        self.check_converted_maps()
        self.append_log(f"Batch conversion completed: {success_count}/{len(self.map_files)} maps converted successfully")
        
    def update_progress(self, message, map_name):
        """Update progress message."""
        self.status_label.setText(message)
        
    def append_log(self, message):
        """Append log message to the log display."""
        self.log_text.append(message)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
        # Also log to the ConverterLogger system (INFO level for user-visible messages)
        _logger.info(message)
        
    # Settings label update methods
    def update_richness_label(self):
        try:
            # Snap to 0.01 increments to match display precision
            raw_value = self.richness_slider.value()
            snapped_value = round(raw_value / 10) * 10  # Snap to nearest 10
            if snapped_value != raw_value:
                self.richness_slider.setValue(snapped_value)  # Update slider to snapped value
            value = snapped_value / 1000.0
            if value < 0.8:
                text = f"{value:.2f} (ore-rich)"
            elif value > 1.2:
                text = f"{value:.2f} (gem-rich)"
            else:
                text = f"{value:.2f} (balanced)"
            self.richness_label.setText(text)
        except Exception as e:
            import traceback
            traceback.print_exc()
        
    def update_balance_bias_label(self):
        value = self.balance_bias_slider.value() / 10.0
        self.balance_bias_label.setText(f"{value:.1f}")
        
    def update_home_radius_label(self):
        value = self.home_radius_slider.value()
        self.home_radius_label.setText(f"{value}")
        
    def load_settings(self):
        """Load saved application settings."""
        # Block signals during settings loading to prevent cascading
        self.richness_slider.blockSignals(True)
        self.balance_radio.blockSignals(True)
        self.distance_radio.blockSignals(True)
        self.even_radio.blockSignals(True)
        self.balance_bias_slider.blockSignals(True)
        self.home_radius_slider.blockSignals(True)
        self.remap_resources_checkbox.blockSignals(True)
        self.remove_actors_checkbox.blockSignals(True)
        self.tooltips_cb.blockSignals(True)
        
        try:
            # Load directories
            incoming_dir = self.settings.value("incoming_dir", "")
            if incoming_dir and os.path.exists(incoming_dir):
                self.incoming_dir = incoming_dir
                self.incoming_dir_label.setText(incoming_dir)
                self.incoming_dir_label.setStyleSheet("color: black;")
                self.load_map_files()
            
            outgoing_dir = self.settings.value("outgoing_dir", "")
            if outgoing_dir and os.path.exists(outgoing_dir):
                self.outgoing_dir = outgoing_dir
                self.outgoing_dir_label.setText(outgoing_dir)
                self.outgoing_dir_label.setStyleSheet("color: black;")
                self.check_converted_maps()
            
            # Load resource settings
            richness = self.settings.value("richness", 1000, type=int)
            self.richness_slider.setValue(richness)
            
            distribution = self.settings.value("distribution", "balance", type=str)
            if distribution == "balance":
                self.balance_radio.setChecked(True)
            elif distribution == "even":
                self.even_radio.setChecked(True)
            else:
                self.distance_radio.setChecked(True)
            
            balance_bias = self.settings.value("balance_bias", 30, type=int)
            self.balance_bias_slider.setValue(balance_bias)
            
            home_radius = self.settings.value("home_radius", 15, type=int)
            self.home_radius_slider.setValue(home_radius)
            
            remap_resources = self.settings.value("remap_resources", True, type=bool)
            self.remap_resources_checkbox.setChecked(remap_resources)

            remove_actors = self.settings.value("remove_actors", True, type=bool)
            self.remove_actors_checkbox.setChecked(remove_actors)
            
            # Load tooltips setting
            tooltips_enabled = self.settings.value("tooltips_enabled", True, type=bool)
            self.tooltips_cb.setChecked(tooltips_enabled)
            self.tooltips_enabled = tooltips_enabled
            
            self.update_convert_buttons()
        finally:
            # Unblock signals after settings loading
            self.richness_slider.blockSignals(False)
            self.balance_radio.blockSignals(False)
            self.distance_radio.blockSignals(False)
            self.even_radio.blockSignals(False)
            self.balance_bias_slider.blockSignals(False)
            self.home_radius_slider.blockSignals(False)
            self.remap_resources_checkbox.blockSignals(False)
            self.remove_actors_checkbox.blockSignals(False)
            self.tooltips_cb.blockSignals(False)
        
    def save_settings(self):
        """Save current application settings."""
        try:
            self.settings.setValue("incoming_dir", self.incoming_dir)
            self.settings.setValue("outgoing_dir", self.outgoing_dir)
            self.settings.setValue("richness", self.richness_slider.value())
            if self.balance_radio.isChecked():
                distribution = "balance"
            elif self.distance_radio.isChecked():
                distribution = "distance"
            else:
                distribution = "even"
            self.settings.setValue("distribution", distribution)
            self.settings.setValue("balance_bias", self.balance_bias_slider.value())
            self.settings.setValue("home_radius", self.home_radius_slider.value())
            self.settings.setValue("remap_resources", self.remap_resources_checkbox.isChecked())
            self.settings.setValue("remove_actors", self.remove_actors_checkbox.isChecked())
            self.settings.setValue("tooltips_enabled", self.tooltips_cb.isChecked())
            self.settings.sync()
        except Exception as e:
            import traceback
            traceback.print_exc()
        
    def reset_resource_settings(self):
        """Reset resource settings to default values."""
        self.richness_slider.setValue(1000)  # 1.0
        self.balance_radio.setChecked(True)  # Default distribution = balance
        self.balance_bias_slider.setValue(30)  # 3.0
        self.home_radius_slider.setValue(15)  # 15
        self.remap_resources_checkbox.setChecked(True)  # Default ON
        self.remove_actors_checkbox.setChecked(True)  # Default ON (drop rocks)
        self.save_settings()
        self.append_log("Resource settings reset to defaults")
        
    def _rebuild_presets_menu(self):
        """Rebuild the Presets menu contents just before it opens."""
        self.presets_menu.clear()
        # Save action
        save_action = QAction("Save Preset…", self)
        save_action.setToolTip("Save the current resource settings as a named preset")
        save_action.triggered.connect(self.save_current_as_preset)
        self.presets_menu.addAction(save_action)
        self.presets_menu.addSeparator()
        # Saved presets as individual actions
        presets = self._load_presets()
        if presets:
            for name in sorted(presets.keys()):
                action = QAction(name, self)
                action.setToolTip(self._preset_summary(presets[name]))
                action.triggered.connect(lambda checked=False, n=name: self._load_preset_by_name(n))
                self.presets_menu.addAction(action)
            self.presets_menu.addSeparator()
            # Delete submenu
            delete_menu = self.presets_menu.addMenu("Delete Preset")
            for name in sorted(presets.keys()):
                del_action = QAction(name, self)
                del_action.triggered.connect(lambda checked=False, n=name: self._delete_preset_by_name(n))
                delete_menu.addAction(del_action)
        else:
            no_presets = QAction("(no saved presets)", self)
            no_presets.setEnabled(False)
            self.presets_menu.addAction(no_presets)

    def _preset_summary(self, p):
        """One-line tooltip summary of a preset dict."""
        dist = p.get("distribution", "balance")
        rich = p.get("richness", 1.0)
        return "richness=%.2f  distribution=%s  bias=%s  home-r=%s" % (
            rich, dist, p.get("balance_bias", 3.0), p.get("balance_home_radius", 15))

    def _load_preset_by_name(self, name):
        """Load a preset by name (called from menu action)."""
        presets = self._load_presets()
        if name not in presets:
            self.append_log(f"Preset not found: {name}")
            return
        p = presets[name]
        self.richness_slider.blockSignals(True)
        self.balance_radio.blockSignals(True)
        self.distance_radio.blockSignals(True)
        self.even_radio.blockSignals(True)
        self.balance_bias_slider.blockSignals(True)
        self.home_radius_slider.blockSignals(True)
        self.remap_resources_checkbox.blockSignals(True)
        self.remove_actors_checkbox.blockSignals(True)
        try:
            if "richness" in p:
                self.richness_slider.setValue(int(round(p["richness"] * 1000)))
                self.update_richness_label()
            dist = p.get("distribution", "balance")
            if dist == "even":
                self.even_radio.setChecked(True)
            elif dist == "distance":
                self.distance_radio.setChecked(True)
            else:
                self.balance_radio.setChecked(True)
            if "balance_bias" in p:
                self.balance_bias_slider.setValue(int(round(p["balance_bias"] * 10)))
                self.update_balance_bias_label()
            if "balance_home_radius" in p:
                self.home_radius_slider.setValue(int(p["balance_home_radius"]))
                self.update_home_radius_label()
            if "remap_resources" in p:
                self.remap_resources_checkbox.setChecked(bool(p["remap_resources"]))
            if "remove_actors" in p:
                self.remove_actors_checkbox.setChecked(bool(p["remove_actors"]))
        finally:
            self.richness_slider.blockSignals(False)
            self.balance_radio.blockSignals(False)
            self.distance_radio.blockSignals(False)
            self.even_radio.blockSignals(False)
            self.balance_bias_slider.blockSignals(False)
            self.home_radius_slider.blockSignals(False)
            self.remap_resources_checkbox.blockSignals(False)
            self.remove_actors_checkbox.blockSignals(False)
        self.save_settings()
        self.schedule_preview_refresh()
        self.append_log(f"Preset loaded: {name}")

    def _delete_preset_by_name(self, name):
        """Delete a preset by name with confirmation."""
        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Delete preset '{name}'?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        presets = self._load_presets()
        if name in presets:
            del presets[name]
            self._save_presets(presets)
        self.append_log(f"Preset deleted: {name}")

    # ------------------------------------------------------------------
    # Preset management
    # ------------------------------------------------------------------

    def _presets_path(self):
        """Return path to presets.json (next to settings.json)."""
        return os.path.join(os.path.dirname(self.settings.settings_file), "presets.json")

    def _load_presets(self):
        """Load and return the presets dict from disk (empty dict if missing/corrupt)."""
        path = self._presets_path()
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            _logger.warning(f"Failed to load presets: {e}")
        return {}

    def _save_presets(self, presets):
        """Persist the presets dict to disk."""
        path = self._presets_path()
        try:
            with open(path, "w") as f:
                json.dump(presets, f, indent=2)
        except Exception as e:
            _logger.warning(f"Failed to save presets: {e}")

    def _refresh_preset_combo(self):
        """No-op stub — presets are now managed via the Presets menu in the menu bar."""
        pass

    def save_current_as_preset(self):
        """Prompt for a name and save current settings as a preset."""
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        presets = self._load_presets()
        if name in presets:
            reply = QMessageBox.question(
                self, "Overwrite Preset",
                f"Preset '{name}' already exists. Overwrite?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        if self.balance_radio.isChecked():
            distribution = "balance"
        elif self.distance_radio.isChecked():
            distribution = "distance"
        else:
            distribution = "even"
        presets[name] = {
            "richness": self.richness_slider.value() / 1000.0,
            "distribution": distribution,
            "balance_bias": self.balance_bias_slider.value() / 10.0,
            "balance_home_radius": float(self.home_radius_slider.value()),
            "remap_resources": self.remap_resources_checkbox.isChecked(),
            "remove_actors": self.remove_actors_checkbox.isChecked(),
        }
        self._save_presets(presets)
        self.append_log(f"Preset saved: {name}")

    def load_selected_preset(self):
        """Stub kept for compatibility — use _load_preset_by_name directly."""
        pass

    def delete_selected_preset(self):
        """Stub kept for compatibility — use _delete_preset_by_name directly."""
        pass

    # ------------------------------------------------------------------
    # Hand-paint mode
    # ------------------------------------------------------------------

    def _clear_paint_overrides(self):
        """Reset all paint override state. Called when the active map changes."""
        self._paint_overrides.clear()
        self._paint_cell_overrides.clear()
        self._paint_node_overrides.clear()
        self._paint_density_overrides.clear()
        self._paint_field_density_overrides.clear()
        self._paint_undo_stack.clear()
        self._paint_redo_stack.clear()
        self._paint_field_cache.clear()
        self._paint_node_cache.clear()
        self._active_paint_map = None
        self._update_paint_buttons()

    def on_paint_mode_toggled(self, checked):
        """Enable/disable paint mode and update button label + legend state."""
        self.paint_mode = checked
        # Update legend panel button (created in init_ui inside the left panel)
        if hasattr(self, "paint_mode_btn"):
            self.paint_mode_btn.blockSignals(True)
            self.paint_mode_btn.setChecked(checked)
            self.paint_mode_btn.blockSignals(False)
        self._update_legend_paint_state(checked)
        if checked:
            self.map_viewer.setCursor(Qt.CrossCursor)
            self.append_log("Paint mode ON — click a legend entry or a resource field in the preview to paint.")
        else:
            self.map_viewer.setCursor(Qt.ArrowCursor)
            self.append_log("Paint mode OFF.")

    def _update_legend_paint_state(self, active):
        """Update legend item visual state when paint mode is toggled."""
        for resource, widgets in self._legend_widgets.items():
            item_widget = widgets.get("item_widget")
            if item_widget is None:
                continue
            if active:
                # Highlight with hover-ready cursor and paintable appearance
                item_widget.setCursor(Qt.PointingHandCursor)
                item_widget.setToolTip(
                    f"Click to set paint type to {self.resource_display_names.get(resource, resource)}\n"
                    "(Paint mode is ON — click resource fields on the preview map to paint them)"
                )
            else:
                item_widget.setCursor(Qt.ArrowCursor)
                item_widget.setToolTip("")
            # Update highlight border to show selected paint type
            selected = getattr(self, "_paint_type", "Ore")
            color = self._legend_colors.get(resource, "#666")
            if active and resource == selected:
                item_widget.setStyleSheet(
                    f"QWidget {{ border: 2px solid white; border-radius: 3px; "
                    f"background-color: {color}22; }}"
                )
            else:
                item_widget.setStyleSheet("")

    def _on_legend_hover_enter(self, resource):
        """Highlight a legend entry when hovered in paint mode."""
        widgets = self._legend_widgets.get(resource, {})
        item_widget = widgets.get("item_widget")
        if item_widget:
            color = self._legend_colors.get(resource, "#666")
            item_widget.setStyleSheet(
                f"QWidget {{ background-color: {color}44; border: 1px solid {color}; border-radius: 3px; }}"
            )

    def _on_legend_hover_leave(self, resource):
        """Remove hover highlight; restore selected-type highlight if applicable."""
        widgets = self._legend_widgets.get(resource, {})
        item_widget = widgets.get("item_widget")
        if item_widget:
            if resource == getattr(self, "_paint_type", "Ore"):
                color = self._legend_colors.get(resource, "#666")
                item_widget.setStyleSheet(
                    f"QWidget {{ border: 2px solid white; border-radius: 3px; "
                    f"background-color: {color}22; }}"
                )
            else:
                item_widget.setStyleSheet("")

    def _on_legend_clicked(self, resource):
        """Select this resource as the active paint type."""
        self._paint_type = resource
        # Refresh all legend item borders to show new selection
        self._update_legend_paint_state(True)
        display = self.resource_display_names.get(resource, resource)
        self.append_log(f"Paint type set to: {display}")

    def _pixel_to_map_cell(self, viewer_pos):
        """Translate a pixel position in the map_viewer widget to (col, row) map cell.

        Returns (col, row) or None if the click is outside the image area.
        The preview image is rendered at scale=4 (4 px per cell).  The QLabel
        scales the pixmap to fit while preserving aspect ratio; we must undo
        that scaling to recover the original image coordinates, then divide by 4
        for the map cell.
        """
        if not self.current_preview_path:
            return None
        from PyQt5.QtGui import QImage
        image = QImage(self.current_preview_path)
        if image.isNull():
            return None
        pixmap = self.map_viewer.pixmap()
        if pixmap is None:
            return None
        viewer_size = self.map_viewer.size()
        pixmap_size = pixmap.size()
        image_size = image.size()
        # Offset of pixmap inside the (centre-aligned) label
        px_off_x = (viewer_size.width()  - pixmap_size.width())  / 2
        px_off_y = (viewer_size.height() - pixmap_size.height()) / 2
        # Position within pixmap
        rel_x = viewer_pos.x() - px_off_x
        rel_y = viewer_pos.y() - px_off_y
        # Clamp to the displayed pixmap area.
        rel_x = max(0, min(rel_x, pixmap_size.width() - 1))
        rel_y = max(0, min(rel_y, pixmap_size.height() - 1))
        # Scale back to original image coordinates
        img_x = rel_x * image_size.width()  / pixmap_size.width()
        img_y = rel_y * image_size.height() / pixmap_size.height()
        # Convert to cell coordinates: divide by SCALE first, then round.
        # This avoids off-by-one errors from rounding pixels before scaling.
        SCALE = 4
        col = int(round(img_x / SCALE))
        row = int(round(img_y / SCALE))
        # Clamp to valid map bounds.
        max_col = image_size.width() // SCALE
        max_row = image_size.height() // SCALE
        col = max(0, min(col, max_col - 1))
        row = max(0, min(row, max_row - 1))
        return col, row

    def _find_field_for_cell(self, col, row):
        """Return the field key and current tier for the cell at (col, row).

        Exact match first: a field whose cell set contains (col, row).  Only if the
        cell is not part of any field do we fall back to the nearest field center.
        Returns (field_key_str, current_tier) or (None, None).
        """
        if not self._paint_field_cache:
            return None, None
        # Exact membership check using the cached map height per field.
        for f in self._paint_field_cache:
            H = f.get("map_height")
            if H is None:
                continue
            cell_index = col * H + row
            if cell_index in f.get("cells", set()):
                cx, cy = f["center"]
                key = "%d,%d" % (round(cx), round(cy))
                tier = self._paint_overrides.get(key, f["tier"])
                return key, tier
        # Fallback: nearest field center (handles clicks near but not inside a field).
        import math
        best_fid = None
        best_d = float("inf")
        for fid, f in enumerate(self._paint_field_cache):
            cx, cy = f["center"]
            d = math.hypot(col - cx, row - cy)
            if d < best_d:
                best_d = d
                best_fid = fid
        if best_fid is None:
            return None, None
        f = self._paint_field_cache[best_fid]
        cx, cy = f["center"]
        key = "%d,%d" % (round(cx), round(cy))
        tier = self._paint_overrides.get(key, f["tier"])
        return key, tier

    def _tier_for_key(self, key):
        """Return the current tier for a field key: override if set, else algorithmic."""
        if key in self._paint_overrides:
            return self._paint_overrides[key]
        for f in self._paint_field_cache:
            cx, cy = f["center"]
            if "%d,%d" % (round(cx), round(cy)) == key:
                return f.get("_paint_tier", f["tier"])
        return "Ore"  # fallback

    def _cell_count_for_key(self, key):
        """Return the cell count for a field identified by its key string, or 0 if unknown."""
        for f in self._paint_field_cache:
            cx, cy = f["center"]
            if "%d,%d" % (round(cx), round(cy)) == key:
                return f.get("cell_count", len(f.get("cells", [])))
        return 0

    def _on_paint_mirror_toggled(self, checked):
        """Update mirror-paint state when the toggle button is clicked."""
        self._paint_mirror = checked
        self.append_log(f"Symmetrical Paint Mode {'ON' if checked else 'OFF'}.")
    
    def _on_density_changed(self, index):
        """Update density setting when dropdown selection changes."""
        density = self.paint_density_combo.itemText(index)
        self._paint_density = density
        self.append_log(f"Paint density set to: {density}")
    
    def _density_setting_to_value(self, resource_type, density_setting):
        """Resolve a density setting to a numeric byte for display/preview.

        Args:
            resource_type: The resource type (e.g., "Ore", "Tiberium", etc.)
            density_setting: The density setting (None, "Replace", "Random",
                or numeric level "1"-"5" / int)

        Returns:
            The density value (0-255) or None for "Replace" / invalid settings.
        """
        if density_setting is None or density_setting == "Replace":
            return None
        max_density = self._tier_max_density.get(resource_type, 40)
        if density_setting == "Random":
            import random
            level = random.randint(1, 5)
            return max(1, (max_density * level) // 5)
        try:
            level = int(density_setting)
            if 1 <= level <= 5:
                return max(1, (max_density * level) // 5)
        except (ValueError, TypeError):
            pass
        return max_density

    def _current_cell_density(self, col, row):
        """Return the currently effective stored density setting for a cell, or None.

        Looks at cell-level override first, then the field-level override for the
        field containing this cell. This is the raw setting (None, "Random",
        int, or "Replace"), not a resolved numeric density.
        """
        cell_key = f"{col},{row}"
        density = self._paint_density_overrides.get(cell_key)
        if density is not None:
            return density
        for f in self._paint_field_cache:
            H = f.get("map_height")
            if H is None:
                continue
            cell_index = col * H + row
            if cell_index in f.get("cells", set()):
                cx, cy = f["center"]
                field_key = "%d,%d" % (round(cx), round(cy))
                field_density = self._paint_field_density_overrides.get(field_key)
                if field_density is not None:
                    return field_density
                return None
        return None

    def _effective_cell_density(self, col, row, field=None, tier=None):
        """Return the density byte to report for a cell, considering overrides.

        Order: cell density override, field density override, field density dict.
        String settings like "Random" are resolved to a numeric value per call.
        """
        cell_key = f"{col},{row}"
        setting = self._paint_density_overrides.get(cell_key)
        if setting is not None:
            return self._density_setting_to_value(tier, setting) if tier is not None else setting
        if field is not None:
            cx, cy = field["center"]
            field_key = "%d,%d" % (round(cx), round(cy))
            field_setting = self._paint_field_density_overrides.get(field_key)
            if field_setting is not None:
                return self._density_setting_to_value(tier, field_setting) if tier is not None else field_setting
            H = field.get("map_height")
            if H is not None:
                cell_index = col * H + row
                return field.get("density", {}).get(cell_index)
        return self._current_cell_density(col, row)

    def _handle_paint_box(self, selection_rect):
        """Process a box-select paint operation: paint cells within the selection.

        The box selects any resource cell whose (col, row) lies inside the bounds,
        regardless of whether the field's center is inside the box. Nodes are also
        selected by their exact coordinates.
        """
        if not self._paint_field_cache:
            self.append_log("Paint: no field data available.")
            return

        if not self.current_preview_path or not os.path.exists(self.current_preview_path):
            return

        # Convert selection corners to map cell coordinates
        tl_cell = self._pixel_to_map_cell(selection_rect.topLeft())
        br_cell = self._pixel_to_map_cell(selection_rect.bottomRight())
        if tl_cell is None or br_cell is None:
            self.append_log("Paint: selection outside map area.")
            return

        min_col = min(tl_cell[0], br_cell[0])
        max_col = max(tl_cell[0], br_cell[0])
        min_row = min(tl_cell[1], br_cell[1])
        max_row = max(tl_cell[1], br_cell[1])

        # Log input selection
        self.append_log(f"Paint box: selection_rect=({selection_rect.left()},{selection_rect.top()})-({selection_rect.right()},{selection_rect.bottom()})")
        self.append_log(f"Paint box: tl_cell={tl_cell}, br_cell={br_cell}")
        self.append_log(f"Paint box: cell_bounds=({min_col},{min_row})-({max_col},{max_row})")

        new_tier = self._paint_type
        new_density_setting = None if self._paint_density == "Replace" else self._paint_density
        undo_diff = {}

        # ------------------------------------------------------------------
        # Select every resource cell whose (col, row) is inside the box.
        # ------------------------------------------------------------------
        cells_to_paint = []
        source_cell_set = set()
        for f in self._paint_field_cache:
            H = f.get("map_height")
            if H is None:
                continue
            cx, cy = f["center"]
            field_key = "%d,%d" % (round(cx), round(cy))
            for cell in f.get("cells", []):
                col = cell // H
                row = cell % H
                if min_col <= col <= max_col and min_row <= row <= max_row:
                    cells_to_paint.append((col, row, field_key))
                    source_cell_set.add((col, row))
                    cell_key = f"{col},{row}"
                    _, old_tier = self._find_field_for_cell(col, row)
                    current_tier = self._paint_cell_overrides.get(cell_key, old_tier)
                    current_density = self._current_cell_density(col, row)
                    undo_diff[f"C:{cell_key}"] = (current_tier, current_density)

        # ------------------------------------------------------------------
        # Select any node inside the box.
        # ------------------------------------------------------------------
        nodes_to_paint = []
        if self._paint_node_cache:
            for node in self._paint_node_cache:
                nx, ny = node["x"], node["y"]
                if min_col <= nx <= max_col and min_row <= ny <= max_row:
                    nodes_to_paint.append((nx, ny))
                    node_key = f"{nx},{ny}"
                    current_tier = self._paint_node_overrides.get(node_key, None)
                    undo_diff[f"N:{node_key}"] = current_tier

        # ------------------------------------------------------------------
        # Compute the mirrored region for the whole box (not per-cell snapping).
        # ------------------------------------------------------------------
        mirrored_cells = set()
        if self._paint_mirror and cells_to_paint:
            transforms = self._get_transforms_for_selection(cells_to_paint)
            if transforms:
                source_cells = [(col, row) for col, row, _ in cells_to_paint]
                mirrored_cells = self._mirror_box_region(source_cells, transforms)
                # Do not repaint source cells; they are handled below.
                mirrored_cells = mirrored_cells - source_cell_set

        # Record undo state for mirrored cells before applying overrides.
        for col, row in mirrored_cells:
            cell_key = f"{col},{row}"
            if f"C:{cell_key}" not in undo_diff:
                _, old_tier = self._find_field_for_cell(col, row)
                current_tier = self._paint_cell_overrides.get(cell_key, old_tier)
                current_density = self._current_cell_density(col, row)
                undo_diff[f"C:{cell_key}"] = (current_tier, current_density)

        # Log what was selected
        self.append_log(f"Paint box: selected {len(cells_to_paint)} cells, {len(nodes_to_paint)} nodes")
        if cells_to_paint:
            self.append_log(f"Paint box: cells_to_paint={cells_to_paint[:10]}{'...' if len(cells_to_paint) > 10 else ''}")
        if nodes_to_paint:
            self.append_log(f"Paint box: nodes_to_paint={nodes_to_paint}")
        if mirrored_cells:
            self.append_log(f"Paint box: mirrored region will paint {len(mirrored_cells)} cells")

        if not cells_to_paint and not nodes_to_paint:
            self.append_log("Paint: no resources in selection.")
            return

        self._paint_undo_stack.append(undo_diff)
        self._paint_redo_stack.clear()

        # Apply source cell overrides and their densities.
        for col, row, field_key in cells_to_paint:
            cell_key = f"{col},{row}"
            self._paint_cell_overrides[cell_key] = new_tier
            self._paint_density_overrides[cell_key] = new_density_setting

        # Apply mirrored region cell overrides and their densities.
        for col, row in mirrored_cells:
            cell_key = f"{col},{row}"
            self._paint_cell_overrides[cell_key] = new_tier
            self._paint_density_overrides[cell_key] = new_density_setting

        # Apply node overrides and mirror them.
        for nx, ny in nodes_to_paint:
            node_key = f"{nx},{ny}"
            self._paint_node_overrides[node_key] = new_tier
            if self._paint_mirror:
                self._mirror_node_override(nx, ny, new_tier, undo_diff)

        self._update_paint_buttons()
        self.schedule_preview_refresh()
        paint_summary = f"Paint: box-select painted {len(cells_to_paint)} cells to {new_tier}."
        if mirrored_cells:
            paint_summary += f" Mirrored {len(mirrored_cells)} cells."
        if nodes_to_paint:
            paint_summary += f" Also painted {len(nodes_to_paint)} nodes."
        self.append_log(paint_summary)

        # Log final override state for debugging
        self.append_log(f"Paint: total cell_overrides={len(self._paint_cell_overrides)}, node_overrides={len(self._paint_node_overrides)}")
        if len(self._paint_cell_overrides) <= 20:
            self.append_log(f"Paint: cell_overrides={dict(list(self._paint_cell_overrides.items())[:10])}")
        if len(self._paint_node_overrides) <= 10:
            self.append_log(f"Paint: node_overrides={self._paint_node_overrides}")

        # Write paint matrix to file for debugging
        self._dump_paint_matrix()

    def _get_transforms_for_selection(self, cells_to_paint):
        """Return the symmetry transforms from the first selected field.

        All fields in a symmetric map share the same transform set, so using the
        first field is sufficient for box-region mirroring.
        """
        if not cells_to_paint:
            return []
        first_field_key = cells_to_paint[0][2]
        for f in self._paint_field_cache:
            cx, cy = f["center"]
            if "%d,%d" % (round(cx), round(cy)) == first_field_key:
                return f.get("transforms", [])
        return []

    def _mirror_box_region(self, source_cells, transforms):
        """Return partner-field cells that mirror the source selection.

        This is a field-aware, count-parity-aware mirror:

        1. The source field is identified from the first selected cell.
        2. For each detected symmetry transform, the source field centre is
           transformed to determine which partner field (from the field's
           ``mirror_keys``) is the destination.
        3. The transformed source field centre is aligned to the actual partner
           field centre by a small per-transform offset. This compensates for
           imperfect map symmetry where the spawn-derived symmetry centre does
           not exactly coincide with the resource field centres.
        4. Only cells inside that partner field are eligible for mirroring.
        5. Each source cell is greedily matched to the nearest unused partner
           cell within ``_MIRROR_MAX_DIST`` cells. This keeps the shape as close
           as possible while never painting outside the partner field and
           avoiding the old "multiple source cells collapse onto one target"
           bug.

        Returns a set of (col, row) mirrored cells.
        """
        import math
        if not transforms or not source_cells:
            return set()

        # Build a lookup from field centre key to field metadata.
        field_by_key = {}
        for f in self._paint_field_cache:
            cx, cy = f["center"]
            key = "%d,%d" % (round(cx), round(cy))
            field_by_key[key] = f

        # Source field and its partners.
        src_col, src_row = source_cells[0]
        src_field_key, _ = self._find_field_for_cell(src_col, src_row)
        if not src_field_key or src_field_key not in field_by_key:
            return set()
        src_field = field_by_key[src_field_key]
        src_cx, src_cy = src_field["center"]
        partner_keys = list(dict.fromkeys(src_field.get("mirror_keys", [src_field_key])))

        max_dist = getattr(self, "_MIRROR_MAX_DIST", 2.0)
        target_cells = set()

        for name, T in transforms:
            # Which partner field does this transform land on?
            tx_c, ty_c = T(src_cx, src_cy)
            best_key = None
            best_d = float("inf")
            for key in partner_keys:
                if key not in field_by_key:
                    continue
                fx, fy = field_by_key[key]["center"]
                d = math.hypot(tx_c - fx, ty_c - fy)
                if d < best_d:
                    best_d = d
                    best_key = key

            if not best_key or best_key == src_field_key:
                continue

            partner_field = field_by_key[best_key]
            partner_cx, partner_cy = partner_field["center"]
            # Align the transformed source field centre with the actual partner
            # field centre. This compensates for imperfect map symmetry where
            # the mathematical symmetry centre (from spawns) does not exactly
            # coincide with the resource field centres.
            offset_x = partner_cx - tx_c
            offset_y = partner_cy - ty_c

            H = partner_field.get("map_height")
            if H is None:
                continue

            partner_cell_set = set()
            for cell_index in partner_field.get("cells", []):
                col = cell_index // H
                row = cell_index % H
                partner_cell_set.add((col, row))

            if not partner_cell_set:
                continue

            # Greedy nearest-neighbor matching inside the partner field only.
            used = set()
            matched_for_transform = 0
            for col, row in source_cells:
                tx, ty = T(col, row)
                tx += offset_x
                ty += offset_y
                best = None
                best_d = float("inf")
                for (pc, pr) in partner_cell_set:
                    if (pc, pr) in used:
                        continue
                    d = math.hypot(tx - pc, ty - pr)
                    if d < best_d and d <= max_dist:
                        best_d = d
                        best = (pc, pr)
                if best:
                    used.add(best)
                    target_cells.add(best)
                    matched_for_transform += 1

            self.append_log(
                f"Mirror: transform={name}, partner={best_key}, "
                f"offset=({offset_x:+.2f},{offset_y:+.2f}), "
                f"matched {matched_for_transform}/{len(source_cells)} cells "
                f"(max_dist={max_dist})"
            )

        return target_cells

    def _handle_paint_click(self, viewer_pos):
        """Process a left-click in paint mode.

        Pixel-perfect behaviour:
        - Click directly on a resource node -> paint node only.
        - Click on any resource cell -> paint that single cell (mirrored if symmetry is on).
        - Click on empty background -> do nothing.
        """
        cell = self._pixel_to_map_cell(viewer_pos)
        if cell is None:
            self.append_log("Paint: click outside map area.")
            return
        col, row = cell

        # DEBUG: Log click details
        self.append_log(f"CLICK: pixel={viewer_pos.x()},{viewer_pos.y()} -> cell=({col},{row})")
        new_tier = getattr(self, "_paint_type", "Ore")

        # Node takes precedence only when directly clicked (0.5 cell tolerance).
        # This lets users paint resource cells immediately next to a node without
        # accidentally switching to node-paint mode.
        node = self._find_node_for_cell(col, row, tolerance=0.5)
        if node is not None:
            self._handle_node_paint_click(col, row, new_tier)
            return

        # Only paint if the cursor is exactly on a resource cell.
        field_key, _ = self._find_field_for_cell(col, row)
        if field_key is not None:
            # Verify exact cell membership to avoid painting a nearby cell when the
            # click is slightly off the field edge.
            for f in self._paint_field_cache:
                cx, cy = f["center"]
                if "%d,%d" % (round(cx), round(cy)) == field_key:
                    H = f.get("map_height")
                    if H is not None and (col * H + row) in f.get("cells", set()):
                        self._handle_cell_paint_click(col, row, new_tier)
                    return
        else:
            self.append_log(f"Paint: no resource at cell ({col},{row}).")

    def _handle_cell_paint_click(self, col, row, new_tier):
        """Handle cell painting mode - paint individual resource cells."""
        cell_key = f"{col},{row}"

        # Find which field this cell belongs to (for symmetry)
        field_key, old_tier = self._find_field_for_cell(col, row)
        if field_key is None:
            self.append_log(f"Paint: no resource field near cell ({col},{row}).")
            return

        new_density_setting = None if self._paint_density == "Replace" else self._paint_density

        # Get current cell tier
        current_tier = self._paint_cell_overrides.get(cell_key, old_tier)
        if current_tier == new_tier:
            return  # No change needed

        current_density = self._current_cell_density(col, row)

        # Record undo entry
        self._paint_undo_stack.append({f"C:{cell_key}": (current_tier, current_density)})
        self._paint_redo_stack.clear()

        # Apply cell override and density
        self._paint_cell_overrides[cell_key] = new_tier
        self._paint_density_overrides[cell_key] = new_density_setting

        # If mirror paint is enabled, also paint the corresponding cell in mirror fields
        if self._paint_mirror:
            self._mirror_cell_override(col, row, field_key, new_tier, new_density_setting, self._paint_undo_stack[-1])

        self._update_paint_buttons()
        self.append_log(f"Paint: cell @({cell_key}) → {new_tier}")
        self.schedule_preview_refresh()
        self._dump_paint_matrix()

    def _handle_node_paint_click(self, col, row, new_tier):
        """Handle node painting mode - paint resource nodes only."""
        # Find the node closest to the clicked position (must be within 0.5 cells).
        node = self._find_node_for_cell(col, row, tolerance=0.5)
        if node is None:
            self.append_log(f"Paint: no resource node near cell ({col},{row}).")
            return

        # Extract node key from the returned node dict
        node_key = f"{node['x']},{node['y']}"

        # Get current node tier
        current_tier = self._paint_node_overrides.get(node_key, None)
        if current_tier == new_tier:
            return  # No change needed

        # Record undo entry
        self._paint_undo_stack.append({f"N:{node_key}": current_tier})
        self._paint_redo_stack.clear()

        # Apply node override
        self._paint_node_overrides[node_key] = new_tier

        # If mirror paint is enabled, also paint mirror nodes
        if self._paint_mirror:
            self._mirror_node_override(node["x"], node["y"], new_tier, self._paint_undo_stack[-1])

        self._update_paint_buttons()
        self.append_log(f"Paint: node @({node_key}) → {new_tier}")
        self.schedule_preview_refresh()
        self._dump_paint_matrix()

    def _find_node_for_field(self, field):
        """Find the actual node coordinate inside a field.

        Args:
            field: Field dictionary with 'center' and 'nodes' keys

        Returns:
            Tuple (x, y) of the node closest to the field center, or None if no nodes
        """
        if not field or "nodes" not in field or not field["nodes"]:
            return None

        cx, cy = field["center"]
        best_node = None
        best_dist = float('inf')

        for node in field["nodes"]:
            nx, ny = node
            dist = ((nx - cx) ** 2 + (ny - cy) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_node = node

        return best_node

    def _mirror_cell_override(self, col, row, field_key, new_tier, new_density_setting, undo_diff):
        """Paint the single corresponding cell in every mirror field.

        Uses the symmetry transforms detected from the map geometry (stored in each
        field's 'transforms' metadata). For each non-identity transform, the source
        cell is transformed to the target location, aligned to the actual partner
        field centre, and the nearest cell in the partner field is painted. This is
        robust to vertical, horizontal, point, diagonal, and rotational symmetries,
        as well as imperfect symmetry via a tolerance.
        """
        import math

        # Build a lookup from field centre key to field metadata.
        field_by_key = {}
        for f in self._paint_field_cache:
            cx, cy = f["center"]
            key = "%d,%d" % (round(cx), round(cy))
            field_by_key[key] = f

        src_field = field_by_key.get(field_key)
        if not src_field:
            return
        H = src_field.get("map_height")
        if H is None:
            return

        src_cx, src_cy = src_field["center"]
        partner_keys = list(dict.fromkeys(src_field.get("mirror_keys", [field_key])))
        transforms = src_field.get("transforms", [])
        if not transforms:
            return

        self.append_log(f"Mirror cell: source=({col},{row}), transforms={len(transforms)}")

        # Track already-painted targets to avoid redundant transforms
        painted_targets = set()

        for name, T in transforms:
            # Which partner field does this transform land on?
            tx_c, ty_c = T(src_cx, src_cy)
            best_key = None
            best_d = float("inf")
            for key in partner_keys:
                if key not in field_by_key:
                    continue
                fx, fy = field_by_key[key]["center"]
                d = math.hypot(tx_c - fx, ty_c - fy)
                if d < best_d:
                    best_d = d
                    best_key = key

            if not best_key or best_key == field_key:
                continue

            partner_field = field_by_key[best_key]
            partner_cx, partner_cy = partner_field["center"]
            # Align the transformed source field centre with the actual partner
            # field centre, then apply the same offset to the cell.
            offset_x = partner_cx - tx_c
            offset_y = partner_cy - ty_c

            tx, ty = T(col, row)
            tx += offset_x
            ty += offset_y
            target_col = int(round(tx))
            target_row = int(round(ty))

            # Skip if transform lands back on the source cell (within tolerance)
            if math.hypot(target_col - col, target_row - row) <= 2.0:
                self.append_log(f"Mirror cell: skipping self-mapping for ({target_col},{target_row})")
                continue

            target_key = f"{target_col},{target_row}"
            if target_key in painted_targets:
                self.append_log(f"Mirror cell: skipping duplicate target ({target_col},{target_row})")
                continue

            pH = partner_field.get("map_height")
            p_cells = partner_field.get("cells", set())
            target_index = target_col * pH + target_row

            if target_index in p_cells:
                # Exact match
                cell_key = f"{target_col},{target_row}"
                old_tier = self._paint_cell_overrides.get(cell_key, partner_field["tier"])
                old_density = self._current_cell_density(target_col, target_row)
                undo_diff[f"C:{cell_key}"] = (old_tier, old_density)
                self._paint_cell_overrides[cell_key] = new_tier
                self._paint_density_overrides[cell_key] = new_density_setting
                painted_targets.add(target_key)
                self.append_log(
                    f"Mirror cell: painted partner cell ({target_col},{target_row}) -> {new_tier} "
                    f"(transform={name}, partner={best_key}, offset=({offset_x:+.2f},{offset_y:+.2f}))"
                )
            else:
                # Nearest cell
                best_cell = None
                best_dist = float('inf')
                for cell_index in p_cells:
                    p_col = cell_index // pH
                    p_row = cell_index % pH
                    dist = ((p_col - target_col) ** 2 + (p_row - target_row) ** 2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
                        best_cell = (p_col, p_row)
                if best_cell and best_dist <= 2.0:
                    m_col, m_row = best_cell
                    cell_key = f"{m_col},{m_row}"
                    old_tier = self._paint_cell_overrides.get(cell_key, partner_field["tier"])
                    old_density = self._current_cell_density(m_col, m_row)
                    undo_diff[f"C:{cell_key}"] = (old_tier, old_density)
                    self._paint_cell_overrides[cell_key] = new_tier
                    self._paint_density_overrides[cell_key] = new_density_setting
                    painted_targets.add(target_key)
                    self.append_log(
                        f"Mirror cell: painted nearest partner cell ({m_col},{m_row}) dist={best_dist:.2f} -> {new_tier} "
                        f"(transform={name}, partner={best_key}, offset=({offset_x:+.2f},{offset_y:+.2f}))"
                    )
                else:
                    self.append_log(
                        f"Mirror cell: no cell within tolerance for ({target_col},{target_row}) "
                        f"partner={best_key} (best_dist={best_dist:.2f})"
                    )

    def _mirror_node_override(self, nx, ny, new_tier, undo_diff):
        """Paint the single corresponding node in every mirror field.

        Uses the detected symmetry transforms stored in the source field's metadata.
        For each transform, the source node coordinate is transformed to the target
        location, aligned to the actual partner field centre, and the nearest resource
        node inside that partner field is painted.
        """
        import math
        NEAREST_NODE_TOL = 2.0  # cells

        field_key, _ = self._find_field_for_cell(nx, ny)
        if field_key is None:
            return

        # Build a lookup from field centre key to field metadata.
        field_by_key = {}
        for f in self._paint_field_cache:
            cx, cy = f["center"]
            key = "%d,%d" % (round(cx), round(cy))
            field_by_key[key] = f

        src_field = field_by_key.get(field_key)
        if not src_field:
            return

        src_cx, src_cy = src_field["center"]
        partner_keys = list(dict.fromkeys(src_field.get("mirror_keys", [field_key])))
        transforms = src_field.get("transforms", [])
        if not transforms:
            return

        self.append_log(f"Mirror node: source=({nx},{ny}), transforms={len(transforms)}")

        # Track already-painted targets to avoid redundant transforms
        painted_targets = set()

        for name, T in transforms:
            # Which partner field does this transform land on?
            tx_c, ty_c = T(src_cx, src_cy)
            best_key = None
            best_d = float("inf")
            for key in partner_keys:
                if key not in field_by_key:
                    continue
                fx, fy = field_by_key[key]["center"]
                d = math.hypot(tx_c - fx, ty_c - fy)
                if d < best_d:
                    best_d = d
                    best_key = key

            if not best_key or best_key == field_key:
                continue

            partner_field = field_by_key[best_key]
            partner_cx, partner_cy = partner_field["center"]
            # Align the transformed source field centre with the actual partner
            # field centre, then apply the same offset to the node.
            offset_x = partner_cx - tx_c
            offset_y = partner_cy - ty_c

            tx, ty = T(nx, ny)
            tx += offset_x
            ty += offset_y
            target_x = int(round(tx))
            target_y = int(round(ty))

            # Skip if transform lands back on the source node (within tolerance)
            if math.hypot(target_x - nx, target_y - ny) <= NEAREST_NODE_TOL:
                self.append_log(f"Mirror node: skipping self-mapping for ({target_x},{target_y})")
                continue

            # Find nearest resource node inside the partner field only
            partner_nodes = partner_field.get("nodes", [])
            if not partner_nodes:
                self.append_log(f"Mirror node: partner field {best_key} has no nodes")
                continue

            best_node = None
            best_d = float("inf")
            for pnx, pny in partner_nodes:
                d = math.hypot(pnx - tx, pny - ty)
                if d < best_d:
                    best_d = d
                    best_node = (pnx, pny)

            if best_node is None or best_d > NEAREST_NODE_TOL:
                self.append_log(
                    f"Mirror node: no match within tolerance for ({target_x},{target_y}) "
                    f"partner={best_key} (best_d={best_d:.2f})"
                )
                continue

            pnx, pny = best_node
            partner_node_key = f"{pnx},{pny}"
            # Skip if already painted by another transform
            if partner_node_key in painted_targets:
                self.append_log(f"Mirror node: skipping duplicate target ({pnx},{pny})")
                continue
            painted_targets.add(partner_node_key)

            # Find the node dict for the partner node to get its original resource
            partner_node_dict = None
            for node in self._paint_node_cache:
                if node["x"] == pnx and node["y"] == pny:
                    partner_node_dict = node
                    break

            old_tier = self._paint_node_overrides.get(partner_node_key, partner_node_dict.get("resource") if partner_node_dict else None)
            undo_diff[f"N:{partner_node_key}"] = old_tier
            self._paint_node_overrides[partner_node_key] = new_tier
            self.append_log(
                f"Mirror node: painted partner node ({pnx},{pny}) -> {new_tier} "
                f"(transform={name}, partner={best_key}, offset=({offset_x:+.2f},{offset_y:+.2f}))"
            )

    def _dump_paint_matrix(self):
        """Dump the current paint override state to a file for debugging.

        Writes the cell and node overrides to paint_matrix_debug.txt in the
        current working directory.
        """
        try:
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open("paint_matrix_debug.txt", "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"Paint Matrix Dump - {timestamp}\n")
                f.write(f"{'='*60}\n")
                f.write(f"Cell Overrides ({len(self._paint_cell_overrides)} total):\n")
                for cell_key, tier in sorted(self._paint_cell_overrides.items()):
                    f.write(f"  {cell_key} -> {tier}\n")
                f.write(f"\nNode Overrides ({len(self._paint_node_overrides)} total):\n")
                for node_key, tier in sorted(self._paint_node_overrides.items()):
                    f.write(f"  {node_key} -> {tier}\n")
                f.write(f"\n")
        except Exception as e:
            self.append_log(f"Failed to write paint matrix debug file: {e}")

    def _find_node_for_cell(self, col, row, tolerance=2.0):
        """Find the resource node closest to the given cell coordinates.

        Args:
            col, row: cell coordinates of the click/hover.
            tolerance: maximum distance in cells to consider a node hit.

        Returns the full node dict with 'x', 'y', 'resource' keys if within
        tolerance, or None otherwise.
        """
        if not self._paint_node_cache:
            return None

        # Find the closest node to the clicked position
        min_dist = float('inf')
        closest_node = None

        for node in self._paint_node_cache:
            nx, ny = node["x"], node["y"]
            dist = ((col - nx) ** 2 + (row - ny) ** 2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                closest_node = node

        return closest_node if min_dist <= tolerance else None

    def _restore_tier_density(self, key, val, is_undo):
        """Restore a paint override from an undo/redo value.

        val may be a plain tier string (legacy) or a (tier, density) tuple.
        """
        if isinstance(val, (list, tuple)) and len(val) == 2:
            tier, density = val
        else:
            tier = val
            density = None  # keep current density unless explicitly provided

        if key.startswith("N:"):
            node_key = key[2:]
            if tier is None:
                self._paint_node_overrides.pop(node_key, None)
            else:
                self._paint_node_overrides[node_key] = tier
            return self._paint_node_overrides.get(node_key, None)

        if key.startswith("C:"):
            cell_key = key[2:]
            if tier is None:
                self._paint_cell_overrides.pop(cell_key, None)
                self._paint_density_overrides.pop(cell_key, None)
            else:
                self._paint_cell_overrides[cell_key] = tier
                if density is not None:
                    self._paint_density_overrides[cell_key] = density
            return self._paint_cell_overrides.get(cell_key, None), self._paint_density_overrides.get(cell_key, None)

        # Field-level override
        if tier is None:
            self._paint_overrides.pop(key, None)
            self._paint_field_density_overrides.pop(key, None)
        else:
            self._paint_overrides[key] = tier
            if density is not None:
                self._paint_field_density_overrides[key] = density
        return self._paint_overrides.get(key, None), self._paint_field_density_overrides.get(key, None)

    def paint_undo(self):
        """Undo the last paint stroke (field, cell, or node)."""
        if not self._paint_undo_stack:
            return
        diff = self._paint_undo_stack.pop()
        redo_diff = {}
        for key, old_val in diff.items():
            # For C: and field keys, store current value as a tuple for redo.
            if key.startswith("N:"):
                node_key = key[2:]
                current = self._paint_node_overrides.get(node_key, None)
                redo_diff[key] = current
                self._restore_tier_density(key, old_val, is_undo=True)
            elif key.startswith("C:"):
                cell_key = key[2:]
                current_tier = self._paint_cell_overrides.get(cell_key, None)
                current_density = self._paint_density_overrides.get(cell_key, None)
                redo_diff[key] = (current_tier, current_density)
                self._restore_tier_density(key, old_val, is_undo=True)
            else:
                current_tier = self._paint_overrides.get(key, None)
                current_density = self._paint_field_density_overrides.get(key, None)
                redo_diff[key] = (current_tier, current_density)
                self._restore_tier_density(key, old_val, is_undo=True)
        self._paint_redo_stack.append(redo_diff)
        self._update_paint_buttons()
        self.schedule_preview_refresh()

    def paint_redo(self):
        """Redo the last undone paint stroke (field, cell, or node)."""
        if not self._paint_redo_stack:
            return
        diff = self._paint_redo_stack.pop()
        undo_diff = {}
        for key, new_val in diff.items():
            if key.startswith("N:"):
                node_key = key[2:]
                current = self._paint_node_overrides.get(node_key, None)
                undo_diff[key] = current
                self._restore_tier_density(key, new_val, is_undo=False)
            elif key.startswith("C:"):
                cell_key = key[2:]
                current_tier = self._paint_cell_overrides.get(cell_key, None)
                current_density = self._paint_density_overrides.get(cell_key, None)
                undo_diff[key] = (current_tier, current_density)
                self._restore_tier_density(key, new_val, is_undo=False)
            else:
                current_tier = self._paint_overrides.get(key, None)
                current_density = self._paint_field_density_overrides.get(key, None)
                undo_diff[key] = (current_tier, current_density)
                self._restore_tier_density(key, new_val, is_undo=False)
        self._paint_undo_stack.append(undo_diff)
        self._update_paint_buttons()
        self.schedule_preview_refresh()

    def paint_clear(self):
        """Remove all paint overrides and restore algorithmic assignment."""
        if (not self._paint_overrides and not self._paint_cell_overrides and not self._paint_node_overrides
                and not self._paint_density_overrides and not self._paint_field_density_overrides):
            return
        # Record full undo entry (combine all override types), including density for
        # cell and field overrides so undo can restore the exact painted state.
        full_undo = {}
        for k, v in self._paint_overrides.items():
            full_undo[k] = (v, self._paint_field_density_overrides.get(k, None))
        for k, v in self._paint_cell_overrides.items():
            full_undo[f"C:{k}"] = (v, self._paint_density_overrides.get(k, None))
        full_undo.update({f"N:{k}": v for k, v in self._paint_node_overrides.items()})
        self._paint_undo_stack.append(full_undo)
        self._paint_redo_stack.clear()
        self._paint_overrides.clear()
        self._paint_cell_overrides.clear()
        self._paint_node_overrides.clear()
        self._paint_density_overrides.clear()
        self._paint_field_density_overrides.clear()
        self._update_paint_buttons()
        self.append_log("Paint: all field, cell, and node overrides cleared.")
        self.schedule_preview_refresh()

    def _update_paint_buttons(self):
        """Sync undo/redo button enabled state with the stack lengths."""
        self.paint_undo_btn.setEnabled(bool(self._paint_undo_stack))
        self.paint_redo_btn.setEnabled(bool(self._paint_redo_stack))

    def on_remap_resources_changed(self):
        """Handle remap_resources checkbox change - no longer clears cache since base data is unchanged."""
        try:
            # Preview cache no longer needs clearing on remap_resources change
            # because base resource data is now always the same (1-1 remapped)
            self.on_setting_changed()
        except Exception as e:
            import traceback
            traceback.print_exc()
    
    def _update_settings_visibility(self, _checked=None):
        """Show/hide settings rows that don't apply to the active distribution mode.

        Balance  → show all rows (Richness, Bias, Home Radius)
        Distance → show Richness + Home Radius; hide Bias
        Even     → hide all three rows (Even ignores the knobs entirely)
        """
        is_even    = self.even_radio.isChecked()
        is_balance = self.balance_radio.isChecked()
        # is_distance is the remaining case

        # Row 1 — Resource Richness: hidden for Even
        for w in (self._richness_label_widget, self.richness_slider, self.richness_label):
            w.setVisible(not is_even)

        # Row 3 — Balance Bias: only shown for Balance
        for w in (self._bias_label_widget, self.balance_bias_slider, self.balance_bias_label):
            w.setVisible(is_balance)

        # Row 4 — Home Radius: shown for Balance and Distance, hidden for Even
        for w in (self._radius_label_widget, self.home_radius_slider, self.home_radius_label):
            w.setVisible(not is_even)

        # Update tooltip/label to reflect distance-mode meaning of home radius
        if is_balance:
            self._radius_label_widget.setText("Home Radius:")
            self._radius_label_widget.setToolTip(
                "Cells within this radius of a spawn are treated as the safe home zone.\n"
                "Nodes inside stay at Ore regardless of contestedness."
            )
        else:
            self._radius_label_widget.setText("Home Radius:")
            self._radius_label_widget.setToolTip(
                "Nodes within this distance of a spawn are suppressed toward Ore.\n"
                "Increase to push the Ore band further from the base."
            )

    def on_setting_changed(self):
        """Handle setting changes and save."""
        try:
            # Stop any pending preview timer immediately
            self.preview_timer.stop()
            self.save_settings()
            self.schedule_preview_refresh()
        except Exception as e:
            import traceback
            traceback.print_exc()
        
    def toggle_tooltips(self, enabled):
        """Toggle tooltips on/off."""
        self.tooltips_enabled = enabled
        self.apply_tooltips()
        
    def apply_tooltips(self):
        """Apply tooltips to UI elements."""
        if not self.tooltips_enabled:
            # Remove all tooltips
            self.incoming_dir_btn.setToolTip("")
            self.outgoing_dir_btn.setToolTip("")
            self.richness_slider.setToolTip("")
            self.balance_radio.setToolTip("")
            self.distance_radio.setToolTip("")
            self.balance_bias_slider.setToolTip("")
            self.home_radius_slider.setToolTip("")
            self.reset_settings_btn.setToolTip("")
            self.convert_map_btn.setToolTip("")
            self.convert_all_btn.setToolTip("")
            self.left_arrow.setToolTip("")
            self.right_arrow.setToolTip("")
            self.preview_converted_btn.setToolTip("")
            return
        
        # Apply tooltips
        self.incoming_dir_btn.setToolTip("Select the folder containing source .oramap files to convert")
        self.outgoing_dir_btn.setToolTip("Select the output folder for converted maps")
        self.richness_slider.setToolTip("Resource Richness: 0.5=all ore, 1.0=balanced, 1.5=all gems")
        self.balance_radio.setToolTip("Balance mode: Richest resources in contested center")
        self.distance_radio.setToolTip("Distance mode: Richest resources at outer edges")
        self.balance_bias_slider.setToolTip("Balance Bias: How strongly to pull rich resources to center (0=distance, 3=default)")
        self.home_radius_slider.setToolTip("Home Radius: Distance from spawn points where resources are protected/less valuable (default 15). Higher values give larger ore-only areas around bases.")
        self.reset_settings_btn.setToolTip("Reset all resource settings to default values")
        self.preview_converted_btn.setToolTip("Left-click: Hold to temporarily preview the already-converted version of this map. Right-click: Toggle to lock/unlock the converted preview (stays on when locked).")
        self.convert_map_btn.setToolTip("Convert the currently displayed map")
        self.convert_all_btn.setToolTip("Convert all maps in the incoming directory")
        self.left_arrow.setToolTip("Previous map")
        self.right_arrow.setToolTip("Next map")


def _crash_log_path():
    """Where to write crash logs: next to the exe (frozen) or this script."""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "gui_crash_log.txt")


def _install_crash_handler():
    """Capture otherwise-silent crashes. In PyQt an unhandled exception inside a
    signal slot aborts the process with no visible traceback; this writes the full
    traceback to gui_crash_log.txt (and stderr) so failures are diagnosable."""
    import traceback
    import datetime

    def _hook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(_crash_log_path(), "a", encoding="utf-8") as f:
                f.write(f"\n===== UNCAUGHT EXCEPTION {stamp} =====\n{msg}\n")
        except Exception:
            pass
        sys.stderr.write(msg)

    sys.excepthook = _hook
    try:
        import faulthandler
        faulthandler.enable()
    except Exception:
        pass


def main():
    """Main entry point for the GUI application."""
    # When the frozen PyInstaller EXE is re-executed to run the bundled
    # converter script (used by the conversion/batch subprocess), dispatch
    # to that script instead of launching the GUI. This keeps the conversion
    # inside the bundled Python 3.12 runtime and prevents the subprocess from
    # loading PyInstaller 3.12 extension modules into a system Python 3.13/3.14
    # interpreter, which causes:
    #   ImportError: Module use of python312.dll conflicts with this version of Python.
    if getattr(sys, 'frozen', False) and len(sys.argv) > 1:
        first_arg = sys.argv[1]
        if first_arg.endswith('cameo_map_converter.py') and os.path.exists(first_arg):
            script_path = os.path.abspath(first_arg)
            # Strip the EXE path so the script sees itself as argv[0]
            sys.argv = sys.argv[1:]
            runpy.run_path(script_path, run_name='__main__')
            sys.exit(0)

    _install_crash_handler()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setWindowIcon(_app_icon())
    window = CameoConverterGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
