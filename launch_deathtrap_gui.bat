@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if errorlevel 1 goto :directory_failure

set "VENV_PY=.venv\Scripts\python.exe"
set "LOG_DIR=logs"
set "LOG_FILE=%LOG_DIR%\deathtrap-gui-launch.log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

if not exist "%VENV_PY%" (
    echo ERROR: .venv is missing. Run install.bat first.
    pause
    exit /b 1
)

>"%LOG_FILE%" echo Deathtrap GUI launch log
>>"%LOG_FILE%" echo Directory: %CD%
>>"%LOG_FILE%" echo Arguments: %*
>>"%LOG_FILE%" echo.

if /I "%~1"=="--text-only" goto :text_preflight

echo Running full-mode preflight for Deathtrap GUI...
"%VENV_PY%" "diagnostics.py" --strict --require-ollama >>"%LOG_FILE%" 2>&1
set "PREFLIGHT_EXIT=%ERRORLEVEL%"
type "%LOG_FILE%"
if not "%PREFLIGHT_EXIT%"=="0" (
    echo.
    echo WARNING: Full preflight failed. Launching anyway with heuristic fallback if Ollama is down.
    echo Review: %CD%\%LOG_FILE%
    echo.
)

goto :run_game

:text_preflight
echo Running text-only preflight...
"%VENV_PY%" "diagnostics.py" --require-ollama >>"%LOG_FILE%" 2>&1

:run_game
echo Starting Puca GUI (Level 1 + illustrations)...
>>"%LOG_FILE%" echo --- game start ---
"%VENV_PY%" -m puca_dungeon.gui %* >>"%LOG_FILE%" 2>&1
set "GAME_EXIT=%ERRORLEVEL%"
>>"%LOG_FILE%" echo --- game exit code %GAME_EXIT% ---
if "%GAME_EXIT%"=="0" exit /b 0

echo.
echo ERROR: Deathtrap GUI exited with code %GAME_EXIT%.
echo Log: %CD%\%LOG_FILE%
pause
exit /b %GAME_EXIT%

:directory_failure
echo ERROR: Could not enter: %~dp0
pause
exit /b 1
