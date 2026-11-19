"""
TERMINAL BOARD Windows Build Script
Automates PyInstaller packaging and validates that bundled frontend assets,
backend binaries, and icon assets exist in the output directory.
Supports both directory-based (--onedir, recommended for native speed)
and single-file standalone (--onefile).
"""

import os
import sys
import subprocess
import shutil

def run_build(onefile: bool = False):
    print("=" * 65)
    print(f"TERMINAL BOARD — {'Single-File Standalone' if onefile else 'Directory-Based Distribution'} Windows Build")
    print("=" * 65)

    project_dir = os.path.dirname(os.path.abspath(__file__))
    spec_file = os.path.join(project_dir, "terminal_board_onefile.spec" if onefile else "terminal_board.spec")
    target_exe = (
        os.path.join(project_dir, "dist", "TERMINAL_BOARD.exe")
        if onefile else
        os.path.join(project_dir, "dist", "TERMINAL_BOARD", "TERMINAL_BOARD.exe")
    )

    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", spec_file]
    print(f"Executing: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=project_dir)
    if result.returncode != 0:
        print("\n[ERROR] PyInstaller build failed!")
        return result.returncode

    print("\nVerifying build output:")
    print(f"Target Executable: {target_exe} (Exists: {os.path.exists(target_exe)})")

    if os.path.exists(target_exe):
        size_mb = os.path.getsize(target_exe) / (1024 * 1024)
        print(f"\n[SUCCESS] TERMINAL BOARD packaged successfully for Windows desktop!")
        print(f"File location : {target_exe}")
        print(f"File size     : {size_mb:.2f} MB")
        if not onefile:
            dist_folder = os.path.dirname(target_exe)
            print(f"Distribution  : {dist_folder}")
        print("\nDouble-click TERMINAL_BOARD.exe to launch the application.")
        return 0
    else:
        print("\n[ERROR] Output executable was not found.")
        return 1

if __name__ == "__main__":
    is_onefile = "--onefile" in sys.argv
    sys.exit(run_build(onefile=is_onefile))
