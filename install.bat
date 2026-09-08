@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if errorlevel 1 goto :fail_directory

echo ============================================
echo    Puca - Reproducible Python Setup
echo ============================================
echo.
echo This installer uses only .venv\Scripts\python.exe for pip.
echo It does not install Ollama or download an Ollama model.
echo.

:: Select an installed, supported Python through the Windows py launcher.
set "PY_CMD="
where py >nul 2>&1
if errorlevel 1 goto :no_py_launcher
py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.13"
if defined PY_CMD goto :python_selected
py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.12"
if defined PY_CMD goto :python_selected
py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.11"
if defined PY_CMD goto :python_selected

echo ERROR: Python 3.11, 3.12, or 3.13 64-bit was not found through the py launcher.
echo Python 3.14 and 32-bit Python are not supported. Install a supported 64-bit Python from python.org,
echo then run this installer again.
goto :fail

:python_selected
echo Using %PY_CMD%.
if exist ".venv\Scripts\python.exe" goto :venv_exists

echo Creating dedicated .venv...
%PY_CMD% -m venv ".venv"
if errorlevel 1 (
    echo ERROR: Could not create .venv.
    goto :fail
)

:venv_exists
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv was created without its Python executable.
    goto :fail
)
".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) and sys.maxsize > 2**32 else 1)"
if errorlevel 1 (
    echo ERROR: Existing .venv uses unsupported Python. Remove .venv and retry.
    goto :fail
)

:: Ensure pip is present, then use only the venv interpreter to invoke it.
echo Checking pip inside .venv...
".venv\Scripts\python.exe" -m ensurepip --upgrade >nul 2>&1
if errorlevel 1 (
    echo ERROR: Could not bootstrap pip inside .venv.
    goto :fail
)
".venv\Scripts\python.exe" -m pip --version
if errorlevel 1 (
    echo ERROR: pip is not usable inside .venv.
    goto :fail
)

:: Torch must come from the official CUDA 12.8 wheel index.
echo Installing Torch 2.7.1 with CUDA 12.8 support...
".venv\Scripts\python.exe" -m pip install --index-url https://download.pytorch.org/whl/cu128 "torch==2.7.1+cu128"
if errorlevel 1 (
    echo ERROR: Torch installation failed. No game launch was attempted.
    goto :fail
)

:: Install the remaining pinned packages from PyPI. Torch is intentionally not
:: in requirements.txt so this step cannot replace the CUDA wheel with CPU Torch.
echo Installing pinned Puca dependencies...
".venv\Scripts\python.exe" -m pip install --requirement "requirements.txt" --index-url https://pypi.org/simple
if errorlevel 1 (
    echo ERROR: Dependency installation failed. No game launch was attempted.
    goto :fail
)

:: Verify packages and a tiny CUDA operation before declaring setup complete.
echo Running read-only GPU/package diagnostics...
".venv\Scripts\python.exe" "diagnostics.py" --skip-ollama --strict
if errorlevel 1 (
    echo ERROR: Preflight diagnostics failed. Review the JSON above.
    echo The environment was installed, but the game was not declared ready.
    goto :fail
)

echo.
echo ============================================
echo Setup complete.
echo ============================================
echo Ollama is required for story play, including --text-only, and was not installed or downloaded by this script.
echo Install and start Ollama separately, then follow the explicit model instructions in SETUP.md.
echo Then launch with Play Puca.bat.
echo.
pause
exit /b 0

:no_py_launcher
echo ERROR: The Windows py launcher was not found.
echo Install Python 3.11, 3.12, or 3.13 with the py launcher enabled.
goto :fail

:fail_directory
echo ERROR: Could not enter the Puca game directory: %~dp0
goto :fail

:fail
echo.
echo Setup failed. No global pip command was used.
pause
exit /b 1
