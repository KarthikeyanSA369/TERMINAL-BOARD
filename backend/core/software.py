"""
SYSFIX Installed Software Discovery Engine
Scans Windows Registry (HKLM, HKCU, 64-bit & 32-bit), system PATH, standard
application folders, and Python importlib.metadata to build a verified software
inventory without relying on hardcoded mock values.
"""

import os
import sys
import shutil
import subprocess
import winreg
from typing import Dict, Any, List, Optional

# Key developer tools to probe specifically
DEV_TOOLS_DEFINITIONS = [
    {"id": "vscode", "name": "Visual Studio Code", "bin": "code", "tag": "Development", "icon": "code"},
    {"id": "git", "name": "Git", "bin": "git", "tag": "Version Control", "icon": "git-branch"},
    {"id": "python", "name": "Python", "bin": "python", "tag": "Runtime", "icon": "terminal"},
    {"id": "nodejs", "name": "Node.js", "bin": "node", "tag": "Runtime", "icon": "hexagon"},
    {"id": "npm", "name": "Node Package Manager", "bin": "npm", "tag": "Package Manager", "icon": "box"},
    {"id": "powershell", "name": "PowerShell", "bin": "powershell", "tag": "Shell", "icon": "terminal-square"},
    {"id": "docker", "name": "Docker Desktop", "bin": "docker", "tag": "Container", "icon": "layers"},
    {"id": "rust", "name": "Rust Compiler", "bin": "rustc", "tag": "Development", "icon": "cpu"},
    {"id": "go", "name": "Go Programming Language", "bin": "go", "tag": "Development", "icon": "cpu"}
]

# Productivity suites definitions
OFFICE_APPS_DEFINITIONS = [
    {"id": "word", "name": "Microsoft Word", "exe": "WINWORD.EXE", "tag": "Productivity", "icon": "file-text"},
    {"id": "excel", "name": "Microsoft Excel", "exe": "EXCEL.EXE", "tag": "Productivity", "icon": "sheet"},
    {"id": "powerpoint", "name": "Microsoft PowerPoint", "exe": "POWERPNT.EXE", "tag": "Productivity", "icon": "presentation"},
    {"id": "acrobat", "name": "Adobe Acrobat Reader", "exe": "AcroRd32.exe", "tag": "Document Viewer", "icon": "file"}
]

def find_license_file(directory: str) -> Optional[str]:
    """Scan an installation directory for standard license files."""
    if not directory or not os.path.isdir(directory):
        return None
    candidates = ["LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE", "COPYING", "NOTICE", "TERMS.txt"]
    try:
        for root, dirs, files in os.walk(directory):
            # Limit depth
            depth = root[len(directory):].count(os.sep)
            if depth > 1:
                continue
            for f in files:
                if f in candidates or f.lower() in [c.lower() for c in candidates]:
                    return os.path.join(root, f)
    except Exception:
        pass
    return None

from backend.core.subproc import safe_run

