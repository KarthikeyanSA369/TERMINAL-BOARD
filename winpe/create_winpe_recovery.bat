@echo off
setlocal

echo ========================================================================
echo   TERMINAL BOARD -- WinPE Bootable Image Builder
echo ========================================================================
echo.

rem 1. Ensure administrator privileges
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] This script requires Administrator privileges for DISM image mounting.
    echo Please right-click CMD or your terminal and choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%..\dist\TERMINAL_BOARD_RECOVERY.exe" (
    set "PROJECT_DIR=%SCRIPT_DIR%.."
) else if exist "%SCRIPT_DIR%dist\TERMINAL_BOARD_RECOVERY.exe" (
    set "PROJECT_DIR=%SCRIPT_DIR%"
) else (
    set "PROJECT_DIR=%SCRIPT_DIR%.."
)
for %%I in ("%PROJECT_DIR%") do set "PROJECT_DIR=%%~fI"

set "RECOVERY_EXE=%PROJECT_DIR%\dist\TERMINAL_BOARD_RECOVERY.exe"
set "MAIN_EXE=%PROJECT_DIR%\dist\TERMINAL_BOARD.exe"
if not exist "%MAIN_EXE%" (
    if exist "%PROJECT_DIR%\dist\TERMINAL_BOARD\TERMINAL_BOARD.exe" (
        set "MAIN_EXE=%PROJECT_DIR%\dist\TERMINAL_BOARD\TERMINAL_BOARD.exe"
    )
)

if exist "%SCRIPT_DIR%startnet.cmd" (
    set "WINPE_RES_DIR=%SCRIPT_DIR%"
) else (
    set "WINPE_RES_DIR=%PROJECT_DIR%\winpe\"
)
set "STARTNET_CMD=%WINPE_RES_DIR%startnet.cmd"
set "WINPESHL_INI=%WINPE_RES_DIR%winpeshl.ini"

rem 2. Verify Recovery Executable
if not exist "%RECOVERY_EXE%" (
    echo [ERROR] Recovery executable not found at:
    echo   "%RECOVERY_EXE%"
    echo Please run build_recovery.bat first to compile it.
    pause
    exit /b 1
)
echo [OK] Verified recovery executable: %RECOVERY_EXE%

if exist "%MAIN_EXE%" (
    echo [OK] Verified main executable: %MAIN_EXE%
) else (
    echo [INFO] Main GUI executable not found at %MAIN_EXE% [optional in WinPE]
)

rem 3. Locate Windows ADK across standard paths and Windows Registry
set "ADK_PATH="

if exist "C:\Program Files (x86)\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\DandISetEnv.bat" (
    set "ADK_PATH=C:\Program Files (x86)\Windows Kits\10\Assessment and Deployment Kit"
    goto :ADK_FOUND
)

if exist "C:\Program Files\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\DandISetEnv.bat" (
    set "ADK_PATH=C:\Program Files\Windows Kits\10\Assessment and Deployment Kit"
    goto :ADK_FOUND
)

if exist "C:\Program Files (x86)\Windows Kits\11\Assessment and Deployment Kit\Deployment Tools\DandISetEnv.bat" (
    set "ADK_PATH=C:\Program Files (x86)\Windows Kits\11\Assessment and Deployment Kit"
    goto :ADK_FOUND
)

if exist "C:\Program Files\Windows Kits\11\Assessment and Deployment Kit\Deployment Tools\DandISetEnv.bat" (
    set "ADK_PATH=C:\Program Files\Windows Kits\11\Assessment and Deployment Kit"
    goto :ADK_FOUND
)

rem Fallback: Query Windows Registry for KitsRoot10
for /f "tokens=2*" %%A in ('reg query "HKLM\Software\Wow6432Node\Microsoft\Windows Kits\Installed Roots" /v KitsRoot10 2^>nul') do (
    if exist "%%BAssessment and Deployment Kit\Deployment Tools\DandISetEnv.bat" (
        set "ADK_PATH=%%BAssessment and Deployment Kit"
        goto :ADK_FOUND
    )
)

