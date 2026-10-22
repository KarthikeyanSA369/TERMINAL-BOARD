"""
SYSFIX Storage & Drive Health Engine
Collects physical drive information for HDD, SATA SSD, and NVMe drives using
PowerShell Get-PhysicalDisk, WMI Win32_DiskDrive, and Windows Event Logs.
Evaluates risk levels (Healthy, Warning, Critical, Unknown) with honest reporting
when low-level SMART/NVMe telemetry is restricted. Safe and read-only.
"""

import subprocess
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("SYSFIX.Storage")

def format_bytes(bytes_val: int) -> str:
    if not bytes_val:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0 or unit == 'TB':
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} TB"

from backend.core.subproc import safe_run

def query_physical_disks_wmi() -> List[Dict[str, Any]]:
    """Query physical disk hardware status via native Windows Storage WMI namespace."""
    disks = []
    try:
        import wmi
        c = wmi.WMI(namespace=r"root\Microsoft\Windows\Storage")
        for disk in c.MSFT_PhysicalDisk():
            op = getattr(disk, "OperationalStatus", None)
            op_val = op[0] if isinstance(op, (list, tuple)) and len(op) > 0 else op

            health_map = {0: "Healthy", 1: "Warning", 2: "Unhealthy", 3: "Unknown"}
            op_map = {2: "OK", 1: "Other", 3: "Degraded", 4: "Stressed", 5: "Predictive Failure", 6: "Error"}
            bus_map = {
                1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "1394", 5: "SSA", 6: "Fibre Channel",
                7: "USB", 8: "RAID", 9: "iSCSI", 10: "SAS", 11: "SATA", 12: "SD",
                13: "MMC", 14: "MAX", 15: "File Backed Virtual", 16: "Storage Spaces", 17: "NVMe"
            }
            media_map = {0: "Unspecified", 3: "HDD", 4: "SSD", 5: "SCM"}

            disks.append({
                "DeviceId": str(getattr(disk, "DeviceId", "")),
                "FriendlyName": getattr(disk, "FriendlyName", ""),
                "MediaType": media_map.get(getattr(disk, "MediaType", 0), "Unknown"),
                "BusType": bus_map.get(getattr(disk, "BusType", 0), "Unknown"),
                "OperationalStatus": op_map.get(op_val, "OK" if op_val == 2 else "Unknown"),
                "HealthStatus": health_map.get(getattr(disk, "HealthStatus", 3), "Unknown"),
                "Size": int(getattr(disk, "Size", 0) or 0)
            })
    except Exception as e:
        logger.debug(f"Native WMI MSFT_PhysicalDisk query unavailable: {e}")
    return disks

def query_physical_disks_powershell() -> List[Dict[str, Any]]:
    """Query physical disk hardware status via native WMI, with hidden PowerShell fallback."""
    native_disks = query_physical_disks_wmi()
    if native_disks:
        return native_disks

    cmd = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
        "Get-PhysicalDisk | Select-Object DeviceId, FriendlyName, MediaType, BusType, OperationalStatus, HealthStatus, Size | ConvertTo-Json -Compress"
    ]
    try:
        res = safe_run(cmd, capture_output=True, text=True, timeout=8)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout.strip())
            if isinstance(data, dict):
                return [data]
            elif isinstance(data, list):
                return data
    except Exception as e:
        logger.warning(f"Error querying Get-PhysicalDisk: {e}")
    return []

def query_wmi_disk_drives() -> List[Dict[str, Any]]:
    """Query WMI Win32_DiskDrive directly in Python without child processes."""
    drives = []
    try:
        import wmi
        c = wmi.WMI()
        for d in c.Win32_DiskDrive():
            drives.append({
                "DeviceID": getattr(d, "DeviceID", ""),
                "Model": getattr(d, "Model", "Unknown Disk"),
                "InterfaceType": getattr(d, "InterfaceType", "Unknown"),
                "Status": getattr(d, "Status", "OK"),
                "Size": int(getattr(d, "Size", 0) or 0),
                "Partitions": int(getattr(d, "Partitions", 0) or 0)
            })
        if drives:
            return drives
    except Exception as e:
        logger.debug(f"Native in-process Win32_DiskDrive query unavailable: {e}")

    # Fallback to hidden non-interactive CLI if native COM failed
    cmd = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
        "Get-CimInstance -ClassName Win32_DiskDrive | Select-Object DeviceID, Model, InterfaceType, Status, Size, Partitions | ConvertTo-Json -Compress"
    ]
    try:
        res = safe_run(cmd, capture_output=True, text=True, timeout=8)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout.strip())
            if isinstance(data, dict):
                return [data]
            elif isinstance(data, list):
                return data
    except Exception as e:
        logger.warning(f"Error querying Win32_DiskDrive fallback: {e}")
    return []

def query_storage_reliability_counters() -> Dict[str, Dict[str, Any]]:
    """Attempt to query Get-StorageReliabilityCounter (requires Admin)."""
    counters = {}
    try:
        import wmi
        c = wmi.WMI(namespace=r"root\Microsoft\Windows\Storage")
        for item in c.MSFT_StorageReliabilityCounter():
            dev_id = str(getattr(item, "DeviceId", ""))
            counters[dev_id] = {
                "DeviceId": dev_id,
                "Temperature": getattr(item, "Temperature", None),
                "ReadErrorsTotal": getattr(item, "ReadErrorsTotal", None),
                "WriteErrorsTotal": getattr(item, "WriteErrorsTotal", None),
                "Wear": getattr(item, "Wear", None)
            }
        return counters
    except Exception:
        # Requires administrator privileges; if not elevated, return empty dict without launching PowerShell
        pass

    return counters

