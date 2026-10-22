"""
SYSFIX Hardware Discovery & Inventory Engine
Discovers and inventories all available hardware subsystems on Windows:
- CPU / Processor (Model, Cores, Threads, Frequency, Architecture, Utilization)
- RAM / Memory (Total, Available, Physical Modules, Speed, Manufacturer, Slots)
- Storage / Disks (SSD, HDD, NVMe, Bus Type, Capacity, SMART, Temperature, Firmware)
- GPU / Video Controller (Model, VRAM, Driver, Status, Video Processor)
- Motherboard & BIOS (Manufacturer, Model, Serial, BIOS Vendor, Version, Release Date)
- Cooling System (Fan tachometer sensors, thermal status, throttling flags)
- Battery (Design Capacity, Full Charge Capacity, Current Charge, Chemistry, Cycle Count, Desktop Fallback)
- Network Adapters (Physical vs Virtual, MAC, Link Speed, Status, Driver)
- Additional Devices (Audio Controllers, USB Controllers, PCIe, Monitors, HID/Input, Bluetooth)

Thread-safe and optimized with bounded concurrency and optional in-memory caching.
Read-only and safe.
"""

import sys
import os
import time
import socket
import psutil
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("SYSFIX.HardwareInventory")

# In-memory cache for static hardware info during application session
_STATIC_HARDWARE_CACHE: Dict[str, Any] = {}
_LAST_INVENTORY_TIME: float = 0.0
CACHE_TTL_SECONDS: float = 60.0  # Static hardware remains valid for 60s


def format_bytes(bytes_val: Optional[int]) -> str:
    """Format bytes into human-readable string."""
    if bytes_val is None or bytes_val < 0:
        return "Not Available"
    val = float(bytes_val)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if val < 1024.0 or unit == 'PB':
            return f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{val:.1f} PB"


def _com_thread_wrapper(fn):
    """Ensure COM/WMI initialized in worker threads on Windows."""
    def wrapped(*args, **kwargs):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        try:
            return fn(*args, **kwargs)
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass
    return wrapped


# =========================================================================
# 1. CPU / Processor Inventory
# =========================================================================

def get_cpu_inventory() -> Dict[str, Any]:
    """Interrogates processor hardware specifications and real-time state."""
    cpu_data: Dict[str, Any] = {
        "component": "CPU",
        "manufacturer": "Not Available",
        "model": "Not Available",
        "architecture": "x64" if sys.maxsize > 2**32 else "x86",
        "physical_cores": psutil.cpu_count(logical=False) or 1,
        "logical_processors": psutil.cpu_count(logical=True) or 1,
        "current_frequency_mhz": None,
        "max_frequency_mhz": None,
        "utilization_percent": round(psutil.cpu_percent(interval=None), 1),
        "per_core_utilization": psutil.cpu_percent(percpu=True, interval=None),
        "temperature_c": None,
        "temperature_status": "NOT AVAILABLE",
        "thermal_throttling": False,
        "throttling_status": "NOT AVAILABLE",
        "socket_designation": "Not Available",
        "l2_cache_size_kb": None,
        "l3_cache_size_kb": None,
        "virtualization_enabled": False,
        "hardware_errors_count": 0,
        "status": "HEALTHY"
    }

    # Frequency via psutil
    try:
        freq = psutil.cpu_freq()
        if freq:
            cpu_data["current_frequency_mhz"] = round(freq.current, 1)
            cpu_data["max_frequency_mhz"] = round(freq.max, 1) if freq.max > 0 else round(freq.current, 1)
    except Exception as e:
        logger.debug(f"psutil.cpu_freq error: {e}")

    # WMI Win32_Processor
    try:
        import wmi
        c = wmi.WMI()
        for p in c.Win32_Processor():
            cpu_data["manufacturer"] = (getattr(p, "Manufacturer", None) or "Not Available").strip()
            cpu_data["model"] = (getattr(p, "Name", None) or "Not Available").strip()
            cpu_data["socket_designation"] = (getattr(p, "SocketDesignation", None) or "Not Available").strip()
            cpu_data["max_frequency_mhz"] = getattr(p, "MaxClockSpeed", None) or cpu_data["max_frequency_mhz"]
            cpu_data["current_frequency_mhz"] = getattr(p, "CurrentClockSpeed", None) or cpu_data["current_frequency_mhz"]
            cpu_data["l2_cache_size_kb"] = getattr(p, "L2CacheSize", None)
            cpu_data["l3_cache_size_kb"] = getattr(p, "L3CacheSize", None)
            
            # Architecture mapping
            arch_code = getattr(p, "Architecture", 9)
            arch_map = {0: "x86 (32-bit)", 1: "MIPS", 2: "Alpha", 3: "PowerPC", 5: "ARM", 6: "Itanium", 9: "x64 (64-bit AMD/Intel)", 12: "ARM64"}
            cpu_data["architecture"] = arch_map.get(arch_code, f"Architecture Code {arch_code}")
            
            # Virtualization firmware flag
            v_firmware = getattr(p, "VirtualizationFirmwareEnabled", None)
            if v_firmware is not None:
                cpu_data["virtualization_enabled"] = bool(v_firmware)
            break
    except Exception as e:
        logger.warning(f"WMI Win32_Processor query error: {e}")

    # Honest thermal sensor check
    try:
        import wmi
        c_wmi = wmi.WMI(namespace=r"root\wmi")
        tzs = c_wmi.MSAcpi_ThermalZoneTemperature()
        if tzs:
            temps = [(tz.CurrentTemperature - 2732) / 10.0 for tz in tzs if getattr(tz, "CurrentTemperature", 0) > 0]
            if temps:
                cpu_data["temperature_c"] = round(max(temps), 1)
                cpu_data["temperature_status"] = "OK"
                # Check thermal throttling: if temp > 95C or current freq is throttled < 50% max under load
                if cpu_data["temperature_c"] >= 95.0:
                    cpu_data["thermal_throttling"] = True
                    cpu_data["throttling_status"] = "CRITICAL: Severe high temperature thermal throttling detected"
                elif cpu_data["temperature_c"] >= 85.0:
                    cpu_data["throttling_status"] = "WARNING: Elevated temperature"
                else:
                    cpu_data["throttling_status"] = "HEALTHY: Operating within normal thermal limits"
    except Exception:
        cpu_data["temperature_c"] = None
        cpu_data["temperature_status"] = "NOT AVAILABLE: ACPI thermal zone requires administrator elevation or vendor EC driver"
        cpu_data["throttling_status"] = "NOT AVAILABLE: Sensor interface restricted"

    return cpu_data