for /f "tokens=2*" %%A in ('reg query "HKLM\Software\Microsoft\Windows Kits\Installed Roots" /v KitsRoot10 2^>nul') do (
    if exist "%%BAssessment and Deployment Kit\Deployment Tools\DandISetEnv.bat" (
        set "ADK_PATH=%%BAssessment and Deployment Kit"
        goto :ADK_FOUND
    )
)

:ADK_NOT_FOUND
echo.
echo ========================================================================
echo [STATUS] Windows ADK Deployment Tools are NOT installed on this machine.
echo ========================================================================
echo To build a custom standalone WinPE ISO using Microsoft DISM/ADK:
echo.
echo 1. Download and install "Windows ADK for Windows 10/11":
echo    https://learn.microsoft.com/en-us/windows-hardware/get-started/adk-install
echo.
echo 2. Download and install "Windows PE add-on for the Windows ADK":
echo    https://go.microsoft.com/fwlink/?linkid=2271338
echo.
echo ========================================================================
echo ALTERNATIVE ZERO-RISK DEMO METHOD [RECOMMENDED FOR COLLEGE DEMO]:
echo ========================================================================
echo You do NOT need to wipe or format a USB drive!
echo.
echo 1. Take any standard Windows 10/11 Installation USB or Ventoy USB.
echo 2. Copy "TERMINAL_BOARD_RECOVERY.exe" directly onto the root of the USB.
echo 3. Boot the college/test PC from the USB.
echo 4. On the Windows Setup screen, press:
echo         SHIFT + F10
echo    A Windows PE Administrator Command Prompt will open instantly.
echo 5. Type:
echo         D:\TERMINAL_BOARD_RECOVERY.exe  [or whichever drive letter USB is]
echo 6. TERMINAL BOARD will launch directly in WinPE pre-boot mode!
echo ========================================================================
echo.
pause
exit /b 0

:ADK_FOUND
echo [OK] Located Windows ADK at: %ADK_PATH%

set "DANDI_SETENV=%ADK_PATH%\Deployment Tools\DandISetEnv.bat"
set "COPY_PE=%ADK_PATH%\Windows Preinstallation Environment\copype.cmd"

rem Check Windows Preinstallation Environment first for MakeWinPEMedia.cmd
set "MAKE_MEDIA=%ADK_PATH%\Windows Preinstallation Environment\MakeWinPEMedia.cmd"
if not exist "%MAKE_MEDIA%" (
    if exist "%ADK_PATH%\Deployment Tools\MakeWinPEMedia.cmd" (
        set "MAKE_MEDIA=%ADK_PATH%\Deployment Tools\MakeWinPEMedia.cmd"
    )
)

set "WINPE_OCS=%ADK_PATH%\Windows Preinstallation Environment\amd64\WinPE_OCs"

if not exist "%DANDI_SETENV%" (
    echo [ERROR] DandISetEnv.bat was not found at:
    echo   "%DANDI_SETENV%"
    pause
    exit /b 1
)
echo [OK] Verified Deployment Tools: %DANDI_SETENV%

if not exist "%COPY_PE%" (
    echo [ERROR] The Windows PE copype.cmd script was not found at:
    echo   "%COPY_PE%"
    echo Please install or repair the Windows PE add-on for Windows ADK.
    pause
    exit /b 1
)
echo [OK] Verified copype.cmd: %COPY_PE%

if not exist "%MAKE_MEDIA%" (
    echo [ERROR] MakeWinPEMedia.cmd was not found at:
    echo   "%MAKE_MEDIA%"
    pause
    exit /b 1
)
echo [OK] Verified MakeWinPEMedia.cmd: %MAKE_MEDIA%

