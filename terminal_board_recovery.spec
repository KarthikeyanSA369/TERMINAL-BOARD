# -*- mode: python ; coding: utf-8 -*-
"""
TERMINAL BOARD — Offline Recovery & Pre-Boot CLI PyInstaller Specification
Builds standalone console executable: dist/TERMINAL_BOARD_RECOVERY.exe
Compatible with Windows PE / WinRE / Recovery USB / Live Windows.
"""

import os
import sys

block_cipher = None

project_dir = os.path.abspath(SPECPATH)
assets_dir = os.path.join(project_dir, 'assets')
icon_path = os.path.join(assets_dir, 'icon.ico')
if not os.path.exists(icon_path):
    icon_path = None

hiddenimports = [
    'win32timezone',
    'win32con',
    'win32api',
    'winreg',
    'wmi',
    'ctypes',
    'ctypes.wintypes',
    'backend.core.subproc',
    'backend.core.cryptic'
]

a = Analysis(
    ['recovery_cli.py'],
    pathex=[project_dir],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'scipy', 'torch', 'cv2', 'PyQt6', 'PySide6', 'kivy', 'webview', 'flask', 'flask_cors', 'clr', 'pythonnet'],
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
    name='TERMINAL_BOARD_RECOVERY',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Crucial for WinPE cmd.exe environment
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path
)
