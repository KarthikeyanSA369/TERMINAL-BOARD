# -*- mode: python ; coding: utf-8 -*-
"""
TERMINAL BOARD — PyInstaller Single-File Build Specification
Bundles everything into a single standalone executable: dist/TERMINAL_BOARD.exe
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

block_cipher = None

project_dir = os.path.abspath(SPECPATH)
frontend_dir = os.path.join(project_dir, 'frontend')
assets_dir = os.path.join(project_dir, 'assets')

datas = [
    (frontend_dir, 'frontend'),
    (assets_dir, 'assets'),
]

# Ensure PyWebView, Python.NET, and CLR loader data files are bundled
datas += collect_data_files('pythonnet')
datas += collect_data_files('clr_loader')
datas += collect_data_files('webview')

binaries = []
binaries += collect_dynamic_libs('pythonnet')
binaries += collect_dynamic_libs('clr_loader')

hiddenimports = [
    'win32timezone',
    'win32evtlog',
    'win32evtlogutil',
    'win32con',
    'win32api',
    'winreg',
    'wmi',
    'psutil',
    'flask',
    'flask_cors',
    'webview',
    'sqlite3',
    'importlib.metadata',
    'clr',
    'pythonnet',
    'clr_loader',
    'pythoncom',
    'pywintypes'
]
hiddenimports += collect_submodules('backend')
hiddenimports += collect_submodules('webview')

icon_path = os.path.join(assets_dir, 'icon.ico')
if not os.path.exists(icon_path):
    icon_path = None

a = Analysis(
    ['app.py'],
    pathex=[project_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'scipy', 'torch', 'cv2', 'PyQt6', 'PySide6', 'kivy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='TERMINAL_BOARD',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path
)
