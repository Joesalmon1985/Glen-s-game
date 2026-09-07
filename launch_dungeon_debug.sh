#!/usr/bin/env bash
# Deathtrap Dungeon — Fighting Fantasy gamebook (heuristic offline default)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
else
  PY=python3
fi
exec "$PY" -m puca_dungeon --heuristic --seed 91 "$@"
