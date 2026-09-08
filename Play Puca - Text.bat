@echo off
REM Puca — text-first play (new narrative pipeline on HermesFixTry1).
REM Double-click to play in a console window. Uses Ollama when available,
REM falls back to offline text when it is not.
setlocal EnableExtensions
cd /d "%~dp0"
if errorlevel 1 (
  echo ERROR: Could not enter: %~dp0
  pause
  exit /b 1
)

set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo ERROR: .venv is missing. Run install.bat first.
  pause
  exit /b 1
)

echo Starting Puca (text) — type freely, /quit to leave...
echo Illustrations on: new scenes pause briefly while the image is painted.
echo (If painting fails or is slow, remove --images from this file to play text-only.)
echo.
"%VENV_PY%" -m puca_dungeon --no-debug --allow-heuristic-fallback --images %*
set "GAME_EXIT=%ERRORLEVEL%"
echo.
if not "%GAME_EXIT%"=="0" (
  echo Game exited with code %GAME_EXIT%.
  pause
)
exit /b %GAME_EXIT%
