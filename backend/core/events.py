"""
SYSFIX Windows Error & Event Monitoring Engine
Collects critical and warning events from Windows Event Logs (System & Application)
using win32evtlog and PowerShell fallback. Categorizes hardware, disk, kernel-power,
and application crash events with suggested diagnostic steps.
"""

import sys
import os
import json
import subprocess
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger("SYSFIX.Events")

# Known Windows event categories and targeted diagnostic guides
EVENT_DIAGNOSTICS_MAP = {
    # Kernel-Power Unexpected Shutdown
    (41, "Microsoft-Windows-Kernel-Power"): {
        "category": "Unexpected Shutdown",
        "severity": "Critical",
        "cause": "The system rebooted without cleanly shutting down first. This can be caused by power loss, hard lockup, thermal throttling, or hardware instability.",
        "steps": "Check power supply and battery integrity. Inspect thermals for overheating. Verify recent driver installations."
    },
    (6008, "EventLog"): {
        "category": "Dirty Shutdown",
        "severity": "Warning",
        "cause": "The previous system shutdown was unexpected.",
        "steps": "Review power logs around the incident timestamp. Check for thermal cut-offs or sudden power interruptions."
    },
    # Disk / Storage errors
    (7, "disk"): {
        "category": "Storage Controller / Bad Block",
        "severity": "Critical",
        "cause": "The device had a bad block during an I/O operation.",
        "steps": "Immediate backup recommended. Run read-only filesystem check (chkdsk /scan) and inspect drive SMART metrics."
    },
    (11, "disk"): {
        "category": "Storage Controller Error",
        "severity": "Critical",
        "cause": "The driver detected a controller error on the storage device.",
        "steps": "Check SATA/NVMe cable connection or slot seating. Update motherboard storage controller drivers."
    },
    (51, "disk"): {
        "category": "Paging Error",
        "severity": "Warning",
        "cause": "An error was detected on device during a paging operation.",
        "steps": "Check pagefile integrity and storage health. Ensure sufficient free disk space on system drive."
    },
    (153, "disk"): {
        "category": "Disk I/O Timeout",
        "severity": "Warning",
        "cause": "The IO operation at logical block address was retried.",
        "steps": "Drive may be experiencing slow sectors or cable latency. Run drive diagnostics."
    },
    (55, "ntfs"): {
        "category": "Filesystem Corruption",
        "severity": "Critical",
        "cause": "A corruption was detected in the file system structure.",
        "steps": "Schedule an offline filesystem check: chkdsk C: /scan."
    },
    # Application Crashes
    (1000, "Application Error"): {
        "category": "Application Crash",
        "severity": "Error",
        "cause": "A desktop application or service terminated unexpectedly due to an unhandled exception.",
        "steps": "Check faulting module path. Verify application updates, dependencies, and memory stability."
    },
    (1001, "Windows Error Reporting"): {
        "category": "Crash Report Telemetry",
        "severity": "Information",
        "cause": "Windows recorded a crash bucket report.",
        "steps": "Inspect specific crash bucket details or update the affected program."
    },
    # Service / Driver failures
    (7000, "Service Control Manager"): {
        "category": "Service Startup Failure",
        "severity": "Error",
        "cause": "A Windows service failed to start due to configuration or dependency error.",
        "steps": "Check Windows Services (services.msc) and inspect startup type and service credentials."
    },
    (7009, "Service Control Manager"): {
        "category": "Service Timeout",
        "severity": "Error",
        "cause": "A service timed out waiting for connection during system startup.",
        "steps": "Check for system startup delay or heavy disk load during boot."
    },
    # WHEA Hardware errors
    (18, "Microsoft-Windows-WHEA-Logger"): {
        "category": "Hardware Machine Check Error",
        "severity": "Critical",
        "cause": "A fatal hardware error occurred reported by CPU / Machine Check Architecture.",
        "steps": "Check CPU thermals, voltage stability, RAM timings (run Windows Memory Diagnostic), and BIOS firmware."
    }
}

def get_event_diagnostic(event_id: int, provider: str, default_severity: str) -> Dict[str, str]:
    """Find specific diagnostic recommendation or generate standard analysis."""
    # Check exact match
    for (eid, prov), diag in EVENT_DIAGNOSTICS_MAP.items():
        if eid == event_id and (prov.lower() in provider.lower() or provider.lower() in prov.lower()):
            return diag

    # General fallback
    if "disk" in provider.lower() or "stor" in provider.lower() or "nvme" in provider.lower():
        return {
            "category": "Storage Subsystem",
            "severity": default_severity,
            "cause": f"Storage event reported by provider '{provider}'.",
            "steps": "Inspect drive SMART attributes and disk cable connections. Review system storage logs."
        }
    elif "kernel" in provider.lower() or "power" in provider.lower():
        return {
            "category": "Power & Kernel",
            "severity": default_severity,
            "cause": f"Kernel power transition or warning reported by '{provider}'.",
            "steps": "Check power management settings and system sleep/hibernate behavior."
        }
    elif "app" in provider.lower():
        return {
            "category": "Application Layer",
            "severity": default_severity,
            "cause": f"Application error or notice recorded by '{provider}'.",
            "steps": "Check application log for faulting module name. Consider reinstalling or updating software."
        }
    else:
        return {
            "category": "System Event",
            "severity": default_severity,
            "cause": f"Recorded event ID {event_id} from provider '{provider}'.",
            "steps": "Review detailed event description for error code references."
        }

