"""
SYSFIX Alert and Notification Engine
Evaluates live system telemetry against configurable thresholds, performs
repeated-alert suppression (debouncing/cooldown), records alert history in SQLite,
dispatches in-app and native Windows toast notifications, and issues recovery notifications.
"""

import time
import subprocess
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from backend.database import (
    insert_alert, update_alert_status, get_active_alert_by_metric,
    get_setting, get_connection, is_expiry_reminder_sent, record_expiry_reminder
)

logger = logging.getLogger("SYSFIX.Alerts")

# Cooldown dictionary to avoid notification spam: {metric_name: last_notified_epoch}
_alert_cooldowns: Dict[str, float] = {}
COOLDOWN_PERIOD_SECONDS = 120.0  # 2 minutes debounce for active repeat alerts

# In-memory transient toast queue for frontend poll/push
_pending_toasts: List[Dict[str, Any]] = []

def send_windows_toast_notification(title: str, message: str) -> bool:
    """Dispatches native Windows 10/11 Toast Notification via PowerShell WindowsRuntime."""
    # Escape quotes for PowerShell string literal
    safe_title = title.replace('"', '`"').replace("'", "''")
    safe_msg = message.replace('"', '`"').replace("'", "''")

    ps_script = f"""
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    $template = @"
    <toast>
        <visual>
            <binding template="ToastGeneric">
                <text>{safe_title}</text>
                <text>{safe_msg}</text>
            </binding>
        </visual>
    </toast>
"@
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($template)
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("TERMINAL BOARD")
    $notifier.Show($toast)
    [System.Environment]::Exit(0)
    """

    try:
        from backend.core.subproc import safe_popen
        safe_popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to dispatch native Windows toast: {e}")
        return False

def push_toast(title: str, message: str, severity: str = "warning") -> None:
    """Queues toast for frontend and triggers Windows native notification if enabled."""
    toast_obj = {
        "id": int(time.time() * 1000),
        "title": title,
        "message": message,
        "severity": severity,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }
    _pending_toasts.append(toast_obj)
    # Keep max 20 toasts in queue
    if len(_pending_toasts) > 20:
        _pending_toasts.pop(0)

    # Check user setting for desktop notifications
    desktop_enabled = get_setting("enable_desktop_notifications", "1") == "1"
    if desktop_enabled:
        send_windows_toast_notification(f"SYSFIX — {title}", message)

def pop_pending_toasts() -> List[Dict[str, Any]]:
    """Fetches and clears pending in-app toasts."""
    global _pending_toasts
    toasts = list(_pending_toasts)
    _pending_toasts = []
    return toasts

