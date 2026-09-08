from pathlib import Path
import tempfile
import unittest

class ImageTests(unittest.TestCase):
    def test_cached_image_does_not_load_gpu(self):
        path = Path(__file__).resolve().parents[1] / 'puca_images.py'
        self.assertTrue(path.exists(), 'Missing lazy, cached image service')
        from puca_images import ImageGenerator
        with tempfile.TemporaryDirectory() as folder:
            gen = ImageGenerator(Path(folder), Path(folder) / 'lora', use_lora=False)
            key = gen.key('gate', 'a blue gate')
            expected = Path(folder) / (key + '.png')
            from PIL import Image
            Image.new('RGB', (512, 512), 'navy').save(expected)
            gen._load_pipeline = lambda: self.fail('Cached image must not load AI')
            self.assertEqual(gen.generate('gate', 'a blue gate')[0], key)
            self.assertIsNone(gen.pipe)

    def test_narration_cues_join_game_state_in_prompt(self):
        from puca_dungeon.facility_models import make_initial_facility
        from puca_dungeon.image_prompt import build_image_prompt, extract_visual_cues_from_narration
        from puca_dungeon.models import AdventureSheet, WorldState
        from puca_dungeon.rng import GameRNG

        cues = extract_visual_cues_from_narration(
            'You look at the open slit. "Stand back," someone says. Water darkens the floor by the cup.'
        )
        self.assertIn('slit', cues.lower())
        self.assertNotIn('Stand back', cues)

        rng = GameRNG.from_seed(7)
        world = WorldState(
            sheet=AdventureSheet(name='Test'),
            mode='facility',
            facility=make_initial_facility(rng),
        )
        prompt = build_image_prompt(
            world,
            narration='You wake on the mattress and see spilled water near the cup. The slit is open.',
        )
        self.assertIn('facility', prompt)
        self.assertIn('from narration:', prompt)
        self.assertIn('mattress', prompt.lower())
        self.assertIn('pixel art', prompt.lower())


if __name__ == '__main__':
    unittest.main()
