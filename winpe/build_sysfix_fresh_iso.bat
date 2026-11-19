@echo off
setlocal enabledelayedexpansion

echo ========================================================================
echo   SYSFIX / TERMINAL BOARD -- Clean WinPE Recovery ISO Rebuilder
echo ========================================================================
echo.

:: 1. Verify Administrator Privileges
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Administrator privileges are required for DISM operations.
    echo Please right-click this script and select "Run as administrator".
    echo.
    pause
    exit /b 1
)

set "PROJECT_DIR=E:\SYSFIX"
set "WINPE_WORK=%PROJECT_DIR%\WinPE_Work"
set "MOUNT_DIR=%WINPE_WORK%\mount"
set "MEDIA_DIR=%WINPE_WORK%\media"
set "BOOT_WIM=%MEDIA_DIR%\sources\boot.wim"
set "DIST_DIR=%PROJECT_DIR%\dist"
set "TARGET_ISO=%DIST_DIR%\SYSFIX_RECOVERY_HARDWARE_FRESH.iso"

set "MAIN_EXE=%DIST_DIR%\TERMINAL_BOARD.exe"
set "MAIN_DIR=%DIST_DIR%\TERMINAL_BOARD"
set "RECOVERY_EXE=%DIST_DIR%\TERMINAL_BOARD_RECOVERY.exe"
set "STARTNET_CMD=%PROJECT_DIR%\winpe\startnet.cmd"
set "WINPESHL_INI=%PROJECT_DIR%\winpe\winpeshl.ini"

set "ADK_DIR=C:\Program Files (x86)\Windows Kits\10\Assessment and Deployment Kit"
set "OSCDIMG=%ADK_DIR%\Deployment Tools\amd64\Oscdimg\oscdimg.exe"
set "WINPE_OCS=%ADK_DIR%\Windows Preinstallation Environment\amd64\WinPE_OCs"

if not exist "%MAIN_EXE%" (
    echo [ERROR] %MAIN_EXE% not found. Run python build_exe.py --onefile first.
    pause
    exit /b 1
)
if not exist "%RECOVERY_EXE%" (
    echo [ERROR] %RECOVERY_EXE% not found. Run build_recovery.bat first.
    pause
    exit /b 1
)

echo [OK] Verified application binaries and dependencies.

:: 2. Mount boot.wim if not already mounted
echo.
echo [1/5] Checking WIM mount state...
if exist "%MOUNT_DIR%\Windows\System32\cmd.exe" (
    echo [INFO] boot.wim is already mounted at: %MOUNT_DIR%
) else (
    echo [INFO] Mounting %BOOT_WIM% to %MOUNT_DIR%...
    dism /Mount-Image /ImageFile:"%BOOT_WIM%" /index:1 /MountDir:"%MOUNT_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to mount boot.wim.
        pause
        exit /b 1
    )
)

:: 3. Inject Optional Components (WMI, StorageWMI, Scripting) if needed
echo.
echo [2/5] Injecting WinPE Optional Packages...
if exist "%WINPE_OCS%\WinPE-WMI.cab" (
    dism /Image:"%MOUNT_DIR%" /Add-Package /PackagePath:"%WINPE_OCS%\WinPE-WMI.cab" >nul 2>&1
    if exist "%WINPE_OCS%\en-us\WinPE-WMI_en-us.cab" (
        dism /Image:"%MOUNT_DIR%" /Add-Package /PackagePath:"%WINPE_OCS%\en-us\WinPE-WMI_en-us.cab" >nul 2>&1
    )
)
if exist "%WINPE_OCS%\WinPE-StorageWMI.cab" (
    dism /Image:"%MOUNT_DIR%" /Add-Package /PackagePath:"%WINPE_OCS%\WinPE-StorageWMI.cab" >nul 2>&1
    if exist "%WINPE_OCS%\en-us\WinPE-StorageWMI_en-us.cab" (
        dism /Image:"%MOUNT_DIR%" /Add-Package /PackagePath:"%WINPE_OCS%\en-us\WinPE-StorageWMI_en-us.cab" >nul 2>&1
    )
)
if exist "%WINPE_OCS%\WinPE-Scripting.cab" (
    dism /Image:"%MOUNT_DIR%" /Add-Package /PackagePath:"%WINPE_OCS%\WinPE-Scripting.cab" >nul 2>&1
    if exist "%WINPE_OCS%\en-us\WinPE-Scripting_en-us.cab" (
        dism /Image:"%MOUNT_DIR%" /Add-Package /PackagePath:"%WINPE_OCS%\en-us\WinPE-Scripting_en-us.cab" >nul 2>&1
    )
)

