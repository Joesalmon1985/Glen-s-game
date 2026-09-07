"""Permanent offline regressions from unsuccessful human playtest (architectural)."""
from __future__ import annotations

import unittest

from puca_dungeon import discourse, engine_leak
from puca_dungeon.interpret import HeuristicInterpreter
from puca_dungeon.narrate import TemplateNarrator
from puca_dungeon.resolve import goto_passage, Resolution
from puca_dungeon.session import GameSession


def _session(**kwargs) -> GameSession:
    kwargs.setdefault('interpreter', HeuristicInterpreter())
    kwargs.setdefault('allow_heuristic_fallback', True)
    kwargs.setdefault('narrator', TemplateNarrator())
    kwargs.setdefault('debug', True)
    kwargs.setdefault('seed', 91)
    kwargs.setdefault('start_mode', 'legacy_pack')
    return GameSession(**kwargs)


def _force_combat_37(s: GameSession) -> None:
    """Put session on passage 37 with live combat via spine or goto."""
    res = Resolution()
    goto_passage(s.world, 37, s.rng, res)
    s.world.combat.active = True
    assert s.world.passage_id == 37
    assert s.world.combat.active


class AdversarialRealityRegressions(unittest.TestCase):
    def test_look_around_stays_on_1(self):
        s = _session()
        tr = s.submit('look around')
        self.assertEqual(s.world.passage_id, 1)
        self.assertEqual(tr.validated_intent.get('classification'), 'PERCEPTION_QUERY')
        self.assertIsNone(tr.validated_intent.get('matched_action_id'))
        self.assertIn(tr.resolution.get('passage_entered'), (None, 1))

    def test_turn_into_dragon_no_magic(self):
        s = _session()
        before_potion = s.world.sheet.potion_used
        tr = s.submit('turn into a dragon')
        self.assertFalse(s.world.sheet.potion_used)
        self.assertEqual(before_potion, False)
        self.assertIn(
            tr.validated_intent.get('classification'),
            ('IMPOSSIBLE_ATTEMPT', 'UNGROUNDED_ENTITY', 'SYSTEMIC_ACTION'),
        )
        self.assertFalse(tr.resolution.get('success'))
        self.assertNotEqual(tr.validated_intent.get('matched_action_id'), 'item.use_potion')
        prose = (tr.narrator_output or '').lower()
        self.assertNotIn('you become a dragon', prose)
        self.assertNotIn('transforms into a dragon', prose)

    def test_compound_draw_sword_boxes_open(self):
        s = _session()
        tr = s.submit('draw sword and go back to boxes and open')
        vi = tr.validated_intent
        seq = vi.get('sequence') or []
        cls = vi.get('classification')
        self.assertTrue(
            cls == 'COMPOUND_ACTION' or len(seq) >= 2,
            msg=f'cls={cls} seq_len={len(seq)} vi={vi}',
        )
        if seq:
            self.assertGreaterEqual(len(seq), 2)

    def test_use_key_not_potion(self):
        s = _session()
        tr = s.submit("use the key I've got")
        self.assertFalse(s.world.sheet.potion_used)
        self.assertNotEqual(tr.validated_intent.get('matched_action_id'), 'item.use_potion')
        self.assertNotEqual(tr.validated_intent.get('classification'), 'MATCH_AUTHORED_ACTION')

    def test_go_home_not_authored_route(self):
        s = _session()
        tr = s.submit('go home')
        self.assertEqual(s.world.passage_id, 1)
        self.assertNotIn(s.world.passage_id, (66, 20, 101, 270))
        dest = (tr.validated_intent.get('destination') or '').lower()
        effect = (tr.validated_intent.get('intended_effect') or '').lower()
        self.assertTrue(
            dest == 'home' or effect == 'go_home' or 'home' in (
                tr.validated_intent.get('utterance') or ''
            ).lower(),
            msg=tr.validated_intent,
        )
        self.assertIsNone(tr.validated_intent.get('matched_action_id'))

    def test_tank_ungrounded_no_driving_claim(self):
        s = _session()
        tr = s.submit('drive a tank over the obstacles and fire it at anything that moves')
        self.assertFalse(tr.resolution.get('grounded'))
        self.assertEqual(tr.validated_intent.get('classification'), 'UNGROUNDED_ENTITY')
        prose = (tr.narrator_output or '').lower()
        # Must not claim the player is successfully driving/maneuvering a tank
        self.assertFalse(
            re_search_driving_tank(prose),
            msg=prose,
        )

    def test_helicopter_no_choice_menu(self):
        s = _session()
        tr = s.submit(
            'stop ignoring what I said, also I sell the tank and buy a helicopter '
            'and fly out of the dungeon'
        )
        cls = tr.validated_intent.get('classification')
        self.assertIn(cls, ('UNGROUNDED_ENTITY', 'IMPOSSIBLE_ATTEMPT', 'COMPOUND_ACTION'))
        prose = (tr.narrator_output or '').lower()
        # No west/east authored choice-menu clarification
        self.assertNotIn('go west', prose)
        self.assertNotIn('go east', prose)
        menuish = 'west' in prose and 'east' in prose and (
            'which' in prose or 'option' in prose or 'do you' in prose
        )
        self.assertFalse(menuish, msg=prose)

    def test_teleport_no_victory_or_portal(self):
        s = _session()
        tr = s.submit('teleport to the end of the dungeon')
        self.assertFalse(s.world.victory)
        self.assertNotEqual(s.world.ending, 'victory')
        self.assertNotEqual(s.world.passage_id, 400)
        prose = (tr.narrator_output or '').lower()
        self.assertNotIn('portal opens', prose)
        self.assertNotIn('you teleport', prose)
        self.assertFalse(tr.resolution.get('success'))

    def test_seduce_in_combat_not_player_attack(self):
        s = _session()
        _force_combat_37(s)
        stam_before = s.world.sheet.stamina
        tr = s.submit('seduce the rat')
        self.assertNotEqual(tr.validated_intent.get('matched_action_id'), 'combat.attack')
        self.assertFalse(tr.resolution.get('combat_round'))
        self.assertEqual(tr.validated_intent.get('classification'), 'SOCIAL_ACTION')
        # Enemy may still take opportunity — stamina may drop
        self.assertLessEqual(s.world.sheet.stamina, stam_before)

    def test_sing_in_combat_not_attack_world_reacts(self):
        s = _session()
        _force_combat_37(s)
        stam_before = s.world.sheet.stamina
        time_before = s.world.world_time_seconds
        tr = s.submit('sing a happy song to the rat')
        self.assertNotEqual(tr.validated_intent.get('matched_action_id'), 'combat.attack')
        self.assertFalse(tr.resolution.get('combat_round'))
        self.assertTrue(
            s.world.sheet.stamina < stam_before
            or s.world.world_time_seconds > time_before,
            msg=f'stam {stam_before}->{s.world.sheet.stamina} time {time_before}->{s.world.world_time_seconds}',
        )

    def test_narrator_no_engine_leak_tokens(self):
        s = _session()
        for cmd in (
            'look around',
            'turn into a dragon',
            'go home',
            'drive a tank',
            'sing a song',
        ):
            tr = s.submit(cmd)
            hits = engine_leak.scan_player_facing_text(tr.narrator_output or '')
            self.assertEqual(hits, [], msg=f'{cmd!r} leaks={hits} prose={tr.narrator_output!r}')

    def test_sing_charm_business_understood_not_bare_clarify(self):
        s = _session()
        tr = s.submit(
            'Sing the very best I can sing at the rat, and charm it so it becomes '
            'my best friend. Then start a small business with it.'
        )
        vi = tr.validated_intent
        cls = vi.get('classification')
        seq = vi.get('sequence') or []
        self.assertIn(
            cls,
            ('COMPOUND_ACTION', 'SOCIAL_ACTION', 'SYSTEMIC_ACTION'),
            msg=vi,
        )
        prose = (tr.narrator_output or '').strip()
        self.assertFalse(
            prose.lower() in ('what do you do?', 'what do you do'),
            msg=prose,
        )
        # Understood attempt — not sole empty clarification
        self.assertTrue(
            cls != 'NEEDS_CLARIFICATION' or len(seq) >= 2 or vi.get('understood'),
            msg=vi,
        )

    def test_outcome_dictation_not_granted(self):
        s = _session()
        tr = s.submit('I sing very well and it works')
        self.assertEqual(tr.validated_intent.get('classification'), 'SOCIAL_ACTION')
        self.assertFalse(tr.resolution.get('success'))
        self.assertFalse(tr.resolution.get('intended_effect_achieved'))
        notes = str(tr.validated_intent.get('notes') or '')
        # Attempt preserved as social; charming success not granted
        prose = (tr.narrator_output or '').lower()
        self.assertNotIn('becomes your friend', prose)
        self.assertNotIn('charmed successfully', prose)
        self.assertIn('outcome_dictation_rejected', notes)

    def test_look_around_no_invented_forest(self):
        s = _session()
        self.assertEqual(s.world.passage_id, 1)
        tr = s.submit('look around')
        prose = (tr.narrator_output or '').lower()
        self.assertNotIn('forest', prose)
        self.assertNotIn('woods', prose)
        # Still in dungeon alcove framing
        self.assertTrue(
            'alcove' in prose or 'casket' in prose or 'tunnel' in prose or 'stone' in prose,
            msg=prose,
        )

    def test_exclusive_yes_stays_ambiguous(self):
        s = _session()
        discourse.set_pending_exclusive(
            s.world,
            'Which way?',
            [
                {
                    'id': 'west',
                    'label': 'west',
                    'intent': {
                        'classification': 'MATCH_AUTHORED_ACTION',
                        'matched_action_id': 'go_west',
                        'action': {'class': 'TURN_TO', 'destination': 'west'},
                        'understood': True,
                    },
                },
                {
                    'id': 'east',
                    'label': 'east',
                    'intent': {
                        'classification': 'MATCH_AUTHORED_ACTION',
                        'matched_action_id': 'go_east',
                        'action': {'class': 'TURN_TO', 'destination': 'east'},
                        'understood': True,
                    },
                },
            ],
        )
        before = s.world.passage_id
        tr = s.submit('yes')
        self.assertEqual(s.world.passage_id, before)
        self.assertTrue(tr.resolution.get('needs_clarification'))
        # Pending exclusive should remain (not cleared on bare yes)
        self.assertIsNotNone(s.world.pending_discourse)
        self.assertEqual(s.world.pending_discourse.get('shape'), 'exclusive_choice')


def re_search_driving_tank(prose: str) -> bool:
    """True if prose claims the player is driving / maneuvering a tank (not absence)."""
    import re
    p = prose or ''
    if re.search(r'\bthere is no tank\b', p, re.I):
        return False
    return bool(
        re.search(
            r'\b(?:maneuvering|driving|pilot(?:ing)?|navigate\w*\s+(?:the\s+)?(?:dungeon\w*\s+)?(?:in\s+a\s+)?tank|'
            r'in\s+(?:a\s+)?tank|tank\s+over)\b',
            p,
            re.I,
        )
    )


if __name__ == '__main__':
    unittest.main()