def evaluate_drive_risk(health_status: str, operational_status: str,
                        read_errors: Optional[int], write_errors: Optional[int],
                        event_errors: int) -> Dict[str, Any]:
    """
    Evaluates drive risk strictly according to requirements:
    Healthy: No known warning detected.
    Warning: Suspicious indicators, increasing errors, or repeated relevant events.
    Critical: Explicit critical health warning or strong failure evidence.
    Unknown: Insufficient information to assess health.
    """
    health_upper = (health_status or "").upper()
    op_upper = (operational_status or "").upper()

    # Critical conditions
    if "UNHEALTHY" in health_upper or "PREDFAIL" in op_upper or "ERROR" in op_upper or "DEGRADED" in op_upper:
        return {
            "level": "Critical",
            "badge_class": "badge-critical",
            "summary": "Immediate failure risk detected or drive reported unhealthy.",
            "recommendation": "Back up all important data immediately. Prepare replacement drive.",
            "backup_recommended": True
        }

    # Warning conditions
    if "WARNING" in health_upper or (read_errors and read_errors > 50) or (write_errors and write_errors > 20) or event_errors > 5:
        return {
            "level": "Warning",
            "badge_class": "badge-warning",
            "summary": "Suspicious indicators or recorded I/O errors detected on this device.",
            "recommendation": "Perform regular backups and monitor SMART error logs closely.",
            "backup_recommended": True
        }

    # Healthy conditions
    if health_upper in ("HEALTHY", "OK") and op_upper in ("OK", "HEALTHY"):
        return {
            "level": "Healthy",
            "badge_class": "badge-healthy",
            "summary": "Reported operational status is OK. No critical storage failures reported.",
            "recommendation": "Drive is operating within normal parameters. Maintain regular scheduled backups.",
            "backup_recommended": False
        }

    # Unknown conditions
    return {
        "level": "Unknown",
        "badge_class": "badge-unknown",
        "summary": "Health data unavailable. Drive did not expose standard telemetry without elevation.",
        "recommendation": "Inspect storage controller logs or run vendor diagnostics tool as administrator.",
        "backup_recommended": False
    }

def get_drive_health_list(recent_disk_events_count: int = 0) -> List[Dict[str, Any]]:
    """
    Aggregates physical drive diagnostic information across available storage interfaces.
    """
    physical_disks = query_physical_disks_powershell()
    wmi_disks = query_wmi_disk_drives()
    reliability = query_storage_reliability_counters()

    drives = []

    if physical_disks:
        for disk in physical_disks:
            dev_id = str(disk.get("DeviceId", ""))
            friendly_name = disk.get("FriendlyName") or f"Disk {dev_id}"
            media_type = disk.get("MediaType") or "Unknown"
            bus_type = disk.get("BusType") or "Unknown"
            op_status = disk.get("OperationalStatus") or "Unknown"
            health_status = disk.get("HealthStatus") or "Unknown"
            size_bytes = disk.get("Size") or 0

            # Low-level reliability counters
            rel_info = reliability.get(dev_id, {})
            read_errors = rel_info.get("ReadErrorsTotal")
            write_errors = rel_info.get("WriteErrorsTotal")
            temperature = rel_info.get("Temperature")
            wear_percent = rel_info.get("Wear")

            # Telemetry status
            telemetry_available = bool(rel_info)
            telemetry_note = "Detailed SMART telemetry accessible" if telemetry_available else "Detailed SMART telemetry restricted (requires administrator elevation)"

            # Risk evaluation
            risk = evaluate_drive_risk(health_status, op_status, read_errors, write_errors, recent_disk_events_count)

            drives.append({
                "device_id": dev_id,
                "model": friendly_name,
                "media_type": media_type,
                "bus_type": bus_type,
                "capacity_bytes": size_bytes,
                "capacity_formatted": format_bytes(size_bytes),
                "operational_status": op_status,
                "health_status": health_status,
                "risk_level": risk["level"],
                "badge_class": risk["badge_class"],
                "summary": risk["summary"],
                "recommendation": risk["recommendation"],
                "backup_recommended": risk["backup_recommended"],
                "smart_status": health_status if health_status != "Unknown" else "SMART Telemetry Unavailable",
                "read_errors": read_errors if read_errors is not None else "N/A",
                "write_errors": write_errors if write_errors is not None else "N/A",
                "temperature": f"{temperature} °C" if temperature else "Unavailable",
                "wear_indicator": f"{wear_percent}%" if wear_percent is not None else "Unavailable",
                "telemetry_available": telemetry_available,
                "telemetry_note": telemetry_note,
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    elif wmi_disks:
        for disk in wmi_disks:
            dev_id = disk.get("DeviceID") or "N/A"
            model = disk.get("Model") or "Generic Drive"
            status = disk.get("Status") or "Unknown"
            size_bytes = disk.get("Size") or 0
            risk = evaluate_drive_risk(status, status, None, None, recent_disk_events_count)

            drives.append({
                "device_id": dev_id,
                "model": model,
                "media_type": "Storage Device",
                "bus_type": disk.get("InterfaceType") or "SATA/IDE",
                "capacity_bytes": size_bytes,
                "capacity_formatted": format_bytes(size_bytes),
                "operational_status": status,
                "health_status": status,
                "risk_level": risk["level"],
                "badge_class": risk["badge_class"],
                "summary": risk["summary"],
                "recommendation": risk["recommendation"],
                "backup_recommended": risk["backup_recommended"],
                "smart_status": status,
                "read_errors": "N/A",
                "write_errors": "N/A",
                "temperature": "Unavailable",
                "wear_indicator": "Unavailable",
                "telemetry_available": False,
                "telemetry_note": "Basic WMI status only; low-level SMART requires elevation.",
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    return drives
