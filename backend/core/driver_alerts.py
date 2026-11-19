"""
SYSFIX Immediate Faulty Driver Alert & Recovery Engine
Monitors Windows hardware telemetry, detects verified driver fault state transitions,
deduplicates alerts using persistent SQLite fault signatures, prevents false-positives,
and sends immediate email alerts and recovery notifications.
Enforces strict 'Cryptic' terminology.
"""

import hashlib
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from backend.core.driver_inventory import get_complete_driver_inventory, PNP_PROBLEM_CODES
from backend.database import (
    get_driver_fault_state,
    record_driver_fault_state,
    mark_driver_fault_alerted,
    mark_driver_fault_recovered,
    get_all_active_driver_faults,
    get_email_settings
)
from backend.core.email_service import send_email_message, DEFAULT_RECIPIENT
from backend.core.cryptic import to_cryptic, sanitize_report_text

logger = logging.getLogger("SYSFIX.DriverAlerts")

# Documented Critical Hardware & Driver Fault Codes (CM_PROB_*)
CRITICAL_DRIVER_PROBLEM_CODES = {
    10: "Device failed to start (Hardware or driver malfunction)",
    19: "Registry configuration corrupted",
    28: "Driver installation failed / Drivers not installed",
    31: "Windows cannot load required drivers (Driver initialization failure)",
    37: "Driver entry routine failed (Driver failed initialization)",
    38: "Previous instance of driver remains loaded in memory",
    39: "Driver binary corrupt or missing on filesystem",
    43: "Windows stopped device because device hardware reported a failure",
    48: "Driver blocked due to confirmed blocking incompatibility"
}

# Non-fault codes that MUST NEVER trigger email alerts (False-Positive Prevention)
IGNORED_PROBLEM_CODES = {
    0: "Working properly",
    22: "Disabled intentionally by user/policy",
    45: "Device disconnected / unplugged (Peripheral offline)"
}


