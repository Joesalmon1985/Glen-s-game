#!/usr/bin/env bash
# Linux text-only bootstrap for Puca (no Windows pywin32, no CUDA Torch).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" - <<'PY'
import sys
v = sys.version_info
if v[:2] not in ((3, 11), (3, 12), (3, 13)):
    raise SystemExit(f'Need Python 3.11-3.13, found {sys.version}')
print(f'Using Python {sys.version.split()[0]}')
PY

if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install 'requests==2.32.3' 'Pillow==11.3.0'

RUNTIME="$ROOT/.runtime/ollama"
MODELS="$ROOT/.runtime/models"
mkdir -p "$RUNTIME" "$MODELS"
if [[ ! -x "$RUNTIME/bin/ollama" ]]; then
  echo "Downloading Ollama linux-amd64 into .runtime/ollama ..."
  curl --fail --show-error --location \
    "https://github.com/ollama/ollama/releases/download/v0.33.3/ollama-linux-amd64.tar.zst" \
    | zstd -d | tar -xf - -C "$RUNTIME"
fi
chmod +x "$RUNTIME/bin/ollama"

export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_MODELS="$MODELS"
if ! curl -fsS "http://${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
  mkdir -p "$ROOT/logs"
  nohup "$RUNTIME/bin/ollama" serve >"$ROOT/logs/ollama.log" 2>&1 &
  echo $! >"$ROOT/logs/ollama.pid"
  echo "Started local Ollama (pid $(cat "$ROOT/logs/ollama.pid"))."
  for _ in $(seq 1 60); do
    curl -fsS "http://${OLLAMA_HOST}/api/tags" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

MODEL="${PUCA_MODEL:-mistral}"
if ! curl -fsS "http://${OLLAMA_HOST}/api/tags" | grep -q "\"${MODEL}\""; then
  echo "Pulling ${MODEL} (large download)..."
  "$RUNTIME/bin/ollama" pull "$MODEL"
fi

echo
echo "Text-only install ready. Launch with:"
echo "  source .venv/bin/activate"
echo "  export OLLAMA_HOST=${OLLAMA_HOST}"
echo "  export OLLAMA_MODELS=${MODELS}"
echo "  python my_version_of_kawa.py --text-only --debug"
