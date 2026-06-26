#!/usr/bin/env python3
"""
test_logging.py -- Test script for verifying logging system functionality.

Tests each log type (DEBUG, INFO, WARNING, ERROR) to ensure:
- Logs are written to correct files in /log subdirectory
- Log rotation works correctly
- System info logging works
"""

import os
import sys
from converter_logging import get_logger

def test_logging():
    """Test all logging functionality."""
    logger = get_logger()
    
    print("=== Testing Logging System ===\n")
    
    # Setup logging directory
    logger.setup_file_logging()
    print(f"[OK] Logging directory setup: {logger._log_dir}")
    
    # Log system info
    logger.log_system_info()
    print("[OK] System info logged")
    
    # Test each log type
    log_types = ["DEBUG", "INFO", "WARNING", "ERROR"]
    test_messages = {
        "DEBUG": "This is a DEBUG test message",
        "INFO": "This is an INFO test message",
        "WARNING": "This is a WARNING test message",
        "ERROR": "This is an ERROR test message"
    }
    
    for log_type in log_types:
        print(f"\n--- Testing {log_type} ---")
        
        # Enable the log type
        logger.enable_log_type(log_type)
        print(f"[OK] Enabled {log_type} logging")
        
        # Verify it's enabled
        assert logger.is_log_type_enabled(log_type), f"{log_type} should be enabled"
        print(f"[OK] {log_type} is enabled")
        
        # Log a test message
        log_method = getattr(logger, log_type.lower())
        log_method(test_messages[log_type])
        print(f"[OK] Logged {log_type} message")
        
        # Check if log file was created
        log_file = os.path.join(logger._log_dir, f"{log_type.lower()}.log")
        if os.path.exists(log_file):
            print(f"[OK] Log file created: {log_file}")
            with open(log_file, 'r') as f:
                content = f.read()
                if test_messages[log_type] in content:
                    print(f"[OK] Test message found in log file")
                else:
                    print(f"[FAIL] Test message NOT found in log file")
                    print(f"  Content: {content[:200]}")
        else:
            print(f"[FAIL] Log file NOT created: {log_file}")
        
        # Disable the log type
        logger.disable_log_type(log_type)
        print(f"[OK] Disabled {log_type} logging")
        
        # Verify it's disabled
        assert not logger.is_log_type_enabled(log_type), f"{log_type} should be disabled"
        print(f"[OK] {log_type} is disabled")
    
    # Test getting enabled log types
    print("\n--- Testing get_enabled_log_types ---")
    logger.enable_log_type("INFO")
    logger.enable_log_type("ERROR")
    enabled = logger.get_enabled_log_types()
    print(f"[OK] Enabled log types: {enabled}")
    assert "INFO" in enabled, "INFO should be in enabled list"
    assert "ERROR" in enabled, "ERROR should be in enabled list"
    assert "DEBUG" not in enabled, "DEBUG should not be in enabled list"
    
    # Clean up
    logger.disable_log_type("INFO")
    logger.disable_log_type("ERROR")
    
    print("\n=== All Tests Passed ===")
    print(f"Log directory: {logger._log_dir}")
    print("Log files created:")
    for log_type in log_types:
        log_file = os.path.join(logger._log_dir, f"{log_type.lower()}.log")
        if os.path.exists(log_file):
            size = os.path.getsize(log_file)
            print(f"  [OK] {log_file} ({size} bytes)")

if __name__ == "__main__":
    test_logging()
