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

if __name__ == '__main__': unittest.main()
