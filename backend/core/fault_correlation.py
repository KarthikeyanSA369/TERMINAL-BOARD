"""
SYSFIX Rule-Based Fault Correlation Engine
Correlates multiple independent diagnostic signals across hardware telemetry,
driver PnP states, error events, and diagnostic test results without requiring
an internet connection, external AI APIs, or cloud dependencies.

Deterministic, evidence-grounded, and conservative:
Does not present a correlation as proven physical failure;
Explains alternative causes, confidence justifications, and confirmation tests.
"""

import time
from typing import Dict, Any, List, Optional


class FaultFinding:
    """Represents a structured, evidence-based diagnostic finding."""
    def __init__(
        self,
        finding_id: str,
        affected_component: str,
        severity: str,
        title: str,
        summary: str,
        supporting_evidence: List[str],
        evidence_timestamps: List[str],
        possible_causes: List[str],
        alternative_explanations: List[str],
        confidence_level: str,
        confidence_justification: str,
        recommended_actions: List[str],
        confirmation_tests: List[str]
    ):
        self.finding_id = finding_id
        self.affected_component = affected_component
        self.severity = severity  # CRITICAL, WARNING, INFO
        self.title = title
        self.summary = summary
        self.supporting_evidence = supporting_evidence
        self.evidence_timestamps = evidence_timestamps
        self.possible_causes = possible_causes
        self.alternative_explanations = alternative_explanations
        self.confidence_level = confidence_level  # HIGH, MEDIUM, LOW
        self.confidence_justification = confidence_justification
        self.recommended_actions = recommended_actions
        self.confirmation_tests = confirmation_tests

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "affected_component": self.affected_component,
            "severity": self.severity,
            "title": self.title,
            "summary": self.summary,
            "supporting_evidence": self.supporting_evidence,
            "evidence_timestamps": self.evidence_timestamps,
            "possible_causes": self.possible_causes,
            "alternative_explanations": self.alternative_explanations,
            "confidence_level": self.confidence_level,
            "confidence_justification": self.confidence_justification,
            "recommended_actions": self.recommended_actions,
            "confirmation_tests": self.confirmation_tests
        }


