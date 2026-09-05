import importlib.util
import pathlib
import tempfile
import tkinter as tk
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class GuiTests(unittest.TestCase):
    def test_game_imports_without_torch_and_busy_guard(self):
        spec = importlib.util.spec_from_file_location('puca_app_under_test', ROOT / 'my_version_of_kawa.py')
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ImportError as exc:
            self.fail(f'Text play must not import optional image dependencies: {exc}')
        self.assertTrue(hasattr(module, 'PucaApp'), 'Missing queue-driven app')
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            root.withdraw()
            try:
                app = module.PucaApp(root, data_dir=pathlib.Path(folder), text_only=True)
                app.busy = True
                app.action_var.set('Wait')
                app.submit()
                self.assertEqual(app.action_var.get(), 'Wait')
                self.assertIsNone(app.worker)
                app.close()
            finally:
                try:
                    if root.winfo_exists(): root.destroy()
                except tk.TclError:
                    pass

if __name__ == '__main__': unittest.main()
