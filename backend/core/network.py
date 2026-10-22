"""
SYSFIX Network Diagnostics Engine
Provides local network diagnostics without external API keys:
- Internet connectivity check
- DNS resolution & latency
- Default gateway reachability
- Ping latency & sampled packet loss
- Network interface / adapter status
- Localhost dev server & port availability
- Distinguishes Local vs DNS vs Remote endpoint failures
"""

import socket
import subprocess
import time
import re
import psutil
from typing import Dict, Any, List, Optional

def check_dns_resolution(host: str = "cloudflare.com") -> Dict[str, Any]:
    """Test DNS lookup time and IP resolution."""
    start = time.perf_counter()
    try:
        ip = socket.gethostbyname(host)
        duration_ms = (time.perf_counter() - start) * 1000.0
        return {
            "success": True,
            "host": host,
            "resolved_ip": ip,
            "latency_ms": round(duration_ms, 2),
            "status": "DNS Working"
        }
    except Exception as e:
        duration_ms = (time.perf_counter() - start) * 1000.0
        return {
            "success": False,
            "host": host,
            "resolved_ip": None,
            "latency_ms": round(duration_ms, 2),
            "status": f"DNS Failed: {str(e)}"
        }

test_dns_resolution = check_dns_resolution

from backend.core.subproc import safe_run

def get_default_gateway() -> Optional[str]:
    """Find default gateway IP using native WMI, with safe route print or hidden PowerShell fallback."""
    try:
        import wmi
        c = wmi.WMI()
        for nic in c.Win32_NetworkAdapterConfiguration(IPEnabled=True):
            if nic.DefaultIPGateway:
                for g in nic.DefaultIPGateway:
                    if g and g != "0.0.0.0" and "." in g:
                        return str(g)
    except Exception:
        pass

    # Method 2: route print 0.0.0.0 via safe hidden subprocess
    try:
        res = safe_run(["route", "print", "0.0.0.0"], capture_output=True, text=True, timeout=4)
        if res.returncode == 0 and res.stdout:
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                    gateway = parts[2]
                    if gateway and gateway != "0.0.0.0" and "." in gateway:
                        return gateway
    except Exception:
        pass

    # Method 3: PowerShell fallback strictly using safe hidden non-interactive runner
    try:
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
               "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Select-Object -First 1).NextHop"]
        res = safe_run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            gateway = res.stdout.strip()
            if gateway and gateway != "0.0.0.0":
                return gateway
    except Exception:
        pass
    return None

def ping_host(host: str, count: int = 4, timeout_sec: int = 2) -> Dict[str, Any]:
    """Ping a host and calculate latency and sampled packet loss."""
    cmd = ["ping", "-n", str(count), "-w", str(timeout_sec * 1000), host]
    try:
        res = safe_run(cmd, capture_output=True, text=True, timeout=(count * timeout_sec) + 3)
        out = res.stdout

        # Extract packet loss
        loss_match = re.search(r"\((\d+)%\s*loss\)", out)
        packet_loss = int(loss_match.group(1)) if loss_match else (0 if res.returncode == 0 else 100)

        # Extract latency
        min_ms, max_ms, avg_ms = None, None, None
        time_matches = re.findall(r"(?:time[=<]|Average = )(\d+)ms", out)
        if time_matches:
            latencies = [float(m) for m in time_matches]
            avg_ms = round(sum(latencies) / len(latencies), 1)
            min_ms = round(min(latencies), 1)
            max_ms = round(max(latencies), 1)

        reachable = packet_loss < 100

        return {
            "reachable": reachable,
            "host": host,
            "packet_loss_percent": packet_loss,
            "avg_latency_ms": avg_ms if avg_ms is not None else ("Timeout" if not reachable else 0.0),
            "min_latency_ms": min_ms,
            "max_latency_ms": max_ms,
            "raw_output": out.strip()
        }
    except subprocess.TimeoutExpired:
        return {
            "reachable": False,
            "host": host,
            "packet_loss_percent": 100,
            "avg_latency_ms": "Timeout",
            "min_latency_ms": None,
            "max_latency_ms": None,
            "raw_output": "Ping command timed out."
        }
    except Exception as e:
        return {
            "reachable": False,
            "host": host,
            "packet_loss_percent": 100,
            "avg_latency_ms": "Error",
            "min_latency_ms": None,
            "max_latency_ms": None,
            "raw_output": str(e)
        }

