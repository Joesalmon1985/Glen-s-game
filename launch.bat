@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if errorlevel 1 goto :directory_failure

set "VENV_PY=.venv\Scripts\python.exe"
set "LOG_DIR=logs"
set "LOG_FILE=%LOG_DIR%\puca-launch.log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
if not exist "%LOG_DIR%" (
    echo ERROR: Could not create the log directory: %LOG_DIR%
    exit /b 1
)

if not exist "%VENV_PY%" (
    echo ERROR: Puca's dedicated .venv is missing.
    echo Run install.bat first. No global Python or pip will be used.
    echo.
    echo Expected interpreter: %CD%\%VENV_PY%
    exit /b 1
)

>"%LOG_FILE%" echo Puca launch log
>>"%LOG_FILE%" echo Directory: %CD%
>>"%LOG_FILE%" echo Interpreter: %CD%\%VENV_PY%
>>"%LOG_FILE%" echo Arguments: %*
>>"%LOG_FILE%" echo.

:: Text-only mode may deliberately omit the optional GPU/image stack, but both
:: launch modes require Ollama and its mistral model for story narration.
if /I "%~1"=="--text-only" goto :text_preflight

echo Running full-mode preflight; results are also in %LOG_FILE%.
"%VENV_PY%" "diagnostics.py" --strict --require-ollama >>"%LOG_FILE%" 2>&1
set "PREFLIGHT_EXIT=%ERRORLEVEL%"
type "%LOG_FILE%"
if not "%PREFLIGHT_EXIT%"=="0" (
    echo.
    echo ERROR: Full-mode preflight failed. The game was not launched.
    echo Fix the reported Python, package, driver, or CUDA issue and retry.
    echo Log: %CD%\%LOG_FILE%
    exit /b 1
)
goto :run_game

:text_preflight
echo Running text-only preflight; results are also in %LOG_FILE%.
"%VENV_PY%" "diagnostics.py" --require-ollama >>"%LOG_FILE%" 2>&1
set "PREFLIGHT_EXIT=%ERRORLEVEL%"
type "%LOG_FILE%"
if not "%PREFLIGHT_EXIT%"=="0" (
    echo.
    echo ERROR: Diagnostics could not run. The game was not launched.
    echo Log: %CD%\%LOG_FILE%
    exit /b 1
)

:run_game

echo Starting Puca. Runtime output is being written to %LOG_FILE%.
>>"%LOG_FILE%" echo.
>>"%LOG_FILE%" echo --- game start ---
"%VENV_PY%" "my_version_of_kawa.py" %* >>"%LOG_FILE%" 2>&1
set "GAME_EXIT=%ERRORLEVEL%"
>>"%LOG_FILE%" echo --- game exit code %GAME_EXIT% ---
if "%GAME_EXIT%"=="0" exit /b 0

echo.
echo ERROR: Puca exited with code %GAME_EXIT%.
echo Review the complete log for the Python traceback:
echo   %CD%\%LOG_FILE%
pause
exit /b %GAME_EXIT%

:directory_failure
echo ERROR: Could not enter the Puca game directory: %~dp0
exit /b 1
