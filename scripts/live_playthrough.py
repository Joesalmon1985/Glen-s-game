"""Real Tk + Ollama + SD playthrough. Never substitutes generated story or art.
The first two scenes request art; remaining choices use the game's text-only toggle.
Results include any visible retries. Each run uses an isolated real save directory.
"""
from pathlib import Path
import copy
import json
import sys
import time
import tkinter as tk
import requests
from PIL import ImageGrab

root_path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_path))
from my_version_of_kawa import PucaApp
from puca_core import load_state

out = root_path / 'docs' / 'verification'
run_dir = out / ('playthrough-' + time.strftime('%Y%m%d-%H%M%S'))
run_dir.mkdir(parents=True)
start = time.monotonic()
while time.monotonic() - start < 1800:
    tags = requests.get('http://127.0.0.1:11434/api/tags', timeout=10).json().get('models', [])
    gpu_file = out / 'gpu.json'
    gpu = json.loads(gpu_file.read_text()) if gpu_file.exists() else None
    if gpu and not gpu['success']:
        raise RuntimeError('Image proof failed; inspect docs/verification/gpu.json')
    if any(x['name'].split(':')[0] == 'mistral' for x in tags) and gpu and gpu['success']:
        break
    time.sleep(3)
else:
    raise RuntimeError('Required real AI downloads did not become ready')

root = tk.Tk()
app = PucaApp(root, data_dir=run_dir, text_only=False)
app.name_var.set('Glen')
app.origin_var.set('At home on a rainy evening')
records = []
seen = -1
retries = {}
resume_verified = False
result = {'success':False, 'run_dir':str(run_dir)}
job_start = time.monotonic()

def capture(name):
    root.update_idletasks()
    path = run_dir / (name + '.png')
    ImageGrab.grab(window=int(root.frame(), 16)).save(path)
    return str(path)

def finish(error=None):
    result.update({'success':error is None, 'error':error, 'turn':app.state.turn,
                   'spirit':app.state.spirit, 'history_records':len(app.state.history),
                   'resume_verified':resume_verified, 'events':records,
                   'save':str(app.save_path), 'elapsed_seconds':time.monotonic()-job_start})
    result['screenshot'] = capture('final')
    (out / 'live-playthrough.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)
    root.after(500, app.close)

def tick():
    global seen, resume_verified
    try:
        if time.monotonic() - job_start > 1200:
            finish('Real playthrough exceeded its 20-minute bound')
            return
        if app.busy:
            root.after(100, tick)
            return
        if app.failed_action or app.pending_scene or app.render_failed:
            key = str(app.state.turn) + ':' + str(app.state.arrived)
            retries[key] = retries.get(key,0) + 1
            records.append({'retry_at_turn':app.state.turn, 'message':app.status_var.get()})
            if retries[key] > 2:
                finish('Narration could not recover: ' + app.status_var.get())
                return
            app.retry_button.invoke()
            root.after(100, tick)
            return
        if not app.state.arrived:
            finish('Begin did not produce a real opening')
            return
        if len(app.state.history) != seen:
            restored = load_state(app.save_path)
            assert restored.history == app.state.history
            assert app.state.history[-1]['narration'] in app.story.get('1.0','end')
            records.append({'turn':app.state.turn, 'spirit':app.state.spirit,
                            'narration':app.state.history[-1]['narration'],
                            'action':app.state.history[-1]['action'],
                            'image_key':app.state.image_key,
                            'image_failed':app.image_failed,
                            'seconds_since_start':time.monotonic()-job_start,
                            'ollama_resident':requests.get('http://127.0.0.1:11434/api/ps',timeout=10).json()})
            seen = len(app.state.history)
            print('Real scene saved and displayed:', app.state.turn, flush=True)
            if app.state.turn == 0:
                result['opening_screenshot'] = capture('opening')
                if app.image_failed or not app.state.image_key:
                    finish('The opening illustration failed: ' + app.status_var.get())
                    return
        if app.state.turn == 3 and not resume_verified:
            before = copy.deepcopy(app.state.history)
            app.resume_button.invoke()
            assert app.state.history == before
            resume_verified = True
        if app.state.finished:
            assert app.submit_button.instate(['disabled'])
            finish()
            return
        if app.state.turn >= 1:
            app.images_var.set(False)
        if app.choice_buttons:
            app.choice_buttons[0].invoke()
        else:
            app.action_var.set('Look carefully and choose the safest honest way forward.')
            app.submit_button.invoke()
        assert app.busy, 'Choice control did not launch the real narrator'
        root.after(100, tick)
    except Exception as exc:
        finish(repr(exc))

root.after(300, app.play_button.invoke)
root.after(500, tick)
root.mainloop()
raise SystemExit(0 if result['success'] else 1)
