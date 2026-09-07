@echo off
REM Deathtrap Dungeon — CLI DEBUG mode with LLM (Ollama) ON
cd /d "%~dp0"

if exist .venv\Scripts\python.exe (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo.
echo Deathtrap Dungeon — debug CLI + LLM
echo Requires Ollama running with model mistral.
echo Do NOT pass --heuristic (that turns the LLM off).
echo.

"%PY%" -m puca_dungeon --seed 91 --model mistral %*
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
  echo.
  echo Failed. Check that Ollama is running, then:
  echo   ollama pull mistral
  echo.
)

pause
exit /b %EXITCODE%
