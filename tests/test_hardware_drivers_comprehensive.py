"""
Comprehensive unit and integration tests for Hardware Devices & Drivers
Validates:
- Real Windows hardware and PnP device discovery
- Accurate driver health classification (HEALTHY, WARNING, CRITICAL, SCAN ERROR, NOT AVAILABLE)
- Safe parsing of PowerShell / CIM dates (positive & negative timestamps)
- Non-usage of 'Unknown' (proper display of 'Not Available')
- API endpoints: /api/drivers, /api/drivers/details, /api/drivers/export/csv, /api/drivers/export/html
- HTML escaping and RFC 4180 CSV compliance
"""

import pytest
import io
import csv
from backend.core.driver_inventory import (
    get_powershell_executable,
    parse_driver_date,
    classify_driver_health,
    get_pnp_problem_info,
    get_complete_driver_inventory,
    export_driver_inventory_to_csv,
    export_driver_inventory_to_html,
    PNP_PROBLEM_CODES
)
from backend.api import SYSFIXApi, create_flask_app


@pytest.fixture
def flask_client():
    app = create_flask_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_powershell_detection():
    """Verify PowerShell executable detection resolves properly on Windows."""
    exe = get_powershell_executable()
    assert exe is not None
    assert "powershell" in exe.lower() or "pwsh" in exe.lower()


def test_driver_date_parsing():
    """Test date parser handles Microsoft JSON dates, CIM timestamps, and negative epochs."""
    # Positive MS JSON date (2006-06-21)
    assert parse_driver_date("/Date(1150848000000)/") == "2006-06-21"

    # Negative MS JSON date (pre-1970 Intel baseline: 1968-07-18)
    assert parse_driver_date("/Date(-45964800000)/") == "1968-07-18"

    # CIM WMI format (20210218...)
    assert parse_driver_date("20210218000000.000000+000") == "2021-02-18"

    # Standard YYYY-MM-DD
    assert parse_driver_date("2023-05-10") == "2023-05-10"

    # None and empty
    assert parse_driver_date(None) == "Not Available"
    assert parse_driver_date("") == "Not Available"
    assert parse_driver_date("Unknown") == "Not Available"


def test_health_classifications_all_states():
    """Verify all health classification categories according to Windows telemetry."""
    # 1. Healthy: Status OK and Code 0
    h = classify_driver_health(status="OK", problem_code=0, device_name="Test Device")
    assert h["level"] == "HEALTHY"
    assert h["badge_class"] == "badge-healthy"

    # 2. Warning: Disabled device (Code 22)
    w_dis = classify_driver_health(status="Disabled", problem_code=22, device_name="Bluetooth")
    assert w_dis["level"] == "WARNING"
    assert w_dis["badge_class"] == "badge-warning"
    assert "disabled" in w_dis["reason"].lower()

    # 3. Warning: Degraded device
    w_deg = classify_driver_health(status="Degraded", problem_code=0, device_name="Intel XTU")
    assert w_deg["level"] == "WARNING"

    # 4. Critical: Code 10, 43, 28, or Error status
    c_10 = classify_driver_health(status="Error", problem_code=10, device_name="PCI Device")
    assert c_10["level"] == "CRITICAL"
    assert c_10["badge_class"] == "badge-critical"

    c_43 = classify_driver_health(status="Error", problem_code=43, device_name="GPU")
    assert c_43["level"] == "CRITICAL"

    # 5. Scan Error
    se = classify_driver_health(status="Error", problem_code=None, scan_error=True)
    assert se["level"] == "SCAN ERROR"
    assert se["badge_class"] == "badge-critical"

    # 6. Not Available
    na = classify_driver_health(status="", problem_code=None)
    assert na["level"] == "NOT AVAILABLE"
    assert na["badge_class"] == "badge-unknown"


