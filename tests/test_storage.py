"""Test Storage and Drive Health Engine"""
import pytest
from backend.core.storage import evaluate_drive_risk, format_bytes, get_drive_health_list

def test_storage_format_bytes():
    assert format_bytes(500107862016) == "465.8 GB"
    assert format_bytes(0) == "Unknown"

def test_evaluate_drive_risk_healthy():
    risk = evaluate_drive_risk("Healthy", "OK", 0, 0, 0)
    assert risk["level"] == "Healthy"
    assert risk["backup_recommended"] is False

def test_evaluate_drive_risk_warning():
    risk = evaluate_drive_risk("Warning", "OK", 100, 0, 0)
    assert risk["level"] == "Warning"
    assert risk["backup_recommended"] is True

def test_evaluate_drive_risk_critical():
    risk = evaluate_drive_risk("Unhealthy", "Degraded", 500, 200, 10)
    assert risk["level"] == "Critical"
    assert risk["backup_recommended"] is True
    assert "immediately" in risk["recommendation"].lower()

def test_evaluate_drive_risk_unknown():
    risk = evaluate_drive_risk("Unknown", "Unknown", None, None, 0)
    assert risk["level"] == "Unknown"

def test_get_drive_health_list():
    drives = get_drive_health_list()
    assert isinstance(drives, list)
    for d in drives:
        assert "model" in d
        assert "risk_level" in d
        assert "telemetry_note" in d
