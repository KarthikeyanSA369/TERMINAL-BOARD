# -*- mode: python ; coding: utf-8 -*-
"""
SYSFIX — PyInstaller Build Specification
Bundles the Python runtime, backend monitoring modules, and HTML5/CSS3 frontend assets
into a standalone Windows desktop executable.
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

project_dir = os.path.abspath(SPECPATH)
frontend_dir = os.path.join(project_dir, 'frontend')

# Collect frontend static files
datas = [
    (frontend_dir, 'frontend'),
]

# Hidden imports required for dynamic dispatch & Windows APIs
hiddenimports = [
    'win32timezone',
    'win32evtlog',
    'win32evtlogutil',
    'win32con',
    'winreg',
    'wmi',
    'psutil',
    'flask',
    'flask_cors',
    'webview',
    'sqlite3',
    'importlib.metadata'
]
hiddenimports += collect_submodules('backend')

a = Analysis(
    ['app.py'],
    pathex=[project_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'torch', 'cv2'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SYSFIX',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Desktop GUI mode without background terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SYSFIX',
)
