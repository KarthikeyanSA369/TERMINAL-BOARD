"""Test API Bridge and Flask Integration"""
import pytest
from backend.api import SYSFIXApi, create_flask_app

@pytest.fixture
def api_client():
    return SYSFIXApi()

@pytest.fixture
def flask_test_client():
    app = create_flask_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_api_dashboard_data(api_client):
    dash = api_client.get_dashboard_data()
    assert "metrics" in dash
    assert "drives" in dash
    assert "curated_tools" in dash
    assert "overall_health" in dash

def test_api_system_health(api_client):
    sys_h = api_client.get_system_health()
    assert "metrics" in sys_h
    assert "processes" in sys_h

def test_api_settings(api_client):
    s = api_client.get_settings()
    assert "cpu_warning_threshold" in s
    assert api_client.update_setting("custom_test_opt", "test_val")
    s2 = api_client.get_settings()
    assert s2.get("custom_test_opt") == "test_val"

def test_flask_routes(flask_test_client):
    res_dash = flask_test_client.get("/api/dashboard")
    assert res_dash.status_code == 200
    assert "overall_health" in res_dash.get_json()

    res_diag = flask_test_client.get("/api/diagnostics")
    assert res_diag.status_code == 200
    assert isinstance(res_diag.get_json(), list)

    res_settings = flask_test_client.get("/api/settings")
    assert res_settings.status_code == 200

def test_api_license_audit(api_client):
    audit = api_client.get_license_audit()
    assert "records" in audit
    assert "total" in audit
    assert audit["total"] >= 0

    # Test update note
    success = api_client.update_license_compliance_note("MockApp", "1.0", "Internal Compliance Approved")
    assert isinstance(success, bool)

    # Test preview snippet
    preview = api_client.get_license_file_preview("non_existent_license.txt")
    assert "snippet" in preview
    assert preview["success"] is False

def test_flask_license_routes(flask_test_client):
    res_audit = flask_test_client.get("/api/license-audit")
    assert res_audit.status_code == 200
    assert "records" in res_audit.get_json()

    res_notes = flask_test_client.post("/api/license-audit/notes", json={
        "name": "TestSoftware",
        "version": "1.0.0",
        "notes": "Verified by Legal"
    })
    assert res_notes.status_code == 200
    assert res_notes.get_json()["success"] in (True, False)

    res_prev = flask_test_client.post("/api/license-audit/preview", json={
        "file_path": "dummy_path.txt"
    })
    assert res_prev.status_code == 200
    assert "snippet" in res_prev.get_json()

def test_flask_email_routes(flask_test_client, monkeypatch):
    from unittest.mock import MagicMock
    import smtplib

    mock_smtp = MagicMock()
    mock_smtp.has_extn.return_value = True
    monkeypatch.setattr("smtplib.SMTP", MagicMock(return_value=mock_smtp))

    # 1. GET /api/email/settings
    res_get = flask_test_client.get("/api/email/settings")
    assert res_get.status_code == 200
    assert "smtp_host" in res_get.get_json()

    # 2. POST /api/email/settings
    res_post = flask_test_client.post("/api/email/settings", json={
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_use_tls": 1,
        "smtp_sender": "karthikeyansa369@gmail.com",
        "smtp_username": "karthikeyansa369@gmail.com",
        "recipient_email": "karthikeyansa369@gmail.com",
        "smtp_password": "test_app_password"
    })
    assert res_post.status_code == 200
    assert res_post.get_json()["success"] is True

    # 3. POST /api/email/test-connection
    res_conn = flask_test_client.post("/api/email/test-connection", json={
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_use_tls": True,
        "smtp_username": "karthikeyansa369@gmail.com"
    })
    assert res_conn.status_code == 200
    assert res_conn.get_json()["success"] is True

    # 4. POST /api/email/test-email
    res_email = flask_test_client.post("/api/email/test-email", json={
        "recipient": "karthikeyansa369@gmail.com"
    })
    assert res_email.status_code == 200
    assert res_email.get_json()["success"] is True

    # 5. GET /api/email/history
    res_hist = flask_test_client.get("/api/email/history")
    assert res_hist.status_code == 200
    assert isinstance(res_hist.get_json(), list)

    # 6. GET /api/email/queue
    res_queue = flask_test_client.get("/api/email/queue")
    assert res_queue.status_code == 200
    assert isinstance(res_queue.get_json(), list)

def test_flask_startup_routes(flask_test_client):
    # GET /api/startup/status
    res = flask_test_client.get("/api/startup/status")
    assert res.status_code == 200
    data = res.get_json()
    assert "enabled" in data
    assert "can_configure" in data

    # POST /api/startup/toggle (disable to leave clean)
    res_toggle = flask_test_client.post("/api/startup/toggle", json={"enabled": False})
    assert res_toggle.status_code == 200
    assert res_toggle.get_json()["success"] is True

def test_flask_driver_routes(flask_test_client):
    """Test /api/drivers and driver export endpoints."""
    # 1. GET /api/drivers
    res = flask_test_client.get("/api/drivers")
    assert res.status_code == 200
    data = res.get_json()
    assert "drivers" in data
    assert "total_count" in data
    assert "healthy_count" in data
    assert "warning_count" in data
    assert "critical_count" in data
    assert data["total_count"] >= 0
    assert isinstance(data["drivers"], list)

    # 2. GET /api/drivers/export/csv
    res_csv = flask_test_client.get("/api/drivers/export/csv")
    assert res_csv.status_code == 200
    csv_data = res_csv.get_json()
    assert "content" in csv_data
    assert "Device Name" in csv_data["content"]
    assert csv_data["format"] == "csv"

    # 3. GET /api/drivers/export/html
    res_html = flask_test_client.get("/api/drivers/export/html")
    assert res_html.status_code == 200
    html_data = res_html.get_json()
    assert "content" in html_data
    assert "<!DOCTYPE html>" in html_data["content"]
    assert html_data["format"] == "html"