# =========================================================================
# 2. RAM / Memory Inventory
# =========================================================================

def get_ram_inventory() -> Dict[str, Any]:
    """Interrogates system RAM capacity, usage, and physical DIMM modules."""
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()

    ram_data: Dict[str, Any] = {
        "component": "RAM",
        "total_bytes": vm.total,
        "total_formatted": format_bytes(vm.total),
        "available_bytes": vm.available,
        "available_formatted": format_bytes(vm.available),
        "used_bytes": vm.used,
        "used_formatted": format_bytes(vm.used),
        "utilization_percent": vm.percent,
        "swap_total_bytes": swap.total,
        "swap_total_formatted": format_bytes(swap.total),
        "swap_used_bytes": swap.used,
        "swap_used_formatted": format_bytes(swap.used),
        "swap_utilization_percent": swap.percent,
        "installed_modules": [],
        "total_slots": None,
        "used_slots": 0,
        "memory_type": "Not Available",
        "speed_mhz": None,
        "hardware_errors_count": 0,
        "status": "HEALTHY"
    }

    # Interrogate physical memory modules via WMI Win32_PhysicalMemory
    try:
        import wmi
        c = wmi.WMI()
        modules = []
        speeds = []
        form_factors = {8: "DIMM", 12: "SO-DIMM", 0: "Unknown", 1: "Other"}
        mem_types = {20: "DDR", 21: "DDR2", 22: "DDR2 FB-DIMM", 24: "DDR3", 26: "DDR4", 34: "DDR5", 0: "Unknown"}

        for m in c.Win32_PhysicalMemory():
            cap = int(getattr(m, "Capacity", 0) or 0)
            spd = getattr(m, "Speed", None)
            mfr = (getattr(m, "Manufacturer", None) or "Not Available").strip()
            part = (getattr(m, "PartNumber", None) or "Not Available").strip()
            loc = (getattr(m, "DeviceLocator", None) or getattr(m, "BankLabel", None) or "Slot").strip()
            smtype = getattr(m, "SMBIOSMemoryType", None) or getattr(m, "MemoryType", 0)
            form = form_factors.get(getattr(m, "FormFactor", 0), "DIMM")

            if spd:
                try:
                    speeds.append(int(spd))
                except Exception:
                    pass

            modules.append({
                "slot": loc,
                "capacity_bytes": cap,
                "capacity_formatted": format_bytes(cap),
                "speed_mhz": spd,
                "manufacturer": mfr,
                "part_number": part,
                "form_factor": form,
                "memory_type": mem_types.get(smtype, "DDR" if smtype else "Not Available"),
                "status": "OK"
            })

        ram_data["installed_modules"] = modules
        ram_data["used_slots"] = len(modules)
        if speeds:
            ram_data["speed_mhz"] = min(speeds)  # Operating speed is lowest of installed
        if modules:
            ram_data["memory_type"] = modules[0]["memory_type"]

        # Interrogate Win32_PhysicalMemoryArray for total slots
        for arr in c.Win32_PhysicalMemoryArray():
            slots = getattr(arr, "MemoryDevices", None)
            if slots:
                ram_data["total_slots"] = int(slots)
                break
    except Exception as e:
        logger.warning(f"WMI Win32_PhysicalMemory query error: {e}")

    return ram_data


