import unittest
import test_integration as helpers

class RecoveryEdgeTests(unittest.TestCase):
    setUp = helpers.IntegrationTests.setUp
    tearDown = helpers.IntegrationTests.tearDown
    spin = helpers.IntegrationTests.spin

    def test_image_cleanup_failure_does_not_break_text_play(self):
        self.app.images_var.set(False)
        def broken_cleanup():
            raise RuntimeError('TEST previous CUDA cleanup failed')
        self.images.release_gpu = broken_cleanup
        self.app._launch('(begin)')
        self.spin(lambda: not self.app.busy)
        self.assertTrue(self.app.state.arrived, 'Optional image cleanup must not break narration')
        self.assertEqual(len(self.narrator.calls), 1)

if __name__ == '__main__': unittest.main()
