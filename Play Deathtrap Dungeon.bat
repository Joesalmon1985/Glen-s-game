@echo off
REM Deathtrap Dungeon POC — typing-first console (images suppressed)
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)
"%PY%" scripts\ensure_story.py
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)
"%PY%" -m puca_dungeon --debug --seed 91 %*
pause
