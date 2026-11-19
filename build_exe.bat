@echo off
setlocal enabledelayedexpansion

echo =====================================================================
echo  TERMINAL BOARD -- Windows Application Packaging and Build System
echo =====================================================================
echo.

:: 1. Navigate to project root directory
cd /d "%~dp0"
echo [1/6] Working directory: %CD%

:: 2. Check Python availability
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python was not found in PATH. Please install Python 3.10+ and add it to PATH.
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do set PYTHON_VER=%%i
echo [2/6] Using %PYTHON_VER%

:: 3. Setup / activate dedicated virtual environment
if not exist ".venv" (
    echo [3/6] Creating dedicated virtual environment in .venv...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to create virtual environment.
        exit /b %ERRORLEVEL%
    )
)

call .venv\Scripts\activate.bat
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to activate virtual environment.
    exit /b %ERRORLEVEL%
)
echo [3/6] Virtual environment active: %VIRTUAL_ENV%

:: 4. Install / verify dependencies from requirements.txt
echo [4/6] Installing and verifying dependencies from requirements.txt...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install project dependencies.
    exit /b %ERRORLEVEL%
)

:: 5. Validate frontend assets and run test suite
echo [5/6] Validating frontend assets and core diagnostic engines...
if not exist "frontend\index.html" (
    echo [ERROR] Frontend entry point frontend\index.html is missing!
    exit /b 1
)
if not exist "assets\icon.ico" (
    echo [ERROR] Application icon assets\icon.ico is missing!
    exit /b 1
)

python -m pytest tests\test_driver_inventory.py tests\test_api_integration.py --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Pre-build validation tests failed! Fix source errors before packaging.
    exit /b %ERRORLEVEL%
)
echo       Pre-build validation tests passed successfully.

:: 6. Package using PyInstaller
echo [6/6] Packaging TERMINAL BOARD using PyInstaller...

set BUILD_MODE=onedir
if "%1"=="--onefile" set BUILD_MODE=onefile
if "%1"=="onefile" set BUILD_MODE=onefile

if "%BUILD_MODE%"=="onefile" (
    echo       Building single-file standalone executable: dist\TERMINAL_BOARD.exe
    python -m PyInstaller --clean --noconfirm terminal_board_onefile.spec
) else (
    echo       Building directory-based distribution: dist\TERMINAL_BOARD\TERMINAL_BOARD.exe
    python -m PyInstaller --clean --noconfirm terminal_board.spec
)

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller packaging failed!
    exit /b %ERRORLEVEL%
)

:: Verification
if "%BUILD_MODE%"=="onefile" (
    set TARGET_EXE=dist\TERMINAL_BOARD.exe
) else (
    set TARGET_EXE=dist\TERMINAL_BOARD\TERMINAL_BOARD.exe
)

if not exist "%TARGET_EXE%" (
    echo [ERROR] Build output executable was not found at %TARGET_EXE%
    exit /b 1
)

echo.
echo =====================================================================
echo  [SUCCESS] TERMINAL BOARD packaged successfully!
echo =====================================================================
echo  Output Location : %CD%\%TARGET_EXE%
if "%BUILD_MODE%"=="onedir" (
    echo  Distribution Dir: %CD%\dist\TERMINAL_BOARD\
)
echo.
echo  Launch Instructions:
echo  1. Desktop Window Mode (Default Native GUI):
echo     "%CD%\%TARGET_EXE%"
echo.
echo  2. Local Web Browser Mode:
echo     "%CD%\%TARGET_EXE%" --web --port 5055
echo.
echo  3. Headless Health Check:
echo     "%CD%\%TARGET_EXE%" --headless
echo =====================================================================
exit /b 0
