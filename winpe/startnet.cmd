@echo off
setlocal enabledelayedexpansion
title SYSFIX / TERMINAL BOARD Pre-Boot Hardware Recovery Environment
color 0B
cls

echo ========================================================================
echo   SYSFIX / TERMINAL BOARD -- PRE-BOOT RECOVERY ENVIRONMENT
echo ========================================================================
echo [1/3] Initializing Windows PE hardware subsystems (wpeinit)...
wpeinit

echo [2/3] Waiting for storage devices and USB controllers to settle...
ping -n 4 127.0.0.1 >nul

echo [3/3] Locating SYSFIX / TERMINAL BOARD Executables...
set SYSFIX_EXE=
set RECOVERY_EXE=
set PERSISTENT_DRIVE=

:: Check internal WinPE paths
if exist "X:\SYSFIX\TERMINAL_BOARD.exe" (
    set "SYSFIX_EXE=X:\SYSFIX\TERMINAL_BOARD.exe"
) else if exist "X:\Windows\System32\TERMINAL_BOARD.exe" (
    set "SYSFIX_EXE=X:\Windows\System32\TERMINAL_BOARD.exe"
) else if exist "X:\Recovery\TERMINAL_BOARD.exe" (
    set "SYSFIX_EXE=X:\Recovery\TERMINAL_BOARD.exe"
)

if exist "X:\Recovery\TERMINAL_BOARD_RECOVERY.exe" (
    set "RECOVERY_EXE=X:\Recovery\TERMINAL_BOARD_RECOVERY.exe"
) else if exist "X:\Windows\System32\TERMINAL_BOARD_RECOVERY.exe" (
    set "RECOVERY_EXE=X:\Windows\System32\TERMINAL_BOARD_RECOVERY.exe"
)

:: Search removable and attached drives
for %%D in (C D E F G H I J K L M N O P Q R S T U V W Y Z) do (
    if exist "%%D:\" (
        if not defined SYSFIX_EXE (
            if exist "%%D:\SYSFIX\TERMINAL_BOARD.exe" set "SYSFIX_EXE=%%D:\SYSFIX\TERMINAL_BOARD.exe"
            if exist "%%D:\TERMINAL_BOARD.exe" set "SYSFIX_EXE=%%D:\TERMINAL_BOARD.exe"
            if exist "%%D:\dist\TERMINAL_BOARD.exe" set "SYSFIX_EXE=%%D:\dist\TERMINAL_BOARD.exe"
        )
        if not defined RECOVERY_EXE (
            if exist "%%D:\TERMINAL_BOARD_RECOVERY.exe" set "RECOVERY_EXE=%%D:\TERMINAL_BOARD_RECOVERY.exe"
            if exist "%%D:\Recovery\TERMINAL_BOARD_RECOVERY.exe" set "RECOVERY_EXE=%%D:\Recovery\TERMINAL_BOARD_RECOVERY.exe"
            if exist "%%D:\SYSFIX\dist\TERMINAL_BOARD_RECOVERY.exe" set "RECOVERY_EXE=%%D:\SYSFIX\dist\TERMINAL_BOARD_RECOVERY.exe"
        )
        :: Check for persistent writable drive
        if not defined PERSISTENT_DRIVE (
            if not "%%D"=="X" (
                mkdir "%%D:\.sysfix_probe" >nul 2>&1
                if not errorlevel 1 (
                    rmdir "%%D:\.sysfix_probe" >nul 2>&1
                    set "PERSISTENT_DRIVE=%%D:"
                )
            )
        )
    )
)

if "%PERSISTENT_DRIVE%"=="" set "PERSISTENT_DRIVE=X:"
echo [INFO] Persistent report drive detected: %PERSISTENT_DRIVE%

if not defined SYSFIX_EXE (
    if defined RECOVERY_EXE (
        set "SYSFIX_EXE=%RECOVERY_EXE%"
    )
)

