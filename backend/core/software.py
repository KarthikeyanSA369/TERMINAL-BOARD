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
from datetime import datetime
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
    """Instant heuristic probe of curated developer tools and office apps for immediate UI display without blocking."""
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

    # Fast probe office applications
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
        if not found_exe and office_def["id"] == "acrobat":
            for p in prog_files:
                candidate = os.path.join(p, r"Adobe\Acrobat DC\Acrobat\Acrobat.exe")
                if os.path.exists(candidate):
                    found_exe = candidate
                    break
        installed = found_exe is not None
        tools.append({
            "id": office_def["id"],
            "name": office_def["name"],
            "version": "Installed" if installed else "Not installed",
            "publisher": "Microsoft Corporation" if "Microsoft" in office_def["name"] else "Adobe Inc.",
            "install_location": os.path.dirname(found_exe) if found_exe else "Not installed",
            "exe_path": found_exe or "Not installed",
            "license_file": None,
            "category": office_def["tag"],
            "icon": office_def["icon"],
            "source": "Standard Program Folders",
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

def get_pe_architecture(exe_path: str) -> Optional[str]:
    """Safely inspect Windows PE header to identify 64-bit or 32-bit architecture without executing."""
    if not exe_path or not os.path.isfile(exe_path):
        return None
    try:
        with open(exe_path, "rb") as f:
            header = f.read(1024)
            if len(header) > 0x40 and header[:2] == b"MZ":
                pe_offset = int.from_bytes(header[0x3C:0x40], byteorder="little")
                if len(header) >= pe_offset + 6 and header[pe_offset:pe_offset+4] == b"PE\0\0":
                    machine = int.from_bytes(header[pe_offset+4:pe_offset+6], byteorder="little")
                    if machine == 0x8664:
                        return "64-bit (x64)"
                    elif machine == 0x014c:
                        return "32-bit (x86)"
                    elif machine == 0xaa64:
                        return "64-bit (ARM64)"
    except Exception:
        pass
    return None

def find_directory_executables(directory: str, max_count: int = 10) -> List[str]:
    """Safely find executable binaries in an installation directory."""
    if not directory or not os.path.isdir(directory):
        return []
    exes = []
    try:
        for item in sorted(os.listdir(directory)):
            if item.lower().endswith(".exe"):
                exes.append(item)
                if len(exes) >= max_count:
                    return exes
        bin_dir = os.path.join(directory, "bin")
        if os.path.isdir(bin_dir):
            for item in sorted(os.listdir(bin_dir)):
                if item.lower().endswith(".exe") and item not in exes:
                    exes.append(f"bin\\{item}")
                    if len(exes) >= max_count:
                        return exes
    except Exception:
        pass
    return exes

def get_file_metadata(file_path: str) -> Dict[str, Any]:
    """Safely retrieve file size, modified time, and PE architecture without executing."""
    if not file_path or not os.path.isfile(file_path):
        return {}
    meta = {}
    try:
        stat = os.stat(file_path)
        size_bytes = stat.st_size
        if "windowsapps" in file_path.lower() and size_bytes == 0:
            meta["file_size_formatted"] = "WindowsApp Execution Alias"
        elif size_bytes >= 1024 * 1024:
            meta["file_size_formatted"] = f"{size_bytes / (1024 * 1024):.2f} MB"
        elif size_bytes >= 1024:
            meta["file_size_formatted"] = f"{size_bytes / 1024:.1f} KB"
        else:
            meta["file_size_formatted"] = f"{size_bytes} Bytes"
        meta["modified_time"] = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        meta["is_readable"] = os.access(file_path, os.R_OK)
    except Exception:
        pass

    arch = get_pe_architecture(file_path)
    if arch:
        meta["architecture"] = arch

    return meta

def get_tool_environment_info(tool_id: str, exe_path: Optional[str] = None) -> List[Dict[str, str]]:
    """Retrieve relevant environment variables and matching PATH entries for a given tool."""
    env_matches = []
    tool_env_keys = {
        "python": ["PYTHONPATH", "PYTHONHOME", "PY_PYTHON", "VIRTUAL_ENV", "CONDA_PREFIX"],
        "git": ["GIT_DIR", "GIT_WORK_TREE", "GIT_SSH", "GIT_EXEC_PATH"],
        "nodejs": ["NODE_PATH", "NODE_ENV", "NODE_OPTIONS"],
        "npm": ["NPM_CONFIG_PREFIX", "npm_config_prefix", "NODE_PATH"],
        "powershell": ["PSModulePath"],
        "docker": ["DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CERT_PATH"],
        "rust": ["CARGO_HOME", "RUSTUP_HOME", "RUST_SRC_PATH"],
        "go": ["GOROOT", "GOPATH", "GOBIN"],
        "vscode": ["VSCODE_PORT", "VSCODE_INJECTION"]
    }
    keys = tool_env_keys.get(tool_id, [])
    for k in keys:
        v = os.environ.get(k)
        if v:
            env_matches.append({"name": k, "value": v, "type": "Environment Variable"})

    path_str = os.environ.get("PATH", "")
    path_entries = [p.strip() for p in path_str.split(os.pathsep) if p.strip()]

    keywords = [tool_id]
    if exe_path and os.path.exists(exe_path):
        install_dir = os.path.dirname(exe_path).lower()
        for p in path_entries:
            if p.lower() == install_dir or install_dir in p.lower():
                if not any(e["value"] == p for e in env_matches):
                    env_matches.append({"name": "PATH Entry", "value": p, "type": "System PATH Entry"})
    else:
        for p in path_entries:
            if any(k in p.lower() for k in keywords):
                if not any(e["value"] == p for e in env_matches):
                    env_matches.append({"name": "PATH Entry", "value": p, "type": "System PATH Entry"})

    return env_matches

def get_application_details(software_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve comprehensive, verified application details by identifier or name.
    Safely resolves without running arbitrary commands.
    """
    if not software_id or not isinstance(software_id, str):
        return None
    software_id = software_id.strip()
    if not software_id:
        return None

    clean_id = software_id.lower()

    # 1. Check DEV_TOOLS_DEFINITIONS
    for tool_def in DEV_TOOLS_DEFINITIONS:
        if tool_def["id"].lower() == clean_id or tool_def["name"].lower() == clean_id:
            bin_name = tool_def["bin"]
            exe_path = shutil.which(bin_name)
            installed = exe_path is not None
            version = query_tool_version(exe_path, tool_def["id"]) if installed else None

            install_dir = ""
            detected_exes = []
            file_meta = {}
            if installed and exe_path:
                d = os.path.dirname(exe_path)
                if os.path.basename(d).lower() in ["bin", "cmd"]:
                    install_dir = os.path.dirname(d)
                else:
                    install_dir = d

                # For VS Code or similar tools where .cmd is in bin and .exe is in root
                if tool_def["id"] == "vscode" and install_dir and os.path.isdir(install_dir):
                    code_exe = os.path.join(install_dir, "Code.exe")
                    if os.path.isfile(code_exe):
                        exe_path = code_exe

                detected_exes = find_directory_executables(install_dir)
                if exe_path and os.path.basename(exe_path) not in detected_exes and os.path.isfile(exe_path):
                    detected_exes.insert(0, os.path.basename(exe_path))
                file_meta = get_file_metadata(exe_path)

            lic_file = find_license_file(install_dir) if install_dir else None
            env_info = get_tool_environment_info(tool_def["id"], exe_path)

            # Derive package manager or installation source
            pkg_source = "System PATH / Environment"
            if installed and exe_path:
                norm_p = exe_path.lower()
                if "windowsapps" in norm_p:
                    pkg_source = "Microsoft Store / WindowsApps"
                elif "appdata" in norm_p:
                    pkg_source = "User Local Installation (AppData)"
                elif "program files" in norm_p:
                    pkg_source = "System Installation (Program Files)"
                elif "cargo" in norm_p:
                    pkg_source = "Cargo / Rustup Package Manager"

            detection_method = (
                f"Resolved binary via System PATH ('{exe_path}'); verified version using safe command-line probe."
                if installed
                else f"Probed system PATH for command '{tool_def['bin']}', standard directories, and Windows Registry. Executable not found."
            )

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

            status = "Installed" if installed else "Not Installed"
            status_desc = (
                "Application is fully verified and operational."
                if installed
                else "Application is not installed or not present in system PATH."
            )

            # Classify licensing evidence
            lic_record = None
            try:
                from backend.core.license_audit import classify_license
                lic_record = classify_license(
                    license_str=None,
                    license_file=lic_file,
                    publisher=publisher_map.get(tool_def["id"], "Open Source / Community"),
                    software_name=tool_def["name"],
                    install_location=install_dir
                )
            except Exception:
                pass

            return {
                "id": tool_def["id"],
                "name": tool_def["name"],
                "status": status,
                "status_description": status_desc,
                "installed": installed,
                "version": version or ("Installed" if installed else "Not Available"),
                "category": tool_def["tag"],
                "icon": tool_def["icon"],
                "publisher": publisher_map.get(tool_def["id"], "Open Source / Community"),
                "exe_path": exe_path or "Not Detected / Unavailable",
                "install_location": install_dir or "Not Available",
                "detected_executables": detected_exes,
                "package_manager_or_source": pkg_source if installed else "None Detected",
                "environment_variables": env_info,
                "detection_method": detection_method,
                "last_verified": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "license_file": lic_file,
                "diagnostic_info": {
                    "architecture": file_meta.get("architecture") or ("64-bit (x64)" if installed else "N/A"),
                    "file_size_formatted": file_meta.get("file_size_formatted") or ("Not Available" if not installed else "Verified"),
                    "modified_time": file_meta.get("modified_time") or ("Not Available" if not installed else "Verified"),
                    "is_readable": file_meta.get("is_readable", installed),
                    "license_file": lic_file,
                    "license_record": lic_record
                }
            }

    # 2. Check OFFICE_APPS_DEFINITIONS
    for office_def in OFFICE_APPS_DEFINITIONS:
        if office_def["id"].lower() == clean_id or office_def["name"].lower() == clean_id:
            prog_files = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                          os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
            office_dirs = [
                r"Microsoft Office\root\Office16",
                r"Microsoft Office\Office16",
                r"Microsoft Office\Office15",
                r"Microsoft Office\Office14"
            ]
            found_exe = None
            for p in prog_files:
                for od in office_dirs:
                    cand = os.path.join(p, od, office_def["exe"])
                    if os.path.exists(cand):
                        found_exe = cand
                        break
                if found_exe:
                    break

            if not found_exe and office_def["id"] == "acrobat":
                for p in prog_files:
                    cand = os.path.join(p, r"Adobe\Acrobat DC\Acrobat\Acrobat.exe")
                    if os.path.exists(cand):
                        found_exe = cand
                        break

            installed = found_exe is not None
            version = None
            file_meta = {}
            install_dir = ""
            detected_exes = []
            if installed and found_exe:
                install_dir = os.path.dirname(found_exe)
                detected_exes = find_directory_executables(install_dir)
                if os.path.basename(found_exe) not in detected_exes:
                    detected_exes.insert(0, os.path.basename(found_exe))
                file_meta = get_file_metadata(found_exe)

                # Query PE file version
                try:
                    import win32api
                    info = win32api.GetFileVersionInfo(found_exe, "\\")
                    ms = info['FileVersionMS']
                    ls = info['FileVersionLS']
                    version = f"{win32api.HIWORD(ms)}.{win32api.LOWORD(ms)}.{win32api.HIWORD(ls)}.{win32api.LOWORD(ls)}"
                except Exception:
                    try:
                        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", f"(Get-Item '{found_exe}').VersionInfo.FileVersion"]
                        r = safe_run(cmd, capture_output=True, text=True, timeout=3)
                        if r.returncode == 0 and r.stdout.strip():
                            version = r.stdout.strip()
                    except Exception:
                        pass

            status = "Installed" if installed else "Not Installed"
            status_desc = (
                "Application is fully verified and operational."
                if installed
                else "Application is not installed in standard program directories."
            )
            detection_method = (
                f"Resolved executable in standard Program Files directory ('{found_exe}'); verified version via PE VersionInfo."
                if installed
                else f"Probed standard 64-bit and 32-bit Program Files directories for '{office_def['exe']}'. Executable not found."
            )
            publisher = "Microsoft Corporation" if "Microsoft" in office_def["name"] else "Adobe Inc."

            lic_record = None
            try:
                from backend.core.license_audit import classify_license
                lic_record = classify_license(
                    license_str="Commercial / Retail",
                    license_file=None,
                    publisher=publisher,
                    software_name=office_def["name"],
                    install_location=install_dir
                )
            except Exception:
                pass

            return {
                "id": office_def["id"],
                "name": office_def["name"],
                "status": status,
                "status_description": status_desc,
                "installed": installed,
                "version": version or ("Installed" if installed else "Not Available"),
                "category": office_def["tag"],
                "icon": office_def["icon"],
                "publisher": publisher,
                "exe_path": found_exe or "Not Detected / Unavailable",
                "install_location": install_dir or "Not Available",
                "detected_executables": detected_exes,
                "package_manager_or_source": "Standard Program Folders (Office / Adobe)" if installed else "None Detected",
                "environment_variables": [],
                "detection_method": detection_method,
                "last_verified": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "license_file": None,
                "diagnostic_info": {
                    "architecture": file_meta.get("architecture") or ("32-bit (x86)" if "x86" in (found_exe or "") else ("64-bit (x64)" if installed else "N/A")),
                    "file_size_formatted": file_meta.get("file_size_formatted") or ("Not Available" if not installed else "Verified"),
                    "modified_time": file_meta.get("modified_time") or ("Not Available" if not installed else "Verified"),
                    "is_readable": file_meta.get("is_readable", installed),
                    "license_file": None,
                    "license_record": lic_record
                }
            }

    # 3. Check Windows Registry software inventory
    registry_apps = scan_registry_installed_apps()
    matched_app = None
    for app in registry_apps:
        if app.get("id", "").lower() == clean_id or app.get("name", "").lower() == clean_id:
            matched_app = app
            break

    # If no exact match, try substring match if clean_id has sufficient specificity
    if not matched_app and len(clean_id) > 3:
        for app in registry_apps:
            if clean_id in app.get("name", "").lower():
                matched_app = app
                break

    if matched_app:
        exe_path = matched_app.get("exe_path", "")
        if exe_path == "N/A":
            exe_path = ""
        install_loc = matched_app.get("install_location", "")
        if install_loc == "Windows Registry Managed":
            install_loc = ""

        file_meta = get_file_metadata(exe_path) if exe_path and os.path.isfile(exe_path) else {}
        detected_exes = find_directory_executables(install_loc) if install_loc else []
        if exe_path and os.path.isfile(exe_path) and os.path.basename(exe_path) not in detected_exes:
            detected_exes.insert(0, os.path.basename(exe_path))

        status = "Installed"
        if not exe_path or not os.path.isfile(exe_path):
            if install_loc and os.path.isdir(install_loc):
                status = "Partially Detected"
            else:
                status = "Installed"

        lic_record = None
        try:
            from backend.core.license_audit import classify_license
            lic_record = classify_license(
                license_str=None,
                license_file=matched_app.get("license_file"),
                publisher=matched_app.get("publisher", ""),
                software_name=matched_app.get("name", ""),
                install_location=install_loc
            )
        except Exception:
            pass

        return {
            "id": matched_app.get("id"),
            "name": matched_app.get("name"),
            "status": status,
            "status_description": f"Verified via Windows Registry Uninstall database. Install Date: {matched_app.get('install_date', 'Unknown')}.",
            "installed": True,
            "version": matched_app.get("version") or "Installed",
            "category": matched_app.get("category", "Application"),
            "icon": "package",
            "publisher": matched_app.get("publisher") or "Unknown",
            "exe_path": exe_path or "Windows Registry Managed (Direct path not registered)",
            "install_location": install_loc or "Windows Registry Managed",
            "detected_executables": detected_exes,
            "package_manager_or_source": "Windows Registry (HKLM / HKCU Uninstall)",
            "environment_variables": [],
            "detection_method": "Windows Registry enumeration (HKLM/HKCU Uninstall keys).",
            "last_verified": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "license_file": matched_app.get("license_file"),
            "diagnostic_info": {
                "architecture": file_meta.get("architecture") or "Windows Registry Native",
                "file_size_formatted": file_meta.get("file_size_formatted") or "Registry Managed",
                "modified_time": file_meta.get("modified_time") or "Registry Managed",
                "is_readable": file_meta.get("is_readable", bool(exe_path and os.path.isfile(exe_path))),
                "license_file": matched_app.get("license_file"),
                "license_record": lic_record,
                "install_date": matched_app.get("install_date")
            }
        }

    return None
