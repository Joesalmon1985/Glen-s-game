@echo off
REM Level 1 facility play with pre-composed sprite scenes (no per-turn AI images).
setlocal EnableExtensions
cd /d "%~dp0"
if errorlevel 1 (
  echo ERROR: Could not enter: %~dp0
  pause
  exit /b 1
)

set "VENV_PY=.venv\Scripts\python.exe"
set "LOG_DIR=logs"
set "LOG_FILE=%LOG_DIR%\deathtrap-sprites-launch.log"
set "SPRITE_CATALOG=assets\sprites\catalog.json"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

if not exist "%VENV_PY%" (
  echo ERROR: .venv is missing. Run install.bat first.
  pause
  exit /b 1
)

if not exist "%SPRITE_CATALOG%" (
  echo ERROR: Sprite catalog missing: %SPRITE_CATALOG%
  echo Generate sprites first:
  echo   .venv\Scripts\python.exe scripts\generate_sprites.py
  pause
  exit /b 1
)

>"%LOG_FILE%" echo Deathtrap sprite GUI launch log
>>"%LOG_FILE%" echo Directory: %CD%
>>"%LOG_FILE%" echo.

echo Checking Ollama for story text...
"%VENV_PY%" "diagnostics.py" --require-ollama >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo.
  echo WARNING: Ollama check failed. The game may fall back to heuristic text.
  echo Review: %CD%\%LOG_FILE%
  echo.
)

echo.
echo Starting Level 1 with sprite illustrations...
echo Scenes are composed from assets\sprites (no per-turn image generation).
echo Log: %CD%\%LOG_FILE%
echo.

set "PUCA_IMAGE_MODE=sprites"
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
