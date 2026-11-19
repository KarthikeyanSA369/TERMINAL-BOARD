"""Test SQLite Database Module"""
import os
import tempfile
import pytest
from backend.database import (
    init_db, get_connection, get_setting, set_setting, get_all_settings,
    record_metric_snapshot, get_recent_metrics, insert_alert, get_alerts,
    update_alert_status, get_active_alert_by_metric, cleanup_old_records,
    clear_metric_history, clear_alert_history, clear_all_history
)

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

def test_init_db_and_defaults(temp_db):
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM settings")
    count = cursor.fetchone()[0]
    conn.close()
    assert count >= 5
    assert get_setting("cpu_warning_threshold", db_path=temp_db) == "85"

def test_settings_crud(temp_db):
    set_setting("custom_key", "custom_value", db_path=temp_db)
    assert get_setting("custom_key", db_path=temp_db) == "custom_value"
    set_setting("custom_key", "updated_value", db_path=temp_db)
    assert get_setting("custom_key", db_path=temp_db) == "updated_value"
    all_s = get_all_settings(db_path=temp_db)
    assert "custom_key" in all_s

def test_metric_snapshot_persistence(temp_db):
    data = {
        "cpu_percent": 45.2,
        "ram_percent": 68.1,
        "ram_used_bytes": 8000000,
        "ram_total_bytes": 16000000,
        "battery_percent": 90,
        "is_charging": True,
        "disk_free_gb": 120.5
    }
    record_metric_snapshot(data, db_path=temp_db)
    recent = get_recent_metrics(limit=5, db_path=temp_db)
    assert len(recent) == 1
    assert recent[0]["cpu_percent"] == 45.2
    assert recent[0]["is_charging"] == 1

def test_alerts_lifecycle(temp_db):
    aid = insert_alert("test_cpu", "warning", "High CPU", "CPU load is high", "Evidence: 88%", "Cool down", db_path=temp_db)
    assert aid > 0
    active = get_active_alert_by_metric("test_cpu", db_path=temp_db)
    assert active is not None
    assert active["title"] == "High CPU"

    # Acknowledge
    assert update_alert_status(aid, "acknowledged", db_path=temp_db)
    active_after = get_active_alert_by_metric("test_cpu", db_path=temp_db)
    assert active_after is None

    all_alerts = get_alerts(db_path=temp_db)
    assert len(all_alerts) == 1
    assert all_alerts[0]["status"] == "acknowledged"

def test_clear_and_cleanup(temp_db):
    data = {"cpu_percent": 50, "ram_percent": 50, "ram_used_bytes": 1000, "ram_total_bytes": 2000, "battery_percent": 100, "is_charging": 0, "disk_free_gb": 50}
    record_metric_snapshot(data, db_path=temp_db)
    assert len(get_recent_metrics(db_path=temp_db)) == 1
    clear_metric_history(db_path=temp_db)
    assert len(get_recent_metrics(db_path=temp_db)) == 0
