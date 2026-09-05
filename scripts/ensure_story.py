"""Start only the project's local narrator if needed, then verify actual readiness."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
from urllib.error import URLError

URL = 'http://127.0.0.1:11434/api/tags'

def tags():
    with urllib.request.urlopen(URL, timeout=3) as response:
        return [item['name'] for item in json.loads(response.read(1024 * 1024))['models']]

def ensure_ready(root):
    root = Path(root)
    try:
        installed = tags()
    except (OSError, URLError):
        exe = root / '.runtime' / 'ollama' / 'ollama.exe'
        if not exe.is_file():
            raise RuntimeError('Start Ollama first, or run scripts/download_ollama.py to install the local narrator runtime.')
        env = os.environ.copy()
        env.update(OLLAMA_HOST='127.0.0.1:11434', OLLAMA_MODELS=str(root / '.runtime' / 'models'),
                   OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_NUM_PARALLEL='1', OLLAMA_FLASH_ATTENTION='1')
        logs = root / 'logs'
        logs.mkdir(exist_ok=True)
        with (logs / 'ollama.log').open('a', encoding='utf-8') as output:
            child = subprocess.Popen([str(exe), 'serve'], cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                installed = tags()
                break
            except (OSError, URLError):
                if child.poll() is not None:
                    raise RuntimeError('Local narrator stopped. See logs/ollama.log.')
                time.sleep(0.3)
        else:
            raise RuntimeError('Local narrator did not become ready within 45 seconds. See logs/ollama.log.')
    wanted = os.environ.get('PUCA_MODEL', 'mistral')
    if wanted not in installed and (wanted + ':latest') not in installed:
        raise RuntimeError(f'The {wanted} AI model is missing. Follow SETUP.md to download it once.')
    return True

if __name__ == '__main__':
    try:
        ensure_ready(Path(__file__).resolve().parents[1])
        print('Local narrator is ready.')
    except Exception as exc:
        print('Cannot start Puca:', exc)
        raise SystemExit(1)