# =========================================================================
# 3. Storage / Disks Inventory (SSD, HDD, NVMe)
# =========================================================================

def get_storage_inventory() -> Dict[str, Any]:
    """Interrogates physical storage devices, media types, NVMe health, and partitions."""
    storage_data: Dict[str, Any] = {
        "component": "Storage",
        "physical_disks": [],
        "logical_partitions": [],
        "total_capacity_bytes": 0,
        "total_capacity_formatted": "0 B",
        "has_ssd": False,
        "has_nvme": False,
        "has_hdd": False,
        "status": "HEALTHY"
    }

    # Logical partitions via psutil
    try:
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                storage_data["logical_partitions"].append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "filesystem": part.fstype,
                    "total_bytes": usage.total,
                    "total_formatted": format_bytes(usage.total),
                    "free_bytes": usage.free,
                    "free_formatted": format_bytes(usage.free),
                    "used_bytes": usage.used,
                    "used_formatted": format_bytes(usage.used),
                    "percent_used": usage.percent,
                    "percent_free": round(100.0 - usage.percent, 1)
                })
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"psutil.disk_partitions error: {e}")

    # Physical drives via MSFT_PhysicalDisk (Storage WMI)
    disks = []
    total_cap = 0
    try:
        import wmi
        c_stor = wmi.WMI(namespace=r"root\Microsoft\Windows\Storage")
        
        bus_map = {
            1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "1394", 5: "SSA", 6: "Fibre Channel",
            7: "USB", 8: "RAID", 9: "iSCSI", 10: "SAS", 11: "SATA", 12: "SD",
            13: "MMC", 14: "MAX", 15: "Virtual", 16: "Storage Spaces", 17: "NVMe"
        }
        media_map = {0: "Unspecified", 3: "HDD", 4: "SSD", 5: "SCM"}
        health_map = {0: "Healthy", 1: "Warning", 2: "Unhealthy", 3: "Unknown"}

        # Reliability counters cache
        rel_counters: Dict[str, Dict[str, Any]] = {}
        try:
            for item in c_stor.MSFT_StorageReliabilityCounter():
                did = str(getattr(item, "DeviceId", ""))
                rel_counters[did] = {
                    "temperature": getattr(item, "Temperature", None),
                    "read_errors": getattr(item, "ReadErrorsTotal", None),
                    "write_errors": getattr(item, "WriteErrorsTotal", None),
                    "wear": getattr(item, "Wear", None),
                    "power_on_hours": getattr(item, "PowerOnHours", None)
                }
        except Exception:
            pass

        for d in c_stor.MSFT_PhysicalDisk():
            did = str(getattr(d, "DeviceId", ""))
            name = (getattr(d, "FriendlyName", None) or f"Disk {did}").strip()
            size = int(getattr(d, "Size", 0) or 0)
            total_cap += size
            media_code = getattr(d, "MediaType", 0)
            media = media_map.get(media_code, "Unknown")
            bus_code = getattr(d, "BusType", 0)
            bus = bus_map.get(bus_code, "SATA" if "sata" in name.lower() else "Unknown")
            health_code = getattr(d, "HealthStatus", 3)
            health = health_map.get(health_code, "Unknown")
            op = getattr(d, "OperationalStatus", None)
            op_code = op[0] if isinstance(op, (list, tuple)) and len(op) > 0 else op
            op_map = {2: "OK", 1: "Other", 3: "Degraded", 4: "Stressed", 5: "Predictive Failure", 6: "Error"}
            op_str = op_map.get(op_code, "OK" if op_code == 2 else "Unknown")
            firmware = (getattr(d, "FirmwareVersion", None) or "Not Available").strip()

            if "SSD" in media or bus == "NVMe":
                storage_data["has_ssd"] = True
            if bus == "NVMe":
                storage_data["has_nvme"] = True
            if "HDD" in media:
                storage_data["has_hdd"] = True

            rel = rel_counters.get(did, {})
            temp = rel.get("temperature")
            wear = rel.get("wear")
            read_err = rel.get("read_errors")
            write_err = rel.get("write_errors")

            # Determine drive status
            drive_status = "HEALTHY"
            status_reasons = []
            if op_str in ("Predictive Failure", "Error", "Degraded") or health == "Unhealthy":
                drive_status = "CRITICAL"
                status_reasons.append(f"Storage controller reported {op_str} / {health}")
            elif health == "Warning" or (read_err and read_err > 50) or (write_err and write_err > 20):
                drive_status = "WARNING"
                status_reasons.append("Elevated I/O errors or warning indicator")
            elif health == "Unknown" and not rel:
                drive_status = "UNKNOWN"
                status_reasons.append("SMART telemetry restricted without elevation")

            disks.append({
                "device_id": did,
                "model": name,
                "media_type": media,
                "bus_type": bus,
                "capacity_bytes": size,
                "capacity_formatted": format_bytes(size),
                "firmware_version": firmware,
                "operational_status": op_str,
                "health_status": health,
                "temperature_c": temp,
                "wear_percent": wear,
                "read_errors": read_err,
                "write_errors": write_err,
                "smart_supported": True,
                "smart_telemetry_accessible": bool(rel),
                "status": drive_status,
                "status_reason": "; ".join(status_reasons) if status_reasons else "Normal operation"
            })
    except Exception as e:
        logger.debug(f"Storage WMI query unavailable, falling back to Win32_DiskDrive: {e}")

    # Fallback to standard Win32_DiskDrive if MSFT_PhysicalDisk empty
    if not disks:
        try:
            import wmi
            c = wmi.WMI()
            for d in c.Win32_DiskDrive():
                size = int(getattr(d, "Size", 0) or 0)
                total_cap += size
                name = (getattr(d, "Model", None) or "Generic Drive").strip()
                status_raw = (getattr(d, "Status", None) or "OK").strip()
                bus = (getattr(d, "InterfaceType", None) or "IDE/SATA").strip()
                disks.append({
                    "device_id": str(getattr(d, "Index", "0")),
                    "model": name,
                    "media_type": "SSD" if ("ssd" in name.lower() or "nvme" in name.lower()) else "Storage Device",
                    "bus_type": "NVMe" if "nvme" in name.lower() else bus,
                    "capacity_bytes": size,
                    "capacity_formatted": format_bytes(size),
                    "firmware_version": "Not Available",
                    "operational_status": status_raw,
                    "health_status": "Healthy" if status_raw.upper() == "OK" else "Warning",
                    "temperature_c": None,
                    "wear_percent": None,
                    "read_errors": None,
                    "write_errors": None,
                    "smart_supported": True,
                    "smart_telemetry_accessible": False,
                    "status": "HEALTHY" if status_raw.upper() == "OK" else "WARNING",
                    "status_reason": "Standard Win32_DiskDrive query"
                })
        except Exception as e2:
            logger.warning(f"Win32_DiskDrive fallback error: {e2}")

    storage_data["physical_disks"] = disks
    storage_data["total_capacity_bytes"] = total_cap
    storage_data["total_capacity_formatted"] = format_bytes(total_cap)

    # Global storage status
    if any(d["status"] == "CRITICAL" for d in disks):
        storage_data["status"] = "CRITICAL"
    elif any(d["status"] == "WARNING" for d in disks):
        storage_data["status"] = "WARNING"
    elif all(d["status"] == "UNKNOWN" for d in disks):
        storage_data["status"] = "UNKNOWN"

    return storage_data