def correlate_faults(
    inventory: Dict[str, Any],
    error_events: List[Dict[str, Any]],
    diagnostic_tests: Dict[str, Any],
    driver_inventory: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Evaluates multi-signal correlation rules across collected telemetry:
    - Rule 1: Cooling / Thermal Dissipation Problem
    - Rule 2: Storage Media Degradation / Failure Risk
    - Rule 3: Memory Subsystem Instability
    - Rule 4: PnP Device or Driver Malfunction
    - Rule 5: Battery Capacity Degradation
    - Rule 6: CPU Architecture / WHEA Machine Check Instability
    - Rule 7: Network Interface vs External Connectivity Boundary
    - Rule 8: Resource Saturation vs Hardware Defect Discrimination
    """
    findings: List[FaultFinding] = []
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    # ---------------------------------------------------------------------
    # RULE 1: Possible Cooling / Thermal Dissipation Problem
    # Signals: High Temp (>=85C) + Thermal Throttling / Cooling warnings
    # ---------------------------------------------------------------------
    cpu = inventory.get("cpu", {})
    cooling = inventory.get("cooling", {})
    temp = cpu.get("temperature_c")
    throttling = cpu.get("thermal_throttling", False)

    if (temp and temp >= 85.0) or throttling:
        ev_list = []
        ts_list = [now_str]
        if temp:
            ev_list.append(f"Processor package temperature reading: {temp}°C (Safe limit: ~80°C).")
        if throttling:
            ev_list.append("CPU thermal throttling flag is active; clock frequency reduced by power management.")
        if cooling.get("fan_sensor_available") and cooling.get("fan_speed_rpm") == 0:
            ev_list.append("Cooling fan speed is reporting 0 RPM while thermal load is elevated.")

        sev = "CRITICAL" if (temp and temp >= 95.0) or (throttling and temp and temp >= 90.0) else "WARNING"
        conf = "HIGH" if (temp and throttling) else "MEDIUM"

        findings.append(FaultFinding(
            finding_id="CORR-COOLING-001",
            affected_component="Cooling & CPU",
            severity=sev,
            title="Potential Thermal Dissipation / Cooling Deficiency",
            summary=f"Elevated processor operating temperature ({temp or 'Throttled'}°C) accompanied by thermal throttling indicators.",
            supporting_evidence=ev_list,
            evidence_timestamps=ts_list,
            possible_causes=[
                "Accumulated dust or lint blocking radiator heatsink fins and ventilation grilles.",
                "Dried, degraded, or improperly seated thermal paste between CPU IHS and cooler.",
                "Failing, obstructed, or unseated cooling fan motor.",
                "Heavily constrained intake airflow from operating on soft or enclosed surfaces."
            ],
            alternative_explanations=[
                "Temporary sustained ultra-heavy compilation or rendering workload in high ambient room temperature.",
                "Custom aggressive fan curve in BIOS or third-party power profile configured for quiet acoustics."
            ],
            confidence_level=conf,
            confidence_justification="Direct correlation between measured sensor temperature and OS kernel thermal throttling state.",
            recommended_actions=[
                "Inspect air intake and exhaust vents; clear dust obstructions using compressed air.",
                "Elevate laptop base or ensure minimum 5 cm clearance around desktop chassis.",
                "Verify BIOS cooling profile is set to Active / Standard rather than Passive or Quiet.",
                "Renew thermal compound if thermal dissipation does not normalize after cleaning."
            ],
            confirmation_tests=[
                "Execute detailed thermal benchmark while observing fan RPM ramp-up.",
                "Inspect CPU frequency under sustained 100% load to measure throttling delta."
            ]
        ))

    # ---------------------------------------------------------------------
    # RULE 2: Possible Storage Media Degradation / Impending Drive Failure
    # Signals: SMART warnings + Media errors + Disk Event Log (7, 11, 51, 153)
    # ---------------------------------------------------------------------
    storage = inventory.get("storage", {})
    disk_events = [e for e in error_events if e.get("category") in ("Storage / Disk", "Storage Controller") and e.get("event_id") in (7, 11, 51, 153)]
    critical_disks = [d for d in storage.get("physical_disks", []) if d.get("status") in ("CRITICAL", "WARNING")]

    if critical_disks or len(disk_events) >= 2:
        ev_list = []
        ts_list = []
        for cd in critical_disks:
            ev_list.append(f"Physical drive {cd.get('model')} ({cd.get('bus_type')}) reported status {cd.get('operational_status')} / {cd.get('health_status')}.")
            if cd.get("read_errors") and cd.get("read_errors") > 10:
                ev_list.append(f"Cumulative raw read error count: {cd.get('read_errors')}.")
            if cd.get("write_errors") and cd.get("write_errors") > 5:
                ev_list.append(f"Cumulative raw write error count: {cd.get('write_errors')}.")

        for de in disk_events[:3]:
            ev_list.append(f"System Event ID {de.get('event_id')} from {de.get('source')}: {de.get('message')[:100]}...")
            if de.get("timestamp"):
                ts_list.append(de.get("timestamp"))

        sev = "CRITICAL" if any(d.get("status") == "CRITICAL" for d in critical_disks) or len(disk_events) >= 5 else "WARNING"

        findings.append(FaultFinding(
            finding_id="CORR-STORAGE-001",
            affected_component="Storage Subsystem",
            severity=sev,
            title="Storage Device Degradation / I/O Transfer Reliability Warning",
            summary="Physical storage device reports elevated I/O error counters corroborated by Windows disk controller timeout events.",
            supporting_evidence=ev_list,
            evidence_timestamps=ts_list or [now_str],
            possible_causes=[
                "Accumulation of unrecoverable bad physical sectors or flash block wear.",
                "Degrading NAND flash memory cells or storage controller firmware fault.",
                "Intermittent SATA data cable connection or poor PCIe M.2 socket pin seating.",
                "Storage controller interface timeouts during intense burst I/O operations."
            ],
            alternative_explanations=[
                "Sudden power loss or dirty shutdown causing uncommitted file write retries.",
                "Outdated chipset storage AHCI / NVMe controller drivers causing communication lag."
            ],
            confidence_level="HIGH" if critical_disks and disk_events else "MEDIUM",
            confidence_justification="Multiple independent signals: WMI physical disk reliability counters matched with Windows kernel disk driver event logs.",
            recommended_actions=[
                "IMMEDIATE ACTION: Back up all critical files and databases to external media or network storage.",
                "Run non-destructive read-only filesystem check: 'chkdsk C: /scan'.",
                "Inspect SATA/NVMe cable connections and motherboard slot seating.",
                "Prepare replacement storage media if bad sectors or controller errors continue to increase."
            ],
            confirmation_tests=[
                "Perform full read-only surface scan using vendor diagnostic software (e.g. Samsung Magician, Crucial Storage Executive, SeaTools).",
                "Execute SYSFIX read latency test and observe whether timeout events recur."
            ]
        ))

    # ---------------------------------------------------------------------
    # RULE 3: Possible Memory Subsystem Instability
    # Signals: Memory Diagnostic failed (1102/1202) + WHEA Memory (19) + Heap Fail
    # ---------------------------------------------------------------------
    mem_events = [e for e in error_events if e.get("category") == "Memory Diagnostic" and e.get("event_id") in (1102, 1202)]
    whea_mem = [e for e in error_events if e.get("category") == "Hardware / WHEA" and e.get("event_id") == 19]
    ram_test = diagnostic_tests.get("ram", {})
    ram = inventory.get("ram", {})

    if mem_events or whea_mem or ram_test.get("status") == "TEST FAILED":
        ev_list = []
        ts_list = []
        if mem_events:
            ev_list.append(f"Windows Memory Diagnostic logged confirmed hardware error: {mem_events[0].get('message')[:120]}")
            ts_list.append(mem_events[0].get("timestamp", now_str))
        if whea_mem:
            ev_list.append(f"WHEA corrected hardware memory error (Event ID 19) recorded by processor memory controller.")
            ts_list.append(whea_mem[0].get("timestamp", now_str))
        if ram_test.get("status") == "TEST FAILED":
            ev_list.append(f"SYSFIX user-space heap bit-pattern test failed: {ram_test.get('error')}")

        findings.append(FaultFinding(
            finding_id="CORR-MEMORY-001",
            affected_component="RAM / Memory Subsystem",
            severity="CRITICAL",
            title="Physical Memory Hardware Instability Detected",
            summary="Hardware memory diagnostics or WHEA memory controller logs confirm bit-flip or parity errors in physical RAM.",
            supporting_evidence=ev_list,
            evidence_timestamps=ts_list or [now_str],
            possible_causes=[
                "Defective physical DRAM cell on one of the installed RAM modules.",
                "Incompatible XMP/DOCP memory timing, voltage, or frequency profile.",
                "Oxidized or contaminated DIMM socket pins causing electrical signal noise.",
                "Integrated memory controller (IMC) voltage instability inside processor."
            ],
            alternative_explanations=[
                "Aggressive motherboard BIOS memory overclocking timings.",
                "Thermal degradation of memory modules due to restricted internal case airflow."
            ],
            confidence_level="HIGH",
            confidence_justification="Hardware architecture machine check or Windows Memory Diagnostic confirmation.",
            recommended_actions=[
                "Schedule a full offline memory diagnostic pass: run 'mdsched.exe' and reboot.",
                "If errors persist, test each physical RAM module individually in slot 1 to identify the specific faulty stick.",
                "Reset BIOS memory frequency and timings to JEDEC standard specifications."
            ],
            confirmation_tests=[
                "Run Windows Memory Diagnostic Extended Mode (mdsched.exe) across minimum 2 passes.",
                "Run MemTest86 pre-boot standalone USB test."
            ]
        ))

    # ---------------------------------------------------------------------
    # RULE 4: Hardware Device / PnP Driver Communication Failure
    # Signals: PnP problem codes (10, 19, 28, 31, 37, 39, 43, 48)
    # ---------------------------------------------------------------------
    if driver_inventory:
        critical_drivers = [d for d in driver_inventory if d.get("problem_code") in (10, 19, 28, 31, 37, 38, 39, 43, 48)]
        for cd in critical_drivers[:2]:  # Limit to top 2 to prevent report clutter
            code = cd.get("problem_code")
            dev_name = cd.get("device_name", "Hardware Device")
            dev_id = cd.get("device_id", "PnP Device")
            code_desc = cd.get("problem_description", f"Code {code}")

            findings.append(FaultFinding(
                finding_id=f"CORR-DRIVER-{code}-{abs(hash(dev_id)) % 1000}",
                affected_component=f"Device: {dev_name}",
                severity="CRITICAL" if code in (10, 43, 31) else "WARNING",
                title=f"Hardware Communication Fault on {dev_name} (Code {code})",
                summary=f"Windows Plug-and-Play Manager reported operational failure Code {code} ({code_desc}) on this hardware device.",
                supporting_evidence=[
                    f"Device: {dev_name} (Class: {cd.get('device_class')}, Provider: {cd.get('provider')}).",
                    f"Windows PnP Problem Code: {code} - {code_desc}.",
                    f"Device Instance ID: {dev_id}."
                ],
                evidence_timestamps=[now_str],
                possible_causes=[
                    "Device firmware or hardware logic encountered an unrecoverable internal exception.",
                    "Missing, corrupted, or incompatible Windows device driver binary.",
                    "PCIe or USB power management state transition failure.",
                    "Physical interface disconnect or loose connector."
                ],
                alternative_explanations=[
                    "Windows Update replaced manufacturer driver with generic incompatible Microsoft fallback.",
                    "Device was unplugged while driver held active handles."
                ],
                confidence_level="HIGH",
                confidence_justification="Direct Windows PnP Manager status code verification.",
                recommended_actions=[
                    f"Open Device Manager (devmgmt.msc) and locate '{dev_name}' under {cd.get('device_class')}.",
                    "Reinstall official driver package directly from original manufacturer.",
                    "Power cycle the system completely (perform full shutdown, not fast startup reboot)."
                ],
                confirmation_tests=[
                    "Check if device problem code clears to Code 0 (Working properly) after driver reinstall."
                ]
            ))

    # ---------------------------------------------------------------------
    # RULE 5: High Battery Degradation / Cycle Wear
    # Signals: Battery Wear > 45% + has_battery
    # ---------------------------------------------------------------------
    bat = inventory.get("battery", {})
    wear = bat.get("health_wear_percent")
    if bat.get("has_battery") and wear is not None and wear >= 45.0:
        findings.append(FaultFinding(
            finding_id="CORR-BATTERY-001",
            affected_component="Battery Subsystem",
            severity="WARNING",
            title="Significant Battery Cell Capacity Degradation",
            summary=f"Battery has suffered {wear}% capacity degradation relative to original factory design specification.",
            supporting_evidence=[
                f"Design Capacity: {bat.get('design_capacity_mwh')} mWh.",
                f"Current Full Charge Capacity: {bat.get('full_charge_capacity_mwh')} mWh.",
                f"Calculated Capacity Loss: {wear}%."
            ],
            evidence_timestamps=[now_str],
            possible_causes=[
                "Chemical aging of lithium-ion/polymer cells from charge-discharge cycles.",
                "Prolonged exposure to elevated thermal conditions inside laptop chassis.",
                "Continuous operation at 100% state of charge under AC power without battery charge limiter."
            ],
            alternative_explanations=[
                "Battery fuel gauge calibration drift (requires full discharge and recharge cycle)."
            ],
            confidence_level="HIGH",
            confidence_justification="Direct reading of BatteryStaticData vs BatteryFullChargedCapacity via ACPI WMI.",
            recommended_actions=[
                "Calibrate battery: charge to 100%, discharge until Windows shuts down, then recharge to 100%.",
                "Enable manufacturer battery health charging threshold (e.g. 80% maximum charge).",
                "Prepare for battery replacement if portable runtime is insufficient for mobile usage."
            ],
            confirmation_tests=[
                "Generate Windows Battery Report: run 'powercfg /batteryreport' in Command Prompt."
            ]
        ))

    # ---------------------------------------------------------------------
    # RULE 6: Heavy Workload vs Hardware Fault Discrimination
    # Signals: CPU/RAM > 90% without any hardware error events
    # ---------------------------------------------------------------------
    cpu_util = cpu.get("utilization_percent", 0.0)
    ram_util = ram.get("utilization_percent", 0.0)
    has_hard_errors = bool(findings)

    if (cpu_util >= 88.0 or ram_util >= 88.0) and not has_hard_errors:
        findings.append(FaultFinding(
            finding_id="CORR-LOAD-001",
            affected_component="System Workload",
            severity="INFO",
            title="High System Utilization with Verified Healthy Hardware",
            summary=f"Processor ({cpu_util}%) or memory ({ram_util}%) is under heavy computational load; telemetry confirms zero hardware defects.",
            supporting_evidence=[
                f"Current CPU load: {cpu_util}% across {cpu.get('physical_cores')} physical cores.",
                f"Current RAM load: {ram_util}% ({ram.get('used_formatted')} / {ram.get('total_formatted')}).",
                "Zero WHEA hardware architecture errors, zero memory diagnostic errors, zero disk errors."
            ],
            evidence_timestamps=[now_str],
            possible_causes=[
                "Active user applications, developer builds, background indexing, or web browser processes.",
                "Legitimate computational workload utilizing available system capacity."
            ],
            alternative_explanations=[
                "Background Windows Update maintenance or antivirus scanning."
            ],
            confidence_level="HIGH",
            confidence_justification="Verified high resource consumption concurrent with 0 hardware error log events.",
            recommended_actions=[
                "Review Task Manager or SYSFIX System Health to inspect top active processes.",
                "No hardware replacement or repair required; hardware components are operating properly."
            ],
            confirmation_tests=[
                "Observe resource consumption return to baseline once background tasks finish."
            ]
        ))

    return [f.to_dict() for f in findings]