def compute_fault_signature(device_id: str, problem_code: int) -> str:
    """Compute a stable hash signature for this hardware device fault."""
    raw = f"{device_id.strip().lower()}:{problem_code}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def format_driver_fault_email(device: Dict[str, Any], corroborating_event: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """
    Generate the subject and HTML body for an immediate faulty driver email alert.
    """
    dev_name = device.get("device_name", "Hardware Device")
    code = device.get("problem_code", 0)
    code_desc = CRITICAL_DRIVER_PROBLEM_CODES.get(code, device.get("problem_description", "Fault reported"))
    dev_class = to_cryptic(device.get("device_class", "System"))
    mfr = to_cryptic(device.get("manufacturer", "System Standard"))
    provider = to_cryptic(device.get("provider", "Windows"))
    version = to_cryptic(device.get("driver_version", "Cryptic"))
    date_val = to_cryptic(device.get("driver_date", "Cryptic"))
    dev_id = device.get("device_id", "Cryptic")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    subject = f"SYSFIX Alert: Fault Detected on {dev_name} (Code {code})"

    # Corroborating event text if present
    ev_html = ""
    if corroborating_event:
        ev_html = f"""
        <div style="background: rgba(255, 100, 124, 0.08); border: 1px solid rgba(255, 100, 124, 0.3); border-radius: 6px; padding: 12px; margin-top: 14px;">
          <strong style="color: #FF647C; font-size: 12px;">Corroborating Windows Diagnostic Event:</strong>
          <div style="font-size: 11px; color: #CBD5E1; margin-top: 4px;">
            Provider: <strong>{corroborating_event.get('provider')}</strong> | Event ID: <code>{corroborating_event.get('event_id')}</code><br>
            Timestamp: {corroborating_event.get('timestamp')}<br>
            Message: {corroborating_event.get('message', '')}
          </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{subject}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #0F172A; color: #F8FAFC; margin: 0; padding: 24px; }}
    .container {{ max-width: 650px; margin: 0 auto; background: #1E293B; border-radius: 12px; padding: 28px; border: 1px solid #334155; border-top: 4px solid #FF647C; }}
    .badge-critical {{ background: #54222b; color: #FF647C; padding: 4px 10px; border-radius: 4px; font-weight: 700; font-size: 11px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 18px 0; font-size: 13px; }}
    th, td {{ padding: 8px 10px; text-align: left; border-bottom: 1px solid #334155; }}
    th {{ color: #94A3B8; font-size: 11px; text-transform: uppercase; width: 35%; }}
    .footer {{ margin-top: 24px; font-size: 11px; color: #64748B; border-top: 1px solid #334155; padding-top: 14px; text-align: center; }}
    .btn {{ display: inline-block; background: #7C83FF; color: #FFFFFF; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: 600; margin-top: 10px; }}
  </style>
</head>
<body>
  <div class="container">
    <div style="display: flex; justify-content: space-between; align-items: center;">
      <span class="badge-critical">CRITICAL HARDWARE / DRIVER ALERT</span>
      <span style="font-size: 12px; color: #94A3B8;">{now_str}</span>
    </div>

    <h2 style="color: #F8FAFC; margin: 16px 0 6px 0; font-size: 20px;">{dev_name} Reported a Problem</h2>
    <p style="color: #FF647C; font-size: 14px; margin: 0 0 18px 0;">
      Windows PnP Failure: <strong>Code {code} — {code_desc}</strong>
    </p>

    <table>
      <tbody>
        <tr>
          <th>Hardware Device</th>
          <td><strong>{dev_name}</strong></td>
        </tr>
        <tr>
          <th>Device Category</th>
          <td>{dev_class}</td>
        </tr>
        <tr>
          <th>Manufacturer</th>
          <td>{mfr}</td>
        </tr>
        <tr>
          <th>Driver Provider</th>
          <td>{provider}</td>
        </tr>
        <tr>
          <th>Driver Version</th>
          <td><code>{version}</code> (Release Date: {date_val})</td>
        </tr>
        <tr>
          <th>Device Instance ID</th>
          <td><code style="font-size: 11px; word-break: break-all;">{dev_id}</code></td>
        </tr>
        <tr>
          <th>Diagnostic Evaluation</th>
          <td>{device.get('health_reason', 'Device reported an operational fault to Windows Plug-and-Play manager.')}</td>
        </tr>
      </tbody>
    </table>

    {ev_html}

    <div style="background: rgba(124, 131, 255, 0.08); border-left: 3px solid #7C83FF; padding: 12px 14px; border-radius: 6px; margin: 18px 0; font-size: 12px; color: #CBD5E1;">
      <strong style="color: #7C83FF;">Recommended Troubleshooting Steps:</strong>
      <ol style="margin: 6px 0 0 0; padding-left: 20px;">
        <li>Open <strong>Device Manager</strong> (<code>devmgmt.msc</code>) and inspect device properties under <strong>{dev_class}</strong>.</li>
        <li>Check if a firmware update or official driver package is available from <strong>{mfr}</strong>.</li>
        <li>Launch the <strong>SYSFIX</strong> desktop application on your PC to inspect correlated Windows crash logs and system telemetry.</li>
      </ol>
    </div>

    <div style="font-size: 11px; color: #94A3B8; margin-top: 14px;">
      <em>Diagnostic Principle: Missing optional devices, unplugged peripherals, or Cryptic metadata states do not trigger alerts. This email was generated because Windows confirmed an active PnP failure code.</em>
    </div>

    <div class="footer">
      SYSFIX Automated Driver Monitor • Sent to {get_email_settings().get('recipient_email', DEFAULT_RECIPIENT)}
    </div>
  </div>
</body>
</html>"""

    return subject, sanitize_report_text(html)


def format_driver_recovery_email(device_id: str, device_name: str) -> Tuple[str, str]:
    """Generate subject and HTML body for a driver recovery notice."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"SYSFIX Recovery Notice: {device_name} Hardware Fault Resolved"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{subject}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #0F172A; color: #F8FAFC; margin: 0; padding: 24px; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #1E293B; border-radius: 12px; padding: 28px; border: 1px solid #334155; border-top: 4px solid #45D6A3; }}
    .badge-recovered {{ background: #234e3f; color: #45D6A3; padding: 4px 10px; border-radius: 4px; font-weight: 700; font-size: 11px; }}
    .footer {{ margin-top: 24px; font-size: 11px; color: #64748B; border-top: 1px solid #334155; padding-top: 14px; text-align: center; }}
  </style>
</head>
<body>
  <div class="container">
    <div style="display: flex; justify-content: space-between; align-items: center;">
      <span class="badge-recovered">HARDWARE RECOVERY CONFIRMED</span>
      <span style="font-size: 12px; color: #94A3B8;">{now_str}</span>
    </div>

    <h2 style="color: #45D6A3; margin: 16px 0 6px 0; font-size: 18px;">Fault Cleared: {device_name}</h2>
    <p style="color: #CBD5E1; font-size: 13px; line-height: 1.5; margin: 12px 0;">
      SYSFIX telemetry confirms that <strong>{device_name}</strong> is now reporting normal operation (Code 0: Working Properly) with no active PnP failure codes.
    </p>

    <div style="background: rgba(69, 214, 163, 0.08); padding: 12px; border-radius: 6px; font-size: 12px; color: #CBD5E1;">
      Device Instance: <code style="word-break: break-all;">{device_id}</code><br>
      Status: <strong style="color: #45D6A3;">HEALTHY / NORMAL OPERATION</strong>
    </div>

    <div class="footer">
      SYSFIX Automated Driver Monitor • Sent to {get_email_settings().get('recipient_email', DEFAULT_RECIPIENT)}
    </div>
  </div>
</body>
</html>"""

    return subject, sanitize_report_text(html)


def evaluate_driver_fault_and_alert_async(corroborating_events: Optional[List[Dict[str, Any]]] = None) -> None:
    """Run driver fault evaluation in background worker thread so monitor loop is never blocked."""
    worker = threading.Thread(
        target=evaluate_driver_faults_and_alert,
        args=(corroborating_events,),
        daemon=True,
        name="SYSFIX-DriverFaultWorker"
    )
    worker.start()


def evaluate_driver_faults_and_alert(corroborating_events: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """
    Core Driver Fault Telemetry & Alert State Machine:
    1. Scans live PnP driver inventory.
    2. Identifies devices with confirmed critical problem codes.
    3. Filters out false-positives (disconnected USB, user disabled, cryptic, or healthy).
    4. Evaluates state transitions (NEW fault -> ACTIVE, RECOVERY -> RECOVERED).
    5. Dispatches email alerts with deduplication and cooldown enforcement.
    6. Dispatches recovery notifications when configured.
    """
    settings = get_email_settings()
    alerts_enabled = settings.get("driver_alerts_enabled", True)
    recovery_enabled = settings.get("driver_recovery_enabled", True)
    cooldown_min = int(settings.get("alert_cooldown_min", 60))
    target_recipient = settings.get("recipient_email", DEFAULT_RECIPIENT)

    drivers = get_complete_driver_inventory()
    now = datetime.now()
    dispatched_alerts = []

    # Map of current scanned devices
    scanned_devices = {d.get("device_id"): d for d in drivers if d.get("device_id")}

    # A. Check for Recoveries (previously ACTIVE faults that are now healthy)
    active_faults = get_all_active_driver_faults()
    for af in active_faults:
        dev_id = af["device_id"]
        current_dev = scanned_devices.get(dev_id)
        if current_dev:
            curr_code = current_dev.get("problem_code", 0)
            curr_health = current_dev.get("health_classification", "HEALTHY")
            
            # If current status is healthy (Code 0) and not critical
            if curr_code == 0 and curr_health == "HEALTHY":
                mark_driver_fault_recovered(dev_id)
                logger.info(f"Driver fault recovered for {af['device_name']} ({dev_id})")
                
                if recovery_enabled:
                    rec_subject, rec_html = format_driver_recovery_email(dev_id, af["device_name"])
                    send_email_message(
                        subject=rec_subject,
                        body_html=rec_html,
                        recipient=target_recipient,
                        alert_type="DRIVER_RECOVERY",
                        allow_queue=True
                    )

    # B. Check for New or Active Critical Faults
    if not alerts_enabled:
        return dispatched_alerts

    for d in drivers:
        code = d.get("problem_code", 0)
        dev_id = d.get("device_id", "").strip()
        dev_name = d.get("device_name", "Unknown Device")
        health = d.get("health_classification", "HEALTHY")

        # False-Positive Filter: only alert if code is an official critical code or health is CRITICAL
        if code in IGNORED_PROBLEM_CODES or health != "CRITICAL":
            continue
        if not dev_id:
            continue

        fault_sig = compute_fault_signature(dev_id, code)
        existing_fault = get_driver_fault_state(dev_id)

        should_alert = False
        if not existing_fault or existing_fault["status"] != "ACTIVE":
            # State Transition: Transitioning into active fault!
            record_driver_fault_state(dev_id, dev_name, fault_sig, code, severity="CRITICAL")
            should_alert = True
        else:
            # Already active. Check deduplication and cooldown
            last_alerted = existing_fault.get("last_alerted_at")
            if last_alerted:
                try:
                    last_alerted_dt = datetime.strptime(last_alerted, "%Y-%m-%d %H:%M:%S")
                    if (now - last_alerted_dt).total_seconds() > (cooldown_min * 60):
                        should_alert = True  # Cooldown expired, allowed to alert again
                except Exception:
                    should_alert = True
            else:
                should_alert = True

        if should_alert:
            # Corroborate with recent event logs if available
            corrob = None
            if corroborating_events:
                dev_low = dev_id.lower()
                name_low = dev_name.lower()
                for ev in corroborating_events:
                    msg_low = ev.get("message", "").lower()
                    if dev_low in msg_low or name_low in msg_low:
                        corrob = ev
                        break

            subject, body_html = format_driver_fault_email(d, corrob)
            success, msg = send_email_message(
                subject=subject,
                body_html=body_html,
                recipient=target_recipient,
                alert_type="DRIVER_FAULT",
                allow_queue=True
            )
            mark_driver_fault_alerted(dev_id)
            dispatched_alerts.append({
                "device_id": dev_id,
                "device_name": dev_name,
                "problem_code": code,
                "dispatched": success,
                "message": msg
            })

    return dispatched_alerts


# Alias for singular/plural consistency
evaluate_driver_fault_and_alert = evaluate_driver_faults_and_alert


def evaluate_driver_fault_and_alert_async(corroborating_events: Optional[List[Dict[str, Any]]] = None) -> threading.Thread:
    """
    Run evaluate_driver_fault_and_alert asynchronously in a background thread.
    """
    t = threading.Thread(
        target=evaluate_driver_fault_and_alert,
        args=(corroborating_events,),
        daemon=True,
        name="SYSFIX-DriverFaultCheck"
    )
    t.start()
    return t

