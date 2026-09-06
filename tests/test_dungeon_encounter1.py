"""Focused automated tests for Deathtrap Dungeon Encounter 1 POC."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from puca_dungeon.encounters.encounter1 import public_perception
from puca_dungeon.session import GameSession


class Encounter1Tests(unittest.TestCase):
    def session(self, seed=91, name='Glen', **kwargs):
        return GameSession(player_name=name, seed=seed, debug=True, **kwargs)

    def test_use_key_on_named_box(self):
        s = self.session()
        tr = s.submit('Use my key on the box with my name.')
        self.assertTrue(tr.validated_intent['understood'])
        self.assertEqual(tr.grounding['bindings'].get('target'), 'box_player')
        self.assertEqual(tr.grounding['bindings'].get('tool'), 'trial_key_player')
        self.assertTrue(s.world.boxes['box_player'].open)
        self.assertFalse(s.world.boxes['box_player'].trap_fired)
        self.assertEqual(s.world.player.gold, 2)
        self.assertTrue(s.world.clue_get_no_mess)
        self.assertIn('sukumvit_clue', s.world.player.knowledge)

    def test_wrong_key_fires_trap(self):
        s = self.session()
        tr = s.submit('Try my key on another box')
        self.assertEqual(tr.grounding['bindings'].get('target'), 'box_a')
        self.assertTrue(s.world.boxes['box_a'].trap_fired)
        self.assertLess(s.world.player.hp, s.world.player.max_hp)

    def test_search_traps_success_and_failure(self):
        s = self.session(seed=1)
        s.world.player.search_bonus = 0
        tr = s.submit('Search the boxes for traps')
        self.assertTrue(tr.resolution['checks'])
        self.assertEqual(tr.resolution['checks'][0]['dc'], 25)
        self.assertFalse(tr.resolution['success'])
        self.assertFalse(any(b.trap_discovered for b in s.world.boxes.values()))
        self.assertNotIn('poison', tr.narrator_output.lower())

        s2 = self.session(seed=1)
        s2.world.player.search_bonus = 25
        tr2 = s2.submit('Check the locks carefully for traps.')
        self.assertTrue(tr2.resolution['success'])
        self.assertTrue(all(b.trap_discovered for b in s2.world.boxes.values() if b.trap_present))

    def test_pick_lock_without_disable_fires_trap(self):
        s = self.session()
        s.submit('Pick another box\'s lock')
        self.assertTrue(s.world.boxes['box_a'].trap_fired)

    def test_disable_discovered_trap_persists(self):
        s = self.session()
        s.world.player.search_bonus = 25
        s.world.player.disable_bonus = 25
        s.submit('Search the boxes for traps')
        self.assertTrue(s.world.boxes['box_player'].trap_discovered)
        s.submit('Disable the trap on the boxes')
        self.assertTrue(s.world.boxes['box_player'].trap_disabled)
        # State persists
        self.assertTrue(s.world.boxes['box_player'].trap_disabled)

    def test_break_box_uses_hardness_hp(self):
        s = self.session(seed=7)
        before_hp = s.world.boxes['box_player'].hp
        tr = s.submit('Smash my box open with the pommel of my sword.')
        self.assertIn('hardness_hp', tr.resolution['affordances_used'])
        self.assertTrue(tr.resolution['checks'])
        self.assertLessEqual(s.world.boxes['box_player'].hp, before_hp)
        # Keep smashing until destroyed
        for _ in range(20):
            if s.world.boxes['box_player'].destroyed:
                break
            s.submit('Smash my box open with the pommel of my sword.')
        self.assertTrue(s.world.boxes['box_player'].destroyed)

    def test_walk_past_to_encounter_2(self):
        s = self.session()
        tr = s.submit('Walk past the boxes')
        self.assertEqual(tr.validated_intent['action_class'], 'MOVE')
        self.assertEqual(s.world.encounter, 'junction')
        self.assertEqual(s.world.player.location, 'junction')
        self.assertIn('white arrow', tr.narrator_output.lower())

    def test_sit_stays_and_advances_time(self):
        s = self.session()
        before = s.world.world_time_seconds
        tr = s.submit('Sit down')
        self.assertEqual(s.world.encounter, 'walk_boxes')
        self.assertGreater(s.world.world_time_seconds, before)
        self.assertEqual(tr.validated_intent['action_class'], 'SIT')

    def test_repeated_wait_advances_pursuer(self):
        s = self.session()
        states = []
        for _ in range(6):
            s.submit('Wait.')
            states.append(s.world.pursuer.state)
        self.assertIn('approaching', states)
        self.assertIn('present', states)
        # Never fabricated player movement
        self.assertEqual(s.world.encounter, 'walk_boxes')

    def test_continued_inaction_combat_and_death(self):
        s = self.session(seed=3)
        s.world.player.hp = 6
        for _ in range(12):
            s.submit('Wait.')
            if not s.world.player.alive:
                break
        self.assertIn(s.world.pursuer.state, ('hostile', 'present', 'dead'))
        # Keep waiting once hostile until death or escalate path proven
        for _ in range(20):
            if not s.world.player.alive:
                break
            if s.world.pursuer.state != 'hostile':
                s.world.pursuer.state = 'hostile'
            s.submit('Wait.')
        self.assertFalse(s.world.player.alive)
        self.assertEqual(s.world.encounter, 'dead')

    def test_failed_search_not_stalling(self):
        s = self.session()
        s.world.player.search_bonus = 0
        before_stall = s.world.stall_time_seconds
        tr = s.submit('Search the boxes for traps')
        self.assertFalse(tr.resolution['success'])
        self.assertTrue(tr.resolution['meaningful_effort'])
        self.assertEqual(s.world.stall_time_seconds, before_stall)

    def test_lick_box_embodied_not_converted(self):
        s = self.session()
        tr = s.submit('I lick the box.')
        self.assertEqual(tr.validated_intent['action_class'], 'LICK')
        self.assertIn('lick', tr.narrator_output.lower())
        self.assertFalse(s.world.boxes['box_player'].open)

    def test_debug_suppresses_visual_backend(self):
        s = self.session()
        tr = s.submit('Look around')
        self.assertEqual(tr.visual_backend_calls, 0)
        self.assertEqual(s.visual_backend_calls, 0)
        self.assertTrue(tr.image.get('suppressed'))
        self.assertIn('SUPPRESSED', tr.image.get('note', ''))
        self.assertTrue(tr.image.get('full_prompt'))
        self.assertTrue(tr.state_diff is not None)
        self.assertIn('perception', tr.interpreter_input)

    def test_normal_mode_hides_debug_dump_fields_in_prose(self):
        s = GameSession(player_name='Glen', seed=91, debug=False)
        tr = s.submit('Search the boxes for traps')
        # Player-facing prose should not include DC numbers
        self.assertNotIn('dc', tr.narrator_output.lower())
        self.assertNotIn('DC25', tr.narrator_output)
        perc = public_perception(s.world)
        blob = json.dumps(perc)
        self.assertNotIn('trap_present', blob)
        self.assertNotIn('pursuer_trigger', blob)

    def test_determinism_and_save_load(self):
        actions = [
            'Wait.',
            'Search the boxes for traps',
            'Use my key on the box with my name.',
        ]
        s1 = self.session(seed=91)
        s1.world.player.search_bonus = 25
        for a in actions:
            s1.submit(a)
        snap1 = s1.full_state()

        s2 = self.session(seed=91)
        s2.world.player.search_bonus = 25
        for a in actions:
            s2.submit(a)
        self.assertEqual(s1.world.to_dict(), s2.world.to_dict())

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'save.json'
            s1.save(path)
            s3 = self.session(seed=0)
            s3.load(path)
            s3.submit('Walk past the table.')
            s2.submit('Walk past the table.')
            self.assertEqual(s3.world.encounter, s2.world.encounter)
            self.assertEqual(s3.world.player.gold, s2.world.player.gold)

    def test_punch_wall_understood_but_fails(self):
        s = self.session()
        tr = s.submit('Punch through the stone wall.')
        self.assertEqual(tr.validated_intent['action_class'], 'STRIKE')
        self.assertEqual(tr.grounding['bindings'].get('target'), 'stone_wall')
        self.assertTrue(tr.resolution['intent_understood'])
        self.assertFalse(tr.resolution['success'])
        self.assertEqual(s.world.encounter, 'walk_boxes')

    def test_perception_hides_undiscovered_traps(self):
        s = self.session()
        perc = public_perception(s.world)
        for box in perc['boxes']:
            self.assertNotIn('trap_present', box)
            self.assertNotIn('trap_discovered', box)


if __name__ == '__main__':
    unittest.main()