if not exist "%WINPE_OCS%" goto :NO_OCS
echo [OK] Verified WinPE Optional Components: %WINPE_OCS%
if exist "%WINPE_OCS%\WinPE-WMI.cab" echo   - WinPE-WMI.cab: FOUND
if exist "%WINPE_OCS%\WinPE-StorageWMI.cab" echo   - WinPE-StorageWMI.cab: FOUND
if exist "%WINPE_OCS%\WinPE-Scripting.cab" echo   - WinPE-Scripting.cab: FOUND
goto :AFTER_OCS

:NO_OCS
echo [WARNING] WinPE Optional Components directory not found at:
echo   "%WINPE_OCS%"
echo Optional packages will be skipped.

:AFTER_OCS

rem Initialize ADK Deployment & Imaging Environment
echo [INFO] Initializing Windows ADK environment variables...
call "%DANDI_SETENV%"
cd /d "%SCRIPT_DIR%"

echo.
set "WINPE_DIR=C:\WinPE_TerminalBoard_amd64"
echo [1/6] Staging WinPE working directory at: %WINPE_DIR%
if exist "%WINPE_DIR%" (
    echo [INFO] Existing WinPE working directory detected at: %WINPE_DIR%
    if exist "%WINPE_DIR%\media\sources\boot.wim" (
        echo [INFO] Existing staged media\sources\boot.wim detected. Preserving directory without deletion.
    ) else (
        echo [ERROR] Directory "%WINPE_DIR%" exists but media\sources\boot.wim is missing.
        echo [ERROR] Destructive cleanup is disabled to prevent accidental data loss.
        echo Please rename or clear "%WINPE_DIR%" manually, then run this script again.
        pause
        exit /b 1
    )
) else (
    echo [INFO] Creating new WinPE amd64 directory via copype...
    call "%COPY_PE%" amd64 "%WINPE_DIR%"
    if errorlevel 1 (
        echo [ERROR] copype.cmd failed to create WinPE directory at %WINPE_DIR%.
        pause
        exit /b 1
    )
)

echo [2/6] Preparing WinPE boot image [boot.wim]...
if exist "%WINPE_DIR%\mount\Windows\System32" (
    echo [INFO] boot.wim is already mounted at "%WINPE_DIR%\mount".
) else (
    echo [INFO] Mounting WinPE boot image to "%WINPE_DIR%\mount"...
    dism /Mount-Image /ImageFile:"%WINPE_DIR%\media\sources\boot.wim" /index:1 /MountDir:"%WINPE_DIR%\mount"
    if errorlevel 1 (
        echo [ERROR] DISM failed to mount boot.wim.
        pause
        exit /b 1
    )
)

echo [3/6] Installing optional WinPE CAB packages [WMI, Storage, Scripting]...
if exist "%WINPE_OCS%\WinPE-WMI.cab" (
    echo   - Adding WinPE-WMI...
    dism /Image:"%WINPE_DIR%\mount" /Add-Package /PackagePath:"%WINPE_OCS%\WinPE-WMI.cab" >nul 2>&1
    if exist "%WINPE_OCS%\en-us\WinPE-WMI_en-us.cab" (
        dism /Image:"%WINPE_DIR%\mount" /Add-Package /PackagePath:"%WINPE_OCS%\en-us\WinPE-WMI_en-us.cab" >nul 2>&1
    )
)
if exist "%WINPE_OCS%\WinPE-StorageWMI.cab" (
    echo   - Adding WinPE-StorageWMI...
    dism /Image:"%WINPE_DIR%\mount" /Add-Package /PackagePath:"%WINPE_OCS%\WinPE-StorageWMI.cab" >nul 2>&1
    if exist "%WINPE_OCS%\en-us\WinPE-StorageWMI_en-us.cab" (
        dism /Image:"%WINPE_DIR%\mount" /Add-Package /PackagePath:"%WINPE_OCS%\en-us\WinPE-StorageWMI_en-us.cab" >nul 2>&1
    )
)
if exist "%WINPE_OCS%\WinPE-Scripting.cab" (
    echo   - Adding WinPE-Scripting...
    dism /Image:"%WINPE_DIR%\mount" /Add-Package /PackagePath:"%WINPE_OCS%\WinPE-Scripting.cab" >nul 2>&1
    if exist "%WINPE_OCS%\en-us\WinPE-Scripting_en-us.cab" (
        dism /Image:"%WINPE_DIR%\mount" /Add-Package /PackagePath:"%WINPE_OCS%\en-us\WinPE-Scripting_en-us.cab" >nul 2>&1
    )
)