def evaluate_system_alerts(metrics: Dict[str, Any], drives: List[Dict[str, Any]],
                           network: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Evaluates current system state against thresholds, handles cooldowns,
    and checks for condition recoveries.
    """
    now = time.time()
    generated_alerts = []

    # Read user configurable thresholds
    cpu_warn_thresh = float(get_setting("cpu_warning_threshold", "85"))
    ram_warn_thresh = float(get_setting("ram_warning_threshold", "85"))
    disk_warn_thresh = float(get_setting("disk_warning_threshold", "10"))

    # 1. CPU Evaluation
    cpu_percent = metrics.get("cpu", {}).get("percent", 0.0)
    sustained_cpu = metrics.get("cpu", {}).get("sustained_high_load", False)
    active_cpu_alert = get_active_alert_by_metric("cpu")

    if cpu_percent >= cpu_warn_thresh or sustained_cpu:
        last_notif = _alert_cooldowns.get("cpu", 0)
        if now - last_notif > COOLDOWN_PERIOD_SECONDS:
            severity = "critical" if sustained_cpu and cpu_percent >= 90 else "warning"
            title = "High CPU Utilization"
            msg = f"CPU usage is currently {cpu_percent}% (Threshold: {cpu_warn_thresh}%)."
            if sustained_cpu:
                msg += " Sustained heavy load detected over multiple sampling intervals."
            evidence = f"Current load: {cpu_percent}%, Logical cores: {metrics.get('cpu', {}).get('logical_cores')}"
            steps = "Inspect Task Manager or SYSFIX System Health to identify high-utilization processes."

            alert_id = insert_alert("cpu", severity, title, msg, evidence, steps)
            push_toast(title, msg, severity)
            _alert_cooldowns["cpu"] = now
            generated_alerts.append({"id": alert_id, "metric": "cpu", "severity": severity, "title": title})
    elif active_cpu_alert and cpu_percent < (cpu_warn_thresh - 5.0):
        # Recovery
        update_alert_status(active_cpu_alert["id"], "resolved")
        push_toast("CPU Normal", f"CPU load normalized to {cpu_percent}%.", "healthy")
        _alert_cooldowns.pop("cpu", None)

    # 2. RAM Evaluation
    ram_percent = metrics.get("ram", {}).get("percent", 0.0)
    sustained_ram = metrics.get("ram", {}).get("sustained_pressure", False)
    active_ram_alert = get_active_alert_by_metric("ram")

    if ram_percent >= ram_warn_thresh or sustained_ram:
        last_notif = _alert_cooldowns.get("ram", 0)
        if now - last_notif > COOLDOWN_PERIOD_SECONDS:
            severity = "critical" if ram_percent >= 95 else "warning"
            title = "High Memory Pressure"
            msg = f"Memory usage is at {ram_percent}% (Threshold: {ram_warn_thresh}%). Available: {metrics.get('ram', {}).get('available_formatted')}."
            evidence = f"RAM Used: {metrics.get('ram', {}).get('used_formatted')} / {metrics.get('ram', {}).get('total_formatted')}"
            steps = "Close memory-heavy applications or browser tabs. Check for memory leaks in background services."

            alert_id = insert_alert("ram", severity, title, msg, evidence, steps)
            push_toast(title, msg, severity)
            _alert_cooldowns["ram"] = now
            generated_alerts.append({"id": alert_id, "metric": "ram", "severity": severity, "title": title})
    elif active_ram_alert and ram_percent < (ram_warn_thresh - 5.0):
        update_alert_status(active_ram_alert["id"], "resolved")
        push_toast("Memory Pressure Relieved", f"RAM usage decreased to {ram_percent}%.", "healthy")
        _alert_cooldowns.pop("ram", None)

    # 3. Disk Free Space Evaluation
    for partition in metrics.get("disks", []):
        pct_free = partition.get("percent_free", 100.0)
        mount = partition.get("mountpoint", "Disk")
        metric_key = f"disk_{mount.replace(':', '').replace(chr(92), '')}"
        active_disk_alert = get_active_alert_by_metric(metric_key)

        if pct_free <= disk_warn_thresh:
            last_notif = _alert_cooldowns.get(metric_key, 0)
            if now - last_notif > COOLDOWN_PERIOD_SECONDS:
                severity = "critical" if pct_free <= 5.0 else "warning"
                title = f"Low Disk Space ({mount})"
                msg = f"Drive {mount} has only {pct_free}% free ({partition.get('free_formatted')} remaining)."
                evidence = f"Total: {partition.get('total_formatted')}, Used: {partition.get('used_formatted')}"
                steps = "Run SYSFIX Safe Diagnostics Disk Cleanup to identify and safely clear temporary files."

                alert_id = insert_alert(metric_key, severity, title, msg, evidence, steps)
                push_toast(title, msg, severity)
                _alert_cooldowns[metric_key] = now
                generated_alerts.append({"id": alert_id, "metric": metric_key, "severity": severity, "title": title})
        elif active_disk_alert and pct_free > (disk_warn_thresh + 3.0):
            update_alert_status(active_disk_alert["id"], "resolved")
            push_toast(f"Disk Space Restored ({mount})", f"Free space on {mount} increased to {pct_free}%.", "healthy")
            _alert_cooldowns.pop(metric_key, None)

    # 4. Drive Hardware / SMART Evaluation
    for drive in drives:
        dev_id = drive.get("device_id", "0")
        risk = drive.get("risk_level", "Unknown")
        metric_key = f"drive_hw_{dev_id}"
        active_hw_alert = get_active_alert_by_metric(metric_key)

        if risk == "Critical":
            last_notif = _alert_cooldowns.get(metric_key, 0)
            if now - last_notif > COOLDOWN_PERIOD_SECONDS:
                title = f"Critical Drive Warning ({drive.get('model')})"
                msg = f"Physical drive {dev_id} ({drive.get('model')}) reported critical SMART or operational failure status."
                evidence = f"Status: {drive.get('operational_status')}, Read Errors: {drive.get('read_errors')}, Wear: {drive.get('wear_indicator')}"
                steps = "URGENT: Back up essential files immediately. Storage device is in imminent danger of data loss."

                alert_id = insert_alert(metric_key, "critical", title, msg, evidence, steps)
                push_toast(title, msg, "critical")
                _alert_cooldowns[metric_key] = now
                generated_alerts.append({"id": alert_id, "metric": metric_key, "severity": "critical", "title": title})

    # 5. Network Connectivity Evaluation
    is_connected = network.get("is_connected", True)
    active_net_alert = get_active_alert_by_metric("network")

    if not is_connected:
        last_notif = _alert_cooldowns.get("network", 0)
        if now - last_notif > COOLDOWN_PERIOD_SECONDS:
            title = "Network Disconnected"
            msg = network.get("root_cause", "Internet host and DNS ping unreachable.")
            evidence = f"Gateway: {network.get('gateway_ip')}, Adapters: {len(network.get('adapters', []))}"
            steps = network.get("recommendation", "Check local router connection and adapter settings.")

            alert_id = insert_alert("network", "warning", title, msg, evidence, steps)
            push_toast(title, msg, "warning")
            _alert_cooldowns["network"] = now
            generated_alerts.append({"id": alert_id, "metric": "network", "severity": "warning", "title": title})
    elif active_net_alert and is_connected:
        update_alert_status(active_net_alert["id"], "resolved")
        push_toast("Network Reconnected", "Internet connectivity and DNS resolution restored.", "healthy")
        _alert_cooldowns.pop("network", None)

    return generated_alerts

def evaluate_license_and_driver_alerts(
    license_records: Optional[List[Dict[str, Any]]] = None,
    driver_records: Optional[List[Dict[str, Any]]] = None,
    office_info: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Evaluates software license expiration thresholds, Office activation anomalies,
    and hardware device PnP errors to dispatch evidence-based alerts and notifications
    with strict deduplication.
    """
    now = time.time()
    generated = []

    # 1. License Expiry Alerts
    if license_records:
        for lic in license_records:
            name = lic.get("name", "Unknown License")
            exp_date = lic.get("expiry_date")
            days_rem = lic.get("days_remaining")
            state = lic.get("expiry_state")

            if not exp_date or days_rem is None:
                continue

            # Determine relevant threshold
            threshold_to_alert = None
            if days_rem < 0 and abs(days_rem) <= 7:
                threshold_to_alert = -1  # Expired alert
            elif days_rem == 0:
                threshold_to_alert = 0   # On expiry day
            elif days_rem in (1, 3, 7, 14, 30):
                threshold_to_alert = days_rem

            if threshold_to_alert is not None:
                # Deduplication check in SQLite
                if not is_expiry_reminder_sent(name, exp_date, threshold_to_alert):
                    severity = "critical" if days_rem <= 0 else ("warning" if days_rem <= 7 else "warning")
                    title = f"License Expired: {name}" if days_rem < 0 else (
                        f"License Expires Today: {name}" if days_rem == 0 else f"License Expiring Soon: {name}"
                    )
                    msg = (
                        f"License expired {abs(days_rem)} days ago on {exp_date}." if days_rem < 0 else
                        f"License will expire in {days_rem} day{'s' if days_rem != 1 else ''} on {exp_date}."
                    )
                    evidence = f"Source: {lic.get('evidence_source', 'Compliance Records')}, Category: {lic.get('license_category')}"
                    steps = f"Review organizational renewal agreement or contact vendor to renew before service disruption."

                    alert_id = insert_alert(f"lic_exp_{name}_{threshold_to_alert}", severity, title, msg, evidence, steps)
                    push_toast(title, msg, severity)
                    record_expiry_reminder(name, exp_date, threshold_to_alert)
                    generated.append({"id": alert_id, "type": "license_expiry", "title": title, "severity": severity})

    # 2. Microsoft Office Activation Notification Mode Alert
    if office_info and office_info.get("records"):
        for rec in office_info.get("records", []):
            norm_status = rec.get("normalized_status")
            if norm_status in ("NOTIFICATIONS", "GRACE_PERIOD"):
                metric_key = f"office_act_{rec.get('sku_id', 'office')[:8]}"
                last_notif = _alert_cooldowns.get(metric_key, 0)
                if now - last_notif > 1800.0:  # 30 minute debounce
                    severity = "warning"
                    title = "Office Activation Required"
                    err_desc = rec.get("error_description") or "Operating in notification mode."
                    msg = f"{rec.get('license_name', 'Microsoft Office')} reported status {rec.get('license_status')}. {err_desc}"
                    evidence = f"Channel: {rec.get('license_channel')}, Key Suffix: ...{rec.get('last_5_key', '')}, Error Code: {rec.get('error_code', 'N/A')}"
                    steps = "Verify connection to KMS host or enter an authorized volume license key."

                    alert_id = insert_alert(metric_key, severity, title, msg, evidence, steps)
                    push_toast(title, msg, severity)
                    _alert_cooldowns[metric_key] = now
                    generated.append({"id": alert_id, "type": "office_activation", "title": title, "severity": severity})

    # 3. Hardware Device & Driver Problem Alerts
    if driver_records:
        for d in driver_records:
            prob_code = d.get("problem_code", 0)
            dev_name = d.get("device_name", "Device")
            dev_id = d.get("device_id", dev_name)

            # Ignore normal or disconnected devices
            if prob_code in (0, 45) or d.get("health_classification") == "HEALTHY":
                continue

            metric_key = f"driver_prob_{dev_id[:16]}"
            last_notif = _alert_cooldowns.get(metric_key, 0)
            if now - last_notif > 3600.0:  # 1 hour debounce for persistent hardware errors
                is_crit = prob_code in (10, 19, 28, 31, 37, 39, 43, 48)
                severity = "critical" if is_crit else "warning"
                title = f"Hardware Driver Error: {dev_name}"
                msg = f"Device reported Windows PnP Code {prob_code}: {d.get('problem_description', 'Device error.')}"
                evidence = f"INF: {d.get('inf_name')}, Provider: {d.get('provider')}, Version: {d.get('driver_version')}"
                steps = f"Inspect Windows Device Manager. Check physical connection or reinstall driver from manufacturer."

                alert_id = insert_alert(metric_key, severity, title, msg, evidence, steps)
                push_toast(title, msg, severity)
                _alert_cooldowns[metric_key] = now
                generated.append({"id": alert_id, "type": "driver_problem", "title": title, "severity": severity})

    return generated

