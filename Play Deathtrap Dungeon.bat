@echo off
REM Deathtrap Dungeon — Fighting Fantasy gamebook (heuristic offline default)
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)
REM Defaults: offline heuristic + seed 91.
REM Examples:
REM   Play Deathtrap Dungeon.bat --no-debug --images
REM   Play Deathtrap Dungeon.bat --potion potion_fortune --name Glen
REM For Ollama LLM interpret, drop --heuristic and ensure Ollama+mistral are running:
REM   Play Deathtrap Dungeon.bat --allow-heuristic-fallback
"%PY%" -m puca_dungeon --heuristic --seed 91 %*
pause
