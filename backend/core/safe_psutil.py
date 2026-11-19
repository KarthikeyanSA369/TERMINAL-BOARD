"""
SYSFIX / TERMINAL BOARD — Safe Hardware Telemetry & psutil Compatibility Layer
Provides transparent psutil wrappers with robust native Windows (Kernel32, Advapi32)
fallbacks for pre-boot environments (WinPE / WinRE) and recovery images where pdh.dll
or performance counter subsystems may be unavailable or uninitialized.
"""

import os
import sys
import time
import socket
import logging
import ctypes
from ctypes import wintypes
from typing import Dict, Any, List, Optional, Tuple, NamedTuple
from collections import namedtuple

logger = logging.getLogger("SYSFIX.SafePsutil")

# ---------------------------------------------------------------------------
# Dynamic Library & Module Load
# ---------------------------------------------------------------------------
_PSUTIL_MODULE = None
_PSUTIL_LOAD_ERROR = None

try:
    import psutil as _real_psutil
    _PSUTIL_MODULE = _real_psutil
    PSUTIL_AVAILABLE = True
except Exception as _err:
    _PSUTIL_MODULE = None
    _PSUTIL_LOAD_ERROR = str(_err)
    PSUTIL_AVAILABLE = False
    logger.warning(f"Native psutil module unavailable ({_err}). Native Windows kernel32 fallbacks active.")


# ---------------------------------------------------------------------------
# Fallback Data Structures Matching psutil NamedTuples
# ---------------------------------------------------------------------------
s_vmem = namedtuple('svmem', ['total', 'available', 'percent', 'used', 'free'])
s_swap = namedtuple('sswap', ['total', 'used', 'free', 'percent', 'sin', 'sout'])
s_disk_part = namedtuple('sdiskpart', ['device', 'mountpoint', 'fstype', 'opts', 'maxfile', 'maxpath'])
s_disk_usage = namedtuple('sdiskusage', ['total', 'used', 'free', 'percent'])
s_battery = namedtuple('sbattery', ['percent', 'secsleft', 'power_plugged'])
s_cpu_freq = namedtuple('scpufreq', ['current', 'min', 'max'])
s_pinfo = namedtuple('pinfo', ['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info', 'status', 'username', 'create_time'])
s_mem_info = namedtuple('pmeminfo', ['rss', 'vms'])

POWER_TIME_UNLIMITED = -2
POWER_TIME_UNKNOWN = -1
AF_LINK = getattr(_PSUTIL_MODULE, 'AF_LINK', -1) if _PSUTIL_MODULE else -1


# ---------------------------------------------------------------------------
# Native Windows Kernel Structures
# ---------------------------------------------------------------------------
class Error(Exception):
    pass

class NoSuchProcess(Error):
    def __init__(self, pid, name=None, msg=None):
        self.pid = pid
        self.name = name
        self.msg = msg

class AccessDenied(Error):
    def __init__(self, pid=None, name=None, msg=None):
        self.pid = pid
        self.name = name
        self.msg = msg

class ZombieProcess(NoSuchProcess):
    pass

class TimeoutExpired(Error):
    def __init__(self, seconds, pid=None, name=None):
        self.seconds = seconds
        self.pid = pid
        self.name = name

# Re-export native exceptions if available
if _PSUTIL_MODULE:
    NoSuchProcess = getattr(_real_psutil, 'NoSuchProcess', NoSuchProcess)
    AccessDenied = getattr(_real_psutil, 'AccessDenied', AccessDenied)
    ZombieProcess = getattr(_real_psutil, 'ZombieProcess', ZombieProcess)
    TimeoutExpired = getattr(_real_psutil, 'TimeoutExpired', TimeoutExpired)

class SafeProcess:
    def __init__(self, pid: int):
        self.pid = pid
        if _PSUTIL_MODULE:
            try:
                self._real = _PSUTIL_MODULE.Process(pid)
            except Exception:
                self._real = None
        else:
            self._real = None

    def terminate(self):
        if self._real:
            try:
                self._real.terminate()
                return
            except Exception:
                pass
        try:
            import ctypes
            PROCESS_TERMINATE = 0x0001
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, self.pid)
            if h:
                ctypes.windll.kernel32.TerminateProcess(h, 1)
                ctypes.windll.kernel32.CloseHandle(h)
        except Exception as e:
            logger.debug(f"Process terminate fallback error: {e}")

    def wait(self, timeout=None):
        if self._real:
            try:
                return self._real.wait(timeout=timeout)
            except Exception:
                pass
        return None

def Process(pid: int) -> SafeProcess:
    if _PSUTIL_MODULE:
        try:
            return _PSUTIL_MODULE.Process(pid)
        except Exception:
            return SafeProcess(pid)
    return SafeProcess(pid)


class _MEMORYSTATUSEX(ctypes.Structure):

    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]

class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", wintypes.BYTE),
        ("BatteryFlag", wintypes.BYTE),
        ("BatteryLifePercent", wintypes.BYTE),
        ("SystemStatusFlag", wintypes.BYTE),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]

class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

