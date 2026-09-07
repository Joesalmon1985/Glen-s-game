@echo off
setlocal
cd /d "%~dp0"
REM Same Spirit adventure as Play Puca.bat, with the turn debug panel.
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first. The original EXE is unchanged.
  pause
  exit /b 1
)
.venv\Scripts\python.exe scripts\ensure_story.py
if errorlevel 1 (
  pause
  exit /b 1
)
call launch.bat --debug %*
if errorlevel 1 pause
