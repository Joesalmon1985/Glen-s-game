"""Fighting Fantasy Deathtrap Dungeon gamebook engine tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from puca_dungeon.content_loader import PASSAGES_DIR, load_passage
from puca_dungeon.graph_validate import validate_pack
from puca_dungeon.interpret import HeuristicInterpreter
from puca_dungeon.resolve import Resolution, goto_passage
from puca_dungeon.session import GameSession


class DeathtrapFFTests(unittest.TestCase):
    def session(self, seed=91, name='Glen', **kwargs):
        kwargs.setdefault('interpreter', HeuristicInterpreter())
        kwargs.setdefault('debug', True)
        return GameSession(player_name=name, seed=seed, **kwargs)

    def test_graph_validate_full_pack(self):
        report = validate_pack()
        cov = report['coverage']
        self.assertEqual(cov['expected'], 400)
        self.assertEqual(cov['present'], 400)
        self.assertEqual(cov['missing_in_range'], [])
        self.assertEqual(len(list(PASSAGES_DIR.glob('*.json'))), 400)

        for link in report['bad_links']:
            to = link.get('to')
            if to is None:
                continue
            try:
                tid = int(to)
            except (TypeError, ValueError):
                self.fail(f'non-integer link target from {link.get("from")}: {to!r}')
            self.assertGreaterEqual(tid, 1, msg=link)
            self.assertLessEqual(tid, 400, msg=link)

        out_of_range = [b for b in report['bad_links'] if b.get('reason') == 'out_of_range']
        self.assertEqual(out_of_range, [])

    def test_opening_fork_box_and_north(self):
        s = self.session(seed=91)
        gold_before = s.world.sheet.gold
        tr = s.submit('open my box')
        self.assertEqual(s.world.passage_id, 270)
        self.assertEqual(s.world.sheet.gold, gold_before + 2)
        self.assertIn('clue_get_no_mess', s.world.sheet.knowledge)
        self.assertIn('sukumvit_clue', s.world.sheet.inventory)
        self.assertTrue(tr.resolution.get('success'))

        s2 = self.session(seed=91)
        s2.submit('continue north')
        self.assertEqual(s2.world.passage_id, 66)

    def test_dismiss_cartwheel_stays_on_1(self):
        s = self.session()
        tr = s.submit('do a cartwheel')
        self.assertEqual(s.world.passage_id, 1)
        self.assertIn(tr.validated_intent['classification'], (
            'SILLY_BUT_VALID', 'GENERAL_WORLD_ACTION',
        ))
        out = tr.narrator_output.lower()
        self.assertTrue(
            'unimpressed' in out or 'unchanged' in out or 'cartwheel' in out or 'odd' in out,
            msg=out,
        )

    def test_perception_inventory_no_passage_change(self):
        s = self.session()
        tr = s.submit('what is my inventory')
        self.assertEqual(s.world.passage_id, 1)
        self.assertEqual(tr.validated_intent['classification'], 'PERCEPTION_QUERY')
        blob = ' '.join(tr.resolution['facts']).lower() + ' ' + tr.narrator_output.lower()
        self.assertTrue(
            'sword' in blob or 'carrying' in blob or 'inventory' in blob,
            msg=blob,
        )

    def test_combat_smoke_win_or_flee(self):
        # Path 1 → 66 → 101 → 37 (Giant Rat); seed 91 wins to 400
        s = self.session(seed=91)
        for cmd in ('continue north', 'go west', 'continue'):
            s.submit(cmd)
        self.assertEqual(s.world.passage_id, 37)
        self.assertTrue(s.world.combat.active)

        for _ in range(40):
            if not s.world.combat.active or not s.world.sheet.alive:
                break
            s.submit('attack')
        self.assertEqual(s.world.passage_id, 400)
        self.assertTrue(s.world.victory)
        self.assertEqual(s.world.ending, 'victory')

        s2 = self.session(seed=91)
        for cmd in ('continue north', 'go west', 'continue'):
            s2.submit(cmd)
        self.assertTrue(s2.world.combat.active)
        s2.submit('flee')
        self.assertEqual(s2.world.passage_id, 66)
        self.assertFalse(s2.world.combat.active)

    def test_potion_once_then_fail(self):
        s = self.session(seed=91, potion_id='potion_skill')
        s.world.sheet.skill = 1
        tr = s.submit('drink potion')
        self.assertTrue(tr.resolution.get('success'))
        self.assertEqual(s.world.sheet.skill, s.world.sheet.skill_initial)
        self.assertTrue(s.world.sheet.potion_used)

        tr2 = s.submit('drink potion')
        self.assertFalse(tr2.resolution.get('success'))
        self.assertEqual(tr2.resolution.get('rejection_reason'), 'potion_already_used')
        facts = ' '.join(tr2.resolution['facts']).lower()
        self.assertIn('already', facts)

    def test_eat_provision_raises_stamina(self):
        s = self.session(seed=91)
        s.world.sheet.stamina = max(1, s.world.sheet.stamina_initial - 6)
        before = s.world.sheet.stamina
        provisions_before = s.world.sheet.provisions
        tr = s.submit('eat a provision')
        self.assertTrue(tr.resolution.get('success'))
        self.assertGreater(s.world.sheet.stamina, before)
        self.assertEqual(s.world.sheet.provisions, provisions_before - 1)

    def test_death_ending_via_399(self):
        s = self.session(seed=91)
        res = Resolution()
        goto_passage(s.world, 399, s.rng, res)
        self.assertEqual(s.world.passage_id, 399)
        self.assertEqual(s.world.ending, 'death')
        self.assertFalse(s.world.sheet.alive)
        self.assertFalse(s.world.victory)

    def test_save_load_roundtrip(self):
        s = self.session(seed=91)
        s.submit('open my box')
        skill = s.world.sheet.skill
        passage = s.world.passage_id
        self.assertEqual(passage, 270)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ff_save.json'
            s.save(path)
            s2 = self.session(seed=0)
            s2.load(path)
            self.assertEqual(s2.world.passage_id, passage)
            self.assertEqual(s2.world.sheet.skill, skill)

    def test_load_passage_1_has_two_choices(self):
        p = load_passage(1)
        self.assertEqual(p.id, 1)
        self.assertEqual(len(p.choices), 2)
        destinations = {c.get('to') for c in p.choices}
        self.assertEqual(destinations, {270, 66})


if __name__ == '__main__':
    unittest.main()