echo [4/6] Injecting recovery executables and startup configuration...
if not exist "%WINPE_DIR%\mount\Recovery" mkdir "%WINPE_DIR%\mount\Recovery" >nul 2>&1
if not exist "%WINPE_DIR%\media" mkdir "%WINPE_DIR%\media" >nul 2>&1

echo   - Copying recovery executable to System32, Recovery, and media root...
copy /y "%RECOVERY_EXE%" "%WINPE_DIR%\mount\Windows\System32\TERMINAL_BOARD_RECOVERY.exe" >nul
if errorlevel 1 (
    echo [ERROR] Failed to copy recovery executable to System32.
    pause
    exit /b 1
)
copy /y "%RECOVERY_EXE%" "%WINPE_DIR%\mount\Recovery\TERMINAL_BOARD_RECOVERY.exe" >nul
copy /y "%RECOVERY_EXE%" "%WINPE_DIR%\media\TERMINAL_BOARD_RECOVERY.exe" >nul

if exist "%MAIN_EXE%" (
    echo   - Copying main executable to System32, Recovery, and media root...
    copy /y "%MAIN_EXE%" "%WINPE_DIR%\mount\Windows\System32\TERMINAL_BOARD.exe" >nul
    copy /y "%MAIN_EXE%" "%WINPE_DIR%\mount\Recovery\TERMINAL_BOARD.exe" >nul
    copy /y "%MAIN_EXE%" "%WINPE_DIR%\media\TERMINAL_BOARD.exe" >nul
)

echo   - Installing startup scripts [startnet.cmd and winpeshl.ini]...
copy /y "%STARTNET_CMD%" "%WINPE_DIR%\mount\Windows\System32\startnet.cmd" >nul
if errorlevel 1 (
    echo [ERROR] Failed to copy startnet.cmd to WinPE.
    pause
    exit /b 1
)
if exist "%WINPESHL_INI%" (
    copy /y "%WINPESHL_INI%" "%WINPE_DIR%\mount\Windows\System32\winpeshl.ini" >nul
)

echo [5/6] Committing changes and unmounting boot image...
dism /Unmount-Image /MountDir:"%WINPE_DIR%\mount" /commit
if errorlevel 1 (
    echo [ERROR] DISM failed to commit image.
    pause
    exit /b 1
)

set "ISO_OUTPUT=%WINPE_DIR%\TERMINAL_BOARD_RECOVERY.iso"
echo [6/6] Generating Bootable ISO: "%ISO_OUTPUT%"...
if exist "%ISO_OUTPUT%" (
    echo [INFO] Deleting existing ISO before rebuilding: "%ISO_OUTPUT%"
    del /f /q "%ISO_OUTPUT%" >nul 2>&1
)

call "%MAKE_MEDIA%" /iso "%WINPE_DIR%" "%ISO_OUTPUT%"
if errorlevel 1 (
    echo [ERROR] MakeWinPEMedia failed to create ISO.
    pause
    exit /b 1
)

if not exist "%ISO_OUTPUT%" (
    echo [ERROR] MakeWinPEMedia command completed, but ISO file was not found:
    echo   "%ISO_OUTPUT%"
    pause
    exit /b 1
)

copy /y "%ISO_OUTPUT%" "%PROJECT_DIR%\dist\TERMINAL_BOARD_RECOVERY.iso" >nul 2>&1

echo.
echo ========================================================================
echo [SUCCESS] WinPE Bootable Image Successfully Built!
echo ISO Path : %ISO_OUTPUT%
for %%F in ("%ISO_OUTPUT%") do echo ISO Size : %%~zF bytes
echo ========================================================================
echo.
pause
exit /b 0
