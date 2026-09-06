"""Native Tk integration with explicit synthetic collaborators, not AI-quality proof."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest

from puca_core import Scene, StoryState, load_state
from puca_services import GenerationError, Narrator, parse_scene

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('puca_integrated', ROOT / 'my_version_of_kawa.py')
app_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_module)

class FixedNarrator:
    def __init__(self):
        self.error = None
        self.calls = []
        self.last_request = None
        self.scene = Scene('You keep your promise and return the lantern.', 'promise', 'positive', 'a gate at dawn', 'gate', ('Wait',), ('The lantern has been returned.',))
    def ask(self, state, action):
        self.calls.append((state, action))
        self.last_request = {
            'url': 'http://127.0.0.1:11434/api/generate',
            'model': 'fixed',
            'prompt_context': {'player_action': action, 'player': state.name},
            'system_sha256': 'test',
            'system_chars': 0,
        }
        if self.error: raise self.error
        return self.scene

class ControlledImages:
    def __init__(self):
        self.use_lora = True
        self.calls = 0
        self.started = threading.Event()
        self.gate = threading.Event()
        self.error = None
    def release_gpu(self): pass
    def key(self, location, prompt):
        return 'a' * 64
    def generate(self, *args, **kwargs):
        self.calls += 1
        self.started.set()
        if not self.gate.wait(4): raise RuntimeError('TEST image wait expired')
        if self.error: raise self.error
        from PIL import Image
        self.path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (512, 512), 'navy').save(self.path)
        return 'a' * 64, self.path

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.narrator = FixedNarrator()
        self.images = ControlledImages()
        self.app = app_module.PucaApp(self.root, data_dir=Path(self.temp.name), narrator=self.narrator, images=self.images)
        self.images.path = self.app.cache_dir / ('a' * 64 + '.png')
        self.app.state = StoryState(name='Audit player', origin='Home')
        self.app._show_image = lambda path: None  # explicit image-display seam; no generated pixels claimed

    def tearDown(self):
        self.images.gate.set()
        worker = self.app.worker
        if worker: worker.join(timeout=5)
        self.app.close()
        self.temp.cleanup()

    def spin(self, predicate, timeout=3):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.root.update()
            if predicate(): return
            time.sleep(0.01)
        self.fail('Timed out waiting for observed GUI state')

    def test_text_is_visible_before_image_and_second_action_is_blocked(self):
        self.app._launch('(begin)')
        self.spin(lambda: self.app.state.arrived and self.images.started.is_set())
        self.assertIn('return the lantern', self.app.story.get('1.0', 'end'))
        self.assertTrue(self.app.busy)
        self.app.action_var.set('Second action')
        self.app.submit()
        self.assertEqual(len(self.narrator.calls), 1)
        self.images.gate.set()
        self.spin(lambda: not self.app.busy)
        self.assertEqual(self.app.state.turn, 0)
        self.assertEqual(load_state(self.app.save_path).image_key, 'a' * 64)

    def test_narrator_failure_does_not_spend_turn_and_retry_commits_once(self):
        self.app.images_var.set(False)
        self.narrator.error = GenerationError('TEST service unavailable')
        self.app._launch('(begin)')
        self.spin(lambda: not self.app.busy)
        self.assertFalse(self.app.state.arrived)
        self.assertFalse(self.app.save_path.exists())
        self.assertEqual(self.app.state.spirit, 100)
        self.assertTrue(self.app.failed_action)
        self.narrator.error = None
        self.app.retry()
        self.spin(lambda: not self.app.busy)
        self.assertEqual(len(self.app.state.history), 1)
        self.assertTrue(self.app.state.arrived)

    def test_debug_records_command_options_engine_and_image_payload(self):
        self.app.images_var.set(False)
        self.app.debug_var.set(True)
        self.app._toggle_debug()
        self.app.action_source = 'opening'
        self.app._launch('(The adventure begins)')
        self.spin(lambda: not self.app.busy)
        data = json.loads(self.app.debug_path.read_text(encoding='utf-8'))
        self.assertEqual(data['player_command'], '(The adventure begins)')
        self.assertEqual(data['action_source'], 'opening')
        self.assertEqual(data['sent_to_narrator']['prompt_context']['player_action'], '(The adventure begins)')
        self.assertEqual(data['interpretation']['spirit'], 'positive')
        self.assertEqual(data['sent_to_game_engine']['spirit_delta'], 0)
        self.assertEqual(data['sent_to_image_generation']['status'], 'skipped_illustrations_off')
        self.assertIn('pixel art', data['sent_to_image_generation']['full_prompt'])
        panel = self.app.debug_text.get('1.0', 'end')
        self.assertIn('sent_to_narrator', panel)
        self.app.choose('Wait')
        self.spin(lambda: not self.app.busy)
        data = json.loads(self.app.debug_path.read_text(encoding='utf-8'))
        self.assertEqual(data['player_command'], 'Wait')
        self.assertEqual(data['action_source'], 'choice_button')
        self.assertIn('Wait', data['options_available_at_submit'])
        self.assertEqual(data['sent_to_game_engine']['spirit_classification'], 'positive')
        self.assertEqual(data['sent_to_game_engine']['turn_after'], 1)
        self.assertEqual(data['interpretation']['choices'], ['Wait'])

    def test_image_failure_keeps_story_and_image_retry_does_not_repeat_turn(self):
        self.images.error = RuntimeError('TEST CUDA failure')
        self.images.gate.set()
        self.app._launch('(begin)')
        self.spin(lambda: not self.app.busy)
        self.assertTrue(self.app.state.arrived)
        self.assertTrue(self.app.image_failed)
        self.assertEqual(len(self.app.state.history), 1)
        self.assertTrue(self.app.save_path.exists())
        self.images.error = None
        self.app.retry()
        self.spin(lambda: not self.app.busy)
        self.assertEqual(len(self.narrator.calls), 1)
        self.assertEqual(len(self.app.state.history), 1)
        self.assertEqual(self.app.state.image_key, 'a' * 64)

    def test_full_session_reuses_same_location_image_and_preserves_final_narration(self):
        self.images.gate.set()
        self.app._launch('(begin)')
        self.spin(lambda: not self.app.busy)
        for i in range(10):
            self.app.action_var.set(f'Keep promise {i}')
            self.app.submit()
            self.spin(lambda: not self.app.busy)
        self.assertEqual(self.images.calls, 1)
        self.assertEqual(self.app.state.turn, 10)
        self.assertEqual(self.app.state.spirit, 100)
        self.assertTrue(self.app.state.finished)
        self.assertIn('Spirit 100/100', self.app.score.cget('text'))
        text = self.app.story.get('1.0', 'end')
        self.assertIn('Choice 10: Keep promise 9', text)
        self.assertIn('Your adventure is complete', text)
        self.assertIn('return the lantern', text)
        self.assertEqual(load_state(self.app.save_path).history, self.app.state.history)
        self.app.resume()
        self.assertTrue(self.app.state.finished)
        self.assertEqual(str(self.app.submit_button.cget('state')), 'disabled')

    def test_close_during_generation_has_no_worker_tk_calls(self):
        self.app._launch('(begin)')
        self.spin(lambda: self.images.started.is_set())
        worker = self.app.worker
        self.app.close()
        self.images.gate.set()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(self.app.closed)

class ProtocolTests(unittest.TestCase):
    def test_invalid_json_and_outcome_are_rejected(self):
        client = Narrator(transport=lambda *a, **k: {'response': 'not JSON'})
        state = StoryState(name='Glen', origin='Home')
        with self.assertRaises(GenerationError): client.ask(state, 'Start')
        self.assertEqual((state.turn, state.spirit, state.history), (0, 100, []))
        for payload in [None, {}, {'spirit': 'POSITIVE'}, {'narration': 'a' * 2500}]:
            with self.assertRaises(GenerationError): parse_scene(payload)

    def test_final_turn_requests_resolution_and_keeps_earlier_choices(self):
        calls = []
        scene = {'narration': 'You return home.', 'event': 'home', 'spirit': 'neutral', 'image_prompt': 'home', 'location': 'home', 'choices': [], 'facts': []}
        def transport(url, body, timeout):
            calls.append(body)
            return {'response': json.dumps(scene)}
        state = StoryState(name='Glen', origin='Home', arrived=True, turn=9, facts=['You promised to return the lantern.'], history=[{'action': 'Keep the promise', 'narration': 'You remember.'}])
        Narrator(transport=transport).ask(state, 'Return home')
        context = json.loads(calls[0]['prompt'])
        self.assertEqual(context['phase'], 'final resolution')
        self.assertIn('lantern', context['established_facts'][0])
        self.assertEqual(context['recent_turns'][0]['action'], 'Keep the promise')

if __name__ == '__main__': unittest.main()
