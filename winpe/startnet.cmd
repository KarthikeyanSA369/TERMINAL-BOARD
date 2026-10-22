@echo off
setlocal enabledelayedexpansion
title TERMINAL BOARD Pre-Boot Recovery Environment
color 0B
cls

echo ========================================================================
echo   TERMINAL BOARD -- PRE-BOOT RECOVERY ENVIRONMENT
echo ========================================================================
echo [1/3] Initializing Windows PE hardware subsystems (wpeinit)...
wpeinit

echo [2/3] Waiting for storage devices to mount...
ping -n 3 127.0.0.1 >nul

echo [3/3] Locating TERMINAL BOARD Recovery Executable...
set RECOVERY_BIN=
set RECOVERY_DRIVE=

if exist "X:\Recovery\TERMINAL_BOARD_RECOVERY.exe" (
    set "RECOVERY_BIN=X:\Recovery\TERMINAL_BOARD_RECOVERY.exe"
    set "RECOVERY_DRIVE=X:"
) else if exist "X:\Windows\System32\TERMINAL_BOARD_RECOVERY.exe" (
    set "RECOVERY_BIN=X:\Windows\System32\TERMINAL_BOARD_RECOVERY.exe"
    set "RECOVERY_DRIVE=X:"
)

:: Search removable / attached drive letters if not found in RAM disk
if "%RECOVERY_BIN%"=="" (
    for %%D in (C D E F G H I J K L M N O P Q R S T U V W Y Z) do (
        if not defined RECOVERY_BIN (
            if exist "%%D:\TERMINAL_BOARD_RECOVERY.exe" (
                set "RECOVERY_BIN=%%D:\TERMINAL_BOARD_RECOVERY.exe"
                set "RECOVERY_DRIVE=%%D:"
            ) else if exist "%%D:\Recovery\TERMINAL_BOARD_RECOVERY.exe" (
                set "RECOVERY_BIN=%%D:\Recovery\TERMINAL_BOARD_RECOVERY.exe"
                set "RECOVERY_DRIVE=%%D:"
            ) else if exist "%%D:\SYSFIX\dist\TERMINAL_BOARD_RECOVERY.exe" (
                set "RECOVERY_BIN=%%D:\SYSFIX\dist\TERMINAL_BOARD_RECOVERY.exe"
                set "RECOVERY_DRIVE=%%D:"
            )
        )
    )
)

if "%RECOVERY_BIN%"=="" (
    echo.
    echo [WARNING] TERMINAL_BOARD_RECOVERY.exe was not found automatically.
    echo Please insert the recovery media or specify the path manually.
    echo.
    goto MENU
)

echo [OK] Located Recovery Utility: %RECOVERY_BIN%
echo.

:: Run initial read-only diagnostics automatically
"%RECOVERY_BIN%"

:MENU
echo.
echo ========================================================================
echo   TERMINAL BOARD RECOVERY OPTIONS (Read-Only Safe Mode)
echo ========================================================================
echo   [1] Re-run Hardware & Offline Windows Diagnostics
echo   [2] Export Diagnostic Report to Media (JSON + Text)
echo   [3] Open Diagnostic Command Prompt (CMD)
echo   [4] Launch DiskPart (Storage Inspection)
echo   [5] Reboot Computer
echo   [6] Turn Off Computer
echo   [7] Exit to Command Prompt (cmd.exe)
echo ========================================================================
set /p CHOICE="Select an option [1-7]: "

if "%CHOICE%"=="1" (
    cls
    if not "%RECOVERY_BIN%"=="" "%RECOVERY_BIN%"
    goto MENU
)

if "%CHOICE%"=="2" (
    echo.
    set TARGET_DRV=%RECOVERY_DRIVE%
    set /p USER_DRV="Enter drive letter to export report to [default: %RECOVERY_DRIVE%]: "
    if not "!USER_DRV!"=="" set TARGET_DRV=!USER_DRV!
    if not "!TARGET_DRV:~-1!"==":" set TARGET_DRV=!TARGET_DRV!:
    
    echo Exporting diagnostics to !TARGET_DRV!\terminal_board_recovery_report.txt ...
    if not "%RECOVERY_BIN%"=="" (
        "%RECOVERY_BIN%" --output "!TARGET_DRV!\terminal_board_recovery_report.txt"
        "%RECOVERY_BIN%" --json > "!TARGET_DRV!\terminal_board_recovery_report.json"
        echo [SUCCESS] Report written to !TARGET_DRV!\
    )
    goto MENU
)

if "%CHOICE%"=="3" (
    echo Starting Command Prompt. Type 'exit' to return to menu.
    cmd.exe
    goto MENU
)

if "%CHOICE%"=="4" (
    echo Launching DiskPart in read-only inspection mode. Type 'exit' to quit.
    diskpart.exe
    goto MENU
)

if "%CHOICE%"=="5" (
    echo Rebooting system...
    wpeutil reboot
)

if "%CHOICE%"=="6" (
    echo Shutting down system...
    wpeutil shutdown
)

if "%CHOICE%"=="7" (
    echo Exiting to Command Prompt. Type 'startnet' to return to this recovery menu.
    cmd.exe
    goto MENU
)

goto MENU

:: Safe exit fallback to CMD so WinPE shell does not reboot
cmd.exe
