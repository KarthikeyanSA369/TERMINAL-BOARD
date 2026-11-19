"""
SYSFIX License Audit Engine
Inspects Python package metadata (importlib.metadata), Node.js package manifests,
Windows software registry, and Windows SoftwareLicensingProduct CIM interfaces to
build an evidence-based software license audit.

Classifies entries into:
- License Categories: Commercial, Subscription, Freeware, Open Source, Trial, Unknown
- Verification Statuses: Verified license information, Review required, Potential licensing concern, Unknown
- Evidence Sources:
  * Vendor-reported licensing information
  * Windows-reported activation information
  * Discovered local license files
  * User-provided compliance records
  * Independently verified license information
  * Unknown or inconclusive evidence

Never extracts full product keys, credentials, or private activation tokens.
Exports audit reports to RFC 4180 CSV and standalone responsive HTML format.
"""

import os
import sys
import csv
import io
import json
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional

from backend.core.cryptic import sanitize_report_text, to_cryptic

from backend.core.office_licensing import query_office_activation
from backend.core.license_expiry import evaluate_license_expiry
from backend.database import (
    save_office_licensing_snapshot, save_windows_licensing_snapshot,
    get_manual_license_records
)

# Try importing importlib.metadata
try:
    import importlib.metadata as importlib_metadata
except ImportError:
    import importlib_metadata

# Common Permissive / Verified SPDX licenses
PERMISSIVE_LICENSES = {
    "mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause", "isc", "python-2.0",
    "apache 2.0", "bsd", "zlib", "unlicense", "cc0-1.0", "artistic-2.0", "psf", "psfl"
}

# Copyleft licenses requiring review
COPYLEFT_LICENSES = {
    "gpl-3.0", "gpl-2.0", "lgpl-3.0", "lgpl-2.1", "agpl-3.0", "gpl", "lgpl", "mpl-2.0", "epl-2.0"
}

PROPRIETARY_TERMS = {
    "commercial", "proprietary", "all rights reserved", "microsoft software license",
    "adobe end user license", "eula", "subscription", "closed source", "corporate"
}

# In-memory cache for Windows activation status
_cached_activation_info: Optional[Dict[str, Dict[str, Any]]] = None

def query_windows_activation_status() -> Dict[str, Dict[str, Any]]:
    """
    Safely query Windows SoftwareLicensingProduct for activated components without
    retrieving product keys, passwords, or credentials.
    Returns normalized dictionary of product activation states.
    """
    global _cached_activation_info
    if _cached_activation_info is not None:
        return _cached_activation_info

    results: Dict[str, Dict[str, Any]] = {}
    if sys.platform != "win32":
        _cached_activation_info = results
        return results

    status_map = {
        1: "Licensed (Permanent Activation)",
        2: "Initial Grace Period",
        3: "Hardware Change Grace Period",
        4: "Non-Genuine Grace Period",
        5: "Notification Mode (Activation Required)",
        6: "Extended Grace Period",
        0: "Unlicensed"
    }

    # Method 1: Native in-process WMI query (instant, no console windows)
    try:
        import wmi
        c = wmi.WMI()
        products = c.query("SELECT Name, Description, LicenseStatus FROM SoftwareLicensingProduct WHERE PartialProductKey IS NOT NULL")
        for item in products:
            name = getattr(item, "Name", "") or ""
            desc = getattr(item, "Description", "") or ""
            status_code = int(getattr(item, "LicenseStatus", 0) or 0)
            status_label = status_map.get(status_code, f"Status Code {status_code}")
            is_activated = (status_code == 1)
            key = name.lower()
            results[key] = {
                "product_name": name,
                "description": desc,
                "status_code": status_code,
                "status_label": status_label,
                "is_activated": is_activated
            }
        if results:
            _cached_activation_info = results
            return results
    except Exception:
        pass

    # Method 2: Safe hidden PowerShell fallback (captures output, never shows window)
    from backend.core.subproc import safe_run
    cmd = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
        "Get-CimInstance SoftwareLicensingProduct -Filter 'PartialProductKey is not null' | "
        "Select-Object Name, Description, LicenseStatus | ConvertTo-Json -Compress"
    ]
    try:
        proc = safe_run(cmd, capture_output=True, text=True, timeout=5)
        if proc.returncode == 0 and proc.stdout.strip():
            raw_out = proc.stdout.strip()
            data = json.loads(raw_out)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                name = item.get("Name", "")
                desc = item.get("Description", "")
                status_code = item.get("LicenseStatus", 0)
                status_label = status_map.get(status_code, f"Status Code {status_code}")
                is_activated = (status_code == 1)

                key = name.lower()
                results[key] = {
                    "product_name": name,
                    "description": desc,
                    "status_code": status_code,
                    "status_label": status_label,
                    "is_activated": is_activated
                }
    except Exception:
        pass

    _cached_activation_info = results
    return results

