"""Test System Metrics Engine"""
import pytest
from backend.core.metrics import (
    get_cpu_metrics, get_ram_metrics, get_battery_metrics,
    get_disk_volume_metrics, get_temperature_sensors, get_system_uptime,
    format_bytes, collect_all_metrics
)

def test_format_bytes():
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1024 * 1024) == "1.00 MB"
    assert format_bytes(1024 * 1024 * 1024) == "1.00 GB"
    assert format_bytes(None) == "N/A"

def test_cpu_metrics_collection():
    cpu = get_cpu_metrics()
    assert "percent" in cpu
    assert isinstance(cpu["percent"], (int, float))
    assert cpu["logical_cores"] > 0
    assert "history" in cpu
    assert isinstance(cpu["history"], list)

def test_ram_metrics_collection():
    ram = get_ram_metrics()
    assert "percent" in ram
    assert ram["total_bytes"] > 0
    assert ram["used_bytes"] > 0
    assert "history" in ram

def test_battery_metrics_desktop_fallback():
    bat = get_battery_metrics()
    assert "has_battery" in bat
    assert "status" in bat
    assert "time_remaining" in bat

def test_disk_volumes():
    volumes = get_disk_volume_metrics()
    assert isinstance(volumes, list)
    if len(volumes) > 0:
        v = volumes[0]
        assert "mountpoint" in v
        assert "total_bytes" in v
        assert "free_gb" in v

def test_missing_sensors_handled_gracefully():
    sensors = get_temperature_sensors()
    assert "available" in sensors
    assert "message" in sensors
    assert isinstance(sensors["message"], str)

def test_uptime_calculation():
    uptime = get_system_uptime()
    assert uptime["uptime_seconds"] > 0
    assert "boot_time" in uptime
    assert "uptime_formatted" in uptime

def test_collect_all_metrics():
    snapshot = collect_all_metrics()
    assert "cpu" in snapshot
    assert "ram" in snapshot
    assert "battery" in snapshot
    assert "disks" in snapshot
    assert "temperatures" in snapshot
    assert "uptime" in snapshot
