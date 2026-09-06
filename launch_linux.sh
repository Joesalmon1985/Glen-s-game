#!/usr/bin/env bash
# Launch Puca in text-only debug mode using the local .runtime Ollama.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source .venv/bin/activate
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$ROOT/.runtime/models}"
export PATH="$ROOT/.runtime/ollama/bin:$PATH"

if ! curl -fsS "http://${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
  mkdir -p "$ROOT/logs"
  nohup "$ROOT/.runtime/ollama/bin/ollama" serve >"$ROOT/logs/ollama.log" 2>&1 &
  echo $! >"$ROOT/logs/ollama.pid"
  for _ in $(seq 1 60); do
    curl -fsS "http://${OLLAMA_HOST}/api/tags" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

exec python my_version_of_kawa.py --text-only --debug "$@"