def query_tool_version(exe_path: str, tool_id: str) -> Optional[str]:
    """Safely query tool version via native registry/metadata or safe hidden CLI."""
    if not exe_path or not os.path.exists(exe_path):
        return None

    # Native resolution for PowerShell without executing any shell process
    if tool_id == "powershell":
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\PowerShell\3\PowerShellEngine") as key:
                v, _ = winreg.QueryValueEx(key, "PowerShellVersion")
                if v:
                    return str(v).strip()
        except Exception:
            pass

        try:
            import win32api
            info = win32api.GetFileVersionInfo(exe_path, "\\")
            ms = info['FileVersionMS']
            ls = info['FileVersionLS']
            return f"{win32api.HIWORD(ms)}.{win32api.LOWORD(ms)}.{win32api.HIWORD(ls)}.{win32api.LOWORD(ls)}"
        except Exception:
            pass

    flag = "--version"
    if tool_id == "powershell":
        cmd = [exe_path, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", "$PSVersionTable.PSVersion.ToString()"]
    elif tool_id == "python":
        cmd = [exe_path, "--version"]
    else:
        cmd = [exe_path, flag]

    try:
        res = safe_run(cmd, capture_output=True, text=True, timeout=3)
        out = (res.stdout or res.stderr).strip()
        if out:
            return out.splitlines()[0].strip()
    except Exception:
        pass
    return None

def scan_registry_installed_apps() -> List[Dict[str, Any]]:
    """Enumerate installed software from Windows Registry."""
    apps = []
    seen_names = set()

    hives = [
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")
    ]

    for hive, subkey in hives:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                count = winreg.QueryInfoKey(key)[0]
                for i in range(count):
                    try:
                        app_guid = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, app_guid) as app_key:
                            def get_val(name):
                                try:
                                    val, _ = winreg.QueryValueEx(app_key, name)
                                    return str(val).strip()
                                except Exception:
                                    return None

                            display_name = get_val("DisplayName")
                            if not display_name or display_name in seen_names:
                                continue

                            # Filter out system hotfixes and patches
                            if get_val("SystemComponent") == "1" or display_name.startswith("Security Update"):
                                continue

                            seen_names.add(display_name)
                            version = get_val("DisplayVersion") or "Unknown"
                            publisher = get_val("Publisher") or "Unknown"
                            install_loc = get_val("InstallLocation") or ""
                            display_icon = get_val("DisplayIcon") or ""
                            uninstall_str = get_val("UninstallString") or ""
                            install_date = get_val("InstallDate") or "Unknown"

                            # Derive executable path
                            exe_path = ""
                            if display_icon and display_icon.lower().endswith(".exe") and os.path.exists(display_icon):
                                exe_path = display_icon
                            elif install_loc and os.path.isdir(install_loc):
                                # check top level .exe
                                for file in os.listdir(install_loc):
                                    if file.lower().endswith(".exe"):
                                        exe_path = os.path.join(install_loc, file)
                                        break

                            # Find license file if directory exists
                            lic_file = find_license_file(install_loc)

                            category = "Application"
                            if any(k in display_name.lower() for k in ["python", "node", "git", "studio", "compiler", "sdk", "dev"]):
                                category = "Development"
                            elif any(k in display_name.lower() for k in ["office", "word", "excel", "adobe", "reader", "pdf"]):
                                category = "Productivity"
                            elif any(k in display_name.lower() for k in ["driver", "runtime", "redistributable", "intel", "realtek", "nvidia", "amd"]):
                                category = "System / Driver"

                            apps.append({
                                "id": f"reg_{len(apps)}",
                                "name": display_name,
                                "version": version,
                                "publisher": publisher,
                                "install_location": install_loc or "Windows Registry Managed",
                                "exe_path": exe_path or "N/A",
                                "license_file": lic_file,
                                "install_date": install_date,
                                "category": category,
                                "source": "Windows Registry",
                                "installed": True
                            })
                    except Exception:
                        continue
        except Exception:
            continue

    return apps

def scan_developer_tools() -> List[Dict[str, Any]]:
    """Probe system PATH for essential developer tools."""
    tools = []
    for tool_def in DEV_TOOLS_DEFINITIONS:
        exe_path = shutil.which(tool_def["bin"])
        installed = exe_path is not None
        version = query_tool_version(exe_path, tool_def["id"]) if installed else "Not installed"
        
        install_dir = os.path.dirname(os.path.dirname(exe_path)) if exe_path else ""
        lic_file = find_license_file(install_dir) if install_dir else None

        publisher_map = {
            "vscode": "Microsoft Corporation",
            "git": "Git Community / Software Freedom Conservancy",
            "python": "Python Software Foundation",
            "nodejs": "OpenJS Foundation",
            "npm": "npm, Inc. / GitHub",
            "powershell": "Microsoft Corporation",
            "docker": "Docker, Inc.",
            "rust": "Rust Foundation",
            "go": "Google / Go Authors"
        }

        tools.append({
            "id": tool_def["id"],
            "name": tool_def["name"],
            "version": version or "Installed",
            "publisher": publisher_map.get(tool_def["id"], "Open Source / Community"),
            "install_location": install_dir or (os.path.dirname(exe_path) if exe_path else "Not installed"),
            "exe_path": exe_path or "Not installed",
            "license_file": lic_file,
            "category": tool_def["tag"],
            "icon": tool_def["icon"],
            "source": "System PATH / Environment",
            "installed": installed
        })

    return tools

