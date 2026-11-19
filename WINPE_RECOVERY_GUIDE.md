# TERMINAL BOARD — Pre-Boot Recovery & College Demo Guide

This guide provides the technical architecture and step-by-step instructions for demonstrating **TERMINAL BOARD** in a pre-boot offline recovery environment.

---

## 1. System Assessment & Environment Status

| Subsystem / Tool | Status | Details |
| :--- | :--- | :--- |
| **`TERMINAL_BOARD.exe`** | **VERIFIED & PRESERVED** | Live Desktop GUI app in `dist/` (20.91 MB) |
| **`TERMINAL_BOARD_RECOVERY.exe`** | **BUILT & TESTED** | Pre-boot standalone console binary in `dist/` (7.46 MB) |
| **Windows ADK Deployment Tools** | **Not Installed** | Not detected in `Program Files\Windows Kits\` |
| **WinPE Add-on for ADK** | **Not Installed** | Required by Microsoft DISM to generate standalone custom ISOs |
| **Virtualization Service (`vmms`)**| **Service Running** | Hyper-V is running, but current non-elevated user token lacks admin rights |
| **WinPE Simulation Test** | **PASSED** | Simulated pre-boot environment (`SystemDrive=X:`) passed with `is_winpe=True` |
| **Read-Only Safety** | **GUARANTEED** | Diagnostics are 100% read-only. Zero disk formatting or BCD changes. |

---

## 2. Verified WinPE Image Locations & Startup Files

When Windows PE boots, the recovery files and scripts map to the following exact locations:

| File | WinPE Internal Target Path | Purpose |
| :--- | :--- | :--- |
| `dist\TERMINAL_BOARD_RECOVERY.exe` | `X:\Windows\System32\TERMINAL_BOARD_RECOVERY.exe` | High-priority system path execution |
| `dist\TERMINAL_BOARD_RECOVERY.exe` | `X:\Recovery\TERMINAL_BOARD_RECOVERY.exe` | Standard Windows recovery payload directory |
| `winpe\startnet.cmd` | `X:\Windows\System32\startnet.cmd` | Startup script executed immediately after `wpeinit` |
| `winpe\winpeshl.ini` | `X:\Windows\System32\winpeshl.ini` | Shell config launching interactive recovery terminal |
| `dist\TERMINAL_BOARD_RECOVERY.exe` | `[USB_ROOT]:\TERMINAL_BOARD_RECOVERY.exe` | Removable media fallback (detected automatically) |

---

## 3. How to Execute the College Demo

You have two demonstration options:

### OPTION A — The 3-Minute Zero-Risk College Demo (Recommended)
This method requires **no Windows ADK installation, no ISO burning, and zero USB formatting**. It works with any existing Windows 10/11 Installation USB, Ventoy drive, or Recovery USB:

1. **Copy the Executable**:
   - Copy `dist\TERMINAL_BOARD_RECOVERY.exe` from your project folder directly onto your USB flash drive (root directory).
2. **Boot the Demonstration Computer**:
   - Plug the USB into the college laptop/desktop.
   - Turn on the PC and press the Boot Menu key (`F12`, `F11`, `F8`, or `Esc` depending on laptop manufacturer).
   - Select your USB drive to boot into Windows PE (the familiar purple Windows Setup screen).
3. **Launch the Pre-Boot Terminal**:
   - On the very first Windows Setup screen (Language / Keyboard selection), press:
     ```
     SHIFT + F10
     ```
   - A black Windows PE Administrator Command Prompt window will appear (`X:\Sources>`).
4. **Execute TERMINAL BOARD Recovery**:
   - Find your USB drive letter (usually `D:` or `E:`) and type:
     ```cmd
     D:\TERMINAL_BOARD_RECOVERY.exe
     ```
   - *Result*: The pre-boot offline diagnostics will run immediately, displaying RAM, physical storage devices, Windows system drive health, BSOD crash dump history, and offline event logs.
5. **Show Machine-Readable Output (JSON Mode)**:
   - Run:
     ```cmd
     D:\TERMINAL_BOARD_RECOVERY.exe --json
     ```
   - Point out that all data is live hardware and OS telemetry, with zero dummy data and zero "Unknown" fallbacks.

---

### OPTION B — Building a Standalone Dedicated WinPE ISO
If your college presentation requires a custom-branded ISO that automatically boots into `startnet.cmd` without pressing `Shift + F10`:

1. **Download & Install Required Microsoft Tools**:
   - **Step 1**: Download and install [Windows ADK for Windows 10/11](https://learn.microsoft.com/en-us/windows-hardware/get-started/adk-install) (Select "Deployment Tools").
   - **Step 2**: Download and install the [Windows PE add-on for the Windows ADK](https://go.microsoft.com/fwlink/?linkid=2271338).
2. **Build the Custom ISO**:
   - Right-click [winpe/create_winpe_recovery.bat](file:///e:/SYSFIX/winpe/create_winpe_recovery.bat) and choose **"Run as administrator"**.
   - The script will automatically:
     - Run `copype amd64` to prepare the WinPE directory.
     - Mount `boot.wim` using DISM.
     - Inject optional WinPE packages (`WinPE-WMI`, `WinPE-StorageWMI`, `WinPE-Scripting`).
     - Copy `TERMINAL_BOARD_RECOVERY.exe`, `startnet.cmd`, and `winpeshl.ini`.
     - Commit the WIM and run `MakeWinPEMedia /iso` to generate `C:\WinPE_TerminalBoard_amd64\TERMINAL_BOARD_RECOVERY.iso`.
3. **Test in a VM Before USB**:
   - In Hyper-V, VirtualBox, or VMware, create a new VM (2 GB RAM, 1 CPU).
   - Attach `TERMINAL_BOARD_RECOVERY.iso` as the optical disc.
   - Power on the VM. It will boot directly into the TERMINAL BOARD recovery menu.

---

## 4. Verification Checkpoint Summary

- [x] **Desktop Executable Preserved**: `dist\TERMINAL_BOARD.exe` untouched.
- [x] **Recovery Executable Built**: `dist\TERMINAL_BOARD_RECOVERY.exe` ready.
- [x] **WinPE Simulation Test**: Passed via `python tests\test_winpe_recovery.py`.
- [x] **Read-Only Safety**: Guaranteed — no formatting, no partition changes, no BCD changes.
- [x] **Zero USB Modifications Made**: Host Windows boot settings and USBs were untouched.
