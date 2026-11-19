"""Test Windows Event Log Engine"""
import pytest
from backend.core.events import get_event_diagnostic, get_recent_windows_events

def test_kernel_power_diagnostic_mapping():
    diag = get_event_diagnostic(41, "Microsoft-Windows-Kernel-Power", "Critical")
    assert diag["category"] == "Unexpected Shutdown"
    assert "rebooted without cleanly" in diag["cause"]

def test_application_crash_diagnostic_mapping():
    diag = get_event_diagnostic(1000, "Application Error", "Error")
    assert diag["category"] == "Application Crash"

def test_disk_error_diagnostic_mapping():
    diag = get_event_diagnostic(7, "disk", "Critical")
    assert diag["category"] == "Storage Controller / Bad Block"
    assert "backup" in diag["steps"].lower()

def test_get_recent_windows_events():
    events = get_recent_windows_events(max_per_log=10)
    assert isinstance(events, list)
    if events:
        ev = events[0]
        assert "event_id" in ev
        assert "provider" in ev
        assert "level" in ev
        assert "suggested_steps" in ev
