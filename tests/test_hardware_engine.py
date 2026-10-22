"""
Unit and Integration Tests for SYSFIX Hardware Diagnostics & Health Assessment Engine
Validates:
1. Hardware Inventory Discovery across all 9 subsystems.
2. Safe Non-Destructive Diagnostic Test Suite.
3. Hardware Error Event Miner (WHEA, Disk, MemoryDiagnostics).
4. Offline Rule-Based Fault Correlation Engine.
5. 20-Section Hardware Report Generation (JSON, TXT, HTML).
6. API Bridge & Progress Polling Integration.
"""

import os
import sys
import json
import time
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.core.hardware_inventory import (
    get_cpu_inventory,
    get_ram_inventory,
    get_storage_inventory,
    get_gpu_inventory,
    get_motherboard_inventory,
    get_cooling_inventory,
    get_battery_inventory,
    get_network_inventory,
    get_additional_devices_inventory,
    get_complete_hardware_inventory
)
from backend.core.hardware_diagnostics import (
    STATUS_HEALTHY,
    STATUS_WARNING,
    STATUS_CRITICAL,
    STATUS_NOT_AVAILABLE,
    STATUS_NOT_TESTED,
    run_cpu_instruction_test,
    run_ram_heap_integrity_test,
    run_storage_read_latency_test,
    run_network_loopback_test,
    collect_hardware_error_events,
    run_hardware_assessment
)
from backend.core.fault_correlation import (
    correlate_faults,
    FaultFinding
)
from backend.core.hardware_report import (
    build_full_report_model,
    export_report_json,
    export_report_txt,
    export_report_html,
    get_default_reports_dir
)
from backend.api import SYSFIXApi


# ============================================================================
# 1. HARDWARE INVENTORY DISCOVERY ENGINE TESTS
# ============================================================================

class TestHardwareInventoryEngine:
    """Tests discovery and schema conformity across all 9 subsystems."""

    def test_cpu_inventory_structure(self):
        cpu_data = get_cpu_inventory()
        assert isinstance(cpu_data, dict)
        assert "model" in cpu_data or "manufacturer" in cpu_data
        assert "physical_cores" in cpu_data
        assert "logical_processors" in cpu_data
        assert "architecture" in cpu_data
        assert "utilization_percent" in cpu_data
        assert cpu_data["physical_cores"] > 0
        assert cpu_data["logical_processors"] >= cpu_data["physical_cores"]

    def test_ram_inventory_structure(self):
        ram_data = get_ram_inventory()
        assert isinstance(ram_data, dict)
        assert "total_bytes" in ram_data
        assert "available_bytes" in ram_data
        assert "used_bytes" in ram_data
        assert "utilization_percent" in ram_data
        assert "installed_modules" in ram_data
        assert isinstance(ram_data["installed_modules"], list)
        assert ram_data["total_bytes"] > 0
        assert 0.0 <= ram_data["utilization_percent"] <= 100.0

    def test_storage_inventory_structure(self):
        storage_data = get_storage_inventory()
        assert isinstance(storage_data, dict)
        assert "physical_disks" in storage_data
        assert "logical_partitions" in storage_data
        assert isinstance(storage_data["physical_disks"], list)
        assert len(storage_data["physical_disks"]) >= 1
        disk = storage_data["physical_disks"][0]
        assert "model" in disk
        assert "capacity_bytes" in disk
        assert "bus_type" in disk

    def test_gpu_inventory_structure(self):
        gpu_data = get_gpu_inventory()
        assert isinstance(gpu_data, dict)
        assert "controllers" in gpu_data
        assert isinstance(gpu_data["controllers"], list)
        if len(gpu_data["controllers"]) > 0:
            adapter = gpu_data["controllers"][0]
            assert "model" in adapter

    def test_motherboard_and_firmware_structure(self):
        mb_data = get_motherboard_inventory()
        assert isinstance(mb_data, dict)
        assert "manufacturer" in mb_data
        assert "product" in mb_data
        assert "bios_vendor" in mb_data
        assert "bios_version" in mb_data

    def test_cooling_inventory_structure(self):
        cooling_data = get_cooling_inventory()
        assert isinstance(cooling_data, dict)
        assert "thermal_zones" in cooling_data
        assert "fans" in cooling_data
        assert "fan_sensor_available" in cooling_data

    def test_battery_inventory_structure(self):
        battery_data = get_battery_inventory()
        assert isinstance(battery_data, dict)
        assert "has_battery" in battery_data
        if not battery_data["has_battery"]:
            assert battery_data.get("is_desktop") is True
        else:
            assert "health_wear_percent" in battery_data
            assert "status" in battery_data

    def test_network_inventory_structure(self):
        net_data = get_network_inventory()
        assert isinstance(net_data, dict)
        assert "adapters" in net_data
        assert isinstance(net_data["adapters"], list)

    def test_additional_devices_inventory_structure(self):
        extra_data = get_additional_devices_inventory()
        assert isinstance(extra_data, dict)
        assert "audio_devices" in extra_data
        assert "monitors" in extra_data
        assert "usb_controllers" in extra_data

    def test_complete_hardware_inventory_aggregation(self):
        inventory = get_complete_hardware_inventory(use_cache=True)
        assert isinstance(inventory, dict)
        for sub in ["cpu", "ram", "storage", "gpu", "motherboard", "cooling", "battery", "network", "additional_devices"]:
            assert sub in inventory


