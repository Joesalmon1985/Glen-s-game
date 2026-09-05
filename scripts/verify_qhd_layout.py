"""Inspect the real UI with a copied, previously generated adventure and artwork."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import shutil
import sys
import tkinter as tk
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import my_version_of_kawa as game

previous = ROOT / 'docs/verification/exe-proof/runtime-check-1788617890144752400/runtime-report.json'
record = json.loads(previous.read_text())
assert record['success']
original_save = Path(record['save'])
out = ROOT / 'docs/verification/qhd-layout'
(out / 'images').mkdir(parents=True, exist_ok=True)
shutil.copy2(original_save, out / 'adventure.json')
for image in (original_save.parent / 'images').glob('*.png'):
    shutil.copy2(image, out / 'images' / image.name)

game.enable_native_pixels()
root = tk.Tk()
app = game.PucaApp(root, data_dir=out, text_only=True)
app.resume_button.invoke()


def inspect():
    try:
        root.update_idletasks()
        native = wintypes.RECT()
        assert ctypes.windll.user32.GetClientRect(int(root.frame(), 16), ctypes.byref(native))
        assert [native.right, native.bottom] == [2560, 1440]
        assert app.state.turn == 1 and len(app.state.history) == 2
        assert app.image_label.image.width() == 768
        bounds = [root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height()]
        for widget in [app.name_entry, app.origin_entry, app.play_button, app.resume_button, app.action_entry, app.submit_button, app.retry_button, app.progress, *app.choice_buttons]:
            assert widget.winfo_ismapped(), str(widget)
            assert widget.winfo_rootx() >= bounds[0] and widget.winfo_rooty() >= bounds[1]
            assert widget.winfo_rootx() + widget.winfo_width() <= bounds[2]
            assert widget.winfo_rooty() + widget.winfo_height() <= bounds[3]
        screenshot = out / '1440p.png'
        ImageGrab.grab(window=int(root.frame(), 16)).save(screenshot)
        result = {'success': True, 'native_client_pixels': [native.right, native.bottom], 'art_pixels': [app.image_label.image.width(), app.image_label.image.height()], 'screenshot': str(screenshot), 'adventure_source': str(original_save), 'new_AI_generations': 0}
        (out / 'layout-report.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2), flush=True)
    finally:
        app.close()

root.after(1200, inspect)
root.mainloop()
assert (out / 'layout-report.json').is_file()
