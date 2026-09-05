"""Presentation-only checks: physical QHD size and CPU-scaled cached artwork."""
import ctypes
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import font as tkfont
import unittest
from PIL import Image
import my_version_of_kawa as game

class QhdLayoutTests(unittest.TestCase):
    def test_qhd_window_and_cached_art_scale_without_generation(self):
        if hasattr(ctypes, 'windll'):
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        root = tk.Tk()
        with tempfile.TemporaryDirectory() as folder:
            app = game.PucaApp(root, data_dir=Path(folder), text_only=True)
            try:
                root.update()
                self.assertEqual((root.winfo_width(), root.winfo_height()), (2560, 1440))
                self.assertGreaterEqual(tkfont.Font(font=app.story.cget('font')).cget('size'), 18)
                self.assertGreaterEqual(app.art_panel.winfo_width(), 800)
                path = Path(folder) / 'fixture.png'
                Image.new('RGB', (512, 512), 'navy').save(path)
                self.assertTrue(app._show_image(path))
                root.update()
                self.assertEqual(app.image_label.image.width(), 768)
                self.assertEqual(app.image_label.image.height(), 768)
                app._choices(['Ask the stranger about the promise you made beneath the old wooden bridge'] * 3)
                root.update()
                for widget in [app.action_entry, app.submit_button, app.retry_button, app.progress, *app.choice_buttons]:
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), root.winfo_rooty() + root.winfo_height())
                root.geometry('1080x800')
                root.update()
                self.assertLessEqual(app.image_label.image.width(), app.art_panel.winfo_width())
                self.assertLessEqual(app.image_label.image.height(), app.art_panel.winfo_height())
                self.assertIsNone(app.images.pipe, 'Display scaling must not load the image AI')
            finally:
                app.close()
