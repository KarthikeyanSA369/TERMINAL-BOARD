"""
Test License Audit Engine — Stage 2 Detailed Software License Audit
Tests license classification, all 6 license categories, evidence source types,
Windows activation mapping, database migrations, compliance notes persistence,
and export formats.
"""
import os
import tempfile
import pytest
from unittest.mock import patch

from backend.core.license_audit import (
    classify_license, audit_python_packages, export_audit_to_csv,
    export_audit_to_html, generate_full_license_audit,
    query_windows_activation_status, read_license_file_snippet
)
from backend.database import (
    init_db, migrate_database, save_or_update_license_audit_records,
    update_license_compliance_note, get_all_license_audit_records
)

# 1. Existing baseline tests (backward compatibility)
def test_classify_license_permissive():
    c = classify_license("MIT", None, "Author", "Pkg")
    assert c["status"] == "Verified license information"
    assert "badge-healthy" in c["badge_class"]
    assert c["license_category"] == "Open Source"
    assert c["evidence_source"] == "Vendor-reported licensing information"

def test_classify_license_copyleft():
    c = classify_license("GPL-3.0", None, "Author", "Pkg")
    assert c["status"] == "Review required"
    assert c["license_category"] == "Open Source"
    assert "Reciprocal" in c["status_reason"] or "Copyleft" in c["status_reason"]

def test_classify_license_unknown():
    c = classify_license(None, None, "Author", "Pkg")
    assert c["status"] == "Unknown"
    assert "does not indicate illegal" in c["note"].lower() or "missing license metadata" in c["status_reason"].lower()
    assert c["license_category"] == "Unknown"
    assert c["evidence_source"] == "Unknown or inconclusive evidence"

# 2. Test All 6 Required License Categories
def test_all_six_license_categories():
    # 1. Open Source
    c_os = classify_license("Apache-2.0", None, "Apache Foundation", "Server")
    assert c_os["license_category"] == "Open Source"

    # 2. Commercial
    c_comm = classify_license("Commercial EULA", None, "Microsoft Corporation", "Software")
    assert c_comm["license_category"] == "Commercial"

    # 3. Subscription
    c_sub = classify_license("Microsoft 365 Subscription Channel", None, "Microsoft Corporation", "App")
    assert c_sub["license_category"] == "Subscription"

    # 4. Freeware
    c_free = classify_license("Freeware License", None, "Adobe Systems", "Reader")
    assert c_free["license_category"] == "Freeware"

    # 5. Trial
    c_trial = classify_license("Evaluation Trial (30 days)", None, "TrialVendor", "Utility")
    assert c_trial["license_category"] == "Trial"

    # 6. Unknown
    c_unk = classify_license("", None, "Unknown Vendor", "Mysterious App")
    assert c_unk["license_category"] == "Unknown"

# 3. Test Evidence Sources Distinction
def test_evidence_source_distinction(tmp_path):
    # Vendor-reported
    res_vendor = classify_license("BSD-3-Clause", None, "BSD Org", "Library")
    assert res_vendor["evidence_source"] == "Vendor-reported licensing information"

    # Windows-reported activation
    act_info = {
        "product_name": "Windows(R), Professional edition",
        "description": "Windows(R) Operating System, RETAIL channel",
        "status_code": 1,
        "status_label": "Licensed (Permanent Activation)",
        "is_activated": True
    }
    res_win = classify_license(None, None, "Microsoft Corporation", "Windows", activation_info=act_info)
    assert res_win["evidence_source"] == "Windows-reported activation information"
    assert "Licensed" in res_win["activation_status"]

    # Discovered local license files
    lic_file = tmp_path / "LICENSE.txt"
    lic_file.write_text("MIT License\nCopyright (c) 2026 Test Authors\nPermission is hereby granted...")
    res_file = classify_license(None, str(lic_file), "Local Developer", "LocalTool")
    assert res_file["evidence_source"] == "Discovered local license files"
    assert res_file["license_category"] == "Open Source"
    # Ensure legal disclaimer is included
    assert "does not guarantee user purchase entitlement" in res_file["status_reason"].lower() or \
           "does not guarantee commercial entitlement" in res_file["status_reason"].lower() or \
           "documents software rights" in res_file["status_reason"].lower()

# 4. Test Missing Metadata and Ambiguous Evidence Disclaimers
def test_missing_metadata_disclaimer():
    res = classify_license(None, None, "Acme", "Tool")
    # Verify strict specification requirement:
    # "Missing license metadata does not prove piracy"
    assert "missing license metadata does not indicate" in res["status_reason"].lower() or \
           "does not indicate illegal installation" in res["note"].lower()

