"""
SYSFIX Metrics Engine
Collects live system performance metrics using psutil, WMI, and native Windows APIs.
Covers CPU, Memory, Disk partitions, Battery status, Processes, and Hardware Sensors.
"""

import time
import os
import psutil
from datetime import datetime
from typing import Dict, Any, List, Optional
import collections

# Circular buffer for tracking CPU load history (up to 60 readings)
_cpu_history = collections.deque(maxlen=60)
_ram_history = collections.deque(maxlen=60)
_sustained_cpu_counter = 0
_sustained_ram_counter = 0

def format_bytes(bytes_val: int) -> str:
    """Format bytes into human-readable string (GB, MB, etc.)."""
    if bytes_val is None:
        return "N/A"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0 or unit == 'TB':
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} TB"

def get_cpu_metrics() -> Dict[str, Any]:
    """Retrieve current CPU utilization, frequencies, core counts, and sustained load."""
    global _sustained_cpu_counter
    cpu_percent = psutil.cpu_percent(interval=None)
    per_cpu = psutil.cpu_percent(percpu=True, interval=None)
    
    # Store history
    _cpu_history.append(cpu_percent)

    # Sustained high load check (>85% for consecutive readings)
    if cpu_percent >= 85.0:
        _sustained_cpu_counter += 1
    else:
        _sustained_cpu_counter = max(0, _sustained_cpu_counter - 1)

    sustained_high_load = _sustained_cpu_counter >= 5  # ~15-20s at 3s interval

    freq = None
    try:
        freq_info = psutil.cpu_freq()
        if freq_info:
            freq = {
                "current_mhz": round(freq_info.current, 1),
                "min_mhz": round(freq_info.min, 1) if freq_info.min else None,
                "max_mhz": round(freq_info.max, 1) if freq_info.max else None
            }
    except Exception:
        pass

    return {
        "percent": cpu_percent,
        "per_cpu": per_cpu,
        "logical_cores": psutil.cpu_count(logical=True),
        "physical_cores": psutil.cpu_count(logical=False),
        "frequency": freq,
        "history": list(_cpu_history),
        "sustained_high_load": sustained_high_load,
        "sustained_count": _sustained_cpu_counter
    }

def get_ram_metrics() -> Dict[str, Any]:
    """Retrieve detailed virtual memory and swap memory usage."""
    global _sustained_ram_counter
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    
    _ram_history.append(mem.percent)

    if mem.percent >= 85.0:
        _sustained_ram_counter += 1
    else:
        _sustained_ram_counter = max(0, _sustained_ram_counter - 1)

    sustained_pressure = _sustained_ram_counter >= 5

    return {
        "percent": mem.percent,
        "total_bytes": mem.total,
        "total_formatted": format_bytes(mem.total),
        "used_bytes": mem.used,
        "used_formatted": format_bytes(mem.used),
        "available_bytes": mem.available,
        "available_formatted": format_bytes(mem.available),
        "free_bytes": mem.free,
        "free_formatted": format_bytes(mem.free),
        "swap_total": swap.total,
        "swap_total_formatted": format_bytes(swap.total),
        "swap_used": swap.used,
        "swap_used_formatted": format_bytes(swap.used),
        "swap_percent": swap.percent,
        "history": list(_ram_history),
        "sustained_pressure": sustained_pressure
    }

def get_battery_metrics() -> Dict[str, Any]:
    """Retrieve battery status with fallback for desktop PCs."""
    try:
        battery = psutil.sensors_battery()
    except Exception:
        battery = None

    if battery is None:
        return {
            "has_battery": False,
            "status": "Desktop PC or AC Power Only",
            "percent": None,
            "power_plugged": True,
            "secsleft": None,
            "time_remaining": "AC Connected (No Battery)",
            "health": "N/A"
        }

    secsleft = battery.secsleft
    if secsleft == psutil.POWER_TIME_UNLIMITED:
        time_rem = "Fully Charged / On AC"
    elif secsleft == psutil.POWER_TIME_UNKNOWN or secsleft is None or secsleft < 0:
        time_rem = "Calculating..."
    else:
        mins, secs = divmod(secsleft, 60)
        hours, mins = divmod(mins, 60)
        time_rem = f"{hours}h {mins}m remaining"

    return {
        "has_battery": True,
        "percent": round(battery.percent, 1),
        "power_plugged": battery.power_plugged,
        "is_charging": battery.power_plugged and battery.percent < 99,
        "secsleft": secsleft if secsleft >= 0 else None,
        "time_remaining": time_rem,
        "status": "Charging" if (battery.power_plugged and battery.percent < 99) else ("AC Connected" if battery.power_plugged else "Discharging"),
        "health": "Good" if battery.percent > 20 else "Low Battery Warning"
    }

