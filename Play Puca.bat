@echo off
REM Puca Level 1 — full GUI with illustrations, Ollama LLM, facility cell + book dungeon
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first.
  pause
  exit /b 1
)
call launch_deathtrap_gui.bat %*
if errorlevel 1 pause
