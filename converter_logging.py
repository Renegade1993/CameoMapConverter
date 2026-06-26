#!/usr/bin/env python3
"""
converter_logging.py -- Centralized logging system for the Cameo Map Converter.

Provides structured logging with configurable levels, per-log-type file output with rotation,
and consistent formatting across all converter modules.
"""

import logging
import logging.handlers
import os
import platform
import sys
import threading
from pathlib import Path
from typing import Optional


class _StdoutToLogger:
    """Redirect stdout/stderr writes into the Python logger.

    This captures every ``print()`` and unhandled stderr emission so it ends up
    in the same log files and GUI log panel as normal logger output. The original
    stdout reference is preserved by the logging StreamHandler installed at
    import time, so redirecting sys.stdout after startup does not create a loop.

    A thread-local re-entry guard prevents infinite recursion if the logging
    system itself fails (e.g. a stream handler attached to a ``None`` stdout in a
    PyInstaller windowed executable).
    """

    def __init__(self, logger, level=logging.INFO):
        self.logger = logger
        self.level = level
        self._buffer = ""
        self._local = threading.local()

    def _write_lines(self, text):
        if not text:
            return
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line)

    def write(self, message):
        if not message:
            return
        if getattr(self._local, 'writing', False):
            return
        self._local.writing = True
        try:
            self._write_lines(message)
        finally:
            self._local.writing = False

    def flush(self):
        if not self._buffer.strip():
            return
        if getattr(self._local, 'writing', False):
            return
        self._local.writing = True
        try:
            self.logger.log(self.level, self._buffer.strip())
            self._buffer = ""
        finally:
            self._local.writing = False

    def isatty(self):
        return False