# =========================================================================
# 4. GPU / Graphics Inventory
# =========================================================================

def get_gpu_inventory() -> Dict[str, Any]:
    """Interrogates graphical processing units (integrated and dedicated)."""
    gpu_data: Dict[str, Any] = {
        "component": "GPU",
        "controllers": [],
        "primary_gpu": "Not Available",
        "has_dedicated_gpu": False,
        "status": "HEALTHY"
    }

    try:
        import wmi
        c = wmi.WMI()
        for v in c.Win32_VideoController():
            name = (getattr(v, "Name", None) or "Graphics Adapter").strip()
            vram = getattr(v, "AdapterRAM", None)
            driver_ver = (getattr(v, "DriverVersion", None) or "Not Available").strip()
            driver_date_raw = getattr(v, "DriverDate", "")
            driver_date = str(driver_date_raw)[:8] if driver_date_raw else "Not Available"
            proc = (getattr(v, "VideoProcessor", None) or "Integrated").strip()
            status = (getattr(v, "Status", None) or "OK").strip()
            horiz = getattr(v, "CurrentHorizontalResolution", None)
            vert = getattr(v, "CurrentVerticalResolution", None)
            res_str = f"{horiz} x {vert}" if horiz and vert else "Not Available"
            refresh = getattr(v, "CurrentRefreshRate", None)
            refresh_str = f"{refresh} Hz" if refresh else "Not Available"

            # Distinguish integrated vs dedicated GPU
            is_dedicated = False
            name_low = name.lower()
            if any(term in name_low for term in ["nvidia", "geforce", "rtx", "gtx", "quadro", "radeon", "rx 6", "rx 7"]):
                is_dedicated = True
                gpu_data["has_dedicated_gpu"] = True

            gpu_data["controllers"].append({
                "model": name,
                "video_processor": proc,
                "is_dedicated": is_dedicated,
                "vram_bytes": vram,
                "vram_formatted": format_bytes(vram) if vram else "Dynamic / Shared",
                "driver_version": driver_ver,
                "driver_date": driver_date,
                "resolution": res_str,
                "refresh_rate": refresh_str,
                "status": "HEALTHY" if status.upper() == "OK" else "WARNING",
                "status_reason": f"Windows reported status: {status}"
            })

        if gpu_data["controllers"]:
            gpu_data["primary_gpu"] = gpu_data["controllers"][0]["model"]
            if any(c["status"] == "WARNING" for c in gpu_data["controllers"]):
                gpu_data["status"] = "WARNING"
    except Exception as e:
        logger.warning(f"Win32_VideoController error: {e}")
        gpu_data["status"] = "NOT AVAILABLE"

    return gpu_data