def get_network_interfaces() -> List[Dict[str, Any]]:
    """Enumerate network adapters and addresses."""
    interfaces = []
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()

    for iface_name, iface_addrs in addrs.items():
        stat = stats.get(iface_name)
        is_up = stat.isup if stat else False
        speed = stat.speed if stat else 0

        ipv4 = None
        mac = None

        for addr in iface_addrs:
            if addr.family == socket.AF_INET:
                ipv4 = addr.address
            elif hasattr(psutil, "AF_LINK") and addr.family == psutil.AF_LINK:
                mac = addr.address

        # Filter out loopback or virtual inactive adapters
        if "Loopback" in iface_name or not ipv4:
            continue

        interfaces.append({
            "name": iface_name,
            "ipv4": ipv4,
            "mac": mac or "N/A",
            "is_up": is_up,
            "speed_mbps": speed,
            "status": "Connected" if is_up else "Disconnected"
        })

    return interfaces

def check_localhost_ports(ports: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """Scan configured common dev server ports on localhost (127.0.0.1)."""
    if ports is None:
        ports = [3000, 5000, 5173, 8000, 8080, 8888]

    results = []
    for port in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        is_open = False
        try:
            res = s.connect_ex(("127.0.0.1", port))
            is_open = (res == 0)
        except Exception:
            is_open = False
        finally:
            s.close()

        service_label = {
            3000: "React / Node Dev Server",
            5000: "Flask / Python API",
            5173: "Vite Dev Server",
            8000: "Django / FastAPI / Python Server",
            8080: "Java / Web Proxy",
            8888: "Jupyter / Local Server"
        }.get(port, "Custom Dev Port")

        results.append({
            "port": port,
            "is_active": is_open,
            "service": service_label,
            "status": "Active / Listening" if is_open else "Closed / Inactive"
        })

    return results

def run_comprehensive_network_diagnosis() -> Dict[str, Any]:
    """
    Executes a complete local diagnostic and root cause analysis:
    Distinguishes:
    - No local adapter connection (Local failure)
    - Gateway unreachable (Local network / router failure)
    - DNS failure while IP reachable (DNS failure)
    - Gateway OK but external IP timeout (ISP / WAN failure)
    - All OK (Healthy)
    """
    interfaces = get_network_interfaces()
    has_active_adapter = any(i["is_up"] for i in interfaces)

    gateway_ip = get_default_gateway()
    gateway_ping = ping_host(gateway_ip, count=2) if gateway_ip else {"reachable": False, "packet_loss_percent": 100}

    # Ping cloudflare IP directly to isolate DNS
    ip_ping = ping_host("1.1.1.1", count=3)
    dns_test = test_dns_resolution("cloudflare.com")

    # Local dev ports
    dev_ports = check_localhost_ports()

    # Diagnostic reasoning
    if not has_active_adapter:
        health = "Critical"
        root_cause = "No active network adapter detected."
        recommendation = "Verify Ethernet cable is plugged in or Wi-Fi is enabled."
    elif gateway_ip and not gateway_ping.get("reachable"):
        health = "Critical"
        root_cause = f"Default gateway ({gateway_ip}) is unreachable."
        recommendation = "Check local Wi-Fi router, cables, or local network DHCP configuration."
    elif ip_ping.get("reachable") and not dns_test.get("success"):
        health = "Warning"
        root_cause = "Direct IP connection succeeded, but domain name resolution (DNS) failed."
        recommendation = "Flush DNS cache (ipconfig /flushdns) or configure secondary DNS (1.1.1.1 or 8.8.8.8)."
    elif not ip_ping.get("reachable"):
        health = "Warning"
        root_cause = "Local network is up, but external Internet hosts timed out."
        recommendation = "Verify WAN / Internet service provider connectivity or proxy settings."
    else:
        health = "Healthy"
        root_cause = "All network layers operating normally."
        recommendation = "Network connectivity and DNS resolution are fully functional."

    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "health_status": health,
        "root_cause": root_cause,
        "recommendation": recommendation,
        "is_connected": ip_ping.get("reachable") and dns_test.get("success"),
        "gateway_ip": gateway_ip or "Not Found",
        "gateway_reachable": gateway_ping.get("reachable", False),
        "gateway_ping": gateway_ping,
        "internet_ping": ip_ping,
        "dns_resolution": dns_test,
        "adapters": interfaces,
        "dev_ports": dev_ports
    }