# ============================================================================
# 2. DIAGNOSTIC TEST SUITE & EVENT MINER TESTS
# ============================================================================

class TestHardwareDiagnosticsEngine:
    """Tests safe non-destructive diagnostic tests and error event miner."""

    def test_cpu_instruction_test(self):
        result = run_cpu_instruction_test(timeout_sec=3.0)
        assert "test_name" in result
        assert result["status"] == STATUS_HEALTHY
        assert result["error"] is None
        assert result["duration_ms"] > 0

    def test_ram_heap_integrity_test(self):
        result = run_ram_heap_integrity_test(size_mb=4, timeout_sec=3.0)
        assert "test_name" in result
        assert result["status"] == STATUS_HEALTHY
        assert result["error"] is None
        assert result["bytes_tested"] == 4 * 1024 * 1024

    def test_storage_read_latency_test(self):
        result = run_storage_read_latency_test(mountpoint="C:\\", samples=3)
        assert "test_name" in result
        assert result["status"] in [STATUS_HEALTHY, STATUS_WARNING, STATUS_NOT_AVAILABLE]
        assert result["error"] is None or result["status"] == STATUS_NOT_AVAILABLE

    def test_network_loopback_test(self):
        result = run_network_loopback_test()
        assert "test_name" in result
        assert result["status"] == STATUS_HEALTHY
        assert result["error"] is None

    def test_hardware_error_event_mining(self):
        events = collect_hardware_error_events(hours_back=72)
        assert isinstance(events, list)
        for ev in events:
            assert "event_id" in ev
            assert "source" in ev
            assert "severity" in ev
            assert "timestamp" in ev

    def test_run_hardware_assessment_fast(self):
        assessment = run_hardware_assessment(scan_type="fast")
        assert isinstance(assessment, dict)
        assert "inventory" in assessment
        assert "assessments" in assessment
        assert "diagnostic_tests" in assessment
        assert "summary" in assessment
        assert "overall_status" in assessment
        assert assessment["overall_status"] in [STATUS_HEALTHY, STATUS_WARNING, STATUS_CRITICAL]


# ============================================================================
# 3. RULE-BASED FAULT CORRELATION ENGINE TESTS
# ============================================================================

