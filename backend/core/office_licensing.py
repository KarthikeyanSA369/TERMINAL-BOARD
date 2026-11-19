"""
SYSFIX Microsoft Office Activation & Licensing Engine
Discovers Microsoft Office installations (Office 2010/2013/2016/2019/2021/365,
MSI and Click-to-Run, 32-bit and 64-bit), locates the diagnostic OSPP.VBS script,
and performs read-only licensing inspection via 'cscript.exe //nologo <path> /dstatus'.

Parses real licensing output:
- SKU ID / Product Name
- License Description & Channel (Volume KMS, Retail, OEM, Subscription)
- License Status (LICENSED, NOTIFICATIONS, GRACE PERIOD, UNLICENSED)
- Last 5 characters of product key (never extracts full keys)
- Error codes and descriptions
- KMS / Activation configuration
- Maps to normalized statuses: ACTIVATED, NOT_ACTIVATED, GRACE_PERIOD, NOTIFICATIONS, UNKNOWN, UNSUPPORTED

Never modifies licensing state, executes rearms, or bypasses activation.
"""

import os
import sys
import re
import subprocess
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("SYSFIX.OfficeLicensing")

# Standard Office installation directories to inspect
OFFICE_PATH_CANDIDATES = [
    # Office 2013 (Office15)
    r"C:\Program Files (x86)\Microsoft Office\Office15\OSPP.VBS",
    r"C:\Program Files\Microsoft Office\Office15\OSPP.VBS",
    # Office 2016 / 2019 / 2021 / 365 (Office16)
    r"C:\Program Files\Microsoft Office\Office16\OSPP.VBS",
    r"C:\Program Files (x86)\Microsoft Office\Office16\OSPP.VBS",
    r"C:\Program Files\Microsoft Office\root\Office16\OSPP.VBS",
    r"C:\Program Files (x86)\Microsoft Office\root\Office16\OSPP.VBS",
    # Office 2010 (Office14)
    r"C:\Program Files\Microsoft Office\Office14\OSPP.VBS",
    r"C:\Program Files (x86)\Microsoft Office\Office14\OSPP.VBS",
]

# In-memory cache for Office licensing results
_cached_office_licensing: Optional[Dict[str, Any]] = None

def find_office_ospp_script() -> Optional[str]:
    """
    Dynamically locate the official OSPP.VBS licensing script across
    standard paths, Click-to-Run roots, and registry install locations.
    """
    # 1. Check known candidates
    for path in OFFICE_PATH_CANDIDATES:
        if os.path.isfile(path):
            return os.path.abspath(path)

    # 2. Check Windows Registry for custom InstallRoot paths
    if sys.platform == "win32":
        try:
            import winreg
            versions = ["16.0", "15.0", "14.0"]
            hives = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Office"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Office")
            ]
            for hive, base_key in hives:
                for ver in versions:
                    subkey = f"{base_key}\\{ver}\\Common\\InstallRoot"
                    try:
                        with winreg.OpenKey(hive, subkey) as k:
                            install_path, _ = winreg.QueryValueEx(k, "Path")
                            if install_path:
                                candidate = os.path.join(install_path.strip(), "OSPP.VBS")
                                if os.path.isfile(candidate):
                                    return os.path.abspath(candidate)
                    except Exception:
                        pass
        except Exception:
            pass

    return None

def normalize_office_license_status(raw_status: str, error_code: Optional[str] = None) -> str:
    """
    Map source license status string into standardized status:
    ACTIVATED, NOT_ACTIVATED, GRACE_PERIOD, NOTIFICATIONS, UNKNOWN, UNSUPPORTED.
    """
    clean = (raw_status or "").upper().strip()
    
    if "LICENSED" in clean and "UNLICENSED" not in clean and "NOTIFICATIONS" not in clean:
        return "ACTIVATED"
    elif "NOTIFICATIONS" in clean:
        return "NOTIFICATIONS"
    elif "GRACE" in clean:
        return "GRACE_PERIOD"
    elif "UNLICENSED" in clean:
        return "NOT_ACTIVATED"
    elif not clean:
        return "UNKNOWN"
    return "UNKNOWN"

