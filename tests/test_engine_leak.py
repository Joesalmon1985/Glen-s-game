"""Unit tests for engine_leak.scan_player_facing_text."""
from __future__ import annotations

import unittest

from puca_dungeon import engine_leak


class EngineLeakScannerTests(unittest.TestCase):
    def test_clean_prose(self):
        self.assertEqual(
            engine_leak.scan_player_facing_text(
                'Damp stone presses close. Nothing answers your call.'
            ),
            [],
        )

    def test_stamina_skill_luck(self):
        hits = engine_leak.scan_player_facing_text(
            'Your STAMINA falls. SKILL is useless. Test your LUCK now.'
        )
        lowered = {h.lower() for h in hits}
        self.assertIn('stamina', lowered)
        self.assertIn('skill', lowered)
        self.assertTrue(any('luck' in h for h in lowered))

    def test_attack_strength(self):
        hits = engine_leak.scan_player_facing_text(
            'Your Attack Strength beats the foe.'
        )
        self.assertTrue(any('attack strength' in h.lower() for h in hits))

    def test_assert_clean_raises(self):
        with self.assertRaises(AssertionError):
            engine_leak.assert_clean('lose 2 STAMINA immediately')

    def test_assert_clean_ok(self):
        engine_leak.assert_clean('The tunnel-hound takes the opening and strikes.')

    def test_any_leaks_across_texts(self):
        hits = engine_leak.any_leaks([
            'Fine prose.',
            'Adventure Sheet beckons.',
            'Still fine.',
        ])
        self.assertTrue(any('adventure sheet' in h.lower() for h in hits))

    def test_empty_and_noneish(self):
        self.assertEqual(engine_leak.scan_player_facing_text(''), [])
        self.assertEqual(engine_leak.scan_player_facing_text(None), [])  # type: ignore[arg-type]


if __name__ == '__main__':
    unittest.main()