def get_disk_volume_metrics() -> List[Dict[str, Any]]:
    """Retrieve all mounted disk partitions, file systems, and space utilization."""
    partitions = []
    try:
        parts = psutil.disk_partitions(all=False)
        for p in parts:
            try:
                usage = psutil.disk_usage(p.mountpoint)
                partitions.append({
                    "device": p.device,
                    "mountpoint": p.mountpoint,
                    "fstype": p.fstype,
                    "opts": p.opts,
                    "total_bytes": usage.total,
                    "total_formatted": format_bytes(usage.total),
                    "used_bytes": usage.used,
                    "used_formatted": format_bytes(usage.used),
                    "free_bytes": usage.free,
                    "free_formatted": format_bytes(usage.free),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "percent_used": usage.percent,
                    "percent_free": round(100.0 - usage.percent, 1),
                    "is_low_space": (100.0 - usage.percent) < 10.0
                })
            except (PermissionError, FileNotFoundError, OSError):
                continue
    except Exception:
        pass
    return partitions

def get_temperature_sensors() -> Dict[str, Any]:
    """Retrieve temperature readings if supported, or provide clear diagnostic status."""
    try:
        # Check psutil sensors
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if temps:
                return {
                    "available": True,
                    "temperatures": temps,
                    "message": "Hardware temperature readings collected."
                }
    except Exception:
        pass

    return {
        "available": False,
        "temperatures": {},
        "message": "ACPI / Thermal Zone sensor access restricted or unsupported on this chipset without elevated vendor drivers."
    }

def get_top_processes(limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve top active processes sorted by CPU and memory consumption."""
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info', 'status', 'username', 'create_time']):
        try:
            info = p.info
            # Filter out Idle process
            if info['pid'] == 0:
                continue
            mem_bytes = info['memory_info'].rss if info.get('memory_info') else 0
            procs.append({
                "pid": info['pid'],
                "name": info['name'] or "Unknown",
                "cpu_percent": round(info['cpu_percent'] or 0.0, 1),
                "memory_percent": round(info['memory_percent'] or 0.0, 1),
                "memory_bytes": mem_bytes,
                "memory_formatted": format_bytes(mem_bytes),
                "status": info.get('status') or "running",
                "username": info.get('username') or "System"
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    # Sort primarily by memory, then CPU
    procs.sort(key=lambda x: (x['memory_percent'], x['cpu_percent']), reverse=True)
    return procs[:limit]

def get_system_uptime() -> Dict[str, Any]:
    """Calculate system uptime from boot time."""
    boot_timestamp = psutil.boot_time()
    boot_time = datetime.fromtimestamp(boot_timestamp)
    now = datetime.now()
    uptime_delta = now - boot_time

    days = uptime_delta.days
    hours, remainder = divmod(uptime_delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return {
        "boot_time": boot_time.strftime("%Y-%m-%d %H:%M:%S"),
        "boot_timestamp": boot_timestamp,
        "uptime_seconds": int(uptime_delta.total_seconds()),
        "uptime_formatted": f"{days}d {hours}h {minutes}m {seconds}s"
    }

def collect_all_metrics() -> Dict[str, Any]:
    """Aggregate complete system metric snapshot."""
    cpu = get_cpu_metrics()
    ram = get_ram_metrics()
    battery = get_battery_metrics()
    disks = get_disk_volume_metrics()
    temps = get_temperature_sensors()
    uptime = get_system_uptime()
    
    # Calculate lowest free disk GB for alert evaluation
    min_free_gb = min([d["free_gb"] for d in disks]) if disks else 999.0

    return {
        "timestamp": datetime.now().isoformat(),
        "cpu": cpu,
        "ram": ram,
        "battery": battery,
        "disks": disks,
        "temperatures": temps,
        "uptime": uptime,
        "disk_free_gb": min_free_gb
    }
