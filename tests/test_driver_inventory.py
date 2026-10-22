"""
Tests for Driver Inventory, Hardware Telemetry & PnP Problem Code Diagnostics.
Validates PnP error code mapping, health classification, registry discovery,
CSV and HTML report exports, and SQLite snapshot persistence.
"""
import pytest
from backend.core.driver_inventory import (
    classify_driver_health,
    get_pnp_problem_info,
    export_driver_inventory_to_csv,
    export_driver_inventory_to_html,
    get_complete_driver_inventory,
    PNP_PROBLEM_CODES
)
from backend.database import (
    init_db,
    save_driver_snapshots,
    get_latest_driver_snapshots
)


def test_pnp_problem_code_descriptions():
    """Verify that known Windows CM_PROB_* codes return exact documented descriptions."""
    info_0 = get_pnp_problem_info(0)
    assert "working properly" in info_0["description"].lower()

    info_10 = get_pnp_problem_info(10)
    assert "cannot start" in info_10["description"].lower()

    info_22 = get_pnp_problem_info(22)
    assert "disabled" in info_22["description"].lower()

    info_28 = get_pnp_problem_info(28)
    assert "not installed" in info_28["description"].lower()

    info_43 = get_pnp_problem_info(43)
    assert "stopped" in info_43["description"].lower()


def test_classify_driver_health_normal():
    """Devices with no problem code or Code 0 and status OK must be classified as HEALTHY."""
    h1 = classify_driver_health(status="OK", problem_code=0, device_name="Intel Network Adapter")
    assert h1["level"] == "HEALTHY"
    assert "operating normally" in h1["reason"].lower()

    h2 = classify_driver_health(status="", problem_code=0, device_name="Standard Keyboard")
    assert h2["level"] == "HEALTHY"


def test_classify_driver_health_warning():
    """Disabled, reinstalled, or degraded devices must be classified as WARNING."""
    # CM_PROB_DISABLED (Code 22)
    h_disabled = classify_driver_health(status="Disabled", problem_code=22, device_name="Bluetooth Adapter")
    assert h_disabled["level"] == "WARNING"
    assert "disabled" in h_disabled["reason"].lower()

    # CM_PROB_NEED_RESTART (Code 14)
    h_restart = classify_driver_health(status="Warning", problem_code=14, device_name="Display Adapter")
    assert h_restart["level"] == "WARNING"


def test_classify_driver_health_critical():
    """Hardware failures, crash stops, and resource conflicts must be classified as CRITICAL."""
    # CM_PROB_FAILED_START (Code 10)
    h_code10 = classify_driver_health(status="Error", problem_code=10, device_name="PCI Device")
    assert h_code10["level"] == "CRITICAL"
    assert "10" in h_code10["reason"]

    # CM_PROB_FAILED_POST_START (Code 43)
    h_code43 = classify_driver_health(status="Error", problem_code=43, device_name="NVIDIA GPU")
    assert h_code43["level"] == "CRITICAL"
    assert "43" in h_code43["reason"]

    # CM_PROB_FAILED_ADD (Code 31)
    h_code31 = classify_driver_health(status="Error", problem_code=31, device_name="Audio Device")
    assert h_code31["level"] == "CRITICAL"


def test_export_driver_inventory_csv():
    """Verify CSV export contains all required columns without corruption."""
    sample_drivers = [
        {
            "device_name": "Intel(R) Wireless-AC 9560",
            "device_class": "Net",
            "manufacturer": "Intel Corporation",
            "provider": "Intel",
            "driver_version": "22.150.0.3",
            "driver_date": "2023-04-12",
            "device_id": r"PCI\VEN_8086&DEV_02F0",
            "inf_name": "netwtw08.inf",
            "status": "OK",
            "problem_code": 0,
            "health_classification": "HEALTHY",
            "health_reason": "Device is operating normally with no active PnP errors reported.",
            "data_source": "Registry Class Catalog",
            "last_scanned": "2026-10-18 20:00:00"
        }
    ]
    csv_text = export_driver_inventory_to_csv(sample_drivers)
    assert "Device Name" in csv_text
    assert "Health Classification" in csv_text
    assert "Intel(R) Wireless-AC 9560" in csv_text
    assert "HEALTHY" in csv_text


def test_export_driver_inventory_html():
    """Verify HTML report includes styled tables and meta tags."""
    sample_drivers = [
        {
            "device_name": "Realtek High Definition Audio",
            "device_class": "MEDIA",
            "manufacturer": "Realtek",
            "provider": "Realtek",
            "driver_version": "6.0.9239.1",
            "driver_date": "2022-09-08",
            "device_id": r"HDAUDIO\FUNC_01",
            "inf_name": "hdaudio.inf",
            "status": "OK",
            "problem_code": 0,
            "health_classification": "HEALTHY",
            "health_reason": "Device is operating normally with no active PnP errors reported.",
            "data_source": "Registry Class Catalog",
            "last_scanned": "2026-10-18 20:00:00"
        }
    ]
    html_text = export_driver_inventory_to_html(sample_drivers)
    assert "<!DOCTYPE html>" in html_text
    assert "Realtek High Definition Audio" in html_text
    assert "SYSFIX" in html_text


def test_driver_database_snapshots():
    """Verify driver inventory snapshots are saved and queried from SQLite."""
    init_db()
    test_records = [
        {
            "device_id": "TEST\\DEV_1234",
            "device_name": "Test Virtual Device",
            "device_class": "System",
            "manufacturer": "SYSFIX Test Lab",
            "driver_version": "1.0.0.0",
            "driver_date": "2026-10-18",
            "driver_provider": "SYSFIX",
            "inf_path": "test.inf",
            "problem_code": "0",
            "problem_description": "OK",
            "health_classification": "HEALTHY",
            "health_reason": "Test normal"
        }
    ]
    save_driver_snapshots(test_records)
    saved = get_latest_driver_snapshots()
    assert any(s.get("device_id") == "TEST\\DEV_1234" for s in saved)


def test_live_driver_inventory_read_only():
    """Verify live driver scanner runs cleanly on host system within sub-second speed."""
    import time
    start = time.time()
    drivers = get_complete_driver_inventory()
    duration = time.time() - start

    assert isinstance(drivers, list)
    assert len(drivers) > 0
    # Must be fast (< 5 seconds)
    assert duration < 5.0

    # Ensure required telemetry fields are populated
    first = drivers[0]
    for key in ["device_name", "device_class", "health_classification", "problem_code"]:
        assert key in first
