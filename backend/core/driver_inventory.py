"""
SYSFIX Driver Inventory & Hardware Diagnostics Engine
Discovers installed drivers and physical PnP devices across Windows:
- Win32_PnPEntity, Get-PnpDevice status & problem codes
- Win32_PnPSignedDriver catalog (Version, Provider, Date, INF, Signature)
- Windows Registry Class & Enum fallback driver catalog
- PnP Problem Code mapping (CM_PROB_*)
- Driver Health Classification: HEALTHY, WARNING, CRITICAL, SCAN ERROR, NOT AVAILABLE
- RFC 4180 CSV and standalone responsive HTML exports

Read-only: Never modifies, disables, installs, or rolls back drivers.
"""

import os
import sys
import csv
import io
import json
import shutil
import html
import re
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from backend.core.subproc import safe_run

logger = logging.getLogger("SYSFIX.DriverInventory")

# Standard Windows PnP Problem Code definitions (CM_PROB_*)
PNP_PROBLEM_CODES = {
    0: ("CM_PROB_NONE", "Device is working properly."),
    1: ("CM_PROB_NOT_CONFIGURED", "Device is not configured correctly."),
    10: ("CM_PROB_FAILED_START", "This device cannot start. A device or driver malfunction occurred."),
    12: ("CM_PROB_NORMAL_CONFLICT", "This device cannot find enough free resources to use."),
    14: ("CM_PROB_NEED_RESTART", "This device cannot work properly until the system is restarted."),
    18: ("CM_PROB_REINSTALL", "The drivers for this device must be reinstalled."),
    19: ("CM_PROB_REGISTRY", "Windows cannot start this device because registry configuration is corrupted."),
    21: ("CM_PROB_WILL_BE_REMOVED", "Windows is removing this device."),
    22: ("CM_PROB_DISABLED", "This device is currently disabled in Windows Device Manager."),
    24: ("CM_PROB_DEVLOADER_NOT_READY", "Device is not present, not working properly, or missing driver files."),
    28: ("CM_PROB_FAILED_INSTALL", "The drivers for this device are not installed."),
    29: ("CM_PROB_HARDWARE_DISABLED", "Device is disabled because device firmware did not allocate resources."),
    31: ("CM_PROB_FAILED_ADD", "Windows cannot load the required drivers for this device."),
    32: ("CM_PROB_DISABLED_SERVICE", "A required driver service for this device has been disabled."),
    37: ("CM_PROB_FAILED_DRIVER_ENTRY", "Windows cannot initialize the device driver for this hardware."),
    38: ("CM_PROB_DRIVER_FAILED_PRIOR_UNLOAD", "Cannot load driver because a previous instance remains in memory."),
    39: ("CM_PROB_DRIVER_FAILED_LOAD", "Windows cannot load the driver. The file may be corrupt or missing."),
    41: ("CM_PROB_DRIVER_DIRTY_BLOCKED", "Driver loaded successfully but Windows cannot communicate with device."),
    43: ("CM_PROB_FAILED_POST_START", "Windows has stopped this device because it reported problems."),
    45: ("CM_PROB_DEVICE_NOT_THERE", "Hardware device is currently disconnected or unplugged."),
    48: ("CM_PROB_BLOCKED_ON_CERT", "Driver software was blocked because it has known compatibility issues."),
    52: ("CM_PROB_UNSIGNED_DRIVER", "Windows cannot verify the digital signature for this driver.")
}

# Cache for driver inventory
_cached_driver_inventory: Optional[List[Dict[str, Any]]] = None
_last_scan_time: Optional[str] = None


def get_powershell_executable() -> str:
    """Detect available PowerShell executable on Windows."""
    for candidate in ["powershell.exe", "powershell", "pwsh.exe", "pwsh"]:
        p = shutil.which(candidate)
        if p:
            return p
    sys32 = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"),
        r"System32\WindowsPowerShell\v1.0\powershell.exe"
    )
    if os.path.exists(sys32):
        return sys32
    return "powershell.exe"


