"""
TERMINAL BOARD — Windows Startup Integration
Configures optional, reversible launch on user sign-in via HKCU Run key.
Does not require administrator privileges. Does not touch boot configurations.
"""

import os
import sys
import winreg
import logging
from typing import Dict, Any

logger = logging.getLogger("TERMINAL_BOARD.Startup")

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "TERMINAL_BOARD"

def get_launch_command() -> str:
    """Determine the command line required to launch the current application."""
    if getattr(sys, "frozen", False):
        # Packaged executable
        exe_path = os.path.abspath(sys.executable)
        return f'"{exe_path}"'
    else:
        # Running from Python source
        python_exe = sys.executable
        # Use pythonw if available to avoid terminal window
        pythonw_candidate = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
        launcher = pythonw_candidate if os.path.exists(pythonw_candidate) else python_exe
        app_script = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "app.py"))
        return f'"{launcher}" "{app_script}"'

def get_startup_status() -> Dict[str, Any]:
    """Check whether TERMINAL BOARD is configured to start with Windows for the current user."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return {
                "enabled": True,
                "command": value,
                "current_target": get_launch_command(),
                "method": "HKCU_Run",
                "can_configure": True
            }
    except FileNotFoundError:
        return {
            "enabled": False,
            "command": "",
            "current_target": get_launch_command(),
            "method": "HKCU_Run",
            "can_configure": True
        }
    except Exception as e:
        logger.warning(f"Error checking Windows startup status: {e}")
        return {
            "enabled": False,
            "command": "",
            "current_target": get_launch_command(),
            "method": "HKCU_Run",
            "can_configure": False,
            "error": str(e)
        }

def set_startup_status(enabled: bool) -> Dict[str, Any]:
    """Enable or disable launch on Windows user sign-in."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
            if enabled:
                cmd = get_launch_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                logger.info(f"Registered Windows startup entry for {APP_NAME}: {cmd}")
                return {"success": True, "enabled": True, "command": cmd, "message": "TERMINAL BOARD registered for automatic startup upon user sign-in."}
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    logger.info(f"Removed Windows startup entry for {APP_NAME}")
                except FileNotFoundError:
                    pass
                return {"success": True, "enabled": False, "message": "TERMINAL BOARD automatic startup has been disabled."}
    except Exception as e:
        logger.error(f"Failed to modify Windows startup entry: {e}")
        return {"success": False, "error": str(e), "message": f"Could not update startup registry: {e}"}
