"""Test Software Discovery Engine"""
import pytest
from backend.core.software import (
    scan_developer_tools, scan_office_applications,
    scan_registry_installed_apps, get_installed_software_inventory
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
