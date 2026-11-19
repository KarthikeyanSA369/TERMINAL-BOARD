"""
SYSFIX Automation & Windows Task Scheduler Integration
Manages daily 7:00 PM full-system diagnostic report schedule, in-app timer checks,
Windows Task Scheduler registration (with explicit consent), and offline queue drain.
"""

import os
import sys
import subprocess
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, Tuple, Optional

from backend.core.subproc import safe_run
from backend.database import get_email_settings, update_email_settings
from backend.core.email_service import process_offline_email_queue

logger = logging.getLogger("SYSFIX.Scheduler")

TASK_NAME = "SYSFIX_DailyReport"
_last_daily_report_sent_date: Optional[str] = None


def get_next_daily_report_time(time_str: str = "19:00") -> datetime:
    """
    Calculate the next occurrence datetime for the daily report.
    Defaults to 7:00 PM local Windows time.
    """
    try:
        parts = time_str.strip().split(":")
        target_hour = int(parts[0])
        target_minute = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        target_hour, target_minute = 19, 0

    now = datetime.now()
    target_today = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

    if now < target_today:
        return target_today
    else:
        # Tomorrow at target hour:minute
        return target_today + timedelta(days=1)


def register_windows_scheduled_task(time_str: str = "19:00", user_consented: bool = False) -> Tuple[bool, str]:
    """
    Register a persistent Windows Task Scheduler job for the daily 7:00 PM report.
    Requires explicit user consent from the frontend UI.
    """
    if not user_consented:
        return False, "User consent is required before registering a Windows scheduled task."

    if sys.platform != "win32":
        return False, "Windows Task Scheduler automation is supported only on Windows."

    # Validate time format HH:MM
    try:
        parts = time_str.strip().split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        formatted_time = f"{h:02d}:{m:02d}"
    except Exception:
        formatted_time = "19:00"

    # Locate python executable and app.py
    python_exe = sys.executable
    app_py = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "app.py"))

    if not os.path.isfile(app_py):
        return False, f"Could not find application entry point at {app_py}"

    cmd = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/TR", f'"{python_exe}" "{app_py}" --send-daily-report',
        "/SC", "DAILY",
        "/ST", formatted_time,
        "/F"
    ]

    try:
        proc = safe_run(cmd, capture_output=True, text=True, timeout=12)
        if proc.returncode == 0:
            next_dt = get_next_daily_report_time(formatted_time)
            next_str = next_dt.strftime("%Y-%m-%d %H:%M:%S")
            update_email_settings({
                "scheduler_registered": True,
                "daily_report_time": formatted_time,
                "next_scheduled_run": next_str
            })
            logger.info(f"Registered Windows scheduled task '{TASK_NAME}' at {formatted_time} daily.")
            return True, f"Windows scheduled task '{TASK_NAME}' registered successfully for {formatted_time} daily."
        else:
            err = proc.stderr.strip() or proc.stdout.strip() or "Unknown error"
            logger.warning(f"Failed to create scheduled task: {err}")
            return False, f"Windows Task Scheduler error: {err}"
    except Exception as e:
        logger.error(f"Error executing schtasks: {e}")
        return False, f"Error registering task: {str(e)}"


def remove_windows_scheduled_task(user_consented: bool = False) -> Tuple[bool, str]:
    """
    Remove the persistent Windows scheduled task.
    """
    if not user_consented:
        return False, "User consent is required before modifying scheduled tasks."

    if sys.platform != "win32":
        update_email_settings({"scheduler_registered": False, "next_scheduled_run": ""})
        return True, "Schedule removed."

    cmd = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    try:
        proc = safe_run(cmd, capture_output=True, text=True, timeout=12)
        update_email_settings({
            "scheduler_registered": False,
            "next_scheduled_run": ""
        })
        if proc.returncode == 0 or "cannot find" in proc.stderr.lower():
            logger.info(f"Windows scheduled task '{TASK_NAME}' removed.")
            return True, f"Windows scheduled task '{TASK_NAME}' removed successfully."
        else:
            return False, f"Error removing task: {proc.stderr.strip()}"
    except Exception as e:
        logger.error(f"Error deleting scheduled task: {e}")
        return False, f"Error deleting task: {str(e)}"


def query_windows_scheduled_task() -> Dict[str, Any]:
    """
    Inspect the current registration and next run status of the Windows scheduled task.
    """
    result = {
        "is_registered": False,
        "task_name": TASK_NAME,
        "next_run_time": "",
        "status": "Not Registered"
    }
    if sys.platform != "win32":
        return result

    try:
        proc = safe_run(
            ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"],
            capture_output=True,
            text=True,
            timeout=8
        )
        if proc.returncode == 0 and proc.stdout:
            result["is_registered"] = True
            result["status"] = "Active"
            for line in proc.stdout.splitlines():
                if "Next Run Time:" in line:
                    result["next_run_time"] = line.split(":", 1)[1].strip()
                elif "Status:" in line:
                    result["status"] = line.split(":", 1)[1].strip()
    except Exception:
        pass

    return result


def check_and_execute_scheduled_tasks() -> None:
    """
    Periodic check called by background monitoring thread while SYSFIX is active:
    1. Checks if current time is within daily report window (e.g. 7:00 PM).
    2. Sends daily report if enabled and not already sent today.
    3. Drains offline queued emails.
    """
    global _last_daily_report_sent_date
    today_str = date.today().isoformat()

    # 1. Check Offline Email Queue
    try:
        process_offline_email_queue()
    except Exception:
        pass

    # 2. Daily Report Schedule Check
    try:
        settings = get_email_settings()
        if not settings.get("daily_report_enabled", True):
            return

        # Has already been sent today?
        if _last_daily_report_sent_date == today_str:
            return

        time_str = settings.get("daily_report_time", "19:00")
        parts = time_str.strip().split(":")
        target_h = int(parts[0])
        target_m = int(parts[1]) if len(parts) > 1 else 0

        now = datetime.now()
        # Trigger if within current minute of scheduled hour:minute
        if now.hour == target_h and now.minute == target_m:
            _last_daily_report_sent_date = today_str
            logger.info(f"Triggering scheduled daily report at {time_str}...")
            
            from backend.core.email_reports import send_daily_full_system_report
            success, msg = send_daily_full_system_report(manual=False)
            if success:
                logger.info("Scheduled daily report delivered successfully.")
            else:
                logger.warning(f"Scheduled daily report failed: {msg}")
    except Exception as e:
        logger.error(f"Error in scheduler tick: {e}")
