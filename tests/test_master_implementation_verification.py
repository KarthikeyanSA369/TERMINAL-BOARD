"""
Master implementation verification test suite for SYSFIX / TERMINAL BOARD.
Covers:
- Settings validation, update, and persistence
- Hardware & Drivers count integrity (total = healthy + warning + critical + unavailable)
- All 10 WinPE recovery diagnostic categories with evidence-based data
- Strict zero 'Unknown' string enforcement in recovery reports and driver inventories
- WinPE startup script syntax, drive searches, and safe CMD exit
"""

import json
import os
import re
import pytest

from backend.database import get_all_settings, get_setting, set_setting, init_db
from backend.api import SYSFIXApi
from recovery_cli import run_recovery_diagnostics, format_text_report


def test_settings_validation_and_persistence():
    """Verify settings validation, persistence, and safe defaults."""
    init_db()

    # Update valid settings
    set_setting("theme", "light")
    assert get_setting("theme") == "light"

    set_setting("retention_days", "60")
    assert get_setting("retention_days") == "60"

    # Reset back to dark
    set_setting("theme", "dark")
    assert get_setting("theme") == "dark"

    # Verify all settings dictionary
    all_s = get_all_settings()
    assert isinstance(all_s, dict)
    assert "theme" in all_s
    assert "retention_days" in all_s


def test_driver_inventory_real_scan_and_count_equality():
    """Verify driver inventory returns real devices and counts strictly equal total."""
    api = SYSFIXApi()
    data = api.get_driver_inventory(force_refresh=True)
    assert isinstance(data, dict)
    assert "drivers" in data
    assert "total_count" in data
    assert "healthy_count" in data
    assert "warning_count" in data
    assert "critical_count" in data
    assert "not_available_count" in data

    total = data["total_count"]
    healthy = data["healthy_count"]
    warning = data["warning_count"]
    critical = data["critical_count"]
    not_avail = data["not_available_count"]

    # Rule: summary counts must strictly match total count
    assert total == (healthy + warning + critical + not_avail), (
        f"Driver counts mismatch: total ({total}) != healthy ({healthy}) + "
        f"warning ({warning}) + critical ({critical}) + not_avail ({not_avail})"
    )

    # In a real Windows environment, drivers should be detected
    assert total > 0, "Expected at least 1 real hardware device to be detected on host"
    
    # Devices must have real fields (device_name, provider, status)
    first = data["drivers"][0]
    assert "device_name" in first
    assert "status" in first


def test_ten_winpe_recovery_diagnostic_categories():
    """Verify run_recovery_diagnostics covers all 10 required diagnostic categories."""
    report = run_recovery_diagnostics()
    assert isinstance(report, dict)

    # 1. Windows Boot and Crash Issues
    assert "crash_dumps" in report
    assert "offline_events" in report

    # 2. HDD / SSD and Storage
    assert "mounted_drives" in report
    assert "physical_disks" in report

    # 3. RAM and Memory
    assert "system_memory" in report
    assert report["system_memory"]["total_phys_gb"] > 0
    assert "avail_phys_gb" in report["system_memory"]
    assert "memory_load_percent" in report["system_memory"]

    # 4. CPU and Overheating
    assert "cpu_details" in report

    # 5. Hardware and Drivers
    assert "driver_stats" in report

    # 6. Network Connectivity
    assert "network_details" in report

    # 7. Performance Problems
    assert "performance_details" in report

    # 8. Battery and Power
    assert "battery_details" in report

    # 9. Software and Windows Services
    assert "service_details" in report

    # 10. Security and Configuration
    assert "security_details" in report

    # Common report summary structure
    assert "overall_summary" in report
    assert isinstance(report["overall_summary"], str)
    assert "summary_stats" in report
    stats = report["summary_stats"]
    assert "checks_completed" in stats
    assert "checks_unavailable" in stats
    assert "confirmed_critical_issues" in stats
    assert "warnings_requiring_inspection" in stats
    assert "healthy_checks" in stats

    # Findings list with 10 diagnostic categories represented
    assert "findings" in report
    categories = {f.get("category") for f in report["findings"]}
    assert "Windows Boot and Crash Issues" in categories
    assert "HDD / SSD and Storage" in categories
    assert "RAM and Memory" in categories
    assert "CPU and Overheating" in categories
    assert "Hardware and Drivers" in categories
    assert "Network Connectivity" in categories
    assert "Performance Problems" in categories
    assert "Battery and Power" in categories
    assert "Software and Windows Services" in categories
    assert "Security and Configuration" in categories


def test_zero_unknown_in_recovery_report():
    """Verify strict prohibition of 'Unknown' in generated recovery report text & JSON."""
    report = run_recovery_diagnostics()
    raw_json = json.dumps(report)
    assert '"Unknown"' not in raw_json, "Found forbidden 'Unknown' value in recovery JSON report"

    text = format_text_report(report)
    # Search for whole word 'Unknown' (case-insensitive) in user-facing report text
    matches = re.findall(r"\bunknown\b", text, flags=re.IGNORECASE)
    assert len(matches) == 0, f"Found forbidden 'Unknown' occurrences in text report: {matches}"


def test_winpe_startup_scripts_integrity():
    """Inspect startnet.cmd, winpeshl.ini, and create_winpe_recovery.bat for safety and requirements."""
    base_dir = os.path.dirname(os.path.dirname(__file__))

    # startnet.cmd checks
    startnet_path = os.path.join(base_dir, "winpe", "startnet.cmd")
    assert os.path.isfile(startnet_path)
    with open(startnet_path, "r", encoding="utf-8", errors="ignore") as f:
        startnet_content = f.read()

    assert "wpeinit" in startnet_content.lower()
    assert "x:\\recovery\\terminal_board_recovery.exe" in startnet_content.lower()
    assert "x:\\windows\\system32\\terminal_board_recovery.exe" in startnet_content.lower()
    assert "%%d:\\terminal_board_recovery.exe" in startnet_content.lower()
    assert "%%d:\\recovery\\terminal_board_recovery.exe" in startnet_content.lower()
    assert "%%d:\\sysfix\\dist\\terminal_board_recovery.exe" in startnet_content.lower()
    assert "cmd.exe" in startnet_content.lower()

    # winpeshl.ini checks
    winpeshl_path = os.path.join(base_dir, "winpe", "winpeshl.ini")
    assert os.path.isfile(winpeshl_path)
    with open(winpeshl_path, "r", encoding="utf-8", errors="ignore") as f:
        winpeshl_content = f.read()
    assert "startnet.cmd" in winpeshl_content

    # create_winpe_recovery.bat safety checks
    builder_path = os.path.join(base_dir, "winpe", "create_winpe_recovery.bat")
    assert os.path.isfile(builder_path)
    with open(builder_path, "r", encoding="utf-8", errors="ignore") as f:
        builder_content = f.read()
    # Confirm it does not execute destructive disk formatting commands
    assert not re.search(r"^\s*format\s+[A-Za-z]:", builder_content, re.MULTILINE | re.IGNORECASE)
    assert not re.search(r"^\s*clean\b", builder_content, re.MULTILINE | re.IGNORECASE)
