import pathlib
import tempfile
import tkinter as tk
import unittest
import my_version_of_kawa as app_module

class ChoiceLabelTests(unittest.TestCase):
    def test_suggestion_labels_are_not_squeezed_to_a_few_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            app = app_module.PucaApp(root, data_dir=pathlib.Path(folder), text_only=True)
            try:
                app._choices(['Ask the stranger about the promise you made beneath the old wooden bridge'] * 3)
                root.update()
                for button in app.choice_buttons:
                    self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
            finally:
                app.close()