class TestFaultCorrelationEngine:
    """Tests deterministic correlation rules and discrimination logic."""

    @pytest.fixture
    def mock_inventory(self):
        return {
            "cpu": {"model": "Test CPU", "utilization_percent": 15.0, "physical_cores": 8, "temperature_c": 52.0, "thermal_throttling": False},
            "ram": {"utilization_percent": 60.0, "total_bytes": 16 * 1024**3, "available_bytes": 6 * 1024**3, "total_formatted": "16 GB", "used_formatted": "10 GB"},
            "storage": {
                "physical_disks": [{
                    "model": "Samsung NVMe 980",
                    "status": "HEALTHY",
                    "bus_type": "NVMe",
                    "smart_status": "OK",
                    "nvme_health": {"critical_warning": 0, "available_spare_percent": 100, "percentage_used": 10}
                }]
            },
            "cooling": {"thermal_zones": [{"temperature_c": 50.0}], "fans": [{"speed_rpm": 1800}]},
            "battery": {"has_battery": True, "health_wear_percent": 12.0, "status": "Healthy"},
            "gpu": {"controllers": [{"name": "Discrete GPU", "status": "OK"}]},
            "network": {"adapters": [{"name": "Wi-Fi 6", "status": "Up"}]}
        }

    @pytest.fixture
    def mock_tests(self):
        return {
            "cpu": {"status": STATUS_HEALTHY},
            "ram": {"status": STATUS_HEALTHY},
            "storage": {"status": STATUS_HEALTHY},
            "network": {"status": STATUS_HEALTHY}
        }

    def test_healthy_system_no_critical_findings(self, mock_inventory, mock_tests):
        findings = correlate_faults(
            inventory=mock_inventory,
            error_events=[],
            diagnostic_tests=mock_tests,
            driver_inventory=[]
        )
        critical_findings = [f for f in findings if f.get("severity") == "CRITICAL"]
        assert len(critical_findings) == 0

    def test_resource_saturation_vs_defect_discrimination(self, mock_inventory, mock_tests):
        # Heavy RAM load (96%) with ZERO hardware errors
        high_load_inv = dict(mock_inventory)
        high_load_inv["ram"] = {
            "utilization_percent": 96.0,
            "total_bytes": 16 * 1024**3,
            "available_bytes": 500 * 1024**2,
            "total_formatted": "16 GB",
            "used_formatted": "15.5 GB"
        }

        findings = correlate_faults(
            inventory=high_load_inv,
            error_events=[],
            diagnostic_tests=mock_tests,
            driver_inventory=[]
        )
        # Verifies discrimination: software load is recognized, not hardware defect
        load_finding = [f for f in findings if f.get("finding_id") == "CORR-LOAD-001"]
        assert len(load_finding) == 1
        assert load_finding[0]["severity"] == "INFO"

        # Now simulate actual hardware error event (WHEA 19 memory controller fault)
        simulated_events = [{
            "event_id": 19,
            "source": "microsoft-windows-whea-logger",
            "category": "Hardware / WHEA",
            "severity": "Critical",
            "timestamp": "2026-10-22 12:00:00",
            "message": "A corrected hardware error has occurred in memory hierarchy."
        }]
        findings_with_event = correlate_faults(
            inventory=high_load_inv,
            error_events=simulated_events,
            diagnostic_tests=mock_tests,
            driver_inventory=[]
        )
        mem_findings = [f for f in findings_with_event if f.get("affected_component") == "RAM / Memory Subsystem"]
        assert len(mem_findings) > 0
        assert mem_findings[0]["confidence_level"] == "HIGH"

    def test_storage_disk_fault_correlation(self, mock_inventory, mock_tests):
        failing_storage_inv = dict(mock_inventory)
        failing_storage_inv["storage"] = {
            "physical_disks": [{
                "model": "Faulty Drive",
                "status": "CRITICAL",
                "bus_type": "SATA",
                "operational_status": "Pred Fail",
                "health_status": "Degraded",
                "read_errors": 45,
                "write_errors": 12
            }]
        }
        simulated_disk_events = [
            {
                "event_id": 7,
                "source": "disk",
                "category": "Storage / Disk",
                "severity": "Critical",
                "timestamp": "2026-10-22 13:00:00",
                "message": "The device \\Device\\Harddisk0\\DR0 has a bad block."
            },
            {
                "event_id": 153,
                "source": "disk",
                "category": "Storage / Disk",
                "severity": "Warning",
                "timestamp": "2026-10-22 13:05:00",
                "message": "The IO operation at logical block address was retried."
            }
        ]
        findings = correlate_faults(
            inventory=failing_storage_inv,
            error_events=simulated_disk_events,
            diagnostic_tests=mock_tests
        )
        storage_findings = [f for f in findings if f.get("affected_component") == "Storage Subsystem"]
        assert len(storage_findings) > 0
        assert storage_findings[0]["severity"] == "CRITICAL"


