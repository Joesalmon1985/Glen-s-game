@echo off
REM Deathtrap Dungeon POC — debug play (no image generation)
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m puca_dungeon --debug --seed 91 %*
) else (
  python -m puca_dungeon --debug --seed 91 %*
)
pause
