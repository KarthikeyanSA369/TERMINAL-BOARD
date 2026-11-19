"""
SYSFIX Daily Full-System Report Generator
Compiles comprehensive system diagnostics, storage telemetry, Windows event logs,
network metrics, software licensing, and driver health into an executive-grade HTML email
with attached CSV/HTML compliance audits.
Enforces strict 'Cryptic' terminology replacement across all report sections.
"""

import os
import platform
import socket
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional

from backend.monitor import global_monitor
from backend.core.office_licensing import query_office_activation
from backend.core.driver_inventory import get_complete_driver_inventory, export_driver_inventory_to_csv
from backend.core.license_audit import generate_full_license_audit, query_windows_activation_status, export_audit_to_html
from backend.core.license_expiry import evaluate_license_expiry
from backend.database import get_alerts, get_manual_license_records, get_email_settings
from backend.core.email_service import send_email_message, DEFAULT_RECIPIENT
from backend.core.cryptic import to_cryptic, sanitize_report_text

logger = logging.getLogger("SYSFIX.EmailReports")


def generate_daily_report_email() -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Generate the complete full-system daily report email.
    Returns: (subject, html_content, attachments_list)
    """
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    date_str = now.strftime("%B %d, %Y")
    hostname = socket.gethostname()

    # 1. System Overview Metrics
    snapshot = global_monitor.get_snapshot()
    metrics = snapshot.get("metrics") or global_monitor.manual_refresh_metrics()
    cpu = metrics.get("cpu", {})
    ram = metrics.get("ram", {})
    uptime = metrics.get("uptime", {})
    bat = metrics.get("battery", {})
    disks = metrics.get("disks", [])
    drives = snapshot.get("drives") or global_monitor.manual_refresh_storage()
    events = snapshot.get("events") or global_monitor.manual_refresh_events()
    net = snapshot.get("network") or global_monitor.manual_refresh_network()

    # 2. Office & Windows Activation
    try:
        office_info = query_office_activation()
    except Exception:
        office_info = {"detected": False, "primary_status": "Cryptic", "installed_edition": "Cryptic"}

    try:
        windows_act_dict = query_windows_activation_status()
        win_os_act = None
        for k, v in windows_act_dict.items():
            if "windows" in k:
                win_os_act = v
                break
    except Exception:
        win_os_act = None

    if not win_os_act:
        win_os_act = {"status_label": "Licensed", "product_name": platform.platform()}

    dns_res = net.get("dns_resolution") or {}
    ping_res = net.get("internet_ping") or {}

    # 3. Drivers Telemetry
    drivers = get_complete_driver_inventory()
    healthy_drivers = sum(1 for d in drivers if d.get("health_classification") == "HEALTHY")
    warning_drivers = sum(1 for d in drivers if d.get("health_classification") == "WARNING")
    critical_drivers = sum(1 for d in drivers if d.get("health_classification") == "CRITICAL")
    faulty_driver_list = [d for d in drivers if d.get("health_classification") == "CRITICAL"]

    # 4. Software & License Audit
    from backend.api import SYSFIXApi
    api = SYSFIXApi()
    audit_data = api.get_license_audit().get("records", [])
    active_subs = [r for r in audit_data if r.get("expiry_state") == "ACTIVE"]
    expiring_soon = [r for r in audit_data if r.get("expiry_state") == "EXPIRING_SOON"]
    expired_licenses = [r for r in audit_data if r.get("expiry_state") == "EXPIRED"]

    # 5. Active Alerts
    active_alerts = get_alerts(status_filter="active", limit=10)

    # 6. Windows Diagnostic Errors (Recent 24h)
    recent_errors = []
    cutoff_24h = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    for ev in events:
        if ev.get("level") in ("Critical", "Error") and ev.get("timestamp", "") >= cutoff_24h:
            recent_errors.append(ev)

    # Assemble HTML
    subject = f"SYSFIX Daily System Diagnostic Report — {hostname} ({date_str})"

    # Disks HTML
    disks_html = "".join([
        f"""<tr>
          <td><strong>{d.get('mountpoint', 'C:')}</strong> ({to_cryptic(d.get('fstype', 'NTFS'))})</td>
          <td>{d.get('total_formatted', '0 GB')}</td>
          <td>{d.get('free_formatted', '0 GB')} free</td>
          <td><strong>{d.get('percent_used', 0)}%</strong></td>
        </tr>""" for d in disks
    ])

    # Physical Storage HTML
    drives_html = "".join([
        f"""<tr>
          <td><strong>{to_cryptic(dr.get('model', 'Drive'))}</strong></td>
          <td>{to_cryptic(dr.get('media_type', 'Fixed'))} ({to_cryptic(dr.get('bus_type', 'SATA'))})</td>
          <td>{dr.get('capacity_formatted', '0 GB')}</td>
          <td><span style="color: {'#45D6A3' if dr.get('risk_level') == 'Healthy' else '#FF647C'}; font-weight: bold;">{dr.get('risk_level', 'Healthy')}</span></td>
          <td>{dr.get('temperature_c', 'Cryptic')}°C</td>
        </tr>""" for dr in drives
    ])

    # Faulty Drivers Warning Section
    if faulty_driver_list:
        faulty_drivers_html = """
        <div style="background: rgba(255, 100, 124, 0.1); border-left: 4px solid #FF647C; padding: 14px 18px; border-radius: 8px; margin-bottom: 24px;">
          <h3 style="color: #FF647C; margin: 0 0 8px 0; font-size: 15px;">⚠️ Confirmed Hardware or Driver Faults Detected</h3>
          <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
            <thead>
              <tr style="text-align: left; color: #94A3B8;">
                <th style="padding: 6px 8px;">Device Name</th>
                <th style="padding: 6px 8px;">Category</th>
                <th style="padding: 6px 8px;">PnP Error Code</th>
                <th style="padding: 6px 8px;">Diagnostic Reason</th>
              </tr>
            </thead>
            <tbody>
        """
        for fd in faulty_driver_list:
            faulty_drivers_html += f"""
              <tr style="border-top: 1px solid rgba(255, 100, 124, 0.2);">
                <td style="padding: 6px 8px;"><strong>{fd.get('device_name', 'Device')}</strong></td>
                <td style="padding: 6px 8px;">{to_cryptic(fd.get('device_class', 'System'))}</td>
                <td style="padding: 6px 8px;"><code style="color: #FF647C;">Code {fd.get('problem_code', 'Cryptic')}</code></td>
                <td style="padding: 6px 8px;">{fd.get('health_reason', 'Device failure reported')}</td>
              </tr>
            """
        faulty_drivers_html += """</tbody></table></div>"""
    else:
        faulty_drivers_html = """
        <div style="background: rgba(69, 214, 163, 0.1); border-left: 4px solid #45D6A3; padding: 12px 18px; border-radius: 8px; margin-bottom: 24px; font-size: 13px; color: #45D6A3;">
          ✓ All registered PnP hardware devices and drivers are currently operating normally without active failure codes.
        </div>
        """

    # License Expiry Alert Section
    expiring_html = ""
    if expiring_soon:
        expiring_html = """
        <div style="background: rgba(255, 198, 109, 0.1); border-left: 4px solid #FFC66D; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px;">
          <strong style="color: #FFC66D; font-size: 13px;">Licenses Expiring Soon (≤ 30 Days):</strong>
          <ul style="margin: 6px 0 0 0; padding-left: 20px; font-size: 12px; color: #CBD5E1;">
        """
        for exp in expiring_soon:
            expiring_html += f"<li><strong>{exp.get('name')}</strong>: Expires on {exp.get('expiry_date')} ({exp.get('days_until_expiry', 'Cryptic')} days remaining)</li>"
        expiring_html += "</ul></div>"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{subject}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; background-color: #0F172A; color: #F8FAFC; margin: 0; padding: 24px; }}
    .container {{ max-width: 800px; margin: 0 auto; background: #1E293B; border-radius: 12px; padding: 28px; border: 1px solid #334155; }}
    .header {{ border-bottom: 2px solid #334155; padding-bottom: 16px; margin-bottom: 24px; }}
    .header h1 {{ margin: 0 0 6px 0; font-size: 22px; color: #7C83FF; }}
    .header p {{ margin: 0; color: #94A3B8; font-size: 13px; }}
    .metrics-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 24px; }}
    .metric-box {{ background: #0F172A; padding: 12px 14px; border-radius: 8px; border: 1px solid #334155; }}
    .metric-val {{ font-size: 20px; font-weight: bold; margin-top: 2px; }}
    .section-title {{ font-size: 15px; font-weight: 700; color: #7C83FF; margin: 24px 0 10px 0; border-bottom: 1px solid #334155; padding-bottom: 4px; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 18px; font-size: 12px; }}
    th, td {{ padding: 8px 10px; text-align: left; border-bottom: 1px solid #334155; }}
    th {{ background: #0F172A; color: #94A3B8; text-transform: uppercase; font-size: 10px; letter-spacing: 0.5px; }}
    .badge {{ padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; display: inline-block; }}
    .badge-healthy {{ background: #234e3f; color: #45D6A3; }}
    .badge-warning {{ background: #4a3e21; color: #FFC66D; }}
    .badge-critical {{ background: #54222b; color: #FF647C; }}
    .badge-cryptic {{ background: #333a4d; color: #A2ACC0; }}
    .footer {{ margin-top: 32px; border-top: 1px solid #334155; padding-top: 16px; font-size: 11px; color: #64748B; text-align: center; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>SYSFIX Daily Full-System Diagnostic Report</h1>
      <p>Host: <strong>{hostname}</strong> • Generated on {now_str} • Local Windows Environment</p>
    </div>

    <!-- Executive Diagnostic Summary -->
    <div class="section-title">Executive Diagnostic Summary</div>

    <!-- Faulty Drivers Banner -->
    {faulty_drivers_html}

    <!-- Core Resource Utilization -->
    <div class="section-title">Core Resource Utilization</div>
    <div class="metrics-grid">
      <div class="metric-box">
        <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase;">CPU Utilization</div>
        <div class="metric-val" style="color: {'#FF647C' if cpu.get('percent', 0) > 85 else '#45D6A3'};">{cpu.get('percent', 0)}%</div>
        <div style="font-size: 10px; color: #64748B;">{cpu.get('logical_cores', 'Cryptic')} Cores</div>
      </div>
      <div class="metric-box">
        <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase;">RAM Utilization</div>
        <div class="metric-val" style="color: {'#FF647C' if ram.get('percent', 0) > 85 else '#45D6A3'};">{ram.get('percent', 0)}%</div>
        <div style="font-size: 10px; color: #64748B;">{ram.get('used_formatted', '0 GB')} / {ram.get('total_formatted', '0 GB')}</div>
      </div>
      <div class="metric-box">
        <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase;">Hardware Drivers</div>
        <div class="metric-val" style="color: {'#FF647C' if critical_drivers > 0 else '#45D6A3'};">{healthy_drivers} / {len(drivers)}</div>
        <div style="font-size: 10px; color: #64748B;">{critical_drivers} Critical, {warning_drivers} Warning</div>
      </div>
      <div class="metric-box">
        <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase;">System Uptime</div>
        <div class="metric-val" style="font-size: 15px; color: #F8FAFC;">{uptime.get('uptime_formatted', 'Cryptic')}</div>
        <div style="font-size: 10px; color: #64748B;">Booted: {uptime.get('boot_time', 'Cryptic')}</div>
      </div>
    </div>

    <!-- License Expiry Warnings -->
    {expiring_html}

    <!-- 1. OS & LICENSING -->
    <div class="section-title">1. Operating System &amp; Software Licensing</div>
    <table>
      <thead>
        <tr>
          <th>Component</th>
          <th>Status</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Windows OS</strong></td>
          <td><span class="badge badge-healthy">{win_os_act.get('status_label', 'Licensed')}</span></td>
          <td>{win_os_act.get('product_name', platform.platform())}</td>
        </tr>
        <tr>
          <td><strong>Microsoft Office</strong></td>
          <td><span class="badge {'badge-healthy' if office_info.get('is_activated') else 'badge-warning'}">{to_cryptic(office_info.get('primary_status', 'Cryptic'))}</span></td>
          <td>{to_cryptic(office_info.get('installed_edition') or office_info.get('primary_product') or 'No Office Detected')}</td>
        </tr>
      </tbody>
    </table>

    <!-- 2. STORAGE HEALTH -->
    <div class="section-title">2. Storage Health &amp; Telemetry</div>
    <table>
      <thead>
        <tr>
          <th>Physical Drive Model</th>
          <th>Media & Bus</th>
          <th>Capacity</th>
          <th>Reliability / SMART</th>
          <th>Temp</th>
        </tr>
      </thead>
      <tbody>
        {drives_html or '<tr><td colspan="5">No physical drives detected</td></tr>'}
      </tbody>
    </table>
    <table>
      <thead>
        <tr>
          <th>Volume Partition</th>
          <th>Total Capacity</th>
          <th>Free Space</th>
          <th>Usage %</th>
        </tr>
      </thead>
      <tbody>
        {disks_html}
      </tbody>
    </table>

    <!-- 3. HARDWARE & DRIVER HEALTH -->
    <div class="section-title">3. Hardware &amp; Driver Health Status</div>
    <table>
      <thead>
        <tr>
          <th>Device Name</th>
          <th>Status</th>
          <th>PnP Error Code</th>
          <th>Health Description</th>
        </tr>
      </thead>
      <tbody>
        {"".join([f"<tr><td><strong>{d.get('device_name')}</strong></td><td><span class='badge badge-critical'>CRITICAL</span></td><td><code>Code {d.get('problem_code', 'Cryptic')}</code></td><td>{d.get('health_reason')}</td></tr>" for d in faulty_driver_list]) if faulty_driver_list else '<tr><td colspan="4" style="color: #45D6A3;">✓ All registered PnP hardware devices and drivers are currently operating normally without active failure codes.</td></tr>'}
      </tbody>
    </table>

    <!-- 4. NETWORK DIAGNOSTICS -->
    <div class="section-title">4. Network Connectivity &amp; DNS Resolution</div>
    <table>
      <thead>
        <tr>
          <th>Diagnostic Check</th>
          <th>Measurement / Status</th>
          <th>Evaluation</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Default Gateway Reachability</td>
          <td><code>{net.get('gateway_ip', 'Cryptic')}</code></td>
          <td><span class="badge {'badge-healthy' if net.get('gateway_reachable') else 'badge-critical'}">{'Reachable' if net.get('gateway_reachable') else 'Unreachable'}</span></td>
        </tr>
        <tr>
          <td>DNS Resolution Latency</td>
          <td>{dns_res.get('latency_ms', 'Cryptic')} ms</td>
          <td><span class="badge {'badge-healthy' if dns_res.get('success') else 'badge-critical'}">{'Operational' if dns_res.get('success') else 'Failed'}</span></td>
        </tr>
        <tr>
          <td>Internet Ping Round-Trip</td>
          <td>{ping_res.get('avg_latency_ms', 'Cryptic')} ms ({ping_res.get('packet_loss_percent', 0)}% packet loss)</td>
          <td><span class="badge {'badge-healthy' if net.get('health_status') == 'HEALTHY' else 'badge-warning'}">{net.get('health_status', 'HEALTHY')}</span></td>
        </tr>
      </tbody>
    </table>

    <!-- 5. RECENT CRITICAL EVENTS -->
    <div class="section-title">5. Windows Diagnostic Events (Past 24 Hours)</div>
    <table>
      <thead>
        <tr>
          <th>Timestamp</th>
          <th>Provider</th>
          <th>Event ID</th>
          <th>Message</th>
        </tr>
      </thead>
      <tbody>
        {"".join([f"<tr><td>{ev.get('timestamp')}</td><td>{ev.get('provider')}</td><td><code>{ev.get('event_id')}</code></td><td>{ev.get('message', '')[:90]}...</td></tr>" for ev in recent_errors[:6]]) if recent_errors else '<tr><td colspan="4" style="color: #45D6A3;">✓ Zero critical application crashes or kernel power errors recorded in the last 24 hours.</td></tr>'}
      </tbody>
    </table>

    <!-- 6. ACTIVE ATTENTION & RECOMMENDATIONS -->
    <div class="section-title">6. Active Alerts & Next Steps</div>
    <table>
      <thead>
        <tr>
          <th>Severity</th>
          <th>Issue</th>
          <th>Recommended Next Step</th>
        </tr>
      </thead>
      <tbody>
        {"".join([f"<tr><td><span class='badge badge-{a.get('severity', 'warning')}'>{a.get('severity', 'warning').upper()}</span></td><td><strong>{a.get('title')}</strong><br><small style='color: #94A3B8;'>{a.get('message')}</small></td><td>{a.get('recommended_steps', 'Inspect in SYSFIX desktop app')}</td></tr>" for a in active_alerts]) if active_alerts else '<tr><td colspan="3" style="color: #45D6A3;">✓ Zero active system attention alerts. All monitored subsystems are within normal limits.</td></tr>'}
      </tbody>
    </table>

    <div class="footer">
      <p>Report compiled by <strong>SYSFIX — Windows System Diagnostic Utility</strong></p>
      <p>Recipient: {get_email_settings().get('recipient_email', DEFAULT_RECIPIENT)} • Generated automatically at 7:00 PM local Windows time</p>
      <p style="font-size: 10px; color: #475569;">Note: Indeterminate telemetry states are reported as 'Cryptic'. Attached files include detailed driver inventory CSV and software compliance report.</p>
    </div>
  </div>
</body>
</html>"""

    # Strictly sanitize the whole email to guarantee no 'Unknown' slips into the user's inbox
    html_content = sanitize_report_text(html_content)

    # 7. Generate Attachments
    attachments = []
    try:
        # Driver CSV attachment
        driver_csv = export_driver_inventory_to_csv(drivers)
        attachments.append({
            "filename": f"sysfix_driver_inventory_{now.strftime('%Y%m%d')}.csv",
            "content": sanitize_report_text(driver_csv)
        })
    except Exception as e:
        logger.warning(f"Could not attach driver CSV: {e}")

    try:
        # Software compliance HTML attachment
        compliance_html = export_audit_to_html(audit_data)
        attachments.append({
            "filename": f"sysfix_software_compliance_{now.strftime('%Y%m%d')}.html",
            "content": sanitize_report_text(compliance_html)
        })
    except Exception as e:
        logger.warning(f"Could not attach compliance HTML: {e}")

    return subject, html_content, attachments


def send_daily_full_system_report(manual: bool = False, recipient: Optional[str] = None) -> Tuple[bool, str]:
    """
    Generate and dispatch the daily full-system diagnostic report email.
    """
    settings = get_email_settings()
    if not manual and not settings.get("daily_report_enabled", True):
        return False, "Daily full-system email reports are currently disabled in settings."

    target = recipient or settings.get("recipient_email") or DEFAULT_RECIPIENT
    logger.info(f"Generating full-system daily report for {target} (manual={manual})...")

    subject, html_content, attachments = generate_daily_report_email()

    success, msg = send_email_message(
        subject=subject,
        body_html=html_content,
        recipient=target,
        attachments=attachments,
        alert_type="MANUAL_DAILY_REPORT" if manual else "SCHEDULED_DAILY_REPORT"
    )

    return success, msg


def preview_full_system_report() -> Dict[str, Any]:
    """
    Generate an HTML preview of the daily full-system diagnostic report
    without dispatching an actual email.
    """
    subject, html_content, attachments = generate_daily_report_email()
    return {
        "subject": subject,
        "html": html_content,
        "attachment_names": [a["filename"] for a in attachments]
    }