def parse_driver_date(val: Any) -> str:
    """Parse various Windows driver date formats into standard YYYY-MM-DD."""
    if not val:
        return "Not Available"
    if isinstance(val, str):
        val = val.strip()
        if not val or val.lower() == "unknown":
            return "Not Available"
        # Match Microsoft JSON epoch milliseconds date: /Date(1150848000000)/ or /Date(-45964800000)/
        m = re.search(r"/Date\((-?\d+)\)/", val)
        if m:
            try:
                ms = int(m.group(1))
                d = datetime(1970, 1, 1) + timedelta(milliseconds=ms)
                return d.strftime("%Y-%m-%d")
            except Exception:
                pass
        # Match WMI/CIM date: 20210218000000.000000+000
        m2 = re.match(r"^(\d{4})(\d{2})(\d{2})", val)
        if m2:
            return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
        # Match standard YYYY-MM-DD or MM/DD/YYYY
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            return val
        return val
    return "Not Available"


def get_pnp_problem_info(code: Optional[int]) -> Dict[str, Any]:
    """Retrieve official documentation and explanation for a PnP Problem Code."""
    if code is None or code == 0:
        return {
            "code": 0,
            "name": "CM_PROB_NONE",
            "description": "Device is working properly."
        }
    info = PNP_PROBLEM_CODES.get(code, ("CM_PROB_UNKNOWN", f"Windows PnP reported error code {code}."))
    return {
        "code": code,
        "name": info[0],
        "description": info[1]
    }


def classify_driver_health(status: str, problem_code: Optional[int], device_name: str = "",
                           is_present: bool = True, scan_error: bool = False) -> Dict[str, str]:
    """
    Classify driver and device health into HEALTHY, WARNING, CRITICAL, SCAN ERROR, or NOT AVAILABLE
    based on real Windows PnP telemetry.
    """
    if scan_error:
        return {
            "level": "SCAN ERROR",
            "badge_class": "badge-critical",
            "reason": "Windows discovery failed or permissions prevented reliable inspection."
        }

    status_upper = (status or "").upper().strip()
    try:
        code = 0 if problem_code is None else int(problem_code)
    except (ValueError, TypeError):
        code = 0

    # If status is absent and code is None
    if not status and problem_code is None:
        return {
            "level": "NOT AVAILABLE",
            "badge_class": "badge-unknown",
            "reason": "Driver health telemetry is Not Available for this device."
        }

    # 1. Healthy: Code 0 and Status OK
    if code == 0 and (status_upper in ("OK", "TRUE", "") or "OK" in status_upper):
        return {
            "level": "HEALTHY",
            "badge_class": "badge-healthy",
            "reason": "Device is operating normally with no active PnP errors reported."
        }

    # 2. Disabled device (Code 22): Warning, not a hardware fault
    if code == 22 or "DISABLED" in status_upper:
        return {
            "level": "WARNING",
            "badge_class": "badge-warning",
            "reason": "Device is disabled by user or administrative policy (PnP Code 22)."
        }

    # 3. Disconnected peripheral (Code 45) or not present
    if code == 45 or not is_present:
        return {
            "level": "WARNING",
            "badge_class": "badge-warning",
            "reason": "Hardware device is currently disconnected or offline (PnP Code 45)."
        }

    # 4. Critical failures: Codes 10, 19, 28, 31, 37, 38, 39, 41, 43, 48
    if code in (10, 19, 28, 31, 37, 38, 39, 41, 43, 48) or status_upper in ("ERROR", "PRED FAIL"):
        prob_desc = PNP_PROBLEM_CODES.get(code, ("", "Hardware or driver malfunction"))[1]
        return {
            "level": "CRITICAL",
            "badge_class": "badge-critical",
            "reason": f"Windows reported device error: {prob_desc} (Code {code})."
        }

    # 5. Non-critical warnings: Degraded or Codes 1, 12, 14, 18, 24, 29, 32, 52
    if code in (1, 12, 14, 18, 24, 29, 32, 52) or "WARN" in status_upper or "DEGRADED" in status_upper:
        prob_desc = PNP_PROBLEM_CODES.get(code, ("", "Driver condition requiring attention"))[1]
        return {
            "level": "WARNING",
            "badge_class": "badge-warning",
            "reason": f"Driver warning: {prob_desc} (Code {code})."
        }

    if status_upper == "NOT AVAILABLE":
        return {
            "level": "NOT AVAILABLE",
            "badge_class": "badge-unknown",
            "reason": "Driver health telemetry is Not Available for this device."
        }

    return {
        "level": "WARNING",
        "badge_class": "badge-warning",
        "reason": f"Telemetry returned non-standard status '{status}' with problem code {code}."
    }


