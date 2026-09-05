"""Opt-in real runtime check, shared by source and frozen executable.
Invokes actual Tk controls, real Ollama, real diffusion, real save/resume.
No fake narrator, image generator, transport, or success response is used.
"""
import hashlib
import json
from pathlib import Path
import sys
import time
from puca_core import load_state
from puca_images import ImageGenerator


def run(app):
    root = app.master
    start = time.monotonic()
    app.name_var.set('Glen')
    app.origin_var.set('At home')
    phase = 0
    report = app.data_dir / 'runtime-report.json'

    def finish(error=None):
        app.runtime_check_failed = error is not None
        result = {'success':error is None, 'error':error, 'frozen':bool(getattr(sys,'frozen',False)),
                  'executable':sys.executable, 'turn':app.state.turn,
                  'history_records':len(app.state.history), 'save':str(app.save_path),
                  'image_key':app.state.image_key, 'adapter_loaded':app.images.adapter_loaded,
                  'elapsed_seconds':time.monotonic()-start}
        root.update_idletasks()
        result['client_pixels'] = [root.winfo_width(), root.winfo_height()]
        photo = getattr(app.image_label, 'image', None)
        result['displayed_art_pixels'] = [photo.width(), photo.height()] if photo else None
        result['story_font_points'] = app.font_size
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            bounds = wintypes.RECT()
            ctypes.windll.user32.GetClientRect(int(root.frame(), 16), ctypes.byref(bounds))
            result['native_client_pixels'] = [bounds.right, bounds.bottom]
        if result['frozen']:
            with Path(sys.executable).open('rb') as source:
                result['executable_sha256'] = hashlib.file_digest(source,'sha256').hexdigest()
        try:
            from PIL import ImageGrab
            screenshot = app.data_dir / 'runtime-screen.png'
            root.update_idletasks()
            ImageGrab.grab(window=int(root.frame(),16)).save(screenshot)
            result['screenshot'] = str(screenshot)
        except Exception as exc:
            result['capture_error'] = str(exc)
        app.data_dir.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(result,indent=2),encoding='utf-8')
        root.after(500,app.close)

    def check():
        nonlocal phase
        try:
            if time.monotonic()-start > 600:
                finish('Real runtime check timed out')
                return
            if app.busy:
                root.after(100,check)
                return
            if app.failed_action or app.pending_scene or app.image_failed or app.render_failed:
                finish(app.status_var.get())
                return
            assert app.state.arrived and app.state.history, 'Opening was not generated'
            assert app.state.image_key and ImageGenerator.valid_image(app.cache_dir / (app.state.image_key+'.png')), 'Real illustration is missing'
            assert app.images.adapter_loaded, 'Pixel adapter did not attach'
            assert app.state.history[-1]['narration'] in app.story.get('1.0','end'), 'Story was not rendered'
            saved = load_state(app.save_path)
            assert saved.history == app.state.history
            if phase == 0:
                phase = 1
                if app.choice_buttons:
                    app.choice_buttons[0].invoke()
                else:
                    app.action_var.set('Look carefully at the path ahead.')
                    app.submit_button.invoke()
                assert app.busy, 'Choice button did not start the next turn'
                root.after(100,check)
                return
            assert app.state.turn == 1 and len(app.state.history) == 2
            app.resume_button.invoke()
            assert app.state.history == saved.history, 'Resume did not restore the actual save'
            root.after(500,finish)
        except Exception as exc:
            finish(repr(exc))

    root.after(200,app.play_button.invoke)
    root.after(400,check)
