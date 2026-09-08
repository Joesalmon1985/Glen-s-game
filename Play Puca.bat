@echo off
REM Puca Level 1 — facility GUI with Ollama story + AI illustrations
setlocal EnableExtensions
cd /d "%~dp0"
if errorlevel 1 (
  echo ERROR: Could not enter: %~dp0
  pause
  exit /b 1
)

set "VENV_PY=.venv\Scripts\python.exe"
set "LOG_DIR=logs"
set "LOG_FILE=%LOG_DIR%\puca-launch.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

if not exist "%VENV_PY%" (
  echo ERROR: .venv is missing. Run install.bat first.
  pause
  exit /b 1
)

>"%LOG_FILE%" echo Puca launch log
>>"%LOG_FILE%" echo Directory: %CD%
>>"%LOG_FILE%" echo.

echo Checking Ollama and local setup...
"%VENV_PY%" "diagnostics.py" --require-ollama >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo.
  echo WARNING: Ollama check failed. The game may fall back to offline text.
  echo Review: %CD%\%LOG_FILE%
  echo.
)

REM Default: AI-drawn scenes from game state + turn narration.
REM For the old sprite kit instead: set PUCA_IMAGE_MODE=sprites
set "PUCA_IMAGE_MODE="

echo.
echo Starting Puca — Level 1 facility...
echo Illustrations use local Stable Diffusion when enabled in the window.
echo Log: %CD%\%LOG_FILE%
echo.

>>"%LOG_FILE%" echo --- game start ---
"%VENV_PY%" -m puca_dungeon.gui %* >>"%LOG_FILE%" 2>&1
set "GAME_EXIT=%ERRORLEVEL%"
>>"%LOG_FILE%" echo --- game exit code %GAME_EXIT% ---
if "%GAME_EXIT%"=="0" exit /b 0

echo.
echo ERROR: Game exited with code %GAME_EXIT%.
echo Log: %CD%\%LOG_FILE%
pause
exit /b %GAME_EXIT%
