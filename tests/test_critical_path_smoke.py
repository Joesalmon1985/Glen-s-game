"""Heuristic smoke tests for Deathtrap FF critical demo paths."""
from __future__ import annotations

import unittest

from puca_dungeon.interpret import HeuristicInterpreter
from puca_dungeon.session import GameSession


class CriticalPathSmokeTests(unittest.TestCase):
    def session(self, seed=91, name="Glen", **kwargs):
        kwargs.setdefault("interpreter", HeuristicInterpreter())
        kwargs.setdefault("debug", True)
        kwargs.setdefault("start_mode", "legacy_pack")
        return GameSession(player_name=name, seed=seed, **kwargs)

    def test_path_1_270_66(self):
        s = self.session(seed=91)
        self.assertEqual(s.world.passage_id, 1)
        s.submit("open my box")
        self.assertEqual(s.world.passage_id, 270)
        s.submit("continue")
        self.assertEqual(s.world.passage_id, 66)

    def test_path_1_66_101_37_attack_victory_400(self):
        s = self.session(seed=91)
        s.submit("continue north")
        self.assertEqual(s.world.passage_id, 66)
        s.submit("go west")
        self.assertEqual(s.world.passage_id, 101)
        s.submit("continue")
        self.assertEqual(s.world.passage_id, 37)
        self.assertTrue(s.world.combat.active)

        for _ in range(40):
            if not s.world.combat.active or not s.world.sheet.alive:
                break
            s.submit("attack")

        self.assertEqual(s.world.passage_id, 400)
        self.assertTrue(s.world.victory)
        self.assertEqual(s.world.ending, "victory")

    def test_drink_potion_and_eat_provision(self):
        s = self.session(seed=91, potion_id="potion_skill")
        s.world.sheet.skill = 1
        tr = s.submit("drink potion")
        self.assertTrue(tr.resolution.get("success"))
        self.assertEqual(s.world.sheet.skill, s.world.sheet.skill_initial)
        self.assertTrue(s.world.sheet.potion_used)

        s.world.sheet.stamina = max(1, s.world.sheet.stamina_initial - 6)
        before = s.world.sheet.stamina
        provisions_before = s.world.sheet.provisions
        tr2 = s.submit("eat a provision")
        self.assertTrue(tr2.resolution.get("success"))
        self.assertGreater(s.world.sheet.stamina, before)
        self.assertEqual(s.world.sheet.provisions, provisions_before - 1)

    def test_cartwheel_dismiss_stays_on_1(self):
        s = self.session()
        tr = s.submit("do a cartwheel")
        self.assertEqual(s.world.passage_id, 1)
        self.assertIn(
            tr.validated_intent["classification"],
            ("SYSTEMIC_ACTION", "GENERAL_WORLD_ACTION"),
        )
        out = tr.narrator_output.lower()
        self.assertTrue(
            'unimpressed' in out or 'unchanged' in out or 'cartwheel' in out
            or 'odd' in out or 'nothing' in out or 'shifts' in out,
            msg=out,
        )


if __name__ == "__main__":
    unittest.main()