if not defined SYSFIX_EXE (
    echo.
    echo [WARNING] SYSFIX executable not found automatically in X:\ or removable media.
    echo Please insert the SYSFIX USB media or specify the path manually.
    echo.
    goto MENU
)

echo [OK] Located Primary Diagnostic Engine: %SYSFIX_EXE%
echo.

:: Automatic Startup: Execute Hardware Diagnostic Scan with Full Report Generation
echo ========================================================================
echo   RUNNING AUTOMATIC PRE-BOOT HARDWARE SCAN & HEALTH ASSESSMENT
echo ========================================================================
"%SYSFIX_EXE%" --hardware-scan --export-report all
echo.

:MENU
echo.
echo ========================================================================
echo   SYSFIX / TERMINAL BOARD RECOVERY OPTIONS (Read-Only Safe Mode)
echo ========================================================================
echo   [1] Re-run Hardware Scan & Diagnostic Assessment (Fast)
echo   [2] Run Detailed Diagnostic Assessment with Component Stress Tests
echo   [3] Launch Interactive Disaster Recovery & Triage Console (CLI)
echo   [4] Export Full Diagnostic Reports to Specific Drive Letter
echo   [5] Open Diagnostic Command Prompt (cmd.exe)
echo   [6] Launch DiskPart (Read-Only Storage Inspection)
echo   [7] Reboot Computer (wpeutil reboot)
echo   [8] Turn Off Computer (wpeutil shutdown)
echo ========================================================================
set /p CHOICE="Select an option [1-8]: "

if "%CHOICE%"=="1" (
    cls
    if defined SYSFIX_EXE "%SYSFIX_EXE%" --hardware-scan --export-report all
    goto MENU
)

if "%CHOICE%"=="2" (
    cls
    if defined SYSFIX_EXE "%SYSFIX_EXE%" --detailed-scan --export-report all
    goto MENU
)

if "%CHOICE%"=="3" (
    cls
    if defined RECOVERY_EXE (
        "%RECOVERY_EXE%"
    ) else if defined SYSFIX_EXE (
        "%SYSFIX_EXE%" --hardware-scan
    )
    goto MENU
)

if "%CHOICE%"=="4" (
    echo.
    set TARGET_DRV=%PERSISTENT_DRIVE%
    set /p USER_DRV="Enter drive letter to export reports to [default: %PERSISTENT_DRIVE%]: "
    if not "!USER_DRV!"=="" set TARGET_DRV=!USER_DRV!
    if not "!TARGET_DRV:~-1!"==":" set TARGET_DRV=!TARGET_DRV!:
    
    echo Exporting diagnostics to !TARGET_DRV!\SYSFIX_Reports\ ...
    mkdir "!TARGET_DRV!\SYSFIX_Reports" >nul 2>&1
    if defined SYSFIX_EXE (
        "%SYSFIX_EXE%" --hardware-scan --export-report all
        copy /y "X:\SYSFIX\reports\*.*" "!TARGET_DRV!\SYSFIX_Reports\" >nul 2>&1
        copy /y "reports\*.*" "!TARGET_DRV!\SYSFIX_Reports\" >nul 2>&1
        echo [SUCCESS] Reports exported to !TARGET_DRV!\SYSFIX_Reports\
    )
    goto MENU
)

if "%CHOICE%"=="5" (
    echo Starting Command Prompt. Type 'exit' to return to recovery menu.
    cmd.exe
    goto MENU
)

if "%CHOICE%"=="6" (
    echo Launching DiskPart in read-only inspection mode. Type 'exit' to quit.
    diskpart.exe
    goto MENU
)

if "%CHOICE%"=="7" (
    echo Rebooting system...
    wpeutil reboot
)

if "%CHOICE%"=="8" (
    echo Shutting down system...
    wpeutil shutdown
)

goto MENU

:: Safe exit fallback to CMD so WinPE shell never reboots unexpectedly
cmd.exe
