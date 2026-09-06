import json
import tempfile
import unittest
from pathlib import Path

from puca_core import Scene, StoryState
from puca_debug import TurnDebug, image_payload, narrator_request_meta, scene_as_dict, write_last_turn
from puca_services import Narrator


class DebugTraceTests(unittest.TestCase):
    def test_narrator_ask_exposes_request_meta_with_player_action(self):
        payload = {
            'narration': 'You return the lantern.', 'event': 'return', 'spirit': 'positive',
            'image_prompt': 'a gate', 'location': 'gate', 'choices': ['Wait'], 'facts': ['The lantern was returned.'],
            'visual_changed': False,
        }
        calls = []

        def transport(url, data, timeout):
            calls.append((url, data))
            return {'response': json.dumps(payload)}

        client = Narrator(transport=transport)
        scene = client.ask(StoryState(name='Glen', origin='Home', arrived=True), 'Return it')
        self.assertEqual(scene.spirit, 'positive')
        self.assertIsNotNone(client.last_request)
        context = client.last_request['prompt_context']
        self.assertEqual(context['player_action'], 'Return it')
        self.assertEqual(context['player'], 'Glen')
        self.assertEqual(client.last_request['model'], 'mistral')
        self.assertIn('system_sha256', client.last_request)

    def test_build_request_matches_transport_body(self):
        client = Narrator(transport=lambda *a, **k: {'response': '{}'})
        body = client.build_request(StoryState(name='Glen', origin='Home'), 'Look around')
        meta = narrator_request_meta(client.url, body)
        self.assertEqual(meta['prompt_context']['player_action'], 'Look around')
        self.assertEqual(body['options']['num_predict'], 900)

    def test_image_payload_reports_skipped_when_illustrations_off(self):
        payload = image_payload(
            'gate', 'a lantern', use_lora=True, need_image=True, reasons=['no_cached_image_key'],
            images_enabled=False, cache_key='ab' * 32)
        self.assertEqual(payload['status'], 'skipped_illustrations_off')
        self.assertIn('pixel art', payload['full_prompt'])
        self.assertIn('a lantern', payload['full_prompt'])
        self.assertEqual(payload['negative_prompt'], 'photorealistic, blurry, text, watermark, explicit, gore')

    def test_write_last_turn(self):
        turn = TurnDebug(player_command='Wait', action_source='choice_button',
                         options_available_at_submit=['Wait', 'Leave'],
                         interpretation=scene_as_dict(Scene(
                             'Quiet.', 'pause', 'neutral', 'a hall', 'hall', ('Leave',), ())))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'debug-last-turn.json'
            write_last_turn(path, turn)
            loaded = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(loaded['player_command'], 'Wait')
            self.assertEqual(loaded['options_available_at_submit'], ['Wait', 'Leave'])


class IllustrationRefreshTests(unittest.TestCase):
    def test_prompt_change_requests_new_image_without_visual_flag(self):
        """Same location + visual_changed=False must still refresh when image_prompt changes."""
        from puca_images import ImageGenerator

        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            gen = ImageGenerator(cache, cache / 'lora', use_lora=False)
            old_prompt = 'a quiet gate at dusk'
            new_prompt = 'the same gate, now open, lantern light spilling out'
            old_key = gen.key('gate', old_prompt)
            new_key = gen.key('gate', new_prompt)
            self.assertNotEqual(old_key, new_key)

            class App:
                cache_dir = cache
                images = gen

                def _need_image_reasons(self, snapshot, location, scene, prompt=None):
                    import my_version_of_kawa as kawa
                    return kawa.PucaApp._need_image_reasons(self, snapshot, location, scene, prompt)

            app = App()
            snapshot = StoryState(name='Glen', origin='Home', arrived=True, location='gate', image_key=old_key)
            (cache / (old_key + '.png')).write_bytes(b'')  # presence only; validity checked separately
            from PIL import Image
            Image.new('RGB', (512, 512), 'navy').save(cache / (old_key + '.png'))
            scene = Scene('The gate opens.', 'open', 'neutral', new_prompt, 'gate',
                          visual_changed=False)
            reasons = app._need_image_reasons(snapshot, 'gate', scene, new_prompt)
            self.assertIn('illustration_content_changed', reasons)
            self.assertTrue(reasons)

            same = Scene('You wait.', 'wait', 'neutral', old_prompt, 'gate', visual_changed=False)
            unchanged = app._need_image_reasons(snapshot, 'gate', same, old_prompt)
            self.assertNotIn('illustration_content_changed', unchanged)
            self.assertEqual(unchanged, [])


if __name__ == '__main__':
    unittest.main()