:: 4. Inject Native Dependencies, Application, and Startup Configuration
echo.
echo [3/5] Injecting pdh.dll, SYSFIX binaries, and startup configuration...

:: Copy pdh.dll into System32 to resolve psutil WinPE import failure
if exist "C:\Windows\System32\pdh.dll" (
    copy /y "C:\Windows\System32\pdh.dll" "%MOUNT_DIR%\Windows\System32\pdh.dll" >nul
    echo   [OK] Injected pdh.dll into WinPE Windows\System32
)

:: Copy startup script and shell ini
copy /y "%STARTNET_CMD%" "%MOUNT_DIR%\Windows\System32\startnet.cmd" >nul
if exist "%WINPESHL_INI%" (
    copy /y "%WINPESHL_INI%" "%MOUNT_DIR%\Windows\System32\winpeshl.ini" >nul
)
echo   [OK] Installed startnet.cmd and winpeshl.ini

:: Ensure Recovery and SYSFIX directories exist
if not exist "%MOUNT_DIR%\Recovery" mkdir "%MOUNT_DIR%\Recovery" >nul
if not exist "%MOUNT_DIR%\SYSFIX" mkdir "%MOUNT_DIR%\SYSFIX" >nul

:: Copy standalone executables into System32, Recovery, and SYSFIX
copy /y "%MAIN_EXE%" "%MOUNT_DIR%\Windows\System32\TERMINAL_BOARD.exe" >nul
copy /y "%MAIN_EXE%" "%MOUNT_DIR%\Recovery\TERMINAL_BOARD.exe" >nul
copy /y "%MAIN_EXE%" "%MOUNT_DIR%\SYSFIX\TERMINAL_BOARD_STANDALONE.exe" >nul

copy /y "%RECOVERY_EXE%" "%MOUNT_DIR%\Windows\System32\TERMINAL_BOARD_RECOVERY.exe" >nul
copy /y "%RECOVERY_EXE%" "%MOUNT_DIR%\Recovery\TERMINAL_BOARD_RECOVERY.exe" >nul
copy /y "%RECOVERY_EXE%" "%MOUNT_DIR%\SYSFIX\TERMINAL_BOARD_RECOVERY.exe" >nul

:: Copy directory distribution into SYSFIX
if exist "%MAIN_DIR%" (
    xcopy /E /I /Y /Q "%MAIN_DIR%\*.*" "%MOUNT_DIR%\SYSFIX\" >nul
    echo   [OK] Injected directory-based TERMINAL_BOARD with _internal and pdh.dll
)

:: Copy executables to media root as well
copy /y "%MAIN_EXE%" "%MEDIA_DIR%\TERMINAL_BOARD.exe" >nul
copy /y "%RECOVERY_EXE%" "%MEDIA_DIR%\TERMINAL_BOARD_RECOVERY.exe" >nul

:: 5. Commit Changes and Unmount
echo.
echo [4/5] Committing changes to boot.wim and unmounting...
dism /Unmount-Image /MountDir:"%MOUNT_DIR%" /commit
if errorlevel 1 (
    echo [ERROR] DISM unmount /commit failed.
    pause
    exit /b 1
)

:: 6. Build Fresh Bootable Recovery ISO via oscdimg
echo.
echo [5/5] Generating Final Bootable ISO via oscdimg...
if exist "%TARGET_ISO%" del /f /q "%TARGET_ISO%" >nul

set "BOOTDATA=2#p0,e,b""%WINPE_WORK%\bootbins\etfsboot.com""#pEF,e,b""%WINPE_WORK%\bootbins\efisys.bin"""
"%OSCDIMG%" -bootdata:%BOOTDATA% -u1 -udfver102 "%MEDIA_DIR%" "%TARGET_ISO%"

if exist "%TARGET_ISO%" (
    echo.
    echo ========================================================================
    echo [SUCCESS] Fresh WinPE Recovery ISO Built Successfully!
    echo ISO Path : %TARGET_ISO%
    for %%F in ("%TARGET_ISO%") do echo ISO Size : %%~zF bytes
    echo ========================================================================
) else (
    echo [ERROR] ISO creation failed.
    pause
    exit /b 1
)

exit /b 0
