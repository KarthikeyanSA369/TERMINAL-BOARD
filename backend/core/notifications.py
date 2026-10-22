"""
Terminal Board — Desktop Notifications & Alert Dispatcher
Provides genuine Windows Action Center toast notifications, configurable categories,
duplicate suppression, rate-limiting, and background delivery.
"""

import os
import sys
import time
import base64
import sqlite3
import threading
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional
from backend.database import get_connection, get_all_settings

# Cache for duplicate suppression: (category, title) -> last_dispatched_timestamp
_NOTIFICATION_CACHE: Dict[str, float] = {}
_CACHE_LOCK = threading.Lock()
_SUPPRESSION_WINDOW_SEC = 180.0  # 3 minutes duplicate suppression

def init_notifications_schema():
    """Ensure notification history table exists."""
    conn = get_connection()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'delivered'
        )
        """)
        conn.commit()
    finally:
        conn.close()

def is_category_enabled(category: str, settings: Dict[str, str]) -> bool:
    """Check if specific notification category is allowed by user settings."""
    if settings.get("notifications_enabled", "1") == "0":
        return False

    cat_map = {
        "resource": "notify_resource_alerts",
        "hardware": "notify_hardware_alerts",
        "driver": "notify_hardware_alerts",
        "network": "notify_network_alerts",
        "disk": "notify_resource_alerts",
        "system": "notifications_enabled"
    }

    setting_key = cat_map.get(category.lower(), "notifications_enabled")
    return settings.get(setting_key, "1") != "0"

def dispatch_desktop_toast(title: str, message: str, category: str = "system") -> Dict[str, Any]:
    """
    Deliver genuine Windows toast notification with duplicate suppression.
    Non-blocking background execution.
    """
    settings = get_all_settings()
    if not is_category_enabled(category, settings):
        return {"success": False, "reason": "Category or notifications disabled by user settings."}

    cache_key = f"{category.lower()}:{title.strip().lower()}"
    now = time.time()

    with _CACHE_LOCK:
        last_sent = _NOTIFICATION_CACHE.get(cache_key, 0.0)
        if (now - last_sent) < _SUPPRESSION_WINDOW_SEC:
            return {"success": False, "reason": "Suppressed duplicate notification within rate limit window."}
        _NOTIFICATION_CACHE[cache_key] = now

    # Log to database
    try:
        init_notifications_schema()
        conn = get_connection()
        conn.execute(
            "INSERT INTO notification_history (category, title, message) VALUES (?, ?, ?)",
            (category, title, message)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Launch toast in daemon background thread to keep caller instant
    def _send():
        try:
            ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName('text')
$textNodes.Item(0).AppendChild($template.CreateTextNode('{title.replace("'", "''")}')) | Out-Null
$textNodes.Item(1).AppendChild($template.CreateTextNode('{message.replace("'", "''")}')) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Terminal Board')
$notifier.Show($toast)
[System.Environment]::Exit(0)
"""
            enc = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
            from backend.core.subproc import safe_run
            safe_run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
                capture_output=True,
                timeout=6
            )
        except Exception:
            pass

    t = threading.Thread(target=_send, daemon=True, name="TB-ToastSender")
    t.start()

    return {"success": True, "dispatched": True, "category": category, "title": title}

def get_notification_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve history of dispatched notifications."""
    init_notifications_schema()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, category, title, message, timestamp, status FROM notification_history ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        return [
            {
                "id": r["id"],
                "category": r["category"],
                "title": r["title"],
                "message": r["message"],
                "timestamp": r["timestamp"],
                "status": r["status"]
            }
            for r in cursor.fetchall()
        ]
    finally:
        conn.close()

def clear_notification_history() -> Dict[str, Any]:
    """Clear notification log."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM notification_history")
        conn.commit()
        return {"success": True, "message": "Notification history cleared."}
    finally:
        conn.close()
