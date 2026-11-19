"""Test Software Discovery Engine"""
import pytest
from backend.core.software import (
    scan_developer_tools, scan_office_applications,
    scan_registry_installed_apps, get_installed_software_inventory,
    get_fast_curated_tools, get_application_details,
    get_pe_architecture, find_directory_executables
)

def test_scan_developer_tools():
    tools = scan_developer_tools()
    assert len(tools) >= 5
    tool_names = [t["name"] for t in tools]
    assert "Git" in tool_names
    assert "Python" in tool_names

def test_scan_office_applications():
    office = scan_office_applications()
    assert len(office) >= 3
    names = [o["name"] for o in office]
    assert "Microsoft Word" in names

def test_scan_registry():
    apps = scan_registry_installed_apps()
    assert isinstance(apps, list)
    # Windows machine should have registry apps
    assert len(apps) > 0
    assert "name" in apps[0]
    assert "version" in apps[0]

def test_inventory_compilation():
    inv = get_installed_software_inventory()
    assert "curated_tools" in inv
    assert "all_registry_software" in inv
    assert inv["total_detected"] > 0

def test_get_fast_curated_tools():
    tools = get_fast_curated_tools()
    assert len(tools) >= 12
    ids = [t["id"] for t in tools]
    assert "python" in ids
    assert "vscode" in ids
    assert "git" in ids
    assert "word" in ids
    assert "excel" in ids
    assert "powerpoint" in ids

def test_get_application_details_installed():
    py = get_application_details("python")
    assert py is not None
    assert py["name"] == "Python"
    assert py["installed"] is True
    assert py["status"] == "Installed"
    assert "Python 3." in py["version"]
    assert py["exe_path"] != "Not Detected / Unavailable"
    assert "detection_method" in py
    assert "last_verified" in py
    assert "diagnostic_info" in py

def test_get_application_details_not_installed():
    rust = get_application_details("rust")
    assert rust is not None
    assert rust["name"] == "Rust Compiler"
    assert rust["installed"] is False
    assert rust["status"] == "Not Installed"
    assert rust["version"] == "Not Available"
    assert rust["exe_path"] == "Not Detected / Unavailable"
    assert rust["install_location"] == "Not Available"
    assert rust["detected_executables"] == []
    assert "detection_method" in rust

def test_get_application_details_office():
    word = get_application_details("word")
    assert word is not None
    assert word["name"] == "Microsoft Word"
    assert word["category"] == "Productivity"
    assert "last_verified" in word

def test_get_application_details_registry():
    apps = scan_registry_installed_apps()
    if apps:
        app_id = apps[0]["id"]
        res = get_application_details(app_id)
        assert res is not None
        assert res["name"] == apps[0]["name"]
        assert res["status"] in ["Installed", "Partially Detected"]

def test_get_application_details_invalid():
    res = get_application_details("non_existent_app_xyz_123")
    assert res is None
    res_empty = get_application_details("")
    assert res_empty is None
    res_none = get_application_details(None)
    assert res_none is None