def _ft_to_uint(ft: _FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

_last_cpu_sample: Optional[Tuple[int, int, int]] = None


# ---------------------------------------------------------------------------
# Telemetry Fallback Implementations
# ---------------------------------------------------------------------------

def safe_cpu_count(logical: bool = True) -> int:
    """Return core count via psutil or os.cpu_count / kernel32."""
    if _PSUTIL_MODULE:
        try:
            cnt = _PSUTIL_MODULE.cpu_count(logical=logical)
            if cnt:
                return cnt
        except Exception as e:
            logger.debug(f"psutil.cpu_count fallback triggered: {e}")

    cnt = os.cpu_count()
    return cnt or 1


def safe_cpu_percent(interval: Optional[float] = None, percpu: bool = False) -> Any:
    """Return CPU utilization percentage via psutil or GetSystemTimes."""
    if _PSUTIL_MODULE:
        try:
            return _PSUTIL_MODULE.cpu_percent(interval=interval, percpu=percpu)
        except Exception as e:
            logger.debug(f"psutil.cpu_percent fallback triggered: {e}")

    # Fallback using GetSystemTimes
    global _last_cpu_sample
    try:
        kernel32 = ctypes.windll.kernel32
        idle_ft, kernel_ft, user_ft = _FILETIME(), _FILETIME(), _FILETIME()
        if kernel32.GetSystemTimes(ctypes.byref(idle_ft), ctypes.byref(kernel_ft), ctypes.byref(user_ft)):
            idle = _ft_to_uint(idle_ft)
            kernel = _ft_to_uint(kernel_ft)
            user = _ft_to_uint(user_ft)
            if _last_cpu_sample is not None:
                last_idle, last_kernel, last_user = _last_cpu_sample
                idle_diff = idle - last_idle
                kernel_diff = kernel - last_kernel
                user_diff = user - last_user
                total_diff = kernel_diff + user_diff
                _last_cpu_sample = (idle, kernel, user)
                if total_diff > 0:
                    pct = round(100.0 * (total_diff - idle_diff) / total_diff, 1)
                    pct = max(0.0, min(100.0, pct))
                    return [pct] * safe_cpu_count() if percpu else pct
            _last_cpu_sample = (idle, kernel, user)
    except Exception as e:
        logger.debug(f"GetSystemTimes CPU fallback error: {e}")

    cores = safe_cpu_count()
    return [0.0] * cores if percpu else 0.0


def safe_cpu_freq() -> Optional[Any]:
    """Return CPU frequencies via psutil or WMI/Registry."""
    if _PSUTIL_MODULE:
        try:
            freq = _PSUTIL_MODULE.cpu_freq()
            if freq and freq.current > 0:
                return freq
        except Exception as e:
            logger.debug(f"psutil.cpu_freq fallback triggered: {e}")

    # Fallback to Windows Registry ~MHz
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        mhz, _ = winreg.QueryValueEx(key, "~MHz")
        winreg.CloseKey(key)
        if mhz:
            return s_cpu_freq(current=float(mhz), min=0.0, max=float(mhz))
    except Exception:
        pass

    return None


def safe_virtual_memory() -> Any:
    """Return system memory statistics via psutil or GlobalMemoryStatusEx."""
    if _PSUTIL_MODULE:
        try:
            return _PSUTIL_MODULE.virtual_memory()
        except Exception as e:
            logger.debug(f"psutil.virtual_memory fallback triggered: {e}")

    # Fallback to GlobalMemoryStatusEx
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            total = stat.ullTotalPhys
            avail = stat.ullAvailPhys
            used = total - avail
            pct = round((used / total) * 100.0, 1) if total > 0 else 0.0
            return s_vmem(total=total, available=avail, percent=pct, used=used, free=avail)
    except Exception as e:
        logger.debug(f"GlobalMemoryStatusEx error: {e}")

    return s_vmem(total=0, available=0, percent=0.0, used=0, free=0)


def safe_swap_memory() -> Any:
    """Return swap / pagefile statistics via psutil or GlobalMemoryStatusEx."""
    if _PSUTIL_MODULE:
        try:
            return _PSUTIL_MODULE.swap_memory()
        except Exception as e:
            logger.debug(f"psutil.swap_memory fallback triggered: {e}")

    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            total = stat.ullTotalPageFile
            avail = stat.ullAvailPageFile
            used = total - avail
            pct = round((used / total) * 100.0, 1) if total > 0 else 0.0
            return s_swap(total=total, used=used, free=avail, percent=pct, sin=0, sout=0)
    except Exception as e:
        logger.debug(f"Swap memory fallback error: {e}")

    return s_swap(total=0, used=0, free=0, percent=0.0, sin=0, sout=0)


def safe_disk_partitions(all: bool = False) -> List[Any]:
    """Return partition mountpoints via psutil or GetLogicalDriveStringsW."""
    if _PSUTIL_MODULE:
        try:
            parts = _PSUTIL_MODULE.disk_partitions(all=all)
            if parts:
                return parts
        except Exception as e:
            logger.debug(f"psutil.disk_partitions fallback triggered: {e}")

    # Fallback using GetLogicalDriveStringsW & GetDriveTypeW
    partitions = []
    try:
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_unicode_buffer(1024)
        length = kernel32.GetLogicalDriveStringsW(1023, buf)
        if length > 0:
            drives = [d.strip() for d in buf[:length].split('\x00') if d.strip()]
            for d in drives:
                dtype = kernel32.GetDriveTypeW(d)
                # DRIVE_FIXED = 3, DRIVE_REMOVABLE = 2, DRIVE_CDROM = 5, DRIVE_REMOTE = 4
                if dtype in (2, 3, 4, 5) or all:
                    partitions.append(s_disk_part(
                        device=d,
                        mountpoint=d,
                        fstype="NTFS",
                        opts="rw,fixed" if dtype == 3 else "rw,removable",
                        maxfile=255,
                        maxpath=260
                    ))
    except Exception as e:
        logger.debug(f"GetLogicalDriveStringsW fallback error: {e}")

    return partitions


def safe_disk_usage(path: str) -> Any:
    """Return disk space usage via psutil or GetDiskFreeSpaceExW."""
    if _PSUTIL_MODULE:
        try:
            return _PSUTIL_MODULE.disk_usage(path)
        except Exception as e:
            logger.debug(f"psutil.disk_usage fallback triggered: {e}")

    try:
        free_bytes = ctypes.c_uint64()
        total_bytes = ctypes.c_uint64()
        total_free = ctypes.c_uint64()
        root = os.path.splitdrive(path)[0] + "\\"
        if ctypes.windll.kernel32.GetDiskFreeSpaceExW(root, ctypes.byref(free_bytes), ctypes.byref(total_bytes), ctypes.byref(total_free)):
            tot = total_bytes.value
            free = free_bytes.value
            used = tot - free
            pct = round((used / tot) * 100.0, 1) if tot > 0 else 0.0
            return s_disk_usage(total=tot, used=used, free=free, percent=pct)
    except Exception as e:
        logger.debug(f"GetDiskFreeSpaceExW error: {e}")

    return s_disk_usage(total=0, used=0, free=0, percent=0.0)


def safe_sensors_battery() -> Optional[Any]:
    """Return battery state via psutil or GetSystemPowerStatus."""
    if _PSUTIL_MODULE:
        try:
            bat = _PSUTIL_MODULE.sensors_battery()
            if bat is not None:
                return bat
        except Exception as e:
            logger.debug(f"psutil.sensors_battery fallback triggered: {e}")

    try:
        sps = _SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
            # Flag 128 = No system battery
            if sps.BatteryFlag == 128 or sps.BatteryLifePercent == 255:
                return None
            plugged = sps.ACLineStatus == 1
            pct = float(sps.BatteryLifePercent)
            secsleft = sps.BatteryLifeTime if sps.BatteryLifeTime != 0xFFFFFFFF else POWER_TIME_UNKNOWN
            return s_battery(percent=pct, secsleft=secsleft, power_plugged=plugged)
    except Exception as e:
        logger.debug(f"GetSystemPowerStatus error: {e}")

    return None


def safe_net_if_stats() -> Dict[str, Any]:
    """Return network interface stats via psutil or safe dictionary."""
    if _PSUTIL_MODULE:
        try:
            return _PSUTIL_MODULE.net_if_stats()
        except Exception as e:
            logger.debug(f"psutil.net_if_stats fallback triggered: {e}")
    return {}


def safe_net_if_addrs() -> Dict[str, List[Any]]:
    """Return network interface addresses via psutil or safe dictionary."""
    if _PSUTIL_MODULE:
        try:
            return _PSUTIL_MODULE.net_if_addrs()
        except Exception as e:
            logger.debug(f"psutil.net_if_addrs fallback triggered: {e}")
    return {}


def safe_boot_time() -> float:
    """Return boot epoch timestamp via psutil or GetTickCount64."""
    if _PSUTIL_MODULE:
        try:
            return _PSUTIL_MODULE.boot_time()
        except Exception as e:
            logger.debug(f"psutil.boot_time fallback triggered: {e}")

    try:
        uptime_ms = ctypes.windll.kernel32.GetTickCount64()
        return time.time() - (uptime_ms / 1000.0)
    except Exception:
        return time.time()


def safe_process_iter(attrs: Optional[List[str]] = None) -> Any:
    """Safely iterate processes via psutil."""
    if _PSUTIL_MODULE:
        try:
            return _PSUTIL_MODULE.process_iter(attrs=attrs)
        except Exception as e:
            logger.debug(f"psutil.process_iter error: {e}")
    return []


# Expose psutil-like interface
cpu_count = safe_cpu_count
cpu_percent = safe_cpu_percent
cpu_freq = safe_cpu_freq
virtual_memory = safe_virtual_memory
swap_memory = safe_swap_memory
disk_partitions = safe_disk_partitions
disk_usage = safe_disk_usage
sensors_battery = safe_sensors_battery
net_if_stats = safe_net_if_stats
net_if_addrs = safe_net_if_addrs
boot_time = safe_boot_time
process_iter = safe_process_iter