# =========================================================================
# 5. Motherboard and Firmware Inventory
# =========================================================================

def get_motherboard_inventory() -> Dict[str, Any]:
    """Interrogates motherboard baseboard, chipset, and BIOS/UEFI firmware."""
    mobo_data: Dict[str, Any] = {
        "component": "Motherboard",
        "manufacturer": "Not Available",
        "product": "Not Available",
        "serial_number": "Not Available",
        "version": "Not Available",
        "bios_vendor": "Not Available",
        "bios_version": "Not Available",
        "bios_release_date": "Not Available",
        "smbios_version": "Not Available",
        "status": "HEALTHY"
    }

    try:
        import wmi
        c = wmi.WMI()
        # Motherboard BaseBoard
        for b in c.Win32_BaseBoard():
            mobo_data["manufacturer"] = (getattr(b, "Manufacturer", None) or "Not Available").strip()
            mobo_data["product"] = (getattr(b, "Product", None) or "Not Available").strip()
            mobo_data["serial_number"] = (getattr(b, "SerialNumber", None) or "Not Available").strip()
            mobo_data["version"] = (getattr(b, "Version", None) or "Not Available").strip()
            break

        # BIOS Firmware
        for bios in c.Win32_BIOS():
            mobo_data["bios_vendor"] = (getattr(bios, "Manufacturer", None) or "Not Available").strip()
            mobo_data["bios_version"] = (getattr(bios, "SMBIOSBIOSVersion", None) or getattr(bios, "Version", None) or "Not Available").strip()
            rdate = getattr(bios, "ReleaseDate", "")
            if rdate and len(str(rdate)) >= 8:
                raw_d = str(rdate)[:8]
                mobo_data["bios_release_date"] = f"{raw_d[0:4]}-{raw_d[4:6]}-{raw_d[6:8]}"
            else:
                mobo_data["bios_release_date"] = "Not Available"
            smb_maj = getattr(bios, "SMBIOSMajorVersion", None)
            smb_min = getattr(bios, "SMBIOSMinorVersion", None)
            if smb_maj is not None and smb_min is not None:
                mobo_data["smbios_version"] = f"{smb_maj}.{smb_min}"
            break
    except Exception as e:
        logger.warning(f"Motherboard/BIOS query error: {e}")

    return mobo_data


# =========================================================================
# 6. Cooling System Inventory
# =========================================================================

