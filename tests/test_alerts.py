"""Test Alert and Notification Engine"""
import pytest
import tempfile
import os
from backend.database import init_db
from backend.core.alerts import evaluate_system_alerts, pop_pending_toasts, _alert_cooldowns

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    try:
        os.remove(path)
    except Exception:
        pass

def test_alert_generation_and_cooldown(monkeypatch, temp_db):
    # Patch database functions in alerts module to use temp_db
    monkeypatch.setattr("backend.core.alerts.get_setting", lambda k, default: "80")
    monkeypatch.setattr("backend.core.alerts.insert_alert", lambda *args: 1)
    monkeypatch.setattr("backend.core.alerts.get_active_alert_by_metric", lambda *args: None)
    monkeypatch.setattr("backend.core.alerts.send_windows_toast_notification", lambda *args: True)

    _alert_cooldowns.clear()

    metrics = {
        "cpu": {"percent": 95.0, "sustained_high_load": True, "logical_cores": 8},
        "ram": {"percent": 40.0, "sustained_pressure": False},
        "disks": []
    }
    drives = []
    network = {"is_connected": True}

    # First run should trigger an alert
    alerts1 = evaluate_system_alerts(metrics, drives, network)
    assert len(alerts1) == 1
    assert alerts1[0]["metric"] == "cpu"

    # Immediate second run should be suppressed by cooldown
    alerts2 = evaluate_system_alerts(metrics, drives, network)
    assert len(alerts2) == 0

    toasts = pop_pending_toasts()
    assert len(toasts) >= 1
    assert "CPU" in toasts[0]["title"]
