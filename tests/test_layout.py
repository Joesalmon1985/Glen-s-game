import importlib.util
from pathlib import Path
import tempfile
import tkinter as tk
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('puca_layout_test', ROOT / 'my_version_of_kawa.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class LayoutTests(unittest.TestCase):
    def test_action_and_retry_controls_fit_inside_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = tk.Tk()
            app = module.PucaApp(root, data_dir=Path(directory), text_only=True)
            try:
                root.geometry('1080x800')
                root.update()
                bottom = root.winfo_rooty() + root.winfo_height()
                for widget in [app.submit_button, app.retry_button, app.progress]:
                    self.assertTrue(widget.winfo_ismapped(), 'Essential control was not mapped')
                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), bottom, 'Essential control is below the window')
            finally:
                app.close()

    def test_all_three_suggestions_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = tk.Tk()
            app = module.PucaApp(root, data_dir=Path(directory), text_only=True)
            try:
                root.geometry('1080x800')
                app._choices(['Ask the stranger about the promise you made beneath the old wooden bridge'] * 3)
                root.update()
                right = root.winfo_rootx() + root.winfo_width()
                for button in app.choice_buttons:
                    self.assertTrue(button.winfo_ismapped(), 'A suggested action is hidden')
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), right)
            finally:
                app.close()