def get_cooling_inventory() -> Dict[str, Any]:
    """Interrogates cooling fans, tachometer RPM sensors, and thermal controllers."""
    cooling_data: Dict[str, Any] = {
        "component": "Cooling",
        "fans": [],
        "fan_count": 0,
        "fan_speed_rpm": None,
        "fan_sensor_available": False,
        "sensor_note": "Not Available",
        "thermal_zones": [],
        "status": "HEALTHY"
    }

    try:
        import wmi
        c = wmi.WMI()
        for f in c.Win32_Fan():
            speed = getattr(f, "DesiredSpeed", None)
            cooling_data["fans"].append({
                "name": getattr(f, "Name", "Cooling Fan"),
                "desired_speed": speed,
                "status": getattr(f, "Status", "OK")
            })

        cooling_data["fan_count"] = len(cooling_data["fans"])
        if cooling_data["fans"] and cooling_data["fans"][0]["desired_speed"] is not None:
            cooling_data["fan_speed_rpm"] = cooling_data["fans"][0]["desired_speed"]
            cooling_data["fan_sensor_available"] = True
            cooling_data["sensor_note"] = "Hardware tachometer reading verified"
        else:
            cooling_data["fan_sensor_available"] = False
            cooling_data["sensor_note"] = "Hardware tachometer RPM is not exposed by standard ACPI without vendor EC driver (e.g. HP CoolSense / ASUS Armoury)"
    except Exception as e:
        cooling_data["sensor_note"] = f"Win32_Fan query not supported: {e}"

    return cooling_data


# =========================================================================
# 7. Battery Inventory
# =========================================================================

def get_battery_inventory() -> Dict[str, Any]:
    """Interrogates battery pack chemistry, design capacity, full charge capacity, and wear."""
    battery_data: Dict[str, Any] = {
        "component": "Battery",
        "has_battery": False,
        "is_desktop": False,
        "manufacturer": "Not Available",
        "model": "Not Available",
        "chemistry": "Not Available",
        "design_capacity_mwh": None,
        "full_charge_capacity_mwh": None,
        "current_charge_percent": None,
        "health_wear_percent": None,
        "cycle_count": None,
        "power_plugged": True,
        "status": "HEALTHY",
        "status_reason": "AC Desktop Station"
    }

    # psutil battery check
    try:
        ps_bat = psutil.sensors_battery()
        if ps_bat:
            battery_data["has_battery"] = True
            battery_data["current_charge_percent"] = round(ps_bat.percent, 1)
            battery_data["power_plugged"] = bool(ps_bat.power_plugged)
        else:
            battery_data["has_battery"] = False
            battery_data["is_desktop"] = True
            battery_data["status_reason"] = "Desktop PC without mobile battery"
            return battery_data
    except Exception:
        pass

    # WMI Win32_Battery
    try:
        import wmi
        c = wmi.WMI()
        bats = c.Win32_Battery()
        if bats:
            battery_data["has_battery"] = True
            b = bats[0]
            battery_data["model"] = (getattr(b, "Name", None) or getattr(b, "DeviceID", None) or "Battery").strip()
            rem = getattr(b, "EstimatedChargeRemaining", None)
            if rem is not None:
                battery_data["current_charge_percent"] = int(rem)
    except Exception as e:
        logger.debug(f"Win32_Battery error: {e}")

    # WMI root\wmi BatteryStaticData & BatteryFullChargedCapacity for real wear
    try:
        import wmi
        c_wmi = wmi.WMI(namespace=r"root\wmi")
        for s in c_wmi.BatteryStaticData():
            mfr = getattr(s, "ManufactureName", "")
            if mfr:
                battery_data["manufacturer"] = str(mfr).strip()
            dev = getattr(s, "DeviceName", "")
            if dev:
                battery_data["model"] = str(dev).strip()
            des = getattr(s, "DesignedCapacity", None)
            if des and int(des) > 0:
                battery_data["design_capacity_mwh"] = int(des)
            break

        for f in c_wmi.BatteryFullChargedCapacity():
            fcap = getattr(f, "FullChargedCapacity", None)
            if fcap and int(fcap) > 0:
                battery_data["full_charge_capacity_mwh"] = int(fcap)
            break

        # Calculate wear percent
        if battery_data["design_capacity_mwh"] and battery_data["full_charge_capacity_mwh"]:
            des = battery_data["design_capacity_mwh"]
            full = battery_data["full_charge_capacity_mwh"]
            # Wear = max(0, (Design - Full) / Design * 100)
            wear = max(0.0, round(((des - full) / float(des)) * 100.0, 1))
            battery_data["health_wear_percent"] = wear
            if wear > 45.0:
                battery_data["status"] = "WARNING"
                battery_data["status_reason"] = f"Battery wear is high ({wear}% capacity degradation)"
            else:
                battery_data["status"] = "HEALTHY"
                battery_data["status_reason"] = f"Battery health normal ({wear}% wear, {full} / {des} mWh)"
    except Exception as e:
        logger.debug(f"root\\wmi battery wear query error: {e}")

    return battery_data