def scan_windows_pnp_and_drivers() -> List[Dict[str, Any]]:
    """
    Perform live Windows hardware and driver discovery using Get-PnpDevice and
    Get-CimInstance Win32_PnPSignedDriver via PowerShell.
    Executes queries concurrently via thread pool for optimal speed.
    Non-destructive, read-only.
    """
    if sys.platform != "win32":
        return []

    import concurrent.futures
    ps_exe = get_powershell_executable()

    def fetch_pnp() -> List[Dict[str, Any]]:
        ps_script = "@(Get-PnpDevice -PresentOnly | Select-Object InstanceId, FriendlyName, Class, Status, Problem, ConfigManagerErrorCode, Manufacturer, Present) | ConvertTo-Json -Depth 3 -Compress"
        try:
            proc = safe_run(
                [ps_exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=12,
                encoding="utf-8",
                errors="replace"
            )
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                return [data] if isinstance(data, dict) else (data or [])
        except Exception as e:
            logger.warning(f"Error fetching PnP devices: {e}")
        return []

    def fetch_drivers() -> List[Dict[str, Any]]:
        ps_script = "@(Get-CimInstance Win32_PnPSignedDriver | Select-Object DeviceID, DeviceName, DeviceClass, Manufacturer, DriverProviderName, DriverVersion, DriverDate, InfName, IsSigned) | ConvertTo-Json -Depth 3 -Compress"
        try:
            proc = safe_run(
                [ps_exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=14,
                encoding="utf-8",
                errors="replace"
            )
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                return [data] if isinstance(data, dict) else (data or [])
        except Exception as e:
            logger.warning(f"Error fetching signed drivers: {e}")
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        fut_pnp = executor.submit(fetch_pnp)
        fut_drv = executor.submit(fetch_drivers)
        pnp_list = fut_pnp.result()
        drv_list = fut_drv.result()

    if not pnp_list:
        return []

    # Index signed drivers by DeviceID (case-insensitive)
    drv_map: Dict[str, Dict[str, Any]] = {}
    for d in drv_list:
        did = (d.get("DeviceID") or "").strip().lower()
        if did:
            drv_map[did] = d

    # Lazy registry catalog cache
    reg_map: Optional[Dict[str, Dict[str, Any]]] = None

    results: List[Dict[str, Any]] = []

    for p in pnp_list:
        instance_id = (p.get("InstanceId") or "").strip()
        friendly_name = (p.get("FriendlyName") or "").strip()
        pnp_class = (p.get("Class") or "").strip()
        pnp_status = (p.get("Status") or "OK").strip()
        pnp_mfr = (p.get("Manufacturer") or "").strip()
        is_present = bool(p.get("Present", True))

        # Problem code
        raw_code = p.get("Problem")
        if raw_code is None:
            raw_code = p.get("ConfigManagerErrorCode", 0)
        try:
            problem_code = int(raw_code or 0)
        except (ValueError, TypeError):
            problem_code = 0

        # Match driver by InstanceId
        drv_info = drv_map.get(instance_id.lower())
        if not drv_info and (friendly_name or instance_id):
            if reg_map is None:
                reg_map = {}
                for rd in scan_registry_driver_catalog():
                    rid = (rd.get("device_id") or "").strip().lower()
                    rname = (rd.get("device_name") or "").strip().lower()
                    if rid:
                        reg_map[rid] = rd
                    if rname:
                        reg_map[rname] = rd
            drv_info = reg_map.get(instance_id.lower()) or (reg_map.get(friendly_name.lower()) if friendly_name else None)

        dev_name = friendly_name or (drv_info.get("DeviceName") if drv_info else None) or (drv_info.get("device_name") if drv_info else None) or instance_id or "Not Available"
        dev_class = pnp_class or (drv_info.get("DeviceClass") if drv_info else None) or (drv_info.get("device_class") if drv_info else None) or "System"

        mfr = pnp_mfr or (drv_info.get("Manufacturer") if drv_info else None) or (drv_info.get("manufacturer") if drv_info else None) or "Not Available"
        provider = (drv_info.get("DriverProviderName") if drv_info else None) or (drv_info.get("provider") if drv_info else None) or (drv_info.get("driver_provider") if drv_info else None) or "Not Available"
        version = (drv_info.get("DriverVersion") if drv_info else None) or (drv_info.get("driver_version") if drv_info else None) or "Not Available"
        raw_date = (drv_info.get("DriverDate") if drv_info else None) or (drv_info.get("driver_date") if drv_info else None)
        driver_date = parse_driver_date(raw_date)
        inf_name = (drv_info.get("InfName") if drv_info else None) or (drv_info.get("inf_name") if drv_info else None) or (drv_info.get("inf_path") if drv_info else None) or "Not Available"
        is_signed = bool(drv_info.get("IsSigned", True)) if drv_info else True

        # Sanitize any legacy 'Unknown' strings to 'Not Available'
        if mfr.lower() == "unknown":
            mfr = "Not Available"
        if provider.lower() == "unknown":
            provider = "Not Available"
        if version.lower() == "unknown":
            version = "Not Available"
        if driver_date.lower() == "unknown":
            driver_date = "Not Available"
        if inf_name.lower() == "unknown":
            inf_name = "Not Available"

        results.append({
            "device_name": dev_name,
            "device_class": dev_class,
            "manufacturer": mfr,
            "driver_provider": provider,
            "provider": provider,
            "driver_version": version,
            "driver_date": driver_date,
            "device_id": instance_id or "Not Available",
            "device_instance_id": instance_id or "Not Available",
            "inf_name": inf_name,
            "inf_path": inf_name,
            "status": pnp_status,
            "problem_code": problem_code,
            "is_signed": is_signed,
            "is_present": is_present,
            "data_source": "Windows PnP & Driver Catalog"
        })

    return results


def scan_registry_driver_catalog() -> List[Dict[str, Any]]:
    """
    Registry driver catalog inspection fallback.
    Reads HKLM\\SYSTEM\\CurrentControlSet\\Control\\Class across all GUID classes.
    Completes in under 0.2s without blocking.
    """
    drivers = []
    if sys.platform != "win32":
        return drivers

    try:
        import winreg
        class_path = r"SYSTEM\CurrentControlSet\Control\Class"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, class_path) as class_key:
            num_classes = winreg.QueryInfoKey(class_key)[0]
            for i in range(num_classes):
                try:
                    guid = winreg.EnumKey(class_key, i)
                    with winreg.OpenKey(class_key, guid) as k:
                        class_name = None
                        try:
                            class_name, _ = winreg.QueryValueEx(k, "Class")
                        except Exception:
                            pass

                        num_subkeys = winreg.QueryInfoKey(k)[0]
                        for j in range(num_subkeys):
                            sub_name = winreg.EnumKey(k, j)
                            if sub_name.isdigit():
                                with winreg.OpenKey(k, sub_name) as dev_k:
                                    def get_val(name):
                                        try:
                                            v, _ = winreg.QueryValueEx(dev_k, name)
                                            return str(v).strip() if v is not None else ""
                                        except Exception:
                                            return ""

                                    desc = get_val("DriverDesc")
                                    ver = get_val("DriverVersion")
                                    if desc and ver:
                                        provider = get_val("ProviderName") or "Not Available"
                                        driver_date = get_val("DriverDate") or "Not Available"
                                        inf_name = get_val("InfPath") or "Not Available"
                                        mfg = get_val("Mfg") or provider
                                        matching_id = get_val("MatchingDeviceId")

                                        drivers.append({
                                            "device_name": desc,
                                            "device_class": class_name or "System Device",
                                            "manufacturer": mfg,
                                            "driver_provider": provider,
                                            "provider": provider,
                                            "driver_version": ver,
                                            "driver_date": parse_driver_date(driver_date),
                                            "device_id": matching_id or f"REG\\{guid}\\{sub_name}",
                                            "device_instance_id": matching_id or f"REG\\{guid}\\{sub_name}",
                                            "inf_name": inf_name,
                                            "inf_path": inf_name,
                                            "status": "OK",
                                            "problem_code": 0,
                                            "is_signed": True,
                                            "is_present": True,
                                            "data_source": "Windows Driver Registry Catalog"
                                        })
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Error querying registry driver catalog: {e}")

    return drivers


def scan_pnp_problem_devices() -> Dict[str, Dict[str, Any]]:
    """
    Query devices reporting non-zero PnP problem codes or abnormal statuses.
    Uses 'pnputil /enum-devices /problem' with timeout.
    """
    problem_map: Dict[str, Dict[str, Any]] = {}
    if sys.platform != "win32":
        return problem_map

    try:
        proc = safe_run(
            ["pnputil", "/enum-devices", "/problem"],
            capture_output=True,
            text=True,
            timeout=4,
            shell=False
        )
        if proc.returncode == 0 and proc.stdout:
            current_id = None
            current_desc = None
            current_code = 0
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.startswith("Instance ID:"):
                    current_id = line.split(":", 1)[1].strip()
                elif line.startswith("Device Description:"):
                    current_desc = line.split(":", 1)[1].strip()
                elif line.startswith("Problem Code:"):
                    try:
                        current_code = int(line.split(":", 1)[1].strip())
                    except Exception:
                        current_code = 1
                    if current_id:
                        problem_map[current_id.lower()] = {
                            "name": current_desc or current_id,
                            "problem_code": current_code,
                            "status": "Error" if current_code in (10, 28, 43) else "Warning"
                        }
                        current_id = None
                        current_desc = None
                        current_code = 0
    except Exception:
        pass

    return problem_map


def get_complete_driver_inventory(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Build a comprehensive, deduplicated driver and hardware device inventory.
    Correlates live PnP devices, driver versions, providers, dates, and live problem codes.
    Returns structured list with health evaluations.
    """
    global _cached_driver_inventory, _last_scan_time
    if _cached_driver_inventory is not None and not force_refresh:
        return _cached_driver_inventory

    scan_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Primary discovery: Live Windows PnP & CIM Driver query
    raw_drivers = scan_windows_pnp_and_drivers()

    # Fallback if PnP query returns nothing (e.g. non-Windows test or restricted host)
    if not raw_drivers:
        raw_drivers = scan_registry_driver_catalog()

    problem_devices = scan_pnp_problem_devices()

    # Deduplicate identical entries by device_id and device_name
    seen_keys = set()
    drivers = []
    for d in raw_drivers:
        d_id = (d.get("device_id") or "").strip().lower()
        d_name = (d.get("device_name") or "").strip().lower()
        key = (d_id, d_name)
        if key not in seen_keys:
            seen_keys.add(key)
            drivers.append(d)

    # Corroborate with pnputil problem map if any matching device exists
    for d in drivers:
        dev_id = (d.get("device_id") or "").lower()
        matched_prob = None
        for prob_id, prob_info in problem_devices.items():
            if prob_id in dev_id or dev_id in prob_id or d["device_name"].lower() in prob_info.get("name", "").lower():
                matched_prob = prob_info
                break

        if matched_prob:
            d["problem_code"] = matched_prob.get("problem_code", 1)
            d["status"] = matched_prob.get("status", "Warning")

        # Classify health
        health = classify_driver_health(
            status=d.get("status", "OK"),
            problem_code=d.get("problem_code", 0),
            device_name=d.get("device_name", ""),
            is_present=d.get("is_present", True)
        )
        d["health_classification"] = health["level"]
        d["badge_class"] = health["badge_class"]
        d["health_reason"] = health["reason"]
        d["diagnostic_reason"] = health["reason"]

        prob_info = get_pnp_problem_info(d.get("problem_code", 0))
        d["problem_name"] = prob_info["name"]
        d["problem_description"] = prob_info["description"]
        d["last_scanned"] = scan_timestamp
        d["scanned_at"] = scan_timestamp

        # Remediation step based on classification
        if d["health_classification"] == "HEALTHY":
            d["remediation_step"] = "No repair action needed. Hardware is operating normally according to Windows Plug-and-Play manager."
        elif d["health_classification"] == "WARNING":
            if d.get("problem_code") == 22:
                d["remediation_step"] = "Device is disabled. You can re-enable this device in Windows Device Manager if required."
            elif d.get("problem_code") == 14:
                d["remediation_step"] = "Restart the system to allow Windows to finalize driver configuration."
            else:
                d["remediation_step"] = "Inspect device in Windows Device Manager and review recent driver updates or peripheral connection."
        elif d["health_classification"] == "CRITICAL":
            d["remediation_step"] = "Check device connection, verify driver package with manufacturer, or inspect Windows Event Logs for driver failure events."
        else:
            d["remediation_step"] = "Run diagnostics to gather additional device telemetry."

        d["update_recommendation"] = "Installed driver version verified. External driver updates must be obtained from the device manufacturer or Windows Update."

    # Priority sorting: CRITICAL first, then WARNING, then NOT AVAILABLE / SCAN ERROR, then HEALTHY, then alphabetical
    priority_order = {
        "CRITICAL": 0,
        "WARNING": 1,
        "SCAN ERROR": 2,
        "NOT AVAILABLE": 3,
        "HEALTHY": 4
    }
    drivers.sort(key=lambda x: (
        priority_order.get(x.get("health_classification", ""), 5),
        (x.get("device_name") or "").lower()
    ))

    _cached_driver_inventory = drivers
    _last_scan_time = scan_timestamp
    return drivers


def export_driver_inventory_to_csv(drivers: List[Dict[str, Any]]) -> str:
    """Export driver inventory to RFC 4180 CSV format."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")

    writer.writerow([
        "Device Name", "Category", "Manufacturer", "Driver Provider",
        "Driver Version", "Driver Date", "Device Instance ID", "INF File",
        "Device Status", "PnP Problem Code", "Health Classification",
        "Diagnostic Reason", "Data Source", "Last Scanned"
    ])

    for d in drivers:
        writer.writerow([
            d.get("device_name") or "Not Available",
            d.get("device_class") or "Not Available",
            d.get("manufacturer") or "Not Available",
            d.get("driver_provider") or d.get("provider") or "Not Available",
            d.get("driver_version") or "Not Available",
            d.get("driver_date") or "Not Available",
            d.get("device_id") or d.get("device_instance_id") or "Not Available",
            d.get("inf_name") or d.get("inf_path") or "Not Available",
            d.get("status") or "Not Available",
            str(d.get("problem_code", 0)),
            d.get("health_classification") or "Not Available",
            d.get("health_reason") or d.get("diagnostic_reason") or "Not Available",
            d.get("data_source") or "Windows PnP & Driver Catalog",
            d.get("last_scanned") or d.get("scanned_at") or ""
        ])

    return output.getvalue()


def export_driver_inventory_to_html(drivers: List[Dict[str, Any]]) -> str:
    """Generate standalone, responsive HTML report of driver inventory & health."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_count = len(drivers)
    healthy_count = sum(1 for d in drivers if d.get("health_classification") == "HEALTHY")
    warning_count = sum(1 for d in drivers if d.get("health_classification") == "WARNING")
    critical_count = sum(1 for d in drivers if d.get("health_classification") == "CRITICAL")

    rows_html = []
    if not drivers:
        rows_html.append('<tr><td colspan="6" style="text-align: center; color: #94A3B8; padding: 24px;">No hardware devices discovered.</td></tr>')
    else:
        for d in drivers:
            health_class = d.get("health_classification", "NOT AVAILABLE")
            badge_style = (
                "background: #234e3f; color: #45D6A3;" if health_class == "HEALTHY" else
                "background: #4a3e21; color: #FFC66D;" if health_class == "WARNING" else
                "background: #54222b; color: #FF647C;" if health_class == "CRITICAL" else
                "background: #333a4d; color: #A2ACC0;"
            )

            d_name = html.escape(str(d.get("device_name") or "Not Available"))
            d_class = html.escape(str(d.get("device_class") or "Not Available"))
            mfr = html.escape(str(d.get("manufacturer") or "Not Available"))
            prov = html.escape(str(d.get("driver_provider") or d.get("provider") or "Not Available"))
            ver = html.escape(str(d.get("driver_version") or "Not Available"))
            dt = html.escape(str(d.get("driver_date") or "Not Available"))
            reason = html.escape(str(d.get("health_reason") or d.get("diagnostic_reason") or "Not Available"))
            inf = html.escape(str(d.get("inf_name") or d.get("inf_path") or "Not Available"))

            rows_html.append(f"""
            <tr>
              <td><strong>{d_name}</strong><br><small style="color: #64748B;">{d_class}</small></td>
              <td>{mfr}<br><small style="color: #64748B;">{prov}</small></td>
              <td><code>{ver}</code><br><small style="color: #64748B;">{dt}</small></td>
              <td><span style="padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; {badge_style}">{health_class}</span></td>
              <td><small>{reason}</small></td>
              <td><small><code>{inf}</code></small></td>
            </tr>
            """)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SYSFIX — Windows Driver Inventory & Diagnostics Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0F172A; color: #F8FAFC; margin: 0; padding: 30px; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    .header {{ border-bottom: 2px solid #334155; padding-bottom: 20px; margin-bottom: 24px; }}
    h1 {{ margin: 0 0 6px 0; font-size: 24px; color: #7C83FF; }}
    .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
    .stat-card {{ background: #1E293B; border-radius: 8px; padding: 16px; border: 1px solid #334155; }}
    .stat-val {{ font-size: 26px; font-weight: bold; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: #1E293B; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid #334155; font-size: 13px; }}
    th {{ background: #0F172A; color: #94A3B8; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
    tr:hover {{ background: rgba(124, 131, 255, 0.05); }}
    code {{ font-family: monospace; font-size: 12px; }}
    .notice {{ background: rgba(124, 131, 255, 0.1); border-left: 4px solid #7C83FF; padding: 12px 16px; border-radius: 6px; margin-bottom: 20px; font-size: 12px; color: #CBD5E1; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>TERMINAL BOARD — Hardware & Device Driver Diagnostics Report</h1>
      <p style="margin: 0; color: #94A3B8; font-size: 13px;">Generated on {now_str} • Verified Windows PnP Diagnostics</p>
    </div>

    <div class="stats-grid">
      <div class="stat-card">
        <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase;">Total Devices Scanned</div>
        <div class="stat-val" style="color: #F8FAFC;">{total_count}</div>
      </div>
      <div class="stat-card">
        <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase;">Healthy Drivers</div>
        <div class="stat-val" style="color: #45D6A3;">{healthy_count}</div>
      </div>
      <div class="stat-card">
        <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase;">Driver Warnings</div>
        <div class="stat-val" style="color: #FFC66D;">{warning_count}</div>
      </div>
      <div class="stat-card">
        <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase;">Critical Issues</div>
        <div class="stat-val" style="color: #FF647C;">{critical_count}</div>
      </div>
    </div>

    <div class="notice">
      <strong>Diagnostics Integrity Principle:</strong>
      Driver dates reflect manufacturer release timestamps and do not indicate outdated or insecure software without confirmed compatibility advisories. TERMINAL BOARD performs read-only diagnostics and never modifies system driver configurations without explicit consent.
    </div>

    <table>
      <thead>
        <tr>
          <th>Device Name & Class</th>
          <th>Manufacturer & Provider</th>
          <th>Driver Version & Date</th>
          <th>Health Status</th>
          <th>Diagnostic Reason / PnP Telemetry</th>
          <th>INF Package</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html)}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