def read_events_native(log_name: str = "System", max_records: int = 50) -> List[Dict[str, Any]]:
    """Read Windows Event Log using pywin32 win32evtlog."""
    try:
        import win32evtlog
        import win32evtlogutil
        import win32con

        hand = win32evtlog.OpenEventLog(None, log_name)
        flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        records = []
        count = 0

        while count < max_records:
            events = win32evtlog.ReadEventLog(hand, flags, 0)
            if not events:
                break
            for ev in events:
                event_type = ev.EventType
                # Filter for Critical (1), Error (2), Warning (3)
                if event_type not in (win32con.EVENTLOG_ERROR_TYPE, win32con.EVENTLOG_WARNING_TYPE, 1):
                    continue

                level_name = "Error"
                if event_type == win32con.EVENTLOG_WARNING_TYPE:
                    level_name = "Warning"
                elif event_type == win32con.EVENTLOG_ERROR_TYPE or event_type == 1:
                    level_name = "Critical" if ev.EventID in (41, 7, 18, 55) else "Error"

                event_id = ev.EventID & 0xFFFF
                provider = ev.SourceName or "Windows"
                time_gen = ev.TimeGenerated.Format() if hasattr(ev.TimeGenerated, "Format") else str(ev.TimeGenerated)

                msg = ""
                try:
                    msg = win32evtlogutil.SafeFormatMessage(ev, log_name)
                except Exception:
                    if ev.StringInserts:
                        msg = " | ".join(str(s) for s in ev.StringInserts if s)

                if not msg:
                    msg = f"Event ID {event_id} generated by source '{provider}'."

                diag = get_event_diagnostic(event_id, provider, level_name)

                records.append({
                    "record_id": ev.RecordNumber,
                    "event_id": event_id,
                    "log_name": log_name,
                    "provider": provider,
                    "level": level_name,
                    "timestamp": time_gen,
                    "message": msg.strip(),
                    "category": diag["category"],
                    "possible_cause": diag["cause"],
                    "suggested_steps": diag["steps"]
                })
                count += 1
                if count >= max_records:
                    break

        win32evtlog.CloseEventLog(hand)
        return records
    except Exception as e:
        logger.warning(f"Native win32evtlog failed for {log_name}: {e}. Trying fallback.")
        return None

from backend.core.subproc import safe_run

def read_events_powershell(log_name: str = "System", max_records: int = 50) -> List[Dict[str, Any]]:
    """Fallback method using PowerShell Get-WinEvent with hidden window and bypass flags."""
    ps_cmd = f"""
    Get-WinEvent -FilterHashtable @{{LogName='{log_name}'; Level=1,2,3}} -MaxEvents {max_records} -ErrorAction SilentlyContinue |
    Select-Object RecordId, Id, ProviderName, LevelDisplayName, TimeCreated, Message | ConvertTo-Json -Compress
    """
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd]
    records = []
    try:
        res = safe_run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout.strip())
            items = [data] if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for item in items:
                eid = item.get("Id", 0)
                provider = item.get("ProviderName", "Unknown")
                level_disp = item.get("LevelDisplayName", "Warning")
                level_name = "Critical" if eid in (41, 7, 18, 55) or level_disp == "Critical" else level_disp
                msg = item.get("Message", "") or f"Event {eid} from {provider}"
                diag = get_event_diagnostic(eid, provider, level_name)

                # Format time
                time_created = item.get("TimeCreated", "")
                if "/Date(" in str(time_created):
                    try:
                        ms = int(time_created.replace("/Date(", "").replace(")/", ""))
                        time_str = datetime.fromtimestamp(ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        time_str = str(time_created)
                else:
                    time_str = str(time_created)

                records.append({
                    "record_id": item.get("RecordId", 0),
                    "event_id": eid,
                    "log_name": log_name,
                    "provider": provider,
                    "level": level_name,
                    "timestamp": time_str,
                    "message": msg.strip(),
                    "category": diag["category"],
                    "possible_cause": diag["cause"],
                    "suggested_steps": diag["steps"]
                })
    except Exception as e:
        logger.error(f"PowerShell event query error: {e}")
    return records

def get_recent_windows_events(max_per_log: int = 35) -> List[Dict[str, Any]]:
    """Collect recent warning, error, and critical events from System and Application logs."""
    all_events = []
    for log_name in ["System", "Application"]:
        events = read_events_native(log_name, max_per_log)
        if events is None:
            events = read_events_powershell(log_name, max_per_log)
        if events:
            all_events.extend(events)

    # Sort newest first
    all_events.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)
    return all_events
