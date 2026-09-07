#!/usr/bin/env bash
# Deathtrap Dungeon POC — debug play (images suppressed)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
else
  PY=python3
fi
"$PY" scripts/ensure_story.py
exec "$PY" -m puca_dungeon --debug --seed 91 "$@"
