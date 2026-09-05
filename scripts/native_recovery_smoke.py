"""Live native error-path smoke. Uses the actual Ollama client, never fake AI output.
Run only when Ollama is absent to exercise startup recovery. Closes by itself.
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('puca_native_smoke', ROOT / 'my_version_of_kawa.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as temp:
    root = tk.Tk()
    app = module.PucaApp(root, data_dir=Path(temp), text_only=True)
    app.state = module.StoryState(name='Native recovery check', origin='At home')
    started = time.monotonic()
    def check():
        if not app.busy:
            result = {'actual_ollama_client': True, 'busy': app.busy,
                      'arrived': app.state.arrived, 'turn': app.state.turn,
                      'spirit': app.state.spirit, 'save_exists': app.save_path.exists(),
                      'retry_available': str(app.retry_button.cget('state')) == 'normal',
                      'status': app.status_var.get()}
            assert not result['arrived'], 'Ollama returned a scene; this smoke expects unavailable-service recovery'
            assert result['turn'] == 0 and result['spirit'] == 100
            assert result['retry_available'] and not result['save_exists']
            evidence = ROOT / 'docs' / 'native-recovery-result.json'
            evidence.write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result), flush=True)
            root.after(1500, app.close)
        elif time.monotonic() - started > 20:
            app.close()
            raise RuntimeError('Native recovery smoke timed out')
        else:
            root.after(50, check)
    root.after(100, lambda: app._launch('(The adventure begins)'))
    root.after(200, check)
    root.mainloop()
