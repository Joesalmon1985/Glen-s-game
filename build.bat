@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist-qhd Puca.spec
if errorlevel 1 exit /b 1
echo Built dist-qhd\Puca\Puca.exe. Keep the entire Puca folder together.
echo The original EXE is not modified. AI weights are not bundled.