def parse_ospp_dstatus_output(stdout_text: str) -> List[Dict[str, Any]]:
    """
    Parse output of 'cscript.exe //nologo OSPP.VBS /dstatus'.
    Handles multiple Office product records independently.
    """
    records: List[Dict[str, Any]] = []
    if not stdout_text:
        return records

    # Split output into distinct processing blocks
    blocks = re.split(r"-{10,}\s*(?:Processing)?\s*-{10,}", stdout_text)
    
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        
        # Check if this block contains an Office SKU / License entry
        has_sku = any("SKU ID:" in l for l in lines)
        has_license_name = any("LICENSE NAME:" in l for l in lines)
        if not (has_sku or has_license_name):
            continue

        record: Dict[str, Any] = {
            "sku_id": "",
            "license_name": "",
            "license_description": "",
            "license_channel": "",
            "license_status": "",
            "normalized_status": "UNKNOWN",
            "error_code": "",
            "error_description": "",
            "last_5_key": "",
            "beta_expiration": "",
            "activation_type": "",
            "kms_server": "",
            "remaining_grace_days": None,
            "raw_block": "\n".join(lines)
        }

        for line in lines:
            if line.startswith("SKU ID:"):
                record["sku_id"] = line.split("SKU ID:", 1)[1].strip()
            elif line.startswith("LICENSE NAME:"):
                record["license_name"] = line.split("LICENSE NAME:", 1)[1].strip()
            elif line.startswith("LICENSE DESCRIPTION:"):
                desc = line.split("LICENSE DESCRIPTION:", 1)[1].strip()
                record["license_description"] = desc
                # Determine channel
                if "VOLUME_KMSCLIENT" in desc.upper() or "KMS" in desc.upper():
                    record["license_channel"] = "Volume KMS"
                elif "VOLUME_MAK" in desc.upper() or "MAK" in desc.upper():
                    record["license_channel"] = "Volume MAK"
                elif "RETAIL" in desc.upper():
                    record["license_channel"] = "Retail"
                elif "OEM" in desc.upper():
                    record["license_channel"] = "OEM"
                elif "SUBSCRIPTION" in desc.upper():
                    record["license_channel"] = "Subscription"
                else:
                    record["license_channel"] = "Commercial"
            elif line.startswith("LICENSE STATUS:"):
                status_raw = line.split("LICENSE STATUS:", 1)[1].strip()
                record["license_status"] = status_raw
                record["normalized_status"] = normalize_office_license_status(status_raw)
            elif line.startswith("ERROR CODE:"):
                record["error_code"] = line.split("ERROR CODE:", 1)[1].strip()
            elif line.startswith("ERROR DESCRIPTION:"):
                record["error_description"] = line.split("ERROR DESCRIPTION:", 1)[1].strip()
            elif "Last 5 characters of installed product key:" in line:
                key_part = line.split("Last 5 characters of installed product key:", 1)[1].strip()
                # Security guarantee: Only store up to 5 alphanumeric characters
                record["last_5_key"] = re.sub(r"[^A-Za-z0-9]", "", key_part)[:5]
            elif line.startswith("BETA EXPIRATION:"):
                record["beta_expiration"] = line.split("BETA EXPIRATION:", 1)[1].strip()
            elif line.startswith("Activation Type Configuration:"):
                record["activation_type"] = line.split("Activation Type Configuration:", 1)[1].strip()
            elif "KMS machine registry override defined:" in line:
                record["kms_server"] = line.split("KMS machine registry override defined:", 1)[1].strip()
            elif "REMAINING GRACE:" in line.upper():
                # e.g. REMAINING GRACE: 30 days  (43200 minute(s) before exhausting grace)
                grace_match = re.search(r"(\d+)\s*days?", line, re.IGNORECASE)
                if grace_match:
                    try:
                        record["remaining_grace_days"] = int(grace_match.group(1))
                    except Exception:
                        pass

        # If normalized status is NOTIFICATIONS, check error code for context
        if record["normalized_status"] == "NOTIFICATIONS" and not record["error_description"]:
            if "0xC004F00F" in record["error_code"]:
                record["error_description"] = "Hardware ID binding beyond tolerance (reactivation required)."
            else:
                record["error_description"] = "Notification mode: activation is required."

        records.append(record)

    return records

def query_office_activation(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Safely query real Microsoft Office activation status.
    Executes 'cscript.exe //nologo <ospp.vbs> /dstatus' with shell=False and timeout.
    Returns comprehensive diagnostics and parsed product records.
    """
    global _cached_office_licensing
    if _cached_office_licensing is not None and not force_refresh:
        return _cached_office_licensing

    result: Dict[str, Any] = {
        "success": False,
        "is_installed": False,
        "ospp_path": None,
        "records": [],
        "primary_status": "UNKNOWN",
        "primary_product": None,
        "diagnostic_method": "OSPP.VBS Inspection",
        "diagnostic_reason": "",
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    if sys.platform != "win32":
        result["diagnostic_reason"] = "Microsoft Office activation query is supported only on Windows."
        result["primary_status"] = "UNSUPPORTED"
        _cached_office_licensing = result
        return result

    script_path = find_office_ospp_script()
    if not script_path or not os.path.isfile(script_path):
        result["diagnostic_reason"] = "OSPP.VBS diagnostic script was not found in standard Office locations. Activation status could not be verified."
        result["primary_status"] = "UNSUPPORTED"
        _cached_office_licensing = result
        return result

    result["is_installed"] = True
    result["ospp_path"] = script_path

    # Execute read-only cscript command
    from backend.core.subproc import safe_run
    cmd = ["cscript.exe", "//nologo", script_path, "/dstatus"]
    try:
        proc = safe_run(
            cmd,
            capture_output=True,
            text=True,
            timeout=25,
            shell=False
        )
        
        stdout_text = proc.stdout or ""
        stderr_text = proc.stderr or ""

        if proc.returncode != 0 and not stdout_text.strip():
            result["diagnostic_reason"] = f"cscript execution returned exit code {proc.returncode}: {stderr_text.strip() or 'No error output'}"
            result["primary_status"] = "UNKNOWN"
            _cached_office_licensing = result
            return result

        parsed_records = parse_ospp_dstatus_output(stdout_text)
        result["records"] = parsed_records
        result["success"] = len(parsed_records) > 0

        if parsed_records:
            # Use first/primary record
            primary = parsed_records[0]
            result["primary_product"] = primary.get("license_name")
            result["primary_status"] = primary.get("normalized_status", "UNKNOWN")
            result["diagnostic_reason"] = f"Parsed from {os.path.basename(script_path)} /dstatus output."
        else:
            result["primary_status"] = "UNKNOWN"
            result["diagnostic_reason"] = "OSPP script ran successfully but returned no active license blocks. Activation status could not be verified."

    except subprocess.TimeoutExpired:
        result["diagnostic_reason"] = "OSPP.VBS query timed out after 12 seconds."
        result["primary_status"] = "UNKNOWN"
    except PermissionError:
        result["diagnostic_reason"] = "Permission denied while attempting to execute OSPP.VBS."
        result["primary_status"] = "UNKNOWN"
    except Exception as e:
        logger.error(f"Error querying Office activation: {e}")
        result["diagnostic_reason"] = f"Unexpected error during Office activation check: {str(e)}"
        result["primary_status"] = "UNKNOWN"

    _cached_office_licensing = result
    return result