# ============================================================================
# 4. REPORT GENERATION ENGINE TESTS (JSON, TXT, HTML)
# ============================================================================

class TestHardwareReportGenerator:
    """Validates 20-section report generation across all formats."""

    @pytest.fixture(scope="class")
    def assessment_data(self):
        return run_hardware_assessment(scan_type="fast")

    @pytest.fixture(scope="class")
    def full_report(self, assessment_data):
        findings = correlate_faults(
            inventory=assessment_data["inventory"],
            error_events=assessment_data["error_events"],
            diagnostic_tests=assessment_data["diagnostic_tests"]
        )
        return build_full_report_model(assessment_data, findings)

    def test_report_schema_has_20_sections(self, full_report):
        assert "report_metadata" in full_report
        # Verify 20 explicit sections exist
        for i in range(1, 21):
            matching_keys = [k for k in full_report.keys() if f"section_{i}_" in k]
            assert len(matching_keys) == 1, f"Missing section_{i} in report model"

    def test_export_json(self, full_report):
        json_path = export_report_json(full_report)
        assert os.path.exists(json_path)
        assert json_path.endswith(".json")
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "report_metadata" in data

    def test_export_txt(self, full_report):
        txt_path = export_report_txt(full_report)
        assert os.path.exists(txt_path)
        assert txt_path.endswith(".txt")
        with open(txt_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "SYSFIX -- COMPLETE HARDWARE DIAGNOSTICS & HEALTH ASSESSMENT REPORT" in content
        assert "SECTION 1: EXECUTIVE SUMMARY" in content

    def test_export_html(self, full_report):
        html_path = export_report_html(full_report)
        assert os.path.exists(html_path)
        assert html_path.endswith(".html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        assert "<!DOCTYPE html>" in html
        assert "SYSFIX Complete Hardware Diagnostics Report" in html


# ============================================================================
# 5. API BRIDGE & REST ENDPOINT TESTS
# ============================================================================

class TestHardwareApiBridge:
    """Validates Flask REST endpoints and SYSFIXApi integration."""

    @pytest.fixture(scope="class")
    def api_instance(self):
        return SYSFIXApi()

    def test_compatibility_matrix(self, api_instance):
        matrix_res = api_instance.get_hardware_compatibility_matrix()
        assert isinstance(matrix_res, list)
        assert len(matrix_res) >= 9
        row = matrix_res[0]
        assert "category" in row
        assert "check_item" in row
        assert "normal_windows" in row
        assert "winpe_status" in row
        assert "admin_required" in row

    def test_hardware_scan_lifecycle(self, api_instance):
        # Check initial progress state
        init_progress = api_instance.get_hardware_scan_progress()
        assert isinstance(init_progress, dict)
        assert "is_running" in init_progress
        assert "progress_percent" in init_progress

        # Trigger fast scan
        start_res = api_instance.start_hardware_scan(scan_type="fast")
        assert start_res["success"] is True

        # Poll scan progress
        start_time = time.time()
        while time.time() - start_time < 30:
            prog = api_instance.get_hardware_scan_progress()
            if not prog["is_running"]:
                break
            time.sleep(0.5)

        final_prog = api_instance.get_hardware_scan_progress()
        assert final_prog["is_running"] is False
        assert final_prog["progress_percent"] == 100
        assert final_prog["current_stage"] == "Complete"

        # Verify latest report retrieval
        latest = api_instance.get_latest_hardware_report()
        assert latest is not None
        assert "report_metadata" in latest
        assert "section_1_executive_summary" in latest

        # Verify report export via API
        exp_res = api_instance.export_hardware_report(format_type="json")
        assert exp_res["success"] is True
        assert os.path.exists(exp_res["file_path"])