def test_no_unknown_terminology():
    """Verify missing fields produce 'Not Available' instead of 'Unknown'."""
    sample = [
        {
            "device_name": "Test Peripheral",
            "device_class": "USB",
            "manufacturer": "",
            "driver_provider": "",
            "driver_version": "",
            "driver_date": "",
            "device_id": "USB\\TEST_01",
            "status": "OK",
            "problem_code": 0
        }
    ]
    csv_out = export_driver_inventory_to_csv(sample)
    assert "Not Available" in csv_out
    assert "Unknown" not in csv_out

    html_out = export_driver_inventory_to_html(sample)
    assert "Not Available" in html_out
    assert "Unknown" not in html_out


def test_api_driver_inventory_endpoint(flask_client):
    """Test /api/drivers returns accurate data structure and computed summary cards."""
    res = flask_client.get("/api/drivers")
    assert res.status_code == 200
    data = res.get_json()

    assert "drivers" in data
    assert "total_count" in data
    assert "healthy_count" in data
    assert "warning_count" in data
    assert "critical_count" in data
    assert "last_checked" in data

    total = data["total_count"]
    healthy = data["healthy_count"]
    warnings = data["warning_count"]
    critical = data["critical_count"]
    scan_errors = data.get("scan_error_count", 0)
    not_avail = data.get("not_available_count", 0)

    # Verification: total count matches sum of classified subsets
    assert total == healthy + warnings + critical + scan_errors + not_avail
    assert total > 0

    # Verify device record schema
    dev = data["drivers"][0]
    required_keys = [
        "device_name", "device_class", "manufacturer",
        "driver_provider", "driver_version", "driver_date",
        "device_id", "status", "problem_code", "health_classification",
        "health_reason"
    ]
    for k in required_keys:
        assert k in dev, f"Missing key {k} in device record"


def test_api_driver_details_endpoint(flask_client):
    """Test /api/drivers/details retrieves device details."""
    inv_res = flask_client.get("/api/drivers")
    data = inv_res.get_json()
    first_dev = data["drivers"][0]
    dev_id = first_dev["device_id"]

    res = flask_client.get(f"/api/drivers/details?device_id={dev_id}")
    assert res.status_code == 200
    details = res.get_json()
    assert "driver" in details
    assert details["driver"] is not None
    assert details["driver"]["device_id"] == dev_id


def test_exports_csv_and_html_generation(flask_client):
    """Test CSV and HTML exports generate content with scan results."""
    # CSV
    res_csv = flask_client.get("/api/drivers/export/csv")
    assert res_csv.status_code == 200
    csv_payload = res_csv.get_json()
    content = csv_payload["content"]
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    assert len(rows) > 1  # Header + at least one device row
    headers = rows[0]
    assert "Device Name" in headers
    assert "Driver Provider" in headers
    assert "Health Classification" in headers

    # HTML
    res_html = flask_client.get("/api/drivers/export/html")
    assert res_html.status_code == 200
    html_payload = res_html.get_json()
    html_content = html_payload["content"]
    assert "<!DOCTYPE html>" in html_content
    assert "Total Devices Scanned" in html_content
    assert "Healthy Drivers" in html_content


def test_html_export_escaping():
    """Verify HTML export properly escapes special characters in device names."""
    malicious = [
        {
            "device_name": "<script>alert('xss')</script> & PCI Device",
            "device_class": "<b>Dangerous</b>",
            "manufacturer": "ACME <Corp>",
            "driver_provider": 'Intel "Special"',
            "driver_version": "1.0 <beta>",
            "driver_date": "2026-01-01",
            "device_id": "TEST_ID",
            "inf_name": "test.inf",
            "status": "OK",
            "problem_code": 0,
            "health_classification": "HEALTHY",
            "health_reason": "Safe & Normal"
        }
    ]
    html_out = export_driver_inventory_to_html(malicious)
    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "&amp; PCI Device" in html_out
    assert "&lt;b&gt;Dangerous&lt;/b&gt;" in html_out
    assert "ACME &lt;Corp&gt;" in html_out
