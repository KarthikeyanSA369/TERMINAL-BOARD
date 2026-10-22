"""
Tests for TERMINAL BOARD Windows Startup integration and Offline Recovery CLI.
"""

import os
import sys
import tempfile
import pytest

from backend.core.startup import get_startup_status, set_startup_status
from recovery_cli import (
    get_mounted_drives, inspect_physical_storage, run_recovery_diagnostics,
    format_text_report
)

def test_startup_integration_lifecycle():
    # Initial status check
    status = get_startup_status()
    assert isinstance(status, dict)
    assert "enabled" in status
    assert "can_configure" in status
    assert status["can_configure"] is True

    # Enable startup
    res = set_startup_status(True)
    assert res["success"] is True
    assert res["enabled"] is True

    check_enabled = get_startup_status()
    assert check_enabled["enabled"] is True
    assert len(check_enabled["command"]) > 0

    # Disable startup
    res_dis = set_startup_status(False)
    assert res_dis["success"] is True
    assert res_dis["enabled"] is False

    check_disabled = get_startup_status()
    assert check_disabled["enabled"] is False

def test_recovery_cli_drive_enumeration():
    drives = get_mounted_drives()
    assert isinstance(drives, list)
    assert len(drives) > 0
    # At least one drive should be C: or current system drive
    letters = [d["letter"] for d in drives]
    assert "C" in letters

def test_recovery_cli_storage_inspection():
    disks = inspect_physical_storage()
    assert isinstance(disks, list)
    # Each disk should have standard physical disk fields
    for d in disks:
        assert "device_id" in d
        assert "model" in d
        assert "status" in d

def test_recovery_cli_full_report_and_export():
    data = run_recovery_diagnostics()
    assert isinstance(data, dict)
    assert "mounted_drives" in data
    assert "physical_disks" in data
    assert "overall_summary" in data

    text = format_text_report(data)
    assert "TERMINAL BOARD" in text
    assert "MOUNTED STORAGE VOLUMES" in text
    assert "PHYSICAL STORAGE HARDWARE" in text

    # Test writing report to temp destination
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        tmp_path = f.name
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
        assert os.path.exists(tmp_path)
        assert os.path.getsize(tmp_path) > 100
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