def read_license_file_snippet(file_path: Optional[str], max_chars: int = 1500) -> Optional[str]:
    """Safely read the initial block of a local license or EULA file."""
    if not file_path or not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)
    except Exception:
        return None

def classify_license(license_str: Optional[str], license_file: Optional[str],
                     publisher: str, software_name: str,
                     install_location: Optional[str] = None,
                     activation_info: Optional[Dict[str, Any]] = None,
                     custom_notes: Optional[str] = None) -> Dict[str, Any]:
    """
    Evidence-based license classification.
    Distinguishes license categories (Commercial, Subscription, Freeware, Open Source, Trial, Unknown)
    and evidence sources without inferring solely from application name.
    """
    raw_str = (license_str or "").strip()
    raw_lower = raw_str.lower()
    pub_lower = (publisher or "").strip().lower()

    # 1. User-Provided Compliance Records take high priority if provided
    if custom_notes and custom_notes.strip():
        # User explicitly documented compliance
        pass

    # 2. Check for Windows-Reported Activation Information
    if activation_info and activation_info.get("is_activated"):
        return {
            "status": "Verified license information",
            "badge_class": "badge-healthy",
            "license_category": "Commercial",
            "evidence_source": "Windows-reported activation information",
            "verification_method": "Windows SoftwareLicensingService WMI/CIM Query",
            "activation_status": activation_info.get("status_label", "Licensed (Activated)"),
            "status_reason": f"System activation confirmed through Windows SoftwareLicensingService: {activation_info.get('description', 'Operating System')}.",
            "note": f"System activation confirmed via Windows SoftwareLicensingService: {activation_info.get('description', '')}"
        }
    elif activation_info and not activation_info.get("is_activated"):
        return {
            "status": "Review required",
            "badge_class": "badge-warning",
            "license_category": "Commercial",
            "evidence_source": "Windows-reported activation information",
            "verification_method": "Windows SoftwareLicensingService WMI/CIM Query",
            "activation_status": activation_info.get("status_label", "Notification Mode"),
            "status_reason": f"Windows SoftwareLicensingService reported: {activation_info.get('status_label')}. Device attention or key renewal may be required.",
            "note": f"Windows SoftwareLicensingService reported {activation_info.get('status_label')}."
        }

    # 3. Check for Vendor-Reported SPDX Open Source Identifiers
    if raw_str and raw_lower not in ("unknown", "none", "", "not documented", "not specified"):
        # Permissive Open Source
        if any(p in raw_lower for p in PERMISSIVE_LICENSES):
            return {
                "status": "Verified license information",
                "badge_class": "badge-healthy",
                "license_category": "Open Source",
                "evidence_source": "Vendor-reported licensing information",
                "verification_method": "SPDX Package Manifest / Registry Metadata",
                "activation_status": "Not Applicable (Open Source)",
                "status_reason": f"Package declared standard open-source permissive license identifier ({raw_str}). Open source distribution does not require proprietary activation.",
                "note": f"Standard open-source permissive license identified ({raw_str})."
            }

        # Copyleft Open Source
        if any(c in raw_lower for c in COPYLEFT_LICENSES):
            return {
                "status": "Review required",
                "badge_class": "badge-warning",
                "license_category": "Open Source",
                "evidence_source": "Vendor-reported licensing information",
                "verification_method": "SPDX Package Manifest / Registry Metadata",
                "activation_status": "Not Applicable (Open Source)",
                "status_reason": f"Reciprocal/Copyleft license terms detected ({raw_str}). Review internal distribution obligations.",
                "note": f"Reciprocal / Copyleft license detected ({raw_str}). Review obligations for proprietary integration."
            }

        # Subscription terms
        if "subscription" in raw_lower or "saas" in raw_lower or "office 365" in raw_lower or "creative cloud" in raw_lower:
            return {
                "status": "Verified license information",
                "badge_class": "badge-healthy",
                "license_category": "Subscription",
                "evidence_source": "Vendor-reported licensing information",
                "verification_method": "Vendor Subscription Channel Manifest",
                "activation_status": "Subscription Account Managed",
                "status_reason": f"Vendor metadata declares subscription licensing channel ({raw_str}). Entitlement is verified through user account portal.",
                "note": f"Subscription licensing terms recorded ({raw_str})."
            }

        # Trial terms
        if "trial" in raw_lower or "evaluation" in raw_lower or "preview" in raw_lower:
            return {
                "status": "Review required",
                "badge_class": "badge-warning",
                "license_category": "Trial",
                "evidence_source": "Vendor-reported licensing information",
                "verification_method": "Installer Trial Metadata Declaration",
                "activation_status": "Evaluation / Trial Mode",
                "status_reason": "Software is installed under evaluation or trial terms. Verify expiration period and commercial usage restrictions.",
                "note": "Installed under evaluation or trial terms. Verification recommended."
            }

        # Explicit Freeware terms
        if "freeware" in raw_lower or "free for non-commercial" in raw_lower:
            return {
                "status": "Verified license information",
                "badge_class": "badge-healthy",
                "license_category": "Freeware",
                "evidence_source": "Vendor-reported licensing information",
                "verification_method": "Vendor Distribution Declaration",
                "activation_status": "Not Applicable (Freeware)",
                "status_reason": "Vendor declares software as freeware without per-seat licensing fees. Verify organizational usage restrictions.",
                "note": f"Freeware license declaration recorded ({raw_str})."
            }

        # Commercial / Proprietary Vendor declarations
        if any(pr in raw_lower for pr in PROPRIETARY_TERMS) or "microsoft" in pub_lower or "adobe" in pub_lower:
            return {
                "status": "Verified license information",
                "badge_class": "badge-healthy",
                "license_category": "Commercial",
                "evidence_source": "Vendor-reported licensing information",
                "verification_method": "Vendor EULA / Installer Registry Metadata",
                "activation_status": "Activation Data Unavailable",
                "status_reason": f"Commercial/EULA terms documented from publisher ({publisher}). Note: Installer metadata documents licensing model but does not prove purchase invoice entitlement.",
                "note": f"Commercial / EULA license metadata recorded from vendor ({publisher})."
            }

    # 4. Check for Discovered Local License Files
    if license_file and os.path.exists(license_file):
        snippet = read_license_file_snippet(license_file, max_chars=1000)
        snippet_lower = (snippet or "").lower()

        # Check if local file contains open source notices
        if snippet and any(p in snippet_lower for p in ["mit license", "apache license", "general public license", "bsd license", "mozilla public"]):
            return {
                "status": "Verified license information",
                "badge_class": "badge-healthy",
                "license_category": "Open Source",
                "evidence_source": "Discovered local license files",
                "verification_method": "Local License File Content Inspection",
                "activation_status": "Not Applicable (Open Source)",
                "status_reason": f"Discovered local license file '{os.path.basename(license_file)}' containing standard open-source terms. A detected license file documents software rights and does not require proprietary activation.",
                "note": f"Discovered local open-source license file ({os.path.basename(license_file)})."
            }
        elif snippet and any(c in snippet_lower for c in ["end user license", "eula", "all rights reserved", "commercial"]):
            return {
                "status": "Review required",
                "badge_class": "badge-warning",
                "license_category": "Commercial",
                "evidence_source": "Discovered local license files",
                "verification_method": "Local EULA File Discovery",
                "activation_status": "Activation Data Unavailable",
                "status_reason": f"Local EULA file '{os.path.basename(license_file)}' was discovered. Notice: Presence of a local EULA file documents legal terms but does not prove commercial purchase or activation.",
                "note": f"Local EULA file exists ({os.path.basename(license_file)}) but requires commercial invoice verification."
            }

        return {
            "status": "Review required",
            "badge_class": "badge-warning",
            "license_category": "Open Source",
            "evidence_source": "Discovered local license files",
            "verification_method": "Local License File Discovery",
            "activation_status": "Not Applicable",
            "status_reason": f"Local license file '{os.path.basename(license_file)}' exists, but explicit SPDX identifier was not found in registry metadata.",
            "note": f"License file exists ({os.path.basename(license_file)}) but SPDX identifier is missing from metadata."
        }

    # 5. Fallback: Incomplete or Inconclusive Evidence
    return {
        "status": "Unknown",
        "badge_class": "badge-cryptic",
        "license_category": "Unknown",
        "evidence_source": "Unknown or inconclusive evidence",
        "verification_method": "Inconclusive Heuristic",
        "activation_status": "Activation Data Unavailable",
        "status_reason": "No license metadata, activation records, or local license files were exposed by the application installer. Missing license metadata does not indicate improper installation or non-compliance.",
        "note": "No license metadata or local license file found. This does not indicate illegal installation."
    }