def scan_office_applications() -> List[Dict[str, Any]]:
    """Probe for Microsoft Office and Adobe applications."""
    apps = []
    # Common paths for Office
    prog_files = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                  os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]

    office_dirs = [
        r"Microsoft Office\root\Office16",
        r"Microsoft Office\Office16",
        r"Microsoft Office\Office15",
        r"Microsoft Office\Office14"
    ]

    for office_def in OFFICE_APPS_DEFINITIONS:
        found_exe = None
        for p in prog_files:
            for od in office_dirs:
                candidate = os.path.join(p, od, office_def["exe"])
                if os.path.exists(candidate):
                    found_exe = candidate
                    break
            if found_exe:
                break

        # Check Adobe Acrobat
        if not found_exe and office_def["id"] == "acrobat":
            for p in prog_files:
                candidate = os.path.join(p, r"Adobe\Acrobat DC\Acrobat\Acrobat.exe")
                if os.path.exists(candidate):
                    found_exe = candidate
                    break

        installed = found_exe is not None
        version = "Unknown"
        if found_exe:
            try:
                import win32api
                info = win32api.GetFileVersionInfo(found_exe, "\\")
                ms = info['FileVersionMS']
                ls = info['FileVersionLS']
                version = f"{win32api.HIWORD(ms)}.{win32api.LOWORD(ms)}.{win32api.HIWORD(ls)}.{win32api.LOWORD(ls)}"
            except Exception:
                try:
                    # Query file version via PowerShell fallback with hidden window
                    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", f"(Get-Item '{found_exe}').VersionInfo.FileVersion"]
                    r = safe_run(cmd, capture_output=True, text=True, timeout=3)
                    if r.returncode == 0 and r.stdout.strip():
                        version = r.stdout.strip()
                except Exception:
                    pass

        apps.append({
            "id": office_def["id"],
            "name": office_def["name"],
            "version": version if installed else "Not installed",
            "publisher": "Microsoft Corporation" if "Microsoft" in office_def["name"] else "Adobe Inc.",
            "install_location": os.path.dirname(found_exe) if found_exe else "Not installed",
            "exe_path": found_exe or "Not installed",
            "license_file": None,
            "category": office_def["tag"],
            "icon": office_def["icon"],
            "source": "Standard Program Folders",
            "installed": installed
        })

    return apps

def get_fast_curated_tools() -> List[Dict[str, Any]]:
    """Instant heuristic probe of curated developer tools for immediate UI display without blocking."""
    tools = []
    publisher_map = {
        "vscode": "Microsoft Corporation",
        "git": "Git Community / Software Freedom Conservancy",
        "python": "Python Software Foundation",
        "nodejs": "OpenJS Foundation",
        "npm": "npm, Inc. / GitHub",
        "powershell": "Microsoft Corporation",
        "docker": "Docker, Inc.",
        "rust": "Rust Foundation",
        "go": "Google / Go Authors"
    }
    for tool_def in DEV_TOOLS_DEFINITIONS:
        exe_path = shutil.which(tool_def["bin"])
        installed = exe_path is not None
        tools.append({
            "id": tool_def["id"],
            "name": tool_def["name"],
            "version": "Installed" if installed else "Not installed",
            "publisher": publisher_map.get(tool_def["id"], "Open Source / Community"),
            "install_location": os.path.dirname(exe_path) if exe_path else "Not installed",
            "exe_path": exe_path or "Not installed",
            "license_file": None,
            "category": tool_def["tag"],
            "icon": tool_def["icon"],
            "source": "System PATH / Environment",
            "installed": installed
        })
    return tools

def get_installed_software_inventory() -> Dict[str, Any]:
    """Compile comprehensive software inventory combining registry, dev tools, and office suites."""
    dev_tools = scan_developer_tools()
    office_apps = scan_office_applications()
    registry_apps = scan_registry_installed_apps()

    # Build primary curated list for the Home Dashboard
    curated_cards = []
    # Add all dev tools
    curated_cards.extend(dev_tools)
    # Add office apps
    curated_cards.extend(office_apps)

    return {
        "curated_tools": curated_cards,
        "all_registry_software": registry_apps,
        "total_detected": len([t for t in curated_cards if t["installed"]]) + len(registry_apps),
        "total_scanned": len(curated_cards) + len(registry_apps)
    }
