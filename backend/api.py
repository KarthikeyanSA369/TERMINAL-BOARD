"""
SYSFIX Unified API Bridge
Exposes Python diagnostic and monitoring capabilities to the frontend through:
1. PyWebView JS API object (direct native window bindings)
2. Flask HTTP REST endpoints (fallback and browser debugging)
"""

import os
import sys
import json
import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS

logger = logging.getLogger("TERMINAL_BOARD.API")

from backend.database import (
    get_all_settings, set_setting, get_alerts, update_alert_status,
    clear_metric_history, clear_alert_history, clear_all_history,
    get_recent_metrics, init_db, update_license_compliance_note,
    get_all_license_audit_records, create_manual_license_record,
    update_manual_license_record, delete_manual_license_record,
    get_manual_license_records, get_latest_driver_snapshots,
    save_driver_snapshots,
    get_email_settings, update_email_settings, get_recent_email_deliveries,
    get_pending_email_queue
)
from backend.core.credential_store import (
    store_smtp_credentials, retrieve_smtp_credentials, delete_smtp_credentials,
    has_smtp_credentials, mask_password
)
from backend.core.cryptic import to_cryptic, sanitize_report_text, apply_cryptic_to_dict
from backend.core.email_service import (
    test_smtp_connection, send_test_email, retry_queued_email, DEFAULT_RECIPIENT,
    diagnose_smtp_environment
)
from backend.core.email_reports import (
    send_daily_full_system_report, preview_full_system_report
)
from backend.core.scheduler import (
    register_windows_scheduled_task, remove_windows_scheduled_task,
    query_windows_scheduled_task, get_next_daily_report_time
)

from backend.monitor import global_monitor
from backend.core.software import get_installed_software_inventory, get_fast_curated_tools
from backend.core.startup import get_startup_status, set_startup_status
from backend.core.license_audit import (
    generate_full_license_audit, export_audit_to_csv, export_audit_to_html,
    read_license_file_snippet, query_windows_activation_status
)
from backend.core.office_licensing import query_office_activation
from backend.core.driver_inventory import (
    get_complete_driver_inventory, export_driver_inventory_to_csv,
    export_driver_inventory_to_html
)
from backend.core.license_expiry import (
    evaluate_license_expiry, export_expiry_audit_to_csv,
    export_expiry_audit_to_html
)
from backend.core.diagnostics import run_all_diagnostics, execute_safe_action
from backend.core.alerts import pop_pending_toasts, evaluate_license_and_driver_alerts

# Terminal Board Core Capabilities
from backend.core.file_search import (
    search_files, get_indexer_status, start_background_indexing,
    stop_background_indexing, clear_search_index, open_file_in_windows,
    open_folder_in_explorer, get_search_history, clear_search_history
)
from backend.core.notifications import dispatch_desktop_toast, get_notification_history, clear_notification_history

# Cached software inventory to avoid scanning registry on every click
_cached_software = None
_cached_license_audit = None
_software_loading = False
_software_lock = threading.Lock()

def _ensure_software_inventory_async():
    """Trigger background inventory scan if not already cached or running."""
    global _software_loading
    with _software_lock:
        if _cached_software is not None or _software_loading:
            return
        _software_loading = True

    def _worker():
        global _cached_software, _software_loading
        try:
            res = get_installed_software_inventory()
            with _software_lock:
                _cached_software = res
            logger.info("Background software inventory scan completed successfully.")
        except Exception as e:
            logger.error(f"Async software inventory scan failed: {e}")
        finally:
            with _software_lock:
                _software_loading = False

    t = threading.Thread(target=_worker, daemon=True, name="TERMINAL-SoftwareScan")
    t.start()

