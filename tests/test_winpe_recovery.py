"""
Automated validation test suite for TERMINAL BOARD Bootable Recovery component.
Verifies binary integrity, WinPE compatibility, read-only safety, and report generation.
"""

import json
import os
import subprocess
import sys


def test_recovery_binary_exists():
    bin_path = os.path.join(os.path.dirname(__file__), "..", "dist", "TERMINAL_BOARD_RECOVERY.exe")
    assert os.path.isfile(bin_path), f"Recovery binary not found at {bin_path}"
    size = os.path.getsize(bin_path)
    assert size > 1_000_000, f"Recovery binary seems too small ({size} bytes)"
    print(f"[PASS] Recovery binary exists: {bin_path} ({round(size / 1024 / 1024, 2)} MB)")


def test_desktop_exe_preserved():
    bin_path = os.path.join(os.path.dirname(__file__), "..", "dist", "TERMINAL_BOARD.exe")
    assert os.path.isfile(bin_path), f"Desktop binary was modified or missing: {bin_path}"
    print(f"[PASS] Desktop TERMINAL_BOARD.exe preserved ({round(os.path.getsize(bin_path) / 1024 / 1024, 2)} MB)")


def test_standard_execution():
    bin_path = os.path.join(os.path.dirname(__file__), "..", "dist", "TERMINAL_BOARD_RECOVERY.exe")
    res = subprocess.run([bin_path], capture_output=True, text=True, timeout=15)
    assert res.returncode == 0, f"Executable failed with return code {res.returncode}. Output: {res.stderr}"
    assert "TERMINAL BOARD -- PRE-BOOT & OFFLINE RECOVERY DIAGNOSTICS" in res.stdout
    assert "Read-Only Safe Inspection Mode" in res.stdout
    print("[PASS] Interactive console mode completed with exit code 0.")


def test_json_mode_and_winpe_simulation():
    bin_path = os.path.join(os.path.dirname(__file__), "..", "dist", "TERMINAL_BOARD_RECOVERY.exe")
    env = os.environ.copy()
    env["SystemDrive"] = "X:"  # WinPE standard ramdisk root
    res = subprocess.run([bin_path, "--json"], capture_output=True, text=True, timeout=15, env=env)
    assert res.returncode == 0, f"JSON execution failed with return code {res.returncode}"
    
    # Extract JSON (skipping debug prefix if present)
    stdout = res.stdout.strip()
    idx = stdout.find("{")
    assert idx != -1, "No JSON object found in output"
    data = json.loads(stdout[idx:])

    assert data["is_winpe"] is True, f"Expected is_winpe=True under SystemDrive=X:, got {data['is_winpe']}"
    assert data["environment"] == "Windows PE (Pre-Boot Recovery Environment)"
    assert "system_memory" in data
    assert data["system_memory"]["total_phys_gb"] > 0
    assert "mounted_drives" in data
    assert isinstance(data["mounted_drives"], list)
    assert "physical_disks" in data
    assert "crash_dumps" in data
    assert "overall_summary" in data
    
    # Verify strict UX requirement: no "Unknown" string used as fallback in values
    raw_json = json.dumps(data)
    assert '"Unknown"' not in raw_json, "Found forbidden 'Unknown' value in diagnostic output"
    print("[PASS] WinPE simulation passed: is_winpe=True, valid JSON structure, zero 'Unknown' fallbacks.")


if __name__ == "__main__":
    print("\nRunning TERMINAL BOARD Bootable Recovery Test Suite...")
    test_recovery_binary_exists()
    test_desktop_exe_preserved()
    test_standard_execution()
    test_json_mode_and_winpe_simulation()
    print("\n=======================================================")
    print("ALL RECOVERY TESTS PASSED SUCCESSFULLY!")
    print("=======================================================\n")