class ConverterLogger:
    """Centralized logger for the Cameo Map Converter with per-log-type file output."""
    
    _instance = None
    _logger = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._logger = logging.getLogger("CameoConverter")
        self._logger.setLevel(logging.DEBUG)  # Capture all levels, handlers filter
        self._logger.propagate = False  # Prevent duplicate logs
        
        # Console handler with INFO level by default. In PyInstaller windowed
        # executables sys.stdout is None; use a NullHandler so logging never
        # tries to write to a non-existent console stream.
        if sys.stdout is None:
            console_handler = logging.NullHandler()
        else:
            console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(levelname)s: %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        self._logger.addHandler(console_handler)
        
        # Per-log-type file handlers (disabled by default)
        self._file_handlers = {
            'DEBUG': None,
            'INFO': None,
            'WARNING': None,
            'ERROR': None
        }
        self._log_dir = None
        self._max_bytes = 10 * 1024 * 1024  # 10 MB
        self._backup_count = 5
        self._initialized = True
    
    def setup_file_logging(
        self,
        log_dir: Optional[str] = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10 MB
        backup_count: int = 5
    ) -> None:
        """Setup logging directory and rotation settings.
        
        Args:
            log_dir: Directory for log files. If None, uses ./log subdirectory.
            max_bytes: Maximum size per log file before rotation.
            backup_count: Number of backup files to keep.
        """
        # Determine log directory
        if log_dir is None:
            # Handle both script and exe environments
            if getattr(sys, 'frozen', False):
                # Running as PyInstaller exe
                base_dir = os.path.dirname(sys.executable)
            else:
                # Running as script
                base_dir = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(base_dir, "log")
        
        self._log_dir = log_dir
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        
        # Ensure directory exists
        Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    def enable_all_file_logging(self) -> None:
        """Enable a single unified log file that captures all levels.

        This is useful for debugging sessions where the user wants one file to
        share or inspect, rather than four separate per-level files. Existing
        per-level handlers are left untouched.
        """
        if self._log_dir is None:
            self.setup_file_logging()
        
        if getattr(self, "_all_handler", None) is not None:
            return  # Already enabled
        
        log_file = os.path.join(self._log_dir, "all.log")
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=self._max_bytes,
            backupCount=self._backup_count,
            encoding='utf-8'
        )
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)
        self._all_handler = handler
    
    def enable_log_type(self, log_type: str) -> None:
        """Enable file logging for a specific log type.
        
        Args:
            log_type: One of 'DEBUG', 'INFO', 'WARNING', 'ERROR'
        """
        log_type = log_type.upper()
        if log_type not in self._file_handlers:
            raise ValueError(f"Invalid log type: {log_type}")
        
        if self._log_dir is None:
            self.setup_file_logging()
        
        # Remove existing handler if present
        if self._file_handlers[log_type] is not None:
            self._logger.removeHandler(self._file_handlers[log_type])
        
        # Create log file path
        log_file = os.path.join(self._log_dir, f"{log_type.lower()}.log")
        
        # Create rotating file handler
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=self._max_bytes,
            backupCount=self._backup_count,
            encoding='utf-8'
        )
        
        # Set handler level to only capture this log type
        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR
        }
        handler.setLevel(level_map[log_type])
        
        # Detailed format for file logs
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(file_formatter)
        self._logger.addHandler(handler)
        self._file_handlers[log_type] = handler
    
    def disable_log_type(self, log_type: str) -> None:
        """Disable file logging for a specific log type.
        
        Args:
            log_type: One of 'DEBUG', 'INFO', 'WARNING', 'ERROR'
        """
        log_type = log_type.upper()
        if log_type not in self._file_handlers:
            raise ValueError(f"Invalid log type: {log_type}")
        
        if self._file_handlers[log_type] is not None:
            self._logger.removeHandler(self._file_handlers[log_type])
            self._file_handlers[log_type] = None
    
    def is_log_type_enabled(self, log_type: str) -> bool:
        """Check if file logging is enabled for a specific log type.
        
        Args:
            log_type: One of 'DEBUG', 'INFO', 'WARNING', 'ERROR'
        
        Returns:
            True if enabled, False otherwise
        """
        log_type = log_type.upper()
        if log_type not in self._file_handlers:
            raise ValueError(f"Invalid log type: {log_type}")
        return self._file_handlers[log_type] is not None
    
    def capture_stdout(self, level: int = logging.INFO) -> None:
        """Redirect ``sys.stdout`` and ``sys.stderr`` into the logger.

        Call this once during application startup so every ``print()`` and
        unhandled exception message is captured in the log files. The original
        streams are saved so they can be restored with ``restore_stdout()``.
        """
        if not getattr(sys, '_cameo_stdout_saved', False):
            sys._cameo_stdout_orig = sys.stdout
            sys._cameo_stderr_orig = sys.stderr
            sys._cameo_stdout_saved = True
        sys.stdout = _StdoutToLogger(self._logger, level)
        sys.stderr = _StdoutToLogger(self._logger, logging.ERROR)
    
    def restore_stdout(self) -> None:
        """Restore the original ``sys.stdout`` and ``sys.stderr``."""
        if getattr(sys, '_cameo_stdout_saved', False):
            sys.stdout = sys._cameo_stdout_orig
            sys.stderr = sys._cameo_stderr_orig
    
    def get_enabled_log_types(self) -> list:
        """Get list of currently enabled log types.
        
        Returns:
            List of enabled log type names
        """
        enabled = []
        for log_type, handler in self._file_handlers.items():
            if handler is not None:
                enabled.append(log_type)
        return enabled
    
    def set_level(self, level: str) -> None:
        """Set the console logging level.
        
        Args:
            level: One of 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
        """
        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }
        self._logger.setLevel(level_map.get(level.upper(), logging.INFO))
    
    def log_system_info(self) -> None:
        """Log system information for diagnostics."""
        system_info = {
            'python_version': platform.python_version(),
            'platform': platform.platform(),
            'system': platform.system(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'executable': sys.executable
        }
        
        self.info("=== SYSTEM INFO ===")
        for key, value in system_info.items():
            self.info(f"{key}: {value}")
        self.info("===================")
    
    def debug(self, message: str, *args, **kwargs) -> None:
        """Log a debug message."""
        self._logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs) -> None:
        """Log an info message."""
        self._logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs) -> None:
        """Log a warning message."""
        self._logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs) -> None:
        """Log an error message."""
        self._logger.error(message, *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs) -> None:
        """Log a critical message."""
        self._logger.critical(message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs) -> None:
        """Log an error message with exception info."""
        self._logger.exception(message, *args, **kwargs)


# Global logger instance
_logger = ConverterLogger()


def get_logger() -> ConverterLogger:
    """Get the global logger instance."""
    return _logger


def setup_logging(
    log_file: Optional[str] = None,
    log_dir: Optional[str] = None,
    level: str = "INFO",
    enable_file: bool = False
) -> None:
    """Setup logging configuration.
    
    Args:
        log_file: Specific log file path.
        log_dir: Directory for log files.
        level: Logging level ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL').
        enable_file: Whether to enable file logging.
    """
    _logger.set_level(level)
    if enable_file:
        _logger.setup_file_logging(log_file, log_dir)


# Convenience functions that match the existing print-based interface
def log_info(message: str) -> None:
    """Log an info message (replaces print for info)."""
    _logger.info(message)


def log_warning(message: str) -> None:
    """Log a warning message (replaces print for warnings)."""
    _logger.warning(message)


def log_error(message: str) -> None:
    """Log an error message (replaces print for errors)."""
    _logger.error(message)


def log_debug(message: str) -> None:
    """Log a debug message."""
    _logger.debug(message)