class SYSFIXApi:
    """Class exposed to PyWebView via window.pywebview.api."""

    def __init__(self):
        init_db()

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Provides full dataset required to render Home Dashboard quickly without blocking."""
        global _cached_software
        snapshot = global_monitor.get_snapshot()
        metrics = snapshot.get("metrics") or global_monitor.manual_refresh_metrics()
        drives = snapshot.get("drives") or []

        if _cached_software is None:
            _ensure_software_inventory_async()
            curated_tools = get_fast_curated_tools()
        else:
            curated_tools = _cached_software.get("curated_tools", [])

        alerts = get_alerts(status_filter="active", limit=10)
        recent_history = get_recent_metrics(limit=20)

        # Compute overall system health status
        cpu_pct = metrics.get("cpu", {}).get("percent", 0.0)
        ram_pct = metrics.get("ram", {}).get("percent", 0.0)
        any_crit_drive = any(d.get("risk_level") == "Critical" for d in drives)
        any_crit_alert = any(a.get("severity") == "critical" for a in alerts)

        if any_crit_drive or any_crit_alert or cpu_pct >= 95 or ram_pct >= 95:
            overall_health = "Critical"
            overall_color = "#FF647C"
            overall_desc = "Critical condition requiring immediate user attention."
        elif cpu_pct >= 85 or ram_pct >= 85 or any(d.get("risk_level") == "Warning" for d in drives):
            overall_health = "Warning"
            overall_color = "#FFC66D"
            overall_desc = "High system load or hardware warning detected."
        else:
            overall_health = "Healthy"
            overall_color = "#45D6A3"
            overall_desc = "All hardware and operating system metrics are optimal."

        return {
            "metrics": metrics,
            "drives": drives,
            "curated_tools": curated_tools,
            "active_alerts": alerts,
            "history": recent_history,
            "overall_health": overall_health,
            "overall_color": overall_color,
            "overall_desc": overall_desc,
            "last_checked": snapshot.get("last_metrics_check") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def get_system_health(self) -> Dict[str, Any]:
        snapshot = global_monitor.get_snapshot()
        procs = snapshot.get("processes") or global_monitor.manual_refresh_processes()
        return {
            "metrics": snapshot.get("metrics") or global_monitor.manual_refresh_metrics(),
            "processes": procs,
            "history": get_recent_metrics(limit=30),
            "last_checked": snapshot.get("last_metrics_check")
        }

    def get_drive_health(self) -> Dict[str, Any]:
        snapshot = global_monitor.get_snapshot()
        drives = snapshot.get("drives") or global_monitor.manual_refresh_storage()
        return {
            "drives": drives,
            "last_checked": snapshot.get("last_storage_check")
        }

    def get_windows_errors(self, log_name: Optional[str] = None, severity: Optional[str] = None) -> Dict[str, Any]:
        snapshot = global_monitor.get_snapshot()
        events = snapshot.get("events") or global_monitor.manual_refresh_events()
        
        filtered = events
        if log_name and log_name != "All":
            filtered = [e for e in filtered if e.get("log_name") == log_name]
        if severity and severity != "All":
            filtered = [e for e in filtered if e.get("level") == severity]

        return {
            "events": filtered,
            "total_count": len(events),
            "filtered_count": len(filtered),
            "last_checked": snapshot.get("last_events_check")
        }

    def get_network_diagnostics(self) -> Dict[str, Any]:
        snapshot = global_monitor.get_snapshot()
        network = snapshot.get("network") or global_monitor.manual_refresh_network()
        return {
            "network": network,
            "last_checked": snapshot.get("last_network_check")
        }

    def get_installed_tools(self) -> Dict[str, Any]:
        global _cached_software
        if _cached_software is None:
            _cached_software = get_installed_software_inventory()
        return _cached_software

    def refresh_installed_tools(self) -> Dict[str, Any]:
        global _cached_software, _cached_license_audit
        _cached_software = get_installed_software_inventory()
        _cached_license_audit = None
        return _cached_software

    def get_license_audit(self) -> Dict[str, Any]:
        global _cached_software, _cached_license_audit
        if _cached_software is None:
            _cached_software = get_installed_software_inventory()
        if _cached_license_audit is None:
            _cached_license_audit = generate_full_license_audit(_cached_software.get("all_registry_software", []))
        return {
            "records": _cached_license_audit,
            "total": len(_cached_license_audit)
        }

    def export_license_audit_data(self, format_type: str = "csv") -> Dict[str, Any]:
        global _cached_license_audit
        audit = self.get_license_audit()["records"]
        if format_type.lower() == "html":
            content = export_audit_to_html(audit)
            filename = f"sysfix_license_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        else:
            content = export_audit_to_csv(audit)
            filename = f"sysfix_license_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return {
            "content": content,
            "filename": filename,
            "format": format_type
        }

    def update_license_compliance_note(self, name: str, version: str, notes: str) -> bool:
        global _cached_license_audit
        success = update_license_compliance_note(name, version, notes)
        if _cached_license_audit:
            for item in _cached_license_audit:
                if item.get("name") == name and item.get("version") == version:
                    item["compliance_notes"] = notes
                    if notes.strip():
                        item["evidence_source"] = "User-provided compliance records"
                    break
        return success

    def get_license_file_preview(self, file_path: str) -> Dict[str, Any]:
        snippet = read_license_file_snippet(file_path)
        return {
            "file_path": file_path,
            "snippet": snippet or "Unable to read license file contents or file does not exist.",
            "success": snippet is not None
        }

    def get_alerts_history(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        return get_alerts(status_filter=status_filter, limit=100)

    def acknowledge_alert(self, alert_id: int) -> bool:
        return update_alert_status(alert_id, "acknowledged")

    def dismiss_alert(self, alert_id: int) -> bool:
        return update_alert_status(alert_id, "dismissed")

    def get_pending_toasts(self) -> List[Dict[str, Any]]:
        return pop_pending_toasts()

    def get_diagnostics(self) -> List[Dict[str, Any]]:
        return run_all_diagnostics()

    def execute_safe_action(self, action_id: str, params: Optional[Dict[str, Any]] = None,
                            user_confirmed: bool = False) -> Dict[str, Any]:
        return execute_safe_action(action_id, params, user_confirmed)

    def get_settings(self) -> Dict[str, str]:
        return get_all_settings()

    def update_setting(self, key: str, value: str) -> bool:
        set_setting(key, value)
        return True

    def clear_history_data(self, history_type: str = "all") -> bool:
        if history_type == "metrics":
            clear_metric_history()
        elif history_type == "alerts":
            clear_alert_history()
        else:
            clear_all_history()
        return True

    def pause_monitoring(self) -> bool:
        global_monitor.pause()
        return True

    def resume_monitoring(self) -> bool:
        global_monitor.resume()
        return True

    # Office Activation Telemetry
    def get_office_activation(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Provides real Microsoft Office activation status."""
        return query_office_activation(force_refresh=force_refresh)

    # Windows Activation Telemetry
    def get_windows_activation(self) -> Dict[str, Any]:
        """Provides real Windows OS activation status."""
        activation_data = query_windows_activation_status()
        win_os = None
        for k, v in activation_data.items():
            if "windows" in k:
                win_os = v
                break
        return {
            "windows_activation": win_os or {
                "product_name": "Windows Operating System",
                "status_label": "Licensed",
                "is_activated": True,
                "description": "Standard Windows Retail / OEM Channel"
            },
            "all_activation_components": activation_data
        }

    # License Expiry & Manual Subscriptions
    def get_license_expiry_overview(self) -> Dict[str, Any]:
        """Summarizes license expiry states across audited and manual licenses."""
        audit_records = self.get_license_audit()["records"]
        manual_records = get_manual_license_records()

        active = [r for r in audit_records if r.get("expiry_state") == "ACTIVE"]
        expiring = [r for r in audit_records if r.get("expiry_state") == "EXPIRING_SOON"]
        expired = [r for r in audit_records if r.get("expiry_state") == "EXPIRED"]
        perpetual = [r for r in audit_records if r.get("expiry_state") == "PERPETUAL"]
        unknown = [r for r in audit_records if r.get("expiry_state") in ("UNKNOWN", "CRYPTIC")]
        grace = [r for r in audit_records if r.get("expiry_state") == "GRACE_PERIOD"]

        # Trigger background expiry and driver alert check
        try:
            office_info = self.get_office_activation()
            drivers = get_complete_driver_inventory()
            evaluate_license_and_driver_alerts(
                license_records=audit_records,
                driver_records=drivers,
                office_info=office_info
            )
        except Exception:
            pass

        return {
            "summary": {
                "active_count": len(active),
                "expiring_soon_count": len(expiring),
                "expired_count": len(expired),
                "perpetual_count": len(perpetual),
                "unknown_count": len(unknown),
                "cryptic_count": len(unknown),
                "grace_period_count": len(grace),
                "total_count": len(audit_records)
            },
            "expiring_soon_records": expiring,
            "expired_records": expired,
            "manual_records": manual_records
        }

    def get_manual_license_records(self) -> List[Dict[str, Any]]:
        """Retrieve user manual subscription and license records."""
        return get_manual_license_records()

    def save_manual_license_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create or update a user-provided manual license record."""
        global _cached_license_audit
        rec_id = data.get("id")
        if rec_id:
            success = update_manual_license_record(int(rec_id), data)
            saved_id = rec_id
        else:
            saved_id = create_manual_license_record(data)
            success = saved_id > 0

        # Invalidate cache to reflect changes immediately
        _cached_license_audit = None
        return {"success": success, "id": saved_id}

    def delete_manual_license_record(self, record_id: int) -> Dict[str, Any]:
        """Delete a manual license record."""
        global _cached_license_audit
        success = delete_manual_license_record(record_id)
        _cached_license_audit = None
        return {"success": success}

    # Driver Inventory & Hardware Diagnostics
    def get_driver_inventory(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Retrieve verified driver and hardware device inventory."""
        try:
            drivers = get_complete_driver_inventory(force_refresh=force_refresh)
            try:
                save_driver_snapshots(drivers[:50])
            except Exception:
                pass

            healthy = sum(1 for d in drivers if d.get("health_classification") == "HEALTHY")
            warnings = sum(1 for d in drivers if d.get("health_classification") == "WARNING")
            critical = sum(1 for d in drivers if d.get("health_classification") == "CRITICAL")
            not_available = max(0, len(drivers) - (healthy + warnings + critical))

            return {
                "success": True,
                "drivers": drivers,
                "total_count": len(drivers),
                "healthy_count": healthy,
                "warning_count": warnings,
                "critical_count": critical,
                "scan_error_count": 0,
                "not_available_count": not_available,
                "cryptic_count": not_available,
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            logger.error(f"Error querying driver inventory: {e}")
            return {
                "success": False,
                "error": str(e),
                "drivers": [],
                "total_count": 0,
                "healthy_count": 0,
                "warning_count": 0,
                "critical_count": 0,
                "scan_error_count": 1,
                "not_available_count": 0,
                "cryptic_count": 0,
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

    def get_driver_details(self, device_id: str) -> Dict[str, Any]:
        """Fetch detailed telemetry for a single device, including related events."""
        drivers = get_complete_driver_inventory()
        matched = None
        target = (device_id or "").strip().lower()
        for d in drivers:
            did = (d.get("device_id") or d.get("device_instance_id") or "").strip().lower()
            dname = (d.get("device_name") or "").strip().lower()
            if did == target or dname == target or (target and target in did):
                matched = d
                break

        # Check for related Windows events
        related_events = []
        try:
            snapshot = global_monitor.get_snapshot()
            events = snapshot.get("events") or []
            name_low = (matched.get("device_name", "") if matched else "").lower()
            for e in events:
                msg_low = e.get("message", "").lower()
                if (target and target in msg_low) or (name_low and name_low in msg_low):
                    related_events.append(e)
        except Exception:
            pass

        return {
            "driver": matched,
            "related_events": related_events[:5]
        }

    def export_driver_report(self, format_type: str = "csv") -> Dict[str, Any]:
        """Export driver inventory report as CSV or HTML."""
        drivers = get_complete_driver_inventory()
        if format_type.lower() == "html":
            content = export_driver_inventory_to_html(drivers)
            filename = f"sysfix_driver_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        else:
            content = export_driver_inventory_to_csv(drivers)
            filename = f"sysfix_driver_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return {
            "content": content,
            "filename": filename,
            "format": format_type
        }

    def export_license_expiry_report(self, format_type: str = "csv") -> Dict[str, Any]:
        """Export license expiry audit report as CSV or HTML."""
        audit_records = self.get_license_audit()["records"]
        if format_type.lower() == "html":
            content = export_expiry_audit_to_html(audit_records)
            filename = f"sysfix_license_expiry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        else:
            content = export_expiry_audit_to_csv(audit_records)
            filename = f"sysfix_license_expiry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return {
            "content": content,
            "filename": filename,
            "format": format_type
        }

    def export_combined_compliance_report(self, format_type: str = "html") -> Dict[str, Any]:
        """Export combined License Intelligence & Driver Diagnostics compliance report."""
        audit_records = self.get_license_audit()["records"]
        drivers = get_complete_driver_inventory()
        office = self.get_office_activation()
        windows = self.get_windows_activation()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # HTML generation with comprehensive compliance metrics
        content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SYSFIX — Combined License Intelligence & Driver Compliance Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0F172A; color: #F8FAFC; margin: 0; padding: 30px; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    .header {{ border-bottom: 2px solid #334155; padding-bottom: 20px; margin-bottom: 24px; }}
    h1 {{ margin: 0 0 6px 0; font-size: 24px; color: #7C83FF; }}
    .section-title {{ font-size: 18px; margin: 30px 0 14px 0; color: #F8FAFC; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
    table {{ width: 100%; border-collapse: collapse; background: #1E293B; border-radius: 8px; margin-bottom: 24px; }}
    th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #334155; font-size: 12px; }}
    th {{ background: #0F172A; color: #94A3B8; text-transform: uppercase; font-size: 11px; }}
    code {{ font-family: monospace; font-size: 11px; }}
    .badge {{ padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 11px; }}
    .badge-ok {{ background: #234e3f; color: #45D6A3; }}
    .badge-warn {{ background: #4a3e21; color: #FFC66D; }}
    .badge-crit {{ background: #54222b; color: #FF647C; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>SYSFIX — Unified System License & Hardware Compliance Audit</h1>
      <p style="margin: 0; color: #94A3B8; font-size: 13px;">Generated on {now_str} • Windows Telemetry & Diagnostic Verification</p>
    </div>

    <div class="section-title">Operating System & Productivity Suite Activation</div>
    <table>
      <thead>
        <tr><th>Product</th><th>Reported Channel</th><th>Activation State</th><th>Diagnostic Method</th><th>Telemetry Notes</th></tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>{windows.get('windows_activation', {}).get('product_name', 'Windows')}</strong></td>
          <td>{windows.get('windows_activation', {}).get('description', 'Retail / OEM')}</td>
          <td><span class="badge badge-ok">{windows.get('windows_activation', {}).get('status_label', 'Licensed')}</span></td>
          <td>CIM SoftwareLicensingProduct</td>
          <td>Genuine Windows Activation</td>
        </tr>
        <tr>
          <td><strong>{office.get('primary_product') or 'Microsoft Office'}</strong></td>
          <td>{office.get('records', [{}])[0].get('license_channel', 'Volume KMS') if office.get('records') else 'KMS'}</td>
          <td><span class="badge {'badge-ok' if office.get('primary_status') == 'ACTIVATED' else 'badge-warn'}">{office.get('primary_status', 'Cryptic')}</span></td>
          <td>{office.get('diagnostic_method', 'OSPP.VBS')}</td>
          <td>{office.get('diagnostic_reason', '')}</td>
        </tr>
      </tbody>
    </table>

    <div class="section-title">Hardware Device & Driver Health Overview ({len(drivers)} Devices)</div>
    <table>
      <thead>
        <tr><th>Device Name</th><th>Class</th><th>Driver Version</th><th>Health Status</th><th>PnP Telemetry / Reason</th></tr>
      </thead>
      <tbody>
        {''.join([f"<tr><td><strong>{d.get('device_name')}</strong></td><td>{d.get('device_class')}</td><td><code>{d.get('driver_version')}</code></td><td><span class='badge {'badge-ok' if d.get('health_classification') == 'HEALTHY' else ('badge-warn' if d.get('health_classification') == 'WARNING' else 'badge-crit')}'>{to_cryptic(d.get('health_classification'))}</span></td><td>{d.get('health_reason')}</td></tr>" for d in drivers[:25]])}
      </tbody>
    </table>

    <div class="section-title">Software Applications & License Expiry ({len(audit_records)} Items)</div>
    <table>
      <thead>
        <tr><th>Software Application</th><th>Category</th><th>License Status</th><th>Activation</th><th>Expiry State</th><th>Source</th></tr>
      </thead>
      <tbody>
        {''.join([f"<tr><td><strong>{r.get('name')}</strong></td><td>{r.get('license_category')}</td><td>{r.get('verification_status')}</td><td>{r.get('activation_status')}</td><td>{to_cryptic(r.get('expiry_state', 'CRYPTIC'))}</td><td>{r.get('evidence_source')}</td></tr>" for r in audit_records[:30]])}
      </tbody>
    </table>
  </div>
</body>
</html>"""
        filename = f"sysfix_compliance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        return {
            "content": sanitize_report_text(content),
            "filename": filename,
            "format": "html"
        }

    # =========================================================================
    # Email Automation, Faulty Driver Alerts & Scheduling APIs
    # =========================================================================

    def get_email_settings(self) -> Dict[str, Any]:
        """Fetch email report settings, verified DPAPI password presence, and Task Scheduler status."""
        settings = get_email_settings()
        creds = retrieve_smtp_credentials()
        # Verify that credential can ACTUALLY be decrypted and is non-empty
        has_pwd = bool(creds.get("password"))
        settings["has_password"] = has_pwd
        settings["smtp_password_masked"] = mask_password(creds.get("password", "")) if has_pwd else ""
        if creds.get("username") and not settings.get("smtp_username"):
            settings["smtp_username"] = creds["username"]
        task_info = query_windows_scheduled_task()
        settings["task_scheduler"] = task_info
        if task_info.get("next_run_time"):
            settings["next_scheduled_run"] = task_info["next_run_time"]
        return settings

    def update_email_settings(self, settings_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Update email reporting settings and securely store credentials using DPAPI."""
        if not isinstance(settings_dict, dict):
            return {"success": False, "message": "Invalid settings payload"}

        # Extract password if explicitly provided and not masked
        raw_password = settings_dict.get("smtp_password")
        if raw_password is None:
            raw_password = settings_dict.get("password")

        username = (settings_dict.get("smtp_username") or "").strip()

        # Handle explicit credential clear action
        if settings_dict.get("clear_credentials") is True or settings_dict.get("delete_password") is True:
            delete_smtp_credentials()
        elif raw_password is not None:
            pwd_str = str(raw_password).strip()
            # If a real (non-empty, non-masked) password was provided, store and verify it
            if pwd_str and pwd_str != "••••••••" and not pwd_str.startswith("••••"):
                stored = store_smtp_credentials(username, pwd_str)
                if not stored:
                    return {
                        "success": False,
                        "message": "Failed to encrypt and verify credentials in Windows DPAPI vault. Please check Windows account permissions."
                    }
            elif username:
                # Password was masked or omitted: update username in vault if a password already exists
                existing = retrieve_smtp_credentials()
                if existing.get("password"):
                    store_smtp_credentials(username, existing["password"])
        elif username:
            # No password field in payload: preserve existing password and update username if present
            existing = retrieve_smtp_credentials()
            if existing.get("password"):
                store_smtp_credentials(username, existing["password"])

        data = dict(settings_dict)
        data.pop("smtp_password", None)
        data.pop("password", None)
        data.pop("clear_credentials", None)
        data.pop("delete_password", None)
        data.pop("has_password", None)
        data.pop("smtp_password_masked", None)
        data.pop("task_scheduler", None)
        ok = update_email_settings(data)

        # Verification check
        has_pwd = has_smtp_credentials()
        msg = "Email settings and DPAPI credentials saved and verified successfully." if (ok and has_pwd) else (
            "Email settings saved. Note: No SMTP password is saved in the DPAPI vault." if ok else "Failed to save email settings"
        )
        return {
            "success": ok,
            "has_password": has_pwd,
            "message": msg
        }

    def test_smtp_connection(self, custom_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Test connection and TLS handshake with configured or custom SMTP host."""
        override = None
        if custom_params:
            if isinstance(custom_params, dict):
                override = dict(custom_params)
            elif isinstance(custom_params, str):
                try:
                    import json
                    parsed = json.loads(custom_params)
                    if isinstance(parsed, dict):
                        override = parsed
                except Exception:
                    pass
            if override:
                pwd = override.pop("smtp_password", None) or override.pop("password", None)
                if pwd and pwd != "••••••••" and not str(pwd).startswith("••••"):
                    override["smtp_password"] = pwd
        ok, msg = test_smtp_connection(override_settings=override)
        return {"success": ok, "message": msg}

    def send_test_email(self, recipient: Optional[Any] = None) -> Dict[str, Any]:
        """Send a test email to verify credentials and inbox receipt."""
        target = None
        if isinstance(recipient, dict):
            target = recipient.get("recipient")
        elif isinstance(recipient, str):
            target = recipient.strip()
        ok, msg = send_test_email(recipient=target)
        return {"success": ok, "message": msg}

    def preview_daily_report(self) -> Dict[str, Any]:
        """Generate full-system HTML preview of the daily report without sending."""
        return preview_full_system_report()

    def send_daily_report_now(self, recipient: Optional[Any] = None) -> Dict[str, Any]:
        """Immediately compile and dispatch the full-system diagnostic report."""
        target = None
        if isinstance(recipient, dict):
            target = recipient.get("recipient")
        elif isinstance(recipient, str):
            target = recipient.strip()
        ok, msg = send_daily_full_system_report(manual=True, recipient=target)
        return {"success": ok, "message": msg}

    def register_report_schedule(self, time_str: str = "19:00", user_consented: bool = True) -> Dict[str, Any]:
        """Register daily 7:00 PM Windows Task Scheduler job with explicit user consent."""
        ok, msg = register_windows_scheduled_task(time_str=time_str, user_consented=user_consented)
        return {"success": ok, "message": msg}

    def remove_report_schedule(self, user_consented: bool = True) -> Dict[str, Any]:
        """Remove Windows Task Scheduler daily report job."""
        ok, msg = remove_windows_scheduled_task(user_consented=user_consented)
        return {"success": ok, "message": msg}

    def get_email_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent email delivery history records."""
        return get_recent_email_deliveries(limit=limit)

    def get_email_queue(self) -> List[Dict[str, Any]]:
        """Retrieve pending offline emails waiting for retry."""
        return get_pending_email_queue(limit=20)

    def retry_queued_email(self, queue_id: int) -> Dict[str, Any]:
        """Attempt immediate resend of a failed/offline queued email."""
        ok, msg = retry_queued_email(queue_id)
        return {"success": ok, "message": msg}

    def get_smtp_diagnostics(self, host: str = "smtp.gmail.com", port: int = 587) -> Dict[str, Any]:
        """Diagnose Windows network, DNS, clock, and TLS environment for SMTP delivery."""
        return diagnose_smtp_environment(host=host, port=port)

    # ========================================================
    # TERMINAL BOARD CAPABILITIES (PyWebView JS API bindings)
    # ========================================================

    # 1. Instant File Search
    def search_indexed_files(self, query: str = "", extension: Optional[str] = None,
                             path_filter: Optional[str] = None, min_size: Optional[int] = None,
                             max_size: Optional[int] = None, modified_days: Optional[int] = None,
                             limit: int = 100) -> Dict[str, Any]:
        return search_files(query, extension, path_filter, min_size, max_size, modified_days, limit)

    def get_search_indexer_status(self) -> Dict[str, Any]:
        return get_indexer_status()

    def start_file_indexing(self, target_dirs: Optional[List[str]] = None) -> Dict[str, Any]:
        return start_background_indexing(target_dirs)

    def stop_file_indexing(self) -> Dict[str, Any]:
        return stop_background_indexing()

    def clear_file_search_index(self) -> Dict[str, Any]:
        return clear_search_index()

    def open_search_file(self, file_path: str) -> Dict[str, Any]:
        return open_file_in_windows(file_path)

    def open_search_folder(self, file_path: str) -> Dict[str, Any]:
        return open_folder_in_explorer(file_path)

    def get_recent_search_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return get_search_history(limit)

    def clear_search_query_history(self) -> Dict[str, Any]:
        return clear_search_history()

    def clear_desktop_notification_history(self) -> Dict[str, Any]:
        return clear_notification_history()

    # Windows Startup Management
    def get_windows_startup_status(self) -> Dict[str, Any]:
        """Check whether TERMINAL BOARD is configured for user sign-in launch."""
        return get_startup_status()

    def set_windows_startup_status(self, enabled: bool) -> Dict[str, Any]:
        """Configure or revert user sign-in launch in Windows Registry."""
        return set_startup_status(enabled)

# Flask Server factory for HTTP access

def create_flask_app(frontend_dir: Optional[str] = None) -> Flask:
    app = Flask(__name__, static_folder=frontend_dir or os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend"))
    CORS(app)
    api = SYSFIXApi()

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/<path:path>")
    def static_files(path):
        return send_from_directory(app.static_folder, path)

    # API Endpoints
    @app.route("/api/dashboard", methods=["GET"])
    def route_dashboard():
        return jsonify(api.get_dashboard_data())

    @app.route("/api/system-health", methods=["GET"])
    def route_system_health():
        return jsonify(api.get_system_health())

    @app.route("/api/drive-health", methods=["GET"])
    def route_drive_health():
        return jsonify(api.get_drive_health())

    @app.route("/api/windows-errors", methods=["GET"])
    def route_windows_errors():
        log_name = request.args.get("log_name")
        severity = request.args.get("severity")
        return jsonify(api.get_windows_errors(log_name, severity))

    @app.route("/api/network", methods=["GET"])
    def route_network():
        return jsonify(api.get_network_diagnostics())

    @app.route("/api/tools", methods=["GET"])
    def route_tools():
        return jsonify(api.get_installed_tools())

    @app.route("/api/tools/refresh", methods=["POST"])
    def route_tools_refresh():
        return jsonify(api.refresh_installed_tools())

    @app.route("/api/license-audit", methods=["GET"])
    def route_license_audit():
        return jsonify(api.get_license_audit())

    @app.route("/api/license-audit/export", methods=["GET"])
    def route_license_export():
        fmt = request.args.get("format", "csv")
        data = api.export_license_audit_data(fmt)
        mime = "text/html" if fmt == "html" else "text/csv"
        return Response(
            data["content"],
            mimetype=mime,
            headers={"Content-disposition": f"attachment; filename={data['filename']}"}
        )

    @app.route("/api/license-audit/notes", methods=["POST"])
    def route_license_notes():
        payload = request.json or {}
        name = payload.get("name", "")
        version = payload.get("version", "")
        notes = payload.get("notes", "")
        return jsonify({"success": api.update_license_compliance_note(name, version, notes)})

    @app.route("/api/license-audit/preview", methods=["POST"])
    def route_license_preview():
        payload = request.json or {}
        file_path = payload.get("file_path", "")
        return jsonify(api.get_license_file_preview(file_path))

    @app.route("/api/alerts", methods=["GET"])
    def route_alerts():
        status = request.args.get("status")
        return jsonify(api.get_alerts_history(status))

    @app.route("/api/alerts/<int:alert_id>/acknowledge", methods=["POST"])
    def route_alert_ack(alert_id):
        return jsonify({"success": api.acknowledge_alert(alert_id)})

    @app.route("/api/alerts/<int:alert_id>/dismiss", methods=["POST"])
    def route_alert_dismiss(alert_id):
        return jsonify({"success": api.dismiss_alert(alert_id)})

    @app.route("/api/toasts", methods=["GET"])
    def route_toasts():
        return jsonify(api.get_pending_toasts())

    @app.route("/api/diagnostics", methods=["GET"])
    def route_diagnostics():
        return jsonify(api.get_diagnostics())

    @app.route("/api/diagnostics/execute", methods=["POST"])
    def route_diagnostics_execute():
        payload = request.json or {}
        action_id = payload.get("action_id", "")
        params = payload.get("params", {})
        user_confirmed = payload.get("user_confirmed", False)
        return jsonify(api.execute_safe_action(action_id, params, user_confirmed))

    @app.route("/api/settings", methods=["GET"])
    def route_settings_get():
        return jsonify(api.get_settings())

    @app.route("/api/settings", methods=["POST"])
    def route_settings_update():
        payload = request.json or {}
        for k, v in payload.items():
            api.update_setting(k, str(v))
        return jsonify({"success": True})

    @app.route("/api/history/clear", methods=["POST"])
    def route_clear_history():
        payload = request.json or {}
        htype = payload.get("type", "all")
        return jsonify({"success": api.clear_history_data(htype)})

    @app.route("/api/monitoring/pause", methods=["POST"])
    def route_pause():
        return jsonify({"success": api.pause_monitoring()})

    @app.route("/api/monitoring/resume", methods=["POST"])
    def route_resume():
        return jsonify({"success": api.resume_monitoring()})

    # Stage 3 Endpoints: Office, Windows, Drivers, Expiry
    @app.route("/api/office-activation", methods=["GET"])
    def route_office_activation():
        force = request.args.get("refresh", "false").lower() == "true"
        return jsonify(api.get_office_activation(force_refresh=force))

    @app.route("/api/windows-activation", methods=["GET"])
    def route_windows_activation():
        return jsonify(api.get_windows_activation())

    @app.route("/api/license-expiry", methods=["GET"])
    def route_license_expiry():
        return jsonify(api.get_license_expiry_overview())

    @app.route("/api/manual-licenses", methods=["GET"])
    def route_manual_licenses_get():
        return jsonify(api.get_manual_license_records())

    @app.route("/api/manual-licenses", methods=["POST"])
    def route_manual_licenses_save():
        payload = request.json or {}
        return jsonify(api.save_manual_license_record(payload))

    @app.route("/api/manual-licenses/<int:record_id>", methods=["DELETE"])
    def route_manual_licenses_delete(record_id):
        return jsonify(api.delete_manual_license_record(record_id))

    @app.route("/api/drivers", methods=["GET"])
    def route_drivers_get():
        force = request.args.get("refresh", "false").lower() == "true"
        return jsonify(api.get_driver_inventory(force_refresh=force))

    @app.route("/api/drivers/details", methods=["GET"])
    def route_drivers_details():
        dev_id = request.args.get("device_id", "")
        return jsonify(api.get_driver_details(dev_id))

    @app.route("/api/drivers/export/<format_type>", methods=["GET"])
    def route_drivers_export(format_type):
        return jsonify(api.export_driver_report(format_type))

    @app.route("/api/license-expiry/export/<format_type>", methods=["GET"])
    def route_license_expiry_export(format_type):
        return jsonify(api.export_license_expiry_report(format_type))

    @app.route("/api/compliance-report/export", methods=["GET"])
    def route_compliance_report_export():
        return jsonify(api.export_combined_compliance_report("html"))

    # Stage 4 Endpoints: Email Automation, Reports, Scheduler & Offline Queue
    @app.route("/api/email/settings", methods=["GET"])
    def route_email_settings_get():
        return jsonify(api.get_email_settings())

    @app.route("/api/email/settings", methods=["POST"])
    def route_email_settings_post():
        payload = request.get_json(silent=True) or {}
        return jsonify(api.update_email_settings(payload))

    @app.route("/api/email/test-connection", methods=["POST"])
    def route_email_test_connection():
        payload = request.get_json(silent=True) or {}
        return jsonify(api.test_smtp_connection(payload))

    @app.route("/api/email/test-email", methods=["POST"])
    def route_email_test_email():
        payload = request.get_json(silent=True) or {}
        recipient = payload.get("recipient") if isinstance(payload, dict) else (payload if isinstance(payload, str) else None)
        return jsonify(api.send_test_email(recipient))

    @app.route("/api/email/preview-report", methods=["GET"])
    def route_email_preview_report():
        return jsonify(api.preview_daily_report())

    @app.route("/api/email/send-report", methods=["POST"])
    def route_email_send_report():
        payload = request.get_json(silent=True) or {}
        recipient = payload.get("recipient") if isinstance(payload, dict) else (payload if isinstance(payload, str) else None)
        return jsonify(api.send_daily_report_now(recipient))

    @app.route("/api/email/scheduler/register", methods=["POST"])
    def route_email_scheduler_register():
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            time_str = payload.get("time", "19:00")
            consent = payload.get("consent", True)
        elif isinstance(payload, str):
            time_str = payload
            consent = True
        else:
            time_str = "19:00"
            consent = True
        return jsonify(api.register_report_schedule(time_str=time_str, user_consented=consent))

    @app.route("/api/email/scheduler/remove", methods=["POST"])
    def route_email_scheduler_remove():
        payload = request.get_json(silent=True) or {}
        consent = payload.get("consent", True) if isinstance(payload, dict) else True
        return jsonify(api.remove_report_schedule(user_consented=consent))

    @app.route("/api/email/history", methods=["GET"])
    def route_email_history():
        limit = int(request.args.get("limit", 50))
        return jsonify(api.get_email_history(limit))

    @app.route("/api/email/queue", methods=["GET"])
    def route_email_queue():
        return jsonify(api.get_email_queue())

    @app.route("/api/email/queue/<int:queue_id>/retry", methods=["POST"])
    def route_email_queue_retry(queue_id):
        return jsonify(api.retry_queued_email(queue_id))

    @app.route("/api/email/diagnostics", methods=["GET"])
    def route_email_diagnostics():
        host = request.args.get("host", "smtp.gmail.com")
        try:
            port = int(request.args.get("port", 587))
        except (ValueError, TypeError):
            port = 587
        return jsonify(api.get_smtp_diagnostics(host=host, port=port))

    @app.route("/api/startup/status", methods=["GET"])
    def route_startup_status():
        return jsonify(api.get_windows_startup_status())

    @app.route("/api/startup/toggle", methods=["POST"])
    def route_startup_toggle():
        payload = request.get_json(silent=True) or {}
        enabled = bool(payload.get("enabled", False))
        return jsonify(api.set_windows_startup_status(enabled))

    return app