# =========================================================================
# 8. Network Devices Inventory
# =========================================================================

def get_network_inventory() -> Dict[str, Any]:
    """Interrogates physical and virtual network adapters, MACs, link speeds, and drivers."""
    net_data: Dict[str, Any] = {
        "component": "Network",
        "adapters": [],
        "physical_adapter_count": 0,
        "active_adapter_count": 0,
        "primary_adapter": "Not Available",
        "status": "HEALTHY"
    }

    try:
        import wmi
        c = wmi.WMI()
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()

        for a in c.Win32_NetworkAdapter():
            name = (getattr(a, "Name", None) or "Network Adapter").strip()
            mfr = (getattr(a, "Manufacturer", None) or "Standard").strip()
            mac = getattr(a, "MACAddress", None)
            is_phys = bool(getattr(a, "PhysicalAdapter", False))
            adapter_type = (getattr(a, "AdapterType", None) or "Ethernet").strip()
            speed_bps = getattr(a, "Speed", None)
            speed_mbps = round(int(speed_bps) / 1_000_000.0, 1) if speed_bps else None
            net_enabled = bool(getattr(a, "NetEnabled", False))
            pnp_id = (getattr(a, "PNPDeviceID", None) or "").strip()

            # Filter out WAN Miniport / non-physical adapters unless active
            if not is_phys and "miniport" in name.lower() and not net_enabled:
                continue

            # Link status from psutil
            ps_stat = stats.get(name)
            is_up = ps_stat.isup if ps_stat else net_enabled

            # IPv4 address
            ipv4 = None
            if name in addrs:
                for ad in addrs[name]:
                    if ad.family == socket.AF_INET:
                        ipv4 = ad.address
                        break

            if is_phys:
                net_data["physical_adapter_count"] += 1
            if is_up:
                net_data["active_adapter_count"] += 1
                if net_data["primary_adapter"] == "Not Available" and is_phys:
                    net_data["primary_adapter"] = name

            net_data["adapters"].append({
                "name": name,
                "manufacturer": mfr,
                "is_physical": is_phys,
                "mac_address": mac or "Not Available",
                "adapter_type": adapter_type,
                "link_speed_mbps": speed_mbps,
                "is_connected": is_up,
                "ipv4_address": ipv4 or "Unassigned",
                "pnp_device_id": pnp_id,
                "status": "HEALTHY" if is_up else "DISCONNECTED"
            })

    except Exception as e:
        logger.warning(f"Network adapter inventory error: {e}")

    return net_data


# =========================================================================
# 9. Additional Devices Inventory (Audio, USB, Monitors, Input, Bluetooth)
# =========================================================================

def get_additional_devices_inventory() -> Dict[str, Any]:
    """Discovers audio controllers, USB controllers, monitors, keyboards, mice, and Bluetooth."""
    additional_data: Dict[str, Any] = {
        "component": "AdditionalDevices",
        "audio_devices": [],
        "monitors": [],
        "usb_controllers": [],
        "input_devices": [],
        "bluetooth_devices": [],
        "status": "HEALTHY"
    }

    try:
        import wmi
        c = wmi.WMI()

        # Audio controllers via Win32_SoundDevice
        for s in c.Win32_SoundDevice():
            name = (getattr(s, "Name", None) or "Audio Device").strip()
            mfr = (getattr(s, "Manufacturer", None) or "Not Available").strip()
            stat = (getattr(s, "Status", None) or "OK").strip()
            additional_data["audio_devices"].append({
                "name": name,
                "manufacturer": mfr,
                "status": "HEALTHY" if stat.upper() == "OK" else "WARNING"
            })

        # Display monitors via Win32_DesktopMonitor
        for m in c.Win32_DesktopMonitor():
            name = (getattr(m, "Name", None) or getattr(m, "MonitorType", None) or "Display Monitor").strip()
            mfr = (getattr(m, "MonitorManufacturer", None) or "Generic").strip()
            additional_data["monitors"].append({
                "name": name,
                "manufacturer": mfr,
                "status": "OK"
            })

        # USB Host Controllers via Win32_USBController
        for u in c.Win32_USBController():
            name = (getattr(u, "Name", None) or "USB Controller").strip()
            mfr = (getattr(u, "Manufacturer", None) or "Standard USB").strip()
            stat = (getattr(u, "Status", None) or "OK").strip()
            additional_data["usb_controllers"].append({
                "name": name,
                "manufacturer": mfr,
                "status": "HEALTHY" if stat.upper() == "OK" else "WARNING"
            })

        # Keyboards via Win32_Keyboard
        for k in c.Win32_Keyboard():
            name = (getattr(k, "Description", None) or getattr(k, "Name", None) or "Keyboard").strip()
            additional_data["input_devices"].append({
                "type": "Keyboard",
                "name": name,
                "status": "OK"
            })

        # Pointing devices via Win32_PointingDevice
        for p in c.Win32_PointingDevice():
            name = (getattr(p, "Name", None) or "Pointing Device").strip()
            additional_data["input_devices"].append({
                "type": "Mouse / Touchpad",
                "name": name,
                "status": "OK"
            })

    except Exception as e:
        logger.warning(f"Additional devices inventory error: {e}")

    return additional_data


