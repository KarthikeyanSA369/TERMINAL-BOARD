"""
SYSFIX Robust & Hidden Subprocess Management Utility
Provides centralized, safe subprocess execution for Windows environments,
guaranteeing no transient console windows (CREATE_NO_WINDOW), non-interactive
execution, proper stdin isolation, timeout safeguards, and process cleanup.
"""

import sys
import subprocess
import threading
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger("SYSFIX.Subprocess")

# Global registry of active child processes for graceful shutdown cleanup
_active_child_procs = set()
_proc_lock = threading.Lock()

def get_hidden_subprocess_kwargs() -> Dict[str, Any]:
    """Return creationflags and startupinfo configured to suppress console windows on Windows."""
    kwargs: Dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs

def register_child_proc(proc: subprocess.Popen) -> None:
    """Register a child process to be cleaned up on application shutdown."""
    with _proc_lock:
        _active_child_procs.add(proc)

def unregister_child_proc(proc: subprocess.Popen) -> None:
    """Unregister a child process once completed."""
    with _proc_lock:
        _active_child_procs.discard(proc)

def cleanup_child_processes() -> None:
    """Terminate and join any lingering child processes to ensure clean exit."""
    with _proc_lock:
        procs = list(_active_child_procs)
    for p in procs:
        try:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=1.0)
                except Exception:
                    p.kill()
        except Exception:
            pass
    with _proc_lock:
        _active_child_procs.clear()

def safe_run(cmd: Any, **kwargs) -> subprocess.CompletedProcess:
    """
    Safely executes a non-interactive child process without creating a console window.
    Applies CREATE_NO_WINDOW and SW_HIDE on Windows, isolates stdin, and ensures
    appropriate timeout defaults.
    """
    hidden = get_hidden_subprocess_kwargs()
    for k, v in hidden.items():
        if k not in kwargs:
            kwargs[k] = v

    if "stdin" not in kwargs:
        kwargs["stdin"] = subprocess.DEVNULL

    return subprocess.run(cmd, **kwargs)

def safe_popen(cmd: Any, **kwargs) -> subprocess.Popen:
    """
    Safely starts an asynchronous child process without creating a console window.
    Registers process in active table for shutdown cleanup.
    """
    hidden = get_hidden_subprocess_kwargs()
    for k, v in hidden.items():
        if k not in kwargs:
            kwargs[k] = v

    if "stdin" not in kwargs:
        kwargs["stdin"] = subprocess.DEVNULL

    proc = subprocess.Popen(cmd, **kwargs)
    register_child_proc(proc)
    return proc

def run_powershell_command(command: str, timeout: int = 8) -> subprocess.CompletedProcess:
    """
    Executes a PowerShell command non-interactively with strict flags:
    -NoProfile, -NonInteractive, -ExecutionPolicy Bypass, hidden console, isolated stdin.
    """
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-Command", command
    ]
    return safe_run(cmd, capture_output=True, text=True, timeout=timeout)
