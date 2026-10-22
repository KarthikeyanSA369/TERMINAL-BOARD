"""
SYSFIX Comprehensive Hardware Diagnostic Report Generator
Produces the complete 20-section Hardware Diagnostic Report from a unified data model.
Exports to:
- JSON (complete structured diagnostic tree)
- TXT (clean ASCII tables, headings, and detailed evidence)
- HTML (standalone Dark Neumorphic responsive report)

Saves timestamped files to 'reports/' directory without overwriting previous runs.
Handles large inventories without truncation.
"""

import os
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional


def get_default_reports_dir() -> str:
    """Returns local project reports directory."""
    import sys
    if getattr(sys, "frozen", False):
        # In PyInstaller frozen bundle, save reports adjacent to the running executable
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    reports_dir = os.path.join(base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    return reports_dir


def build_full_report_model(
    assessment_result: Dict[str, Any],
    correlated_findings: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Compiles the unified 20-section report model from assessment data
    and correlated fault findings.
    """
    inv = assessment_result.get("inventory", {})
    assess = assessment_result.get("assessments", {})
    events = assessment_result.get("error_events", [])
    tests = assessment_result.get("diagnostic_tests", {})
    summary = assessment_result.get("summary", {})
    scan_t = assessment_result.get("scan_timestamp", time.strftime("%Y-%m-%d %H:%M:%S"))
    scan_dur = assessment_result.get("scan_duration_ms", 0.0)

    # Compile 20 Sections
    report: Dict[str, Any] = {
        "report_metadata": {
            "title": "SYSFIX Complete Hardware Diagnostics & Health Assessment Report",
            "version": "2.0.0",
            "generated_at": scan_t,
            "scan_type": assessment_result.get("scan_type", "fast").upper(),
            "overall_status": assessment_result.get("overall_status", "HEALTHY"),
            "host_name": inv.get("system_host", "Unknown Host"),
            "os_platform": inv.get("os_platform", "Windows")
        },
        "section_1_executive_summary": {
            "overall_health": assessment_result.get("overall_status", "HEALTHY"),
            "total_components_inspected": summary.get("total_components", 0),
            "passed_healthy": summary.get("passed", 0),
            "warnings_detected": summary.get("warning", 0),
            "critical_failures": summary.get("critical", 0),
            "untested_diagnostics": summary.get("untested", 0),
            "unavailable_sensors": summary.get("unavailable", 0),
            "fault_findings_count": len(correlated_findings),
            "summary_statement": (
                f"Diagnostic scan completed with {summary.get('passed', 0)} of {summary.get('total_components', 0)} components evaluated as HEALTHY. "
                + (f"Identified {len(correlated_findings)} rule-based diagnostic findings requiring review." if correlated_findings else "Zero critical hardware failure conditions or anomalies detected.")
            )
        },
        "section_2_system_identification": {
            "host_name": inv.get("system_host"),
            "motherboard_manufacturer": inv.get("motherboard", {}).get("manufacturer"),
            "motherboard_product": inv.get("motherboard", {}).get("product"),
            "motherboard_serial": inv.get("motherboard", {}).get("serial_number"),
            "bios_vendor": inv.get("motherboard", {}).get("bios_vendor"),
            "bios_version": inv.get("motherboard", {}).get("bios_version"),
            "bios_release_date": inv.get("motherboard", {}).get("bios_release_date"),
            "smbios_version": inv.get("motherboard", {}).get("smbios_version")
        },
        "section_3_hardware_inventory": inv,
        "section_4_cpu_diagnostics": {
            "telemetry": inv.get("cpu", {}),
            "assessment": assess.get("cpu", {})
        },
        "section_5_ram_diagnostics": {
            "telemetry": inv.get("ram", {}),
            "assessment": assess.get("ram", {})
        },
        "section_6_storage_diagnostics": {
            "telemetry": inv.get("storage", {}),
            "assessment": assess.get("storage", {})
        },
        "section_7_gpu_diagnostics": {
            "telemetry": inv.get("gpu", {}),
            "assessment": assess.get("gpu", {})
        },
        "section_8_motherboard_and_firmware": {
            "telemetry": inv.get("motherboard", {}),
            "assessment": assess.get("motherboard", {})
        },
        "section_9_cooling_and_temperature_analysis": {
            "telemetry": inv.get("cooling", {}),
            "cpu_thermal_state": {
                "temperature_c": inv.get("cpu", {}).get("temperature_c"),
                "temperature_status": inv.get("cpu", {}).get("temperature_status"),
                "thermal_throttling": inv.get("cpu", {}).get("thermal_throttling"),
                "throttling_status": inv.get("cpu", {}).get("throttling_status")
            },
            "assessment": assess.get("cooling", {})
        },
        "section_10_battery_health": {
            "telemetry": inv.get("battery", {}),
            "assessment": assess.get("battery", {})
        },
        "section_11_network_adapter_diagnostics": {
            "telemetry": inv.get("network", {}),
            "assessment": assess.get("network", {})
        },
        "section_12_additional_device_inventory": {
            "telemetry": inv.get("additional_devices", {}),
            "assessment": assess.get("additional_devices", {})
        },
        "section_13_hardware_error_events": {
            "total_events_scanned": len(events),
            "recent_events": events
        },
        "section_14_diagnostic_test_results": tests,
        "section_15_rule_based_fault_correlation": correlated_findings,
        "section_16_identified_warnings_and_critical_findings": [f for f in correlated_findings if f.get("severity") in ("CRITICAL", "WARNING")],
        "section_17_recommended_actions": [act for f in correlated_findings for act in f.get("recommended_actions", [])],
        "section_18_test_coverage": {
            "categories_covered": list(assess.keys()),
            "total_subsystems": len(assess),
            "active_tests_executed": len(tests)
        },
        "section_19_missing_data_and_limitations": [
            "ACPI thermal zone temperature sensors require administrator elevation or OEM EC drivers on modern Windows 10/11.",
            "Hardware cooling fan tachometer RPM is not exposed by standard ACPI without proprietary OEM sensor drivers (e.g. HP CoolSense / ASUS Armoury).",
            "NVMe SMART low-level reliability counters require elevated administrative privileges (MSFT_StorageReliabilityCounter)."
        ],
        "section_20_scan_duration_and_performance": {
            "total_scan_duration_ms": scan_dur,
            "scan_mode": assessment_result.get("scan_type"),
            "inventory_cache_used": (assessment_result.get("scan_type") == "fast")
        }
    }

    return report


# =========================================================================
# Report Exporters: JSON, TXT, HTML
# =========================================================================

def export_report_json(report_data: Dict[str, Any], output_path: Optional[str] = None) -> str:
    """Exports structured diagnostic report as formatted JSON."""
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(get_default_reports_dir(), f"SYSFIX_Hardware_Report_{ts}.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    return output_path


def export_report_txt(report_data: Dict[str, Any], output_path: Optional[str] = None) -> str:
    """Exports comprehensive human-readable ASCII text report."""
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(get_default_reports_dir(), f"SYSFIX_Hardware_Report_{ts}.txt")

    meta = report_data.get("report_metadata", {})
    exec_sum = report_data.get("section_1_executive_summary", {})
    inv = report_data.get("section_3_hardware_inventory", {})
    assess = report_data.get("report_metadata", {})
    findings = report_data.get("section_15_rule_based_fault_correlation", [])
    tests = report_data.get("section_14_diagnostic_test_results", {})

    lines = []
    lines.append("=" * 80)
    lines.append("   SYSFIX -- COMPLETE HARDWARE DIAGNOSTICS & HEALTH ASSESSMENT REPORT")
    lines.append("=" * 80)
    lines.append(f" Generated: {meta.get('generated_at')} | Host: {meta.get('host_name')} | Platform: {meta.get('os_platform')}")
    lines.append(f" Overall Status: {meta.get('overall_status')} | Mode: {meta.get('scan_type')} | Report Version: {meta.get('version')}")
    lines.append("-" * 80)
    lines.append("")

    # Section 1: Executive Summary
    lines.append("SECTION 1: EXECUTIVE SUMMARY")
    lines.append("----------------------------")
    lines.append(f" Overall Health Status:   {exec_sum.get('overall_health')}")
    lines.append(f" Total Components:        {exec_sum.get('total_components_inspected')}")
    lines.append(f" Passed (Healthy):        {exec_sum.get('passed_healthy')}")
    lines.append(f" Warnings:                {exec_sum.get('warnings_detected')}")
    lines.append(f" Critical Failures:       {exec_sum.get('critical_failures')}")
    lines.append(f" Correlated Faults:       {exec_sum.get('fault_findings_count')}")
    lines.append(f" Summary: {exec_sum.get('summary_statement')}")
    lines.append("")

    # Section 2: System Identification
    sys_id = report_data.get("section_2_system_identification", {})
    lines.append("SECTION 2: SYSTEM IDENTIFICATION")
    lines.append("--------------------------------")
    lines.append(f" Host Name:          {sys_id.get('host_name')}")
    lines.append(f" Motherboard:        {sys_id.get('motherboard_manufacturer')} {sys_id.get('motherboard_product')} (Serial: {sys_id.get('motherboard_serial')})")
    lines.append(f" BIOS / Firmware:    {sys_id.get('bios_vendor')} Version {sys_id.get('bios_version')} (Released: {sys_id.get('bios_release_date')})")
    lines.append(f" SMBIOS Version:     {sys_id.get('smbios_version')}")
    lines.append("")

    # Section 3-6: Component Summaries
    lines.append("SECTION 3-12: HARDWARE COMPONENT HEALTH ASSESSMENTS")
    lines.append("--------------------------------------------------")
    for sec_num, sec_key in [
        (4, "section_4_cpu_diagnostics"),
        (5, "section_5_ram_diagnostics"),
        (6, "section_6_storage_diagnostics"),
        (7, "section_7_gpu_diagnostics"),
        (8, "section_8_motherboard_and_firmware"),
        (9, "section_9_cooling_and_temperature_analysis"),
        (10, "section_10_battery_health"),
        (11, "section_11_network_adapter_diagnostics"),
        (12, "section_12_additional_device_inventory")
    ]:
        sec = report_data.get(sec_key, {})
        comp_name = sec.get("assessment", {}).get("component", sec_key.replace("section_", "").replace("_diagnostics", "").upper())
        status = sec.get("assessment", {}).get("health_status", "NOT EVALUATED")
        reasons = "; ".join(sec.get("assessment", {}).get("reasons", []))
        lines.append(f" [{comp_name.upper():<18}] Status: {status:<12} | Evaluation: {reasons}")
        for ev in sec.get("assessment", {}).get("evidence", []):
            lines.append(f"   * Evidence: {ev}")
        lines.append("")

    # Section 13: Hardware Events
    hw_events = report_data.get("section_13_hardware_error_events", {}).get("recent_events", [])
    lines.append("SECTION 13: HARDWARE ERROR EVENTS (PAST 72 HOURS)")
    lines.append("-------------------------------------------------")
    if hw_events:
        for ev in hw_events[:10]:
            lines.append(f" [{ev.get('timestamp')}] {ev.get('category')} | Event ID {ev.get('event_id')} | {ev.get('severity')}")
            lines.append(f"   Source: {ev.get('source')} -- {ev.get('message')}")
    else:
        lines.append(" Zero hardware error events (WHEA, Disk, MemoryDiagnostics) recorded in System log.")
    lines.append("")

    # Section 14: Diagnostic Tests
    lines.append("SECTION 14: ACTIVE DIAGNOSTIC TEST RESULTS")
    lines.append("------------------------------------------")
    if tests:
        for t_key, t_val in tests.items():
            lines.append(f" - {t_val.get('test_name')}: {t_val.get('status')} ({t_val.get('duration_ms')} ms)")
            lines.append(f"   Details: {t_val.get('details')}")
    else:
        lines.append(" Active diagnostic stress tests were skipped in Fast Scan mode.")
    lines.append("")

    # Section 15-16: Correlated Findings
    lines.append("SECTION 15-16: RULE-BASED FAULT CORRELATION FINDINGS")
    lines.append("----------------------------------------------------")
    if findings:
        for f in findings:
            lines.append(f" [FINDING: {f.get('finding_id')}] Severity: {f.get('severity')} | Confidence: {f.get('confidence_level')}")
            lines.append(f" Title:   {f.get('title')}")
            lines.append(f" Summary: {f.get('summary')}")
            lines.append(" Supporting Evidence:")
            for ev in f.get("supporting_evidence", []):
                lines.append(f"   - {ev}")
            lines.append(" Possible Causes:")
            for c in f.get("possible_causes", []):
                lines.append(f"   - {c}")
            lines.append(" Recommended Actions:")
            for a in f.get("recommended_actions", []):
                lines.append(f"   - {a}")
            lines.append("")
    else:
        lines.append(" Zero fault correlation rules triggered. All subsystems operating within expected parameters.")
    lines.append("")

    # Section 19: Limitations
    lines.append("SECTION 19: LIMITATIONS & MISSING DATA")
    lines.append("--------------------------------------")
    for lim in report_data.get("section_19_missing_data_and_limitations", []):
        lines.append(f" * {lim}")
    lines.append("")

    # Section 20: Performance
    perf = report_data.get("section_20_scan_duration_and_performance", {})
    lines.append("SECTION 20: SCAN DURATION & PERFORMANCE")
    lines.append("---------------------------------------")
    lines.append(f" Total Scan Execution Time: {perf.get('total_scan_duration_ms')} ms")
    lines.append("=" * 80)

    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path


def export_report_html(report_data: Dict[str, Any], output_path: Optional[str] = None) -> str:
    """Exports complete responsive standalone Dark Neumorphic HTML diagnostic report."""
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(get_default_reports_dir(), f"SYSFIX_Hardware_Report_{ts}.html")

    meta = report_data.get("report_metadata", {})
    exec_sum = report_data.get("section_1_executive_summary", {})
    sys_id = report_data.get("section_2_system_identification", {})
    inv = report_data.get("section_3_hardware_inventory", {})
    findings = report_data.get("section_15_rule_based_fault_correlation", [])
    tests = report_data.get("section_14_diagnostic_test_results", {})
    events = report_data.get("section_13_hardware_error_events", {}).get("recent_events", [])

    status_badge_color = {
        "HEALTHY": "#45D6A3",
        "WARNING": "#FFC66D",
        "CRITICAL": "#FF647C",
        "NOT TESTED": "#A2ACC0",
        "NOT AVAILABLE": "#7C83FF",
        "UNKNOWN": "#64748B"
    }

    # Generate Findings HTML
    findings_html = ""
    if findings:
        for f in findings:
            sev_col = "#FF647C" if f.get("severity") == "CRITICAL" else ("#FFC66D" if f.get("severity") == "WARNING" else "#7C83FF")
            ev_items = "".join(f"<li>{ev}</li>" for ev in f.get("supporting_evidence", []))
            cause_items = "".join(f"<li>{c}</li>" for c in f.get("possible_causes", []))
            act_items = "".join(f"<li>{a}</li>" for a in f.get("recommended_actions", []))

            findings_html += f"""
            <div style="background: #1E2538; border-radius: 8px; border-left: 4px solid {sev_col}; padding: 16px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 11px; font-weight: 700; color: {sev_col}; background: rgba(255,255,255,0.06); padding: 3px 8px; border-radius: 4px;">{f.get('finding_id')} • {f.get('severity')}</span>
                    <span style="font-size: 11px; color: #8F9BB3;">Confidence: {f.get('confidence_level')}</span>
                </div>
                <h4 style="color: #F4F6FC; margin: 8px 0 4px 0; font-size: 15px;">{f.get('title')}</h4>
                <p style="color: #A2ACC0; font-size: 13px; margin: 0 0 10px 0;">{f.get('summary')}</p>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 10px;">
                    <div>
                        <strong style="font-size: 11px; color: #7C83FF; text-transform: uppercase;">Supporting Evidence:</strong>
                        <ul style="font-size: 12px; color: #CBD5E1; margin: 4px 0 0 16px; padding: 0;">{ev_items}</ul>
                    </div>
                    <div>
                        <strong style="font-size: 11px; color: #FFC66D; text-transform: uppercase;">Possible Causes:</strong>
                        <ul style="font-size: 12px; color: #CBD5E1; margin: 4px 0 0 16px; padding: 0;">{cause_items}</ul>
                    </div>
                </div>
                <div style="background: rgba(124, 131, 255, 0.08); padding: 10px; border-radius: 6px; margin-top: 10px;">
                    <strong style="font-size: 11px; color: #7C83FF; text-transform: uppercase;">Recommended Actions:</strong>
                    <ul style="font-size: 12px; color: #CBD5E1; margin: 4px 0 0 16px; padding: 0;">{act_items}</ul>
                </div>
            </div>
            """
    else:
        findings_html = """
        <div style="background: rgba(69, 214, 163, 0.08); border-left: 4px solid #45D6A3; padding: 14px; border-radius: 6px; color: #45D6A3; font-size: 13px;">
            <strong>Zero Hardware Faults Detected:</strong> All diagnostic signals and correlation rules evaluated normally. No hardware degradation or stability anomalies identified.
        </div>
        """

    # Generate Component Cards HTML
    comp_cards_html = ""
    for sec_key, title, icon in [
        ("section_4_cpu_diagnostics", "CPU / Processor", "CPU"),
        ("section_5_ram_diagnostics", "RAM / Memory", "RAM"),
        ("section_6_storage_diagnostics", "Storage (SSD/HDD/NVMe)", "STORAGE"),
        ("section_7_gpu_diagnostics", "GPU / Graphics", "GPU"),
        ("section_8_motherboard_and_firmware", "Motherboard & BIOS", "MOBO"),
        ("section_9_cooling_and_temperature_analysis", "Cooling & Thermals", "COOLING"),
        ("section_10_battery_health", "Battery Health", "BATTERY"),
        ("section_11_network_adapter_diagnostics", "Network Devices", "NETWORK"),
        ("section_12_additional_device_inventory", "Additional Devices", "PERIPHERAL")
    ]:
        sec = report_data.get(sec_key, {})
        assess = sec.get("assessment", {})
        stat = assess.get("health_status", "HEALTHY")
        stat_col = status_badge_color.get(stat, "#45D6A3")
        reasons = "<br>".join(assess.get("reasons", ["Operational."]))
        ev_items = "".join(f"<li>{e}</li>" for e in assess.get("evidence", []))

        comp_cards_html += f"""
        <div style="background: #1C2234; border: 1px solid #283049; border-radius: 10px; padding: 16px; margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #283049; padding-bottom: 8px;">
                <h3 style="margin: 0; font-size: 15px; color: #F4F6FC;">{title}</h3>
                <span style="font-size: 11px; font-weight: 700; color: {stat_col}; background: rgba(255,255,255,0.06); padding: 4px 10px; border-radius: 4px;">{stat}</span>
            </div>
            <p style="font-size: 12px; color: #A2ACC0; margin: 8px 0;">{reasons}</p>
            <div style="font-size: 11px; color: #7C83FF; text-transform: uppercase; font-weight: 700; margin-top: 8px;">Collected Telemetry & Evidence:</div>
            <ul style="font-size: 12px; color: #CBD5E1; margin: 4px 0 0 16px; padding: 0;">{ev_items}</ul>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{meta.get('title')}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #0F1320; color: #F4F6FC; margin: 0; padding: 24px; }}
    .container {{ max-width: 1000px; margin: 0 auto; background: #161A29; border-radius: 12px; border: 1px solid #262D42; padding: 32px; box-shadow: 0 12px 36px rgba(0,0,0,0.4); }}
    .header {{ border-bottom: 1px solid #262D42; padding-bottom: 20px; margin-bottom: 24px; }}
    .title {{ font-size: 22px; font-weight: 700; color: #F4F6FC; margin: 0 0 6px 0; }}
    .subtitle {{ font-size: 12px; color: #8F9BB3; margin: 0; }}
    .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 28px; }}
    .stat-card {{ background: #1C2234; border-radius: 8px; padding: 14px; border: 1px solid #283049; text-align: center; }}
    .stat-num {{ font-size: 24px; font-weight: 700; margin-bottom: 4px; }}
    .stat-lbl {{ font-size: 11px; color: #8F9BB3; text-transform: uppercase; font-weight: 600; }}
    h2 {{ font-size: 16px; color: #7C83FF; text-transform: uppercase; border-bottom: 1px solid #262D42; padding-bottom: 8px; margin: 28px 0 16px 0; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 12px; }}
    th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #262D42; }}
    th {{ color: #8F9BB3; font-weight: 600; text-transform: uppercase; font-size: 11px; }}
    .footer {{ margin-top: 36px; border-top: 1px solid #262D42; padding-top: 16px; font-size: 11px; color: #64748B; text-align: center; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <h1 class="title">SYSFIX Complete Hardware Diagnostics Report</h1>
        <span style="font-size: 12px; font-weight: 700; color: {status_badge_color.get(meta.get('overall_status'), '#45D6A3')}; background: #22293E; padding: 6px 14px; border-radius: 6px;">{meta.get('overall_status')}</span>
      </div>
      <p class="subtitle">Host: <strong>{meta.get('host_name')}</strong> | Platform: <strong>{meta.get('os_platform')}</strong> | Scanned: <strong>{meta.get('generated_at')}</strong> | Mode: <strong>{meta.get('scan_type')}</strong></p>
    </div>

    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-num" style="color: #7C83FF;">{exec_sum.get('total_components_inspected')}</div>
        <div class="stat-lbl">Components</div>
      </div>
      <div class="stat-card">
        <div class="stat-num" style="color: #45D6A3;">{exec_sum.get('passed_healthy')}</div>
        <div class="stat-lbl">Passed Healthy</div>
      </div>
      <div class="stat-card">
        <div class="stat-num" style="color: #FFC66D;">{exec_sum.get('warnings_detected')}</div>
        <div class="stat-lbl">Warnings</div>
      </div>
      <div class="stat-card">
        <div class="stat-num" style="color: #FF647C;">{exec_sum.get('critical_failures')}</div>
        <div class="stat-lbl">Critical</div>
      </div>
    </div>

    <h2>System Identification & Firmware</h2>
    <table>
      <tr><th>Host Name</th><td>{sys_id.get('host_name')}</td><th>Motherboard</th><td>{sys_id.get('motherboard_manufacturer')} {sys_id.get('motherboard_product')}</td></tr>
      <tr><th>BIOS Vendor</th><td>{sys_id.get('bios_vendor')}</td><th>BIOS Version</th><td>{sys_id.get('bios_version')} ({sys_id.get('bios_release_date')})</td></tr>
    </table>

    <h2>Rule-Based Fault Correlation Findings</h2>
    {findings_html}

    <h2>Hardware Subsystem Assessments</h2>
    {comp_cards_html}

    <div class="footer">
      SYSFIX Windows Diagnostics & Hardware Assessment Engine • Report Generated Locally • 100% Offline & Private
    </div>
  </div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
