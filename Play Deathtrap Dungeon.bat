@echo off
REM Deathtrap Dungeon — Fighting Fantasy (Ollama LLM by default; debug CLI)
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)
REM Debug + LLM (no --heuristic). Pass --allow-heuristic-fallback only if you want offline backup.
REM Player-facing (no debug dump): Play Deathtrap Dungeon.bat --no-debug
REM Dedicated shortcut: Play Deathtrap Dungeon Debug LLM.bat
"%PY%" -m puca_dungeon --seed 91 --model mistral %*
if errorlevel 1 (
  echo.
  echo Ollama LLM required. Start Ollama and run: ollama pull mistral
  echo Dedicated launcher: Play Deathtrap Dungeon Debug LLM.bat
)
pause
