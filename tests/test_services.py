import json
import tempfile
import unittest
from pathlib import Path
from puca_core import Scene, StoryState

class ContractTests(unittest.TestCase):
    def test_narrator_request_and_response(self):
        path = Path(__file__).resolve().parents[1] / 'puca_services.py'
        self.assertTrue(path.exists(), 'Missing validated narrator client')
        from puca_services import Narrator
        calls = []
        payload = {'narration': 'You return the lantern.', 'event': 'return', 'spirit': 'positive',
                   'image_prompt': 'a gate', 'location': 'gate', 'choices': ['Wait'], 'facts': ['The lantern was returned.']}
        def transport(url, data, timeout):
            calls.append((url, data))
            return {'response': json.dumps(payload)}
        client = Narrator(transport=transport)
        scene = client.ask(StoryState(name='Glen', origin='Home', arrived=True), 'Return it')
        self.assertEqual(scene.spirit, 'positive')
        body = calls[0][1]
        self.assertIn('num_predict', body['options'])
        self.assertNotIn('max_tokens', body)
        self.assertEqual(body['keep_alive'], 0)
        self.assertIn('system', body)
        self.assertEqual(body['format']['type'], 'object')

if __name__ == '__main__': unittest.main()