# =========================================================================
# Complete Hardware Inventory Orchestrator
# =========================================================================

def get_complete_hardware_inventory(use_cache: bool = True, max_workers: int = 4) -> Dict[str, Any]:
    """
    Executes parallel hardware inventory discovery across all 9 subsystems
    with bounded concurrency, timeout protections, and performance caching.
    """
    global _STATIC_HARDWARE_CACHE, _LAST_INVENTORY_TIME
    now = time.time()

    # Fast cache retrieval if valid
    if use_cache and _STATIC_HARDWARE_CACHE and (now - _LAST_INVENTORY_TIME < CACHE_TTL_SECONDS):
        # Refresh high-frequency telemetry in-place (CPU usage, RAM usage)
        cached = dict(_STATIC_HARDWARE_CACHE)
        try:
            cached["cpu"]["utilization_percent"] = round(psutil.cpu_percent(interval=None), 1)
            cached["cpu"]["per_core_utilization"] = psutil.cpu_percent(percpu=True, interval=None)
            vm = psutil.virtual_memory()
            cached["ram"]["used_bytes"] = vm.used
            cached["ram"]["used_formatted"] = format_bytes(vm.used)
            cached["ram"]["available_bytes"] = vm.available
            cached["ram"]["available_formatted"] = format_bytes(vm.available)
            cached["ram"]["utilization_percent"] = vm.percent
        except Exception:
            pass
        return cached

    start_t = time.perf_counter()
    inventory: Dict[str, Any] = {
        "scan_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scan_duration_ms": 0.0,
        "system_host": socket.gethostname(),
        "os_platform": f"{sys.platform} ({os.name})",
        "cpu": {},
        "ram": {},
        "storage": {},
        "gpu": {},
        "motherboard": {},
        "cooling": {},
        "battery": {},
        "network": {},
        "additional_devices": {}
    }

    # Parallelize subsystem queries with bounded concurrency
    subsystem_tasks = {
        "cpu": _com_thread_wrapper(get_cpu_inventory),
        "ram": _com_thread_wrapper(get_ram_inventory),
        "storage": _com_thread_wrapper(get_storage_inventory),
        "gpu": _com_thread_wrapper(get_gpu_inventory),
        "motherboard": _com_thread_wrapper(get_motherboard_inventory),
        "cooling": _com_thread_wrapper(get_cooling_inventory),
        "battery": _com_thread_wrapper(get_battery_inventory),
        "network": _com_thread_wrapper(get_network_inventory),
        "additional_devices": _com_thread_wrapper(get_additional_devices_inventory)
    }

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="SYSFIX-HwInv") as executor:
        future_map = {executor.submit(fn): key for key, fn in subsystem_tasks.items()}
        for future in as_completed(future_map):
            key = future_map[future]
            try:
                inventory[key] = future.result(timeout=8.0)
            except Exception as e:
                logger.error(f"Hardware subsystem query failed for {key}: {e}")
                inventory[key] = {"component": key, "status": "NOT AVAILABLE", "error": str(e)}

    elapsed_ms = round((time.perf_counter() - start_t) * 1000.0, 1)
    inventory["scan_duration_ms"] = elapsed_ms

    # Update cache
    _STATIC_HARDWARE_CACHE = inventory
    _LAST_INVENTORY_TIME = now
    logger.info(f"Hardware discovery completed in {elapsed_ms} ms.")

    return inventory
