import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class StoryTests(unittest.TestCase):
    def test_spirit_direction_is_not_random(self):
        path = ROOT / 'puca_core.py'
        self.assertTrue(path.exists(), 'Missing deterministic story engine')
        import puca_core as core
        state = core.StoryState(name='Glen', origin='Home', spirit=60, arrived=True)
        state.apply('Help', core.Scene('You help.', 'help', 'positive', 'a gate', 'gate'), opening=False)
        self.assertEqual(state.spirit, 70)
        state.apply('Betray', core.Scene('You betray.', 'betrayal', 'negative', 'a gate', 'gate'), opening=False)
        self.assertEqual(state.spirit, 58)

    def test_save_resume_and_actual_end_score(self):
        import tempfile
        from pathlib import Path
        import puca_core as core
        state = core.StoryState(name='Glen', origin='Home')
        opening = core.Scene('A gate appears.', 'arrival', 'negative', 'gate', 'gate')
        state.apply('(begin)', opening, opening=True)
        self.assertEqual((state.spirit, state.turn), (100, 0))
        for i in range(10):
            state.apply('Look', core.Scene('You look.', 'observe', 'neutral', 'gate', 'gate'))
        self.assertTrue(state.finished)
        self.assertEqual(state.spirit, 100)
        self.assertTrue(hasattr(core, 'save_state'), 'Missing atomic save/resume')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'save.json'
            core.save_state(path, state)
            restored = core.load_state(path)
            self.assertEqual(restored, state)
            path.write_text('{"version": 1, "state": {"spirit": -10}}')
            with self.assertRaises(ValueError): core.load_state(path)

if __name__ == '__main__':
    unittest.main()