# 5. Test Python Packages Audit
def test_audit_python_packages():
    pkgs = audit_python_packages(limit=10)
    assert len(pkgs) > 0
    assert "license_identifier" in pkgs[0]
    assert "verification_status" in pkgs[0]
    assert "license_category" in pkgs[0]
    assert "evidence_source" in pkgs[0]

# 6. Test Windows Activation Mocking
def test_mock_windows_activation_mapping():
    mock_json = '[{"Name": "Windows(R), Enterprise edition", "Description": "Windows VOLUME_KMSCLIENT", "LicenseStatus": 1}]'
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = mock_json
        
        # Test direct activation parsing
        with patch("sys.platform", "win32"):
            # Clear cache for isolated test
            import backend.core.license_audit as lic_module
            lic_module._cached_activation_info = None
            data = query_windows_activation_status()
            assert any("windows" in k for k in data.keys())
            # Clean cache after test
            lic_module._cached_activation_info = None

# 7. Test Database Migration & Compliance Notes Persistence
def test_database_migration_and_compliance_notes():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db_path = f.name

    try:
        # Initialize fresh DB and run migrations
        init_db(temp_db_path)
        migrate_database(temp_db_path)

        records = [
            {
                "name": "SuperCAD",
                "version": "2026.1",
                "publisher": "CAD Systems",
                "category": "Design",
                "license_category": "Commercial",
                "license_identifier": "Commercial EULA",
                "license_source": "Registry",
                "evidence_source": "Vendor-reported licensing information",
                "verification_status": "Verified license information",
                "verification_method": "Installer Registry Metadata",
                "activation_status": "Activation Data Unavailable",
                "file_path": "C:\\Program Files\\SuperCAD\\EULA.txt",
                "status_reason": "Commercial terms verified",
                "notes": "Standard",
                "compliance_notes": "",
                "install_location": "C:\\Program Files\\SuperCAD"
            }
        ]

        # 1. Save record
        save_or_update_license_audit_records(records, db_path=temp_db_path)
        all_records = get_all_license_audit_records(db_path=temp_db_path)
        assert len(all_records) == 1
        assert all_records[0]["name"] == "SuperCAD"
        assert all_records[0]["compliance_notes"] == ""

        # 2. User updates manual compliance note
        note_text = "Enterprise Volume License Agreement #PO-99214 — 50 seats"
        assert update_license_compliance_note("SuperCAD", "2026.1", note_text, db_path=temp_db_path)

        # 3. Check updated note and updated evidence source
        updated = get_all_license_audit_records(db_path=temp_db_path)
        assert updated[0]["compliance_notes"] == note_text

        # 4. Rescan / Re-save: Ensure existing compliance note is NOT overwritten by blank
        records[0]["notes"] = "Updated analysis note from rescan"
        records[0]["compliance_notes"] = ""  # Incoming scanner doesn't have the note
        save_or_update_license_audit_records(records, db_path=temp_db_path)

        persisted_again = get_all_license_audit_records(db_path=temp_db_path)
        assert persisted_again[0]["compliance_notes"] == note_text  # Successfully preserved!

    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)

# 8. Test Export CSV and HTML
def test_export_csv_and_html_with_stage2_fields():
    sample_records = [
        {
            "name": "TestApp",
            "version": "1.0.0",
            "publisher": "Acme Corp",
            "category": "Tool",
            "license_category": "Open Source",
            "license_identifier": "MIT",
            "license_source": "Manifest",
            "evidence_source": "Vendor-reported licensing information",
            "verification_status": "Verified license information",
            "verification_method": "SPDX Package Manifest",
            "activation_status": "Not Applicable (Open Source)",
            "license_file": "C:\\Program Files\\TestApp\\LICENSE",
            "status_reason": "Permissive open source terms declared",
            "notes": "Standard",
            "compliance_notes": "Internal audit approved on 2026-10-18",
            "install_path": "C:\\Program Files\\TestApp",
            "last_audited": "2026-10-18 20:00:00"
        }
    ]

    csv_str = export_audit_to_csv(sample_records)
    assert "TestApp" in csv_str
    assert "Verified license information" in csv_str
    assert "Open Source" in csv_str
    assert "Vendor-reported licensing information" in csv_str
    assert "Internal audit approved on 2026-10-18" in csv_str

    html_str = export_audit_to_html(sample_records)
    assert "SYSFIX — Software License Audit Report" in html_str
    assert "TestApp" in html_str
    assert "Open Source" in html_str
    assert "Internal audit approved on 2026-10-18" in html_str
    assert "Auditing & Compliance Notice" in html_str