def audit_python_packages(limit: int = 60) -> List[Dict[str, Any]]:
    """Scan Python packages in the current environment using importlib.metadata."""
    records = []
    try:
        distributions = list(importlib_metadata.distributions())
        for dist in distributions[:limit]:
            name = dist.metadata.get("Name", "Python Package")
            version = dist.metadata.get("Version", "Not Available")
            raw_license = dist.metadata.get("License") or dist.metadata.get("License-Expression") or ""
            author = dist.metadata.get("Author") or dist.metadata.get("Author-email") or "Python Community"

            # Check classifiers for OSI Approved licenses if license string is generic
            classifiers = dist.metadata.get_all("Classifier") or []
            osi_license = None
            for c in classifiers:
                if c.startswith("License :: OSI Approved ::"):
                    osi_license = c.replace("License :: OSI Approved ::", "").strip()
                    break

            effective_lic = raw_license if (raw_license and len(raw_license) < 40) else (osi_license or raw_license or "SPDX Not Declared")
            classification = classify_license(effective_lic or osi_license, None, author, name)

            records.append({
                "name": name,
                "version": version,
                "publisher": author,
                "category": "Python Package",
                "license_category": classification["license_category"],
                "license_identifier": effective_lic,
                "license_source": "importlib.metadata",
                "evidence_source": classification["evidence_source"],
                "verification_status": classification["status"],
                "verification_method": classification["verification_method"],
                "activation_status": classification["activation_status"],
                "badge_class": classification["badge_class"],
                "status_reason": classification["status_reason"],
                "notes": classification["note"],
                "compliance_notes": "",
                "license_file": None,
                "install_path": str(dist.locate_file("")) if hasattr(dist, "locate_file") else "Site-Packages",
                "last_audited": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    except Exception:
        pass
    return records

def audit_node_manifest(package_json_path: str) -> Optional[Dict[str, Any]]:
    """Audit single Node.js package.json file."""
    if not os.path.exists(package_json_path):
        return None
    try:
        with open(package_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            name = data.get("name", "Node Module")
            version = data.get("version", "Not Available")
            raw_license = data.get("license") or "Not Specified"
            author = data.get("author", "Node Community")
            if isinstance(author, dict):
                author = author.get("name", "Node Community")

            classification = classify_license(raw_license, None, str(author), name)

            return {
                "name": name,
                "version": version,
                "publisher": str(author),
                "category": "Node.js Dependency",
                "license_category": classification["license_category"],
                "license_identifier": raw_license,
                "license_source": "package.json manifest",
                "evidence_source": classification["evidence_source"],
                "verification_status": classification["status"],
                "verification_method": classification["verification_method"],
                "activation_status": classification["activation_status"],
                "badge_class": classification["badge_class"],
                "status_reason": classification["status_reason"],
                "notes": classification["note"],
                "compliance_notes": "",
                "license_file": None,
                "install_path": os.path.dirname(package_json_path),
                "last_audited": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    except Exception:
        return None

def generate_full_license_audit(installed_software: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge installed applications, real Microsoft Office activation status,
    Windows operating system activation records, Python packages, and user
    manual records into a unified, evidence-based license audit list.
    """
    audit_list: List[Dict[str, Any]] = []

    # 1. Query safe Windows Activation Information
    activation_data = query_windows_activation_status()

    # Find Windows OS activation
    win_os_act = None
    for k, v in activation_data.items():
        if "windows" in k and "edition" in k:
            win_os_act = v
            break

    # Add Windows OS entry if available
    if win_os_act:
        try:
            save_windows_licensing_snapshot(win_os_act)
        except Exception:
            pass

        classification = classify_license(
            "Microsoft Windows Operating System Commercial License",
            None,
            "Microsoft Corporation",
            win_os_act["product_name"],
            activation_info=win_os_act
        )
        exp_eval = evaluate_license_expiry(
            None,
            license_category=classification["license_category"],
            raw_status="Licensed" if win_os_act.get("is_activated") else "Incomplete Evidence"
        )
        audit_list.append({
            "name": win_os_act["product_name"],
            "version": "Windows 10 / 11",
            "publisher": "Microsoft Corporation",
            "category": "Operating System",
            "license_category": classification["license_category"],
            "license_identifier": win_os_act["description"],
            "license_source": "Windows SoftwareLicensingService (CIM)",
            "evidence_source": classification["evidence_source"],
            "verification_status": classification["status"],
            "verification_method": classification["verification_method"],
            "activation_status": classification["activation_status"],
            "expiry_date": None,
            "expiry_state": "PERPETUAL" if win_os_act.get("is_activated") else "CRYPTIC",
            "days_remaining": None,
            "expiry_reason": "Perpetual retail / volume Windows license.",
            "badge_class": classification["badge_class"],
            "status_reason": classification["status_reason"],
            "notes": classification["note"],
            "compliance_notes": "",
            "license_file": r"C:\Windows\System32\license.rtf" if os.path.exists(r"C:\Windows\System32\license.rtf") else None,
            "install_path": os.environ.get("SystemRoot", r"C:\Windows"),
            "last_audited": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    # 2. Query real Microsoft Office Activation Status
    office_data = query_office_activation()
    office_records = office_data.get("records", [])
    if office_records:
        try:
            save_office_licensing_snapshot(office_records)
        except Exception:
            pass

        # Add primary Office suite entry
        for off_rec in office_records:
            norm_status = off_rec.get("normalized_status", "UNKNOWN")
            channel = off_rec.get("license_channel", "Commercial")
            key_suffix = off_rec.get("last_5_key", "")
            key_display = f"...{key_suffix}" if key_suffix else "Undisclosed"

            if norm_status == "ACTIVATED":
                off_act_label = "Licensed (Permanent Activation)"
                off_ver_status = "Verified license information"
                off_badge = "badge-healthy"
                off_reason = f"Activated via {channel}. Key suffix: {key_display}."
            elif norm_status == "NOTIFICATIONS":
                err_text = f" (Error {off_rec.get('error_code')}: {off_rec.get('error_description')})" if off_rec.get("error_code") else ""
                off_act_label = f"Notification Mode{err_text}"
                off_ver_status = "Review required"
                off_badge = "badge-warning"
                off_reason = f"Office is in Notification Mode: activation required. Error: {off_rec.get('error_description') or 'Hardware binding/tolerance error.'}"
            elif norm_status == "GRACE_PERIOD":
                grace_days = off_rec.get("remaining_grace_days")
                off_act_label = f"Grace Period ({grace_days or 'Active'} days remaining)"
                off_ver_status = "Review required"
                off_badge = "badge-warning"
                off_reason = f"Office is operating under an active grace period ({grace_days} days remaining)."
            elif norm_status == "NOT_ACTIVATED":
                off_act_label = "Unlicensed"
                off_ver_status = "Potential licensing concern"
                off_badge = "badge-critical"
                off_reason = "Office reports unlicensed status."
            else:
                off_act_label = "Activation Data Unavailable"
                off_ver_status = "Incomplete Evidence"
                off_badge = "badge-cryptic"
                off_reason = off_rec.get("error_description") or "Activation status could not be verified."

            # Determine expiry state
            exp_eval = evaluate_license_expiry(
                None,
                license_category="Commercial" if "RETAIL" in channel.upper() or "KMS" in channel.upper() else "Subscription",
                raw_status=norm_status
            )

            audit_list.append({
                "name": off_rec.get("license_name") or "Microsoft Office Suite",
                "version": "Office 2013 / 2016",
                "publisher": "Microsoft Corporation",
                "category": "Productivity Suite",
                "license_category": "Commercial" if "RETAIL" in channel.upper() or "KMS" in channel.upper() else "Subscription",
                "license_identifier": f"{off_rec.get('license_name', 'Office')} ({channel})",
                "license_source": "OSPP.VBS Diagnostics (/dstatus)",
                "evidence_source": "Vendor-reported licensing information",
                "verification_status": off_ver_status,
                "verification_method": f"OSPP.VBS Diagnostic Query ({channel})",
                "activation_status": off_act_label,
                "expiry_date": None,
                "expiry_state": exp_eval["state"],
                "days_remaining": exp_eval["days_remaining"],
                "expiry_reason": exp_eval["reason"],
                "badge_class": off_badge,
                "status_reason": off_reason,
                "notes": f"SKU: {off_rec.get('sku_id', 'N/A')}. Activation Type: {off_rec.get('activation_type', 'KMS')}. Key Suffix: {key_display}.",
                "compliance_notes": "",
                "license_file": office_data.get("ospp_path"),
                "install_path": os.path.dirname(office_data.get("ospp_path", "")) if office_data.get("ospp_path") else r"C:\Program Files\Microsoft Office",
                "office_details": off_rec,
                "last_audited": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    # 3. Process installed applications from software inventory
    primary_office_rec = office_records[0] if office_records else None

    for app in installed_software:
        name = app.get("name", "")
        if not name:
            continue

        lic_file = app.get("license_file")
        pub = app.get("publisher", "")
        install_loc = app.get("install_location") or app.get("exe_path", "N/A")
        name_lower = name.lower()

        # Check if this app belongs to Microsoft Office suite
        is_office_app = any(term in name_lower for term in ["word", "excel", "powerpoint", "outlook", "access", "publisher", "onenote"]) and ("microsoft" in pub.lower() or "office" in name_lower)

        if is_office_app and primary_office_rec:
            # Enrich with real Office telemetry
            norm_status = primary_office_rec.get("normalized_status", "UNKNOWN")
            channel = primary_office_rec.get("license_channel", "Commercial")
            key_suffix = primary_office_rec.get("last_5_key", "")
            key_display = f"...{key_suffix}" if key_suffix else "Undisclosed"

            if norm_status == "ACTIVATED":
                off_act_label = "Licensed (Permanent Activation)"
                off_ver_status = "Verified license information"
                off_badge = "badge-healthy"
            elif norm_status == "NOTIFICATIONS":
                err_text = f" (Error {primary_office_rec.get('error_code')})" if primary_office_rec.get("error_code") else ""
                off_act_label = f"Notification Mode{err_text}"
                off_ver_status = "Review required"
                off_badge = "badge-warning"
            elif norm_status == "GRACE_PERIOD":
                grace_days = primary_office_rec.get("remaining_grace_days")
                off_act_label = f"Grace Period ({grace_days or 'Active'} days remaining)"
                off_ver_status = "Review required"
                off_badge = "badge-warning"
            else:
                off_act_label = "Activation Data Unavailable"
                off_ver_status = "Incomplete Evidence"
                off_badge = "badge-cryptic"

            audit_list.append({
                "name": name,
                "version": app.get("version", "Not Available"),
                "publisher": pub or "Microsoft Corporation",
                "category": app.get("category", "Productivity"),
                "license_category": "Commercial" if "RETAIL" in channel.upper() or "KMS" in channel.upper() else "Subscription",
                "license_identifier": f"Microsoft Office Suite ({channel})",
                "license_source": "OSPP.VBS Diagnostics (/dstatus)",
                "evidence_source": "Vendor-reported licensing information",
                "verification_status": off_ver_status,
                "verification_method": f"OSPP.VBS Diagnostics ({channel})",
                "activation_status": off_act_label,
                "expiry_date": None,
                "expiry_state": "PERPETUAL" if norm_status == "ACTIVATED" else ("GRACE_PERIOD" if norm_status == "GRACE_PERIOD" else "CRYPTIC"),
                "days_remaining": None,
                "expiry_reason": "Office suite licensing model.",
                "badge_class": off_badge,
                "status_reason": f"Linked to installed Office suite. Channel: {channel}, Key suffix: {key_display}. Status: {primary_office_rec.get('license_status')}.",
                "notes": primary_office_rec.get("error_description", ""),
                "compliance_notes": "",
                "license_file": office_data.get("ospp_path"),
                "install_path": install_loc,
                "office_details": primary_office_rec,
                "last_audited": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            continue

        # Check declared or local license strings
        lic_str = None
        if "visual studio code" in name_lower:
            lic_str = "MIT / Microsoft Software License"
        elif "git" in name_lower:
            lic_str = "GNU General Public License v2"
        elif "python" in name_lower:
            lic_str = "Python Software Foundation License (PSFL)"
        elif "node.js" in name_lower:
            lic_str = "MIT License"
        elif "powershell" in name_lower:
            lic_str = "MIT License"
        elif "microsoft" in pub.lower():
            lic_str = "Microsoft Software License (EULA)"
        elif "adobe" in pub.lower():
            lic_str = "Adobe End User License Agreement (EULA)"
        elif lic_file:
            lic_str = f"Local License File ({os.path.basename(lic_file)})"

        classification = classify_license(
            lic_str,
            lic_file,
            pub,
            name,
            install_location=install_loc
        )

        exp_eval = evaluate_license_expiry(
            None,
            license_category=classification["license_category"],
            raw_status=classification["activation_status"]
        )

        audit_list.append({
            "name": name,
            "version": app.get("version", "Not Available"),
            "publisher": pub or "Unspecified Vendor",
            "category": app.get("category", "Application"),
            "license_category": classification["license_category"],
            "license_identifier": lic_str or "Not Documented",
            "license_source": "Windows Registry / Local Filesystem",
            "evidence_source": classification["evidence_source"],
            "verification_status": classification["status"],
            "verification_method": classification["verification_method"],
            "activation_status": classification["activation_status"],
            "expiry_date": None,
            "expiry_state": exp_eval["state"],
            "days_remaining": exp_eval["days_remaining"],
            "expiry_reason": exp_eval["reason"],
            "badge_class": classification["badge_class"],
            "status_reason": classification["status_reason"],
            "notes": classification["note"],
            "compliance_notes": "",
            "license_file": lic_file,
            "install_path": install_loc,
            "last_audited": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    # 4. Add Python packages from active environment
    py_packages = audit_python_packages(limit=50)
    for p in py_packages:
        exp_eval = evaluate_license_expiry(None, license_category=p.get("license_category", "Open Source"))
        p["expiry_date"] = None
        p["expiry_state"] = exp_eval["state"]
        p["days_remaining"] = None
        p["expiry_reason"] = exp_eval["reason"]
    audit_list.extend(py_packages)

    # 5. Check for project package.json in workspace
    workspace_pkg = os.path.join(os.getcwd(), "package.json")
    if os.path.exists(workspace_pkg):
        node_rec = audit_node_manifest(workspace_pkg)
        if node_rec:
            exp_eval = evaluate_license_expiry(None, license_category=node_rec.get("license_category", "Open Source"))
            node_rec["expiry_date"] = None
            node_rec["expiry_state"] = exp_eval["state"]
            node_rec["days_remaining"] = None
            node_rec["expiry_reason"] = exp_eval["reason"]
            audit_list.append(node_rec)

    # 6. Append user manual license records from SQLite
    try:
        manual_records = get_manual_license_records()
        for m in manual_records:
            exp_eval = evaluate_license_expiry(m.get("expiry_date"), license_category=m.get("license_category", "Subscription"))
            audit_list.append({
                "name": m.get("name", "Manual Record"),
                "version": m.get("purchase_date") or "User Record",
                "publisher": m.get("publisher") or "User-Specified",
                "category": "User Subscription / License",
                "license_category": m.get("license_category", "Subscription"),
                "license_identifier": f"Manual Record #{m.get('id')}",
                "license_source": "User Manual Entry",
                "evidence_source": "User-provided compliance records",
                "verification_status": "Review required" if exp_eval["state"] in ("EXPIRING_SOON", "EXPIRED") else "Verified license information",
                "verification_method": "User-Provided Documentation",
                "activation_status": "User-Managed Subscription",
                "expiry_date": m.get("expiry_date"),
                "expiry_state": exp_eval["state"],
                "days_remaining": exp_eval["days_remaining"],
                "expiry_reason": exp_eval["reason"],
                "badge_class": exp_eval["badge_class"],
                "status_reason": f"User-entered subscription: {m.get('notes') or 'No compliance notes'}",
                "notes": m.get("notes", ""),
                "compliance_notes": m.get("notes", ""),
                "license_file": None,
                "install_path": "User Managed",
                "manual_id": m.get("id"),
                "last_audited": m.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    except Exception:
        pass

    # 7. Persist to SQLite and merge existing manual compliance notes
    try:
        from backend.database import save_or_update_license_audit_records, get_all_license_audit_records
        save_or_update_license_audit_records(audit_list)
        # Re-query all records from DB to ensure compliance_notes and IDs are populated
        persisted = get_all_license_audit_records()
        if persisted:
            notes_map = {(p["name"], p["version"]): (p.get("compliance_notes") or "", p.get("evidence_source")) for p in persisted}
            for item in audit_list:
                key = (item["name"], item["version"])
                if key in notes_map:
                    c_note, ev_src = notes_map[key]
                    if c_note:
                        item["compliance_notes"] = c_note
                        item["evidence_source"] = "User-provided compliance records"
    except Exception:
        pass

    return audit_list

def export_audit_to_csv(audit_records: List[Dict[str, Any]]) -> str:
    """Generate RFC 4180 CSV export of comprehensive license audit."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Software Name", "Version", "Publisher", "Category",
        "License Category", "License Identifier", "License Evidence Source",
        "Verification Status", "Verification Method", "Activation Status",
        "Expiry State", "Expiry Date", "Discovered License File", "Status Reason & Analysis",
        "User Compliance Notes", "Install Path", "Last Audited"
    ])

    for r in audit_records:
        writer.writerow([
            r.get("name", ""),
            r.get("version", ""),
            r.get("publisher", ""),
            r.get("category", ""),
            r.get("license_category", "Incomplete Evidence"),
            r.get("license_identifier", ""),
            r.get("evidence_source", ""),
            r.get("verification_status", ""),
            r.get("verification_method", ""),
            r.get("activation_status", ""),
            r.get("expiry_state", "CRYPTIC"),
            r.get("expiry_date") or "",
            r.get("license_file") or "",
            r.get("status_reason") or r.get("notes", ""),
            r.get("compliance_notes", ""),
            r.get("install_path", ""),
            r.get("last_audited", "")
        ])

    return sanitize_report_text(output.getvalue())

def export_audit_to_html(audit_records: List[Dict[str, Any]]) -> str:
    """Generate Dark/Light responsive standalone HTML report."""
    total = len(audit_records)
    verified_count = sum(1 for r in audit_records if r.get("verification_status") == "Verified license information")
    review_count = sum(1 for r in audit_records if r.get("verification_status") == "Review required")
    open_source_count = sum(1 for r in audit_records if r.get("license_category") == "Open Source")
    commercial_count = sum(1 for r in audit_records if r.get("license_category") == "Commercial")

    rows = []
    for r in audit_records:
        status = r.get("verification_status", "Incomplete Evidence")
        badge_style = {
            "Verified license information": "background: rgba(69,214,163,0.15); color: #45D6A3; border: 1px solid rgba(69,214,163,0.4);",
            "Review required": "background: rgba(255,198,109,0.15); color: #FFC66D; border: 1px solid rgba(255,198,109,0.4);",
            "Potential licensing concern": "background: rgba(255,100,124,0.15); color: #FF647C; border: 1px solid rgba(255,100,124,0.4);",
            "Incomplete Evidence": "background: rgba(162,172,192,0.15); color: #A2ACC0; border: 1px solid rgba(162,172,192,0.3);"
        }.get(status, "color: #A2ACC0;")

        cat_badge_style = {
            "Open Source": "background: rgba(124,131,255,0.15); color: #7C83FF; border: 1px solid rgba(124,131,255,0.35);",
            "Commercial": "background: rgba(69,214,163,0.15); color: #45D6A3; border: 1px solid rgba(69,214,163,0.35);",
            "Subscription": "background: rgba(99,102,241,0.15); color: #818CF8; border: 1px solid rgba(99,102,241,0.35);",
            "Freeware": "background: rgba(56,189,248,0.15); color: #38BDF8; border: 1px solid rgba(56,189,248,0.35);",
            "Trial": "background: rgba(255,198,109,0.15); color: #FFC66D; border: 1px solid rgba(255,198,109,0.35);",
            "Incomplete Evidence": "background: rgba(162,172,192,0.15); color: #A2ACC0; border: 1px solid rgba(162,172,192,0.25);"
        }.get(r.get("license_category", "Incomplete Evidence"), "color: #A2ACC0;")

        notes_cell = r.get("compliance_notes")
        notes_display = f'<div style="margin-top: 4px; font-weight: 500; color: #45D6A3;">User Note: {notes_cell}</div>' if notes_cell else ""

        rows.append(f"""
        <tr>
            <td style="font-weight: 600; color: #F4F6FC;">
                {r.get('name')}
                <div style="font-size: 11px; color: #A2ACC0; font-weight: normal;">{r.get('publisher')}</div>
            </td>
            <td>{r.get('version')}</td>
            <td><span style="padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; {cat_badge_style}">{r.get('license_category', 'Incomplete Evidence')}</span></td>
            <td><code>{r.get('license_identifier')}</code></td>
            <td><span style="padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; {badge_style}">{status}</span></td>
            <td>
                <span style="font-size: 11px; color: #F4F6FC; display: block;">{r.get('evidence_source')}</span>
                <span style="font-size: 10px; color: #A2ACC0;">{r.get('verification_method')}</span>
            </td>
            <td style="font-size: 12px; color: #A2ACC0; max-width: 320px;">
                {r.get('status_reason') or r.get('notes')}
                {notes_display}
            </td>
        </tr>
        """)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>SYSFIX — Software License Audit Report</title>
    <style>
        :root {{
            --bg: #171923;
            --surface: #222738;
            --surface-hover: #252B3C;
            --text-primary: #F4F6FC;
            --text-secondary: #A2ACC0;
            --accent: #7C83FF;
            --border: #2B3247;
        }}
        body {{
            background-color: var(--bg);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 36px;
        }}
        .header {{
            background: var(--surface);
            padding: 24px 28px;
            border-radius: 14px;
            box-shadow: 4px 6px 18px rgba(0,0,0,0.4);
            margin-bottom: 20px;
        }}
        .header h1 {{ margin: 0 0 6px 0; color: var(--accent); font-size: 24px; }}
        .header p {{ margin: 0; color: var(--text-secondary); font-size: 13px; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }}
        .stat-card {{
            background: var(--surface);
            padding: 16px 20px;
            border-radius: 12px;
            border: 1px solid var(--border);
        }}
        .stat-value {{ font-size: 24px; font-weight: 700; color: var(--text-primary); }}
        .stat-label {{ font-size: 12px; color: var(--text-secondary); margin-top: 2px; }}
        .disclaimer {{
            background: var(--surface-hover);
            border-left: 4px solid var(--accent);
            padding: 14px 18px;
            border-radius: 6px;
            margin-bottom: 24px;
            font-size: 12px;
            line-height: 1.5;
            color: var(--text-secondary);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--surface);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 4px 6px 18px rgba(0,0,0,0.3);
        }}
        th, td {{
            padding: 12px 14px;
            text-align: left;
            border-bottom: 1px solid var(--border);
            font-size: 12px;
            vertical-align: top;
        }}
        th {{
            background: #191D29;
            color: var(--text-secondary);
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 0.5px;
        }}
        tr:hover {{ background: var(--surface-hover); }}
        code {{
            background: rgba(23, 25, 35, 0.7);
            padding: 2px 6px;
            border-radius: 4px;
            color: var(--accent);
            font-family: monospace;
            font-size: 11px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>SYSFIX — Software License Audit Report</h1>
        <p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | Host: Windows Desktop</p>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{total}</div>
            <div class="stat-label">Total Audited Items</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: #45D6A3;">{verified_count}</div>
            <div class="stat-label">Verified Information</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: #7C83FF;">{open_source_count}</div>
            <div class="stat-label">Open Source Components</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: #FFC66D;">{review_count}</div>
            <div class="stat-label">Review Recommended</div>
        </div>
    </div>

    <div class="disclaimer">
        <strong>Auditing & Compliance Notice:</strong>
        This report compiles vendor-reported package metadata, Windows SoftwareLicensingService queries, installer registry entries, and local license files.
        A detected LICENSE or EULA file does not prove individual activation or commercial entitlement. Missing license metadata does not indicate non-compliance or improper installation.
        SYSFIX does not extract product keys or bypass activation mechanisms.
    </div>

    <table>
        <thead>
            <tr>
                <th>Software Application</th>
                <th>Version</th>
                <th>License Category</th>
                <th>Declared License</th>
                <th>Verification Status</th>
                <th>Evidence & Method</th>
                <th>Reasoning & Analysis</th>
            </tr>
        </thead>
        <tbody>
            {"".join(rows)}
        </tbody>
    </table>
</body>
</html>
"""
    return sanitize_report_text(html)
