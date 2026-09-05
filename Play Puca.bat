@echo off
setlocal
cd /d "%~dp0"
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
if exist "dist-qhd\Puca\VERIFIED.json" (
  "dist-qhd\Puca\Puca.exe" %*
) else (
  call launch.bat %*
)
if errorlevel 1 pause
