"""
Tests for License Expiry Engine, Manual Subscriptions, Reminders, and Reporting.
Validates multi-format date parsing, expiry state evaluations, reminder logic,
and database CRUD operations for manual license records.
"""
import pytest
from datetime import datetime, date, timedelta

from backend.core.license_expiry import (
    parse_date_safe,
    evaluate_license_expiry,
    export_expiry_audit_to_csv,
    export_expiry_audit_to_html
)
from backend.database import (
    init_db,
    create_manual_license_record,
    get_manual_license_records,
    update_manual_license_record,
    delete_manual_license_record
)


def test_parse_date_safe():
    """Verify that multiple date string representations parse reliably to date objects."""
    d1 = parse_date_safe("2026-12-31")
    assert d1 == date(2026, 12, 31)

    d2 = parse_date_safe("15/06/2027")
    assert d2 == date(2027, 6, 15)

    d3 = parse_date_safe("October 18, 2026")
    assert d3 == date(2026, 10, 18)

    assert parse_date_safe("Invalid Date String") is None
    assert parse_date_safe(None) is None
    assert parse_date_safe("01-01-1601") is None  # Placeholder non-expiring


def test_evaluate_license_expiry_perpetual():
    """Permanent or commercial perpetual licenses must be evaluated as PERPETUAL."""
    eval_res = evaluate_license_expiry(
        expiry_date_str=None,
        license_category="Open Source",
        raw_status="Licensed"
    )
    assert eval_res["state"] == "PERPETUAL"
    assert eval_res["expiry_date"] is None
    assert eval_res["days_remaining"] is None
    assert "perpetual" in eval_res["reason"].lower()


def test_evaluate_license_expiry_active():
    """A subscription expiring far in the future must be evaluated as ACTIVE."""
    future_date = (datetime.now() + timedelta(days=120)).strftime("%Y-%m-%d")
    eval_res = evaluate_license_expiry(
        expiry_date_str=future_date,
        license_category="Subscription"
    )
    assert eval_res["state"] == "ACTIVE"
    assert eval_res["expiry_date"] == future_date
    assert eval_res["days_remaining"] >= 115


def test_evaluate_license_expiry_expiring_soon():
    """A subscription expiring within warning threshold must trigger EXPIRING_SOON."""
    soon_date = (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d")
    eval_res = evaluate_license_expiry(
        expiry_date_str=soon_date,
        license_category="Subscription",
        warning_threshold_days=30
    )
    assert eval_res["state"] == "EXPIRING_SOON"
    assert eval_res["expiry_date"] == soon_date
    assert eval_res["days_remaining"] == 15
    assert "expires in" in eval_res["reason"].lower()


def test_evaluate_license_expiry_expired():
    """A license past its expiry date must evaluate as EXPIRED."""
    past_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    eval_res = evaluate_license_expiry(
        expiry_date_str=past_date,
        license_category="Subscription"
    )
    assert eval_res["state"] == "EXPIRED"
    assert eval_res["days_remaining"] <= -10
    assert "expired" in eval_res["reason"].lower()


def test_evaluate_license_expiry_grace_period():
    """Grace period statuses must evaluate as GRACE_PERIOD."""
    eval_res = evaluate_license_expiry(
        expiry_date_str=None,
        license_category="Commercial",
        raw_status="---OOB_GRACE---"
    )
    assert eval_res["state"] == "GRACE_PERIOD"


def test_evaluate_license_expiry_unknown():
    """When no date or perpetual evidence exists, return UNKNOWN."""
    eval_res = evaluate_license_expiry(
        expiry_date_str=None,
        license_category="Commercial",
        raw_status="Activation Data Unavailable"
    )
    assert eval_res["state"] == "UNKNOWN"
    assert eval_res["expiry_date"] is None


def test_manual_license_database_crud():
    """Verify complete CRUD lifecycle of manual subscription records in SQLite."""
    init_db()

    # Create
    record_data = {
        "app_name": "Test Enterprise Tool",
        "publisher": "Acme Corp",
        "category": "Subscription",
        "expiry_date": "2027-05-01",
        "reminder_days_before": 14,
        "license_reference": "PO-99120",
        "compliance_notes": "Purchased for backend team"
    }
    new_id = create_manual_license_record(record_data)
    assert new_id > 0

    # Read
    records = get_manual_license_records()
    matched = next((r for r in records if r["id"] == new_id), None)
    assert matched is not None
    assert matched["app_name"] == "Test Enterprise Tool"
    assert matched["license_reference"] == "PO-99120"

    # Update
    update_data = {
        "app_name": "Test Enterprise Tool Updated",
        "publisher": "Acme Corp Worldwide",
        "category": "Enterprise Volume",
        "expiry_date": "2027-06-01",
        "reminder_days_before": 30,
        "license_reference": "PO-99120-REV2",
        "compliance_notes": "Renewed for 2027"
    }
    updated = update_manual_license_record(new_id, update_data)
    assert updated is True

    records_after = get_manual_license_records()
    matched_after = next((r for r in records_after if r["id"] == new_id), None)
    assert matched_after["app_name"] == "Test Enterprise Tool Updated"
    assert matched_after["license_reference"] == "PO-99120-REV2"

    # Delete
    deleted = delete_manual_license_record(new_id)
    assert deleted is True

    records_final = get_manual_license_records()
    assert not any(r["id"] == new_id for r in records_final)


def test_export_expiry_audit_reports():
    """Verify CSV and HTML export generation for license expiry."""
    sample_records = [
        {
            "name": "IntelliJ IDEA Ultimate",
            "publisher": "JetBrains s.r.o.",
            "version": "2024.1",
            "license_category": "Subscription",
            "expiry_state": "EXPIRING_SOON",
            "expiry_date": "2026-11-15",
            "days_until_expiry": 28,
            "expiry_message": "Subscription expires in 28 days"
        }
    ]
    csv_out = export_expiry_audit_to_csv(sample_records)
    assert "IntelliJ IDEA Ultimate" in csv_out
    assert "EXPIRING_SOON" in csv_out

    html_out = export_expiry_audit_to_html(sample_records)
    assert "<!DOCTYPE html>" in html_out
    assert "SYSFIX" in html_out
    assert "IntelliJ IDEA Ultimate" in html_out
