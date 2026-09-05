import copy
import json
from pathlib import Path
import queue
import tempfile
import threading
import types
import unittest
from unittest.mock import patch, Mock

import test_integration as helpers
import my_version_of_kawa as app_module
from puca_core import StoryState, Scene, save_state, load_state
from puca_images import ImageGenerator
from puca_services import Narrator, RULES

class SaveRepairTests(unittest.TestCase):
    setUp = helpers.IntegrationTests.setUp
    tearDown = helpers.IntegrationTests.tearDown
    spin = helpers.IntegrationTests.spin

    def test_failed_save_keeps_prior_state_and_retry_reuses_scene(self):
        self.app.images_var.set(False)
        with patch.object(helpers.app_module, 'save_state', side_effect=OSError('TEST disk full')):
            self.app._launch('(begin)')
            self.spin(lambda: not self.app.busy)
        self.assertFalse(self.app.state.arrived, 'Failed persistence must not spend the scene')
        self.assertEqual(len(self.app.state.history), 0)
        self.app.retry()
        self.spin(lambda: not self.app.busy)
        self.assertTrue(self.app.state.arrived)
        self.assertEqual(len(self.narrator.calls), 1, 'Save retry must not reroll the story')

    def test_missing_resumed_image_exposes_image_retry(self):
        self.app.state.apply('(begin)', self.narrator.scene, opening=True)
        self.app.state.image_key = 'b' * 64
        save_state(self.app.save_path, self.app.state)
        self.app.resume()
        self.assertTrue(self.app.image_failed)
        self.assertEqual(self.app.state.image_key, '')

class FinalRepairTests(unittest.TestCase):
    def test_corrupt_cache_is_not_returned(self):
        with tempfile.TemporaryDirectory() as folder:
            gen = ImageGenerator(folder, Path(folder) / 'lora', use_lora=False)
            dest = Path(folder) / (gen.key('gate', 'gate') + '.png')
            dest.write_bytes(b'not a PNG')
            gen._load_pipeline = Mock(side_effect=RuntimeError('TEST reload requested'))
            with self.assertRaisesRegex(RuntimeError, 'reload requested'):
                gen.generate('gate', 'gate')
            self.assertFalse(dest.exists())

    def test_enabled_missing_adapter_does_not_use_base_cache_key(self):
        with tempfile.TemporaryDirectory() as folder:
            gen = ImageGenerator(folder, Path(folder) / 'missing', use_lora=True)
            with self.assertRaisesRegex(RuntimeError, 'adapter'):
                gen.key('gate', 'gate')

    def test_cancel_during_load_prevents_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            gen = ImageGenerator(folder, Path(folder) / 'lora', use_lora=False)
            cancel = threading.Event()
            pipe = Mock()
            def load():
                gen.pipe = pipe
                cancel.set()
            gen._load_pipeline = load
            gen.release_gpu = Mock()
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                gen.generate('gate', 'gate', cancel=cancel)
            pipe.assert_not_called()

    def test_dead_voice_worker_can_restart(self):
        voice = app_module.Voice(queue.Queue())
        voice.enabled.set()
        dead = types.SimpleNamespace(is_alive=lambda: False)
        voice.thread = dead
        with patch.object(app_module.threading, 'Thread') as factory:
            voice.speak('A new sentence')
            factory.assert_called_once()

    def test_inconsistent_save_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            state = StoryState(name='Glen', origin='Home')
            state.apply('(begin)', Scene('You arrive.', 'arrival', 'neutral', 'gate', 'gate'), opening=True)
            dest = Path(folder) / 'save.json'
            save_state(dest, state)
            payload = json.loads(dest.read_text())
            payload['state']['history'][0]['spirit_delta'] = 10
            payload['state']['location'] = 'wrong place'
            dest.write_text(json.dumps(payload))
            with self.assertRaises(ValueError): load_state(dest)

    def test_prompt_has_conservative_input_budget(self):
        calls = []
        state = StoryState(name='Glen', origin='Home', arrived=True, turn=9,
                           facts=['fact ' + ('x' * 230) for _ in range(44)],
                           history=[{'action': 'a' * 800, 'narration': 'n' * 2400} for _ in range(3)])
        payload = {'narration':'You wait.', 'event':'wait','spirit':'neutral','image_prompt':'gate','location':'gate','choices':[],'facts':[]}
        def send(url, body, timeout):
            calls.append(body)
            return {'response':json.dumps(payload)}
        Narrator(transport=send).ask(state, 'a' * 800)
        body = calls[0]
        # UTF-8 bytes is a deliberately conservative token upper bound.
        self.assertLessEqual(len(body['prompt'].encode()) + len(body['system'].encode()) + body['options']['num_predict'] + 256,
                             body['options']['num_ctx'])

if __name__ == '__main__': unittest.main()
