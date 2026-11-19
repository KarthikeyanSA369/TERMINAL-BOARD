@echo off
setlocal enabledelayedexpansion

echo ========================================================================
echo   TERMINAL BOARD -- Standalone Recovery Executable Builder
echo ========================================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not found in PATH. Please install Python 3.10+ and add to PATH.
    exit /b 1
)

:: 2. Check PyInstaller
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] PyInstaller not detected. Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller.
        exit /b 1
    )
)

:: 3. Build Recovery Executable using Spec
echo [INFO] Compiling dist\TERMINAL_BOARD_RECOVERY.exe using terminal_board_recovery.spec...
python -m PyInstaller --clean --noconfirm terminal_board_recovery.spec
if errorlevel 1 (
    echo [ERROR] Build failed. See output above.
    exit /b 1
)

:: 4. Verify Output
if exist "dist\TERMINAL_BOARD_RECOVERY.exe" (
    echo.
    echo ========================================================================
    echo [SUCCESS] TERMINAL_BOARD_RECOVERY.exe built successfully!
    echo Location : %~dp0dist\TERMINAL_BOARD_RECOVERY.exe
    for %%F in ("dist\TERMINAL_BOARD_RECOVERY.exe") do echo Size     : %%~zF bytes
    echo ========================================================================
    echo.
    echo To test the executable in normal Windows:
    echo   dist\TERMINAL_BOARD_RECOVERY.exe
    echo   dist\TERMINAL_BOARD_RECOVERY.exe --json
    echo.
) else (
    echo [ERROR] dist\TERMINAL_BOARD_RECOVERY.exe was not found after build.
    exit /b 1
)

exit /b 0
