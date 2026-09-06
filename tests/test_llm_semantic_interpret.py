"""Semantic interpreter pipeline tests using canned LLM-shaped fixtures.

These do NOT expand HeuristicInterpreter regexes. They feed normalized LLM JSON
through ground → resolve → pressure like Ollama would.
"""
from __future__ import annotations

import os
import unittest
from typing import Optional

from puca_dungeon.interpret import HeuristicInterpreter, normalize_intent, ollama_reachable
from puca_dungeon.session import GameSession


class FixtureInterpreter:
    """Maps player text → canned interpreter JSON (simulates Ollama output)."""

    def __init__(self, table: dict[str, dict]):
        self.table = {k.lower().strip(): v for k, v in table.items()}
        self.calls: list[dict] = []

    def interpret(self, text: str, perception: dict, authored_actions: list | None = None):
        key = text.lower().strip()
        self.calls.append({
            'player_text': text,
            'perception': perception,
            'authored_actions': authored_actions or [],
        })
        if key not in self.table:
            raise KeyError(f'No fixture for {text!r}')
        raw = dict(self.table[key])
        return raw, normalize_intent(raw, player_text=text)


# Canonical fixtures for the plan §21 phrase list
FIXTURES: dict[str, dict] = {
    'use my key on my box': {
        'classification': 'MATCH_AUTHORED_ACTION',
        'matched_action_id': 'box.unlock.player',
        'confidence': 0.98,
        'understood': True,
        'action': {
            'class': 'USE', 'target_ref': 'box with my name', 'tool_ref': 'my key',
            'method': 'unlock', 'intended_effect': 'open',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'use this key on the box with my name': {
        'classification': 'MATCH_AUTHORED_ACTION',
        'matched_action_id': 'box.unlock.player',
        'confidence': 0.97,
        'understood': True,
        'action': {
            'class': 'USE', 'target_ref': 'the box with my name', 'tool_ref': 'this key',
            'method': 'unlock', 'intended_effect': 'open',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'grab the box with my name on it and open it': {
        'classification': 'MATCH_AUTHORED_ACTION',
        'matched_action_id': 'box.unlock.player',
        'confidence': 0.9,
        'understood': True,
        'action': {
            'class': 'USE', 'target_ref': 'box with my name on it', 'tool_ref': 'my key',
            'method': 'unlock', 'intended_effect': 'open',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'grab the box with my name and open it': {
        'classification': 'MATCH_AUTHORED_ACTION',
        'matched_action_id': 'box.unlock.player',
        'confidence': 0.9,
        'understood': True,
        'action': {
            'class': 'USE', 'target_ref': 'box with my name', 'tool_ref': 'my key',
            'method': 'unlock', 'intended_effect': 'open',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'shake one of the boxes': {
        'classification': 'GENERAL_WORLD_ACTION',
        'matched_action_id': None,
        'confidence': 0.92,
        'understood': True,
        'action': {
            'class': 'MANIPULATE', 'target_ref': 'one of the boxes',
            'method': 'shake', 'intended_effect': 'shake/test',
        },
        'ambiguities': ['which box'], 'needs_clarification': True,
    },
    'shake the box': {
        'classification': 'NEEDS_CLARIFICATION',
        'matched_action_id': None,
        'confidence': 0.85,
        'understood': True,
        'action': {
            'class': 'MANIPULATE', 'target_ref': 'the box',
            'method': 'shake', 'intended_effect': 'shake/test',
        },
        'ambiguities': ['which box'], 'needs_clarification': True,
    },
    'hit the box': {
        'classification': 'NEEDS_CLARIFICATION',
        'matched_action_id': None,
        'confidence': 0.88,
        'understood': True,
        'action': {
            'class': 'BREAK', 'target_ref': 'the box',
            'method': 'force', 'intended_effect': 'damage',
            'tool_ref': None,
        },
        'ambiguities': ['which box'], 'needs_clarification': True,
    },
    'hit my box': {
        'classification': 'MATCH_AUTHORED_ACTION',
        'matched_action_id': 'box.damage',
        'confidence': 0.93,
        'understood': True,
        'action': {
            'class': 'BREAK', 'target_ref': 'my box',
            'method': 'force', 'intended_effect': 'open_force',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'lick the box': {
        'classification': 'GENERAL_WORLD_ACTION',
        'matched_action_id': None,
        'confidence': 0.95,
        'understood': True,
        'action': {
            'class': 'LICK', 'target_ref': 'the box',
            'method': 'lick', 'intended_effect': 'taste',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'do a cartwheel': {
        'classification': 'SILLY_BUT_VALID',
        'matched_action_id': None,
        'confidence': 0.99,
        'understood': True,
        'action': {
            'class': 'BODILY', 'method': 'cartwheel', 'intended_effect': 'cartwheel',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'turn around': {
        'classification': 'GENERAL_WORLD_ACTION',
        'matched_action_id': None,
        'confidence': 0.9,
        'understood': True,
        'action': {'class': 'TURN', 'method': 'turn_around', 'destination': 'passage_behind'},
        'ambiguities': [], 'needs_clarification': False,
    },
    'turn back around': {
        'classification': 'MATCH_AUTHORED_ACTION',
        'matched_action_id': 'move.passage_behind',
        'confidence': 0.86,
        'understood': True,
        'action': {
            'class': 'MOVE', 'destination': 'passage_behind', 'method': 'turn_back',
            'intended_effect': 'retreat',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'run': {
        'classification': 'MATCH_AUTHORED_ACTION',
        'matched_action_id': 'move.passage_ahead',
        'confidence': 0.8,
        'understood': True,
        'action': {
            'class': 'MOVE', 'destination': 'passage_ahead', 'manner': 'run',
            'intended_effect': 'leave_area',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'run away from the footsteps': {
        'classification': 'MATCH_AUTHORED_ACTION',
        'matched_action_id': 'react.footsteps',
        'confidence': 0.9,
        'understood': True,
        'action': {
            'class': 'FLEE', 'destination': 'passage_ahead', 'intended_effect': 'escape',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'how many boxes are there?': {
        'classification': 'PERCEPTION_QUERY',
        'matched_action_id': None,
        'confidence': 0.99,
        'understood': True,
        'action': {
            'class': 'PERCEIVE', 'query_focus': 'box_count', 'intended_effect': 'learn',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'which one has my name on it?': {
        'classification': 'PERCEPTION_QUERY',
        'matched_action_id': None,
        'confidence': 0.99,
        'understood': True,
        'action': {
            'class': 'PERCEIVE', 'query_focus': 'named_box', 'intended_effect': 'learn',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'what am i carrying?': {
        'classification': 'PERCEPTION_QUERY',
        'matched_action_id': None,
        'confidence': 0.99,
        'understood': True,
        'action': {
            'class': 'PERCEIVE', 'query_focus': 'inventory', 'intended_effect': 'learn',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'open inventory': {
        'classification': 'META_REQUEST',
        'matched_action_id': None,
        'confidence': 0.95,
        'understood': True,
        'action': {
            'class': 'META', 'query_focus': 'inventory', 'method': 'open inventory',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'press x': {
        'classification': 'META_REQUEST',
        'matched_action_id': None,
        'confidence': 0.9,
        'understood': True,
        'action': {'class': 'META', 'method': 'press x', 'query_focus': 'button'},
        'ambiguities': [], 'needs_clarification': False,
    },
    'summon a helicopter': {
        'classification': 'GENERAL_WORLD_ACTION',
        'matched_action_id': None,
        'confidence': 0.95,
        'understood': True,
        'action': {
            'class': 'IMPOSSIBLE', 'method': 'summon', 'intended_effect': 'helicopter',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'sing to the boxes': {
        'classification': 'GENERAL_WORLD_ACTION',
        'matched_action_id': None,
        'confidence': 0.94,
        'understood': True,
        'action': {
            'class': 'MANIPULATE', 'target_ref': 'the boxes', 'method': 'sing',
            'intended_effect': 'sing',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'wait': {
        'classification': 'GENERAL_WORLD_ACTION',
        'matched_action_id': None,
        'confidence': 0.99,
        'understood': True,
        'action': {'class': 'WAIT', 'intended_effect': 'pass_time'},
        'ambiguities': [], 'needs_clarification': False,
    },
    'asdfgh': {
        'classification': 'UNINTERPRETABLE',
        'matched_action_id': None,
        'confidence': 0.2,
        'understood': False,
        'action': {'class': 'UNINTERPRETABLE', 'utterance': 'asdfgh'},
        'ambiguities': [], 'needs_clarification': False,
    },
    'look closely at the boxes': {
        'classification': 'MATCH_AUTHORED_ACTION',
        'matched_action_id': 'box.inspect',
        'confidence': 0.92,
        'understood': True,
        'action': {
            'class': 'INSPECT', 'target_ref': 'boxes', 'method': 'look',
            'intended_effect': 'inspect',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'check the boxes for traps': {
        'classification': 'MATCH_AUTHORED_ACTION',
        'matched_action_id': 'box.search',
        'confidence': 0.96,
        'understood': True,
        'action': {
            'class': 'SEARCH', 'target_ref': 'boxes', 'method': 'careful',
            'intended_effect': 'discover_information',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'walk past the table': {
        'classification': 'MATCH_AUTHORED_ACTION',
        'matched_action_id': 'move.passage_ahead',
        'confidence': 0.94,
        'understood': True,
        'action': {
            'class': 'MOVE', 'destination': 'passage_ahead', 'intended_effect': 'leave_area',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'do nothing': {
        'classification': 'GENERAL_WORLD_ACTION',
        'matched_action_id': None,
        'confidence': 0.9,
        'understood': True,
        'action': {'class': 'WAIT', 'intended_effect': 'pass_time', 'method': 'do nothing'},
        'ambiguities': [], 'needs_clarification': False,
    },
    'look at the boxes closely': {
        'classification': 'MATCH_AUTHORED_ACTION',
        'matched_action_id': 'box.inspect',
        'confidence': 0.92,
        'understood': True,
        'action': {
            'class': 'INSPECT', 'target_ref': 'boxes', 'method': 'look',
            'intended_effect': 'inspect',
        },
        'ambiguities': [], 'needs_clarification': False,
    },
    'grab one of the boxes and shake it': {
        'classification': 'GENERAL_WORLD_ACTION',
        'matched_action_id': None,
        'confidence': 0.93,
        'understood': True,
        'action': {
            'class': 'MANIPULATE', 'target_ref': 'one of the boxes',
            'method': 'shake', 'intended_effect': 'shake/test',
        },
        'ambiguities': ['which box'], 'needs_clarification': True,
    },
}


class SemanticPipelineTests(unittest.TestCase):
    def session(self, fixtures: Optional[dict] = None, seed=91):
        interp = FixtureInterpreter(fixtures or FIXTURES)
        return GameSession(player_name='Glen', seed=seed, debug=True, interpreter=interp), interp

    def test_authored_key_unlock(self):
        s, _ = self.session()
        tr = s.submit('use my key on my box')
        self.assertEqual(tr.validated_intent['classification'], 'MATCH_AUTHORED_ACTION')
        self.assertEqual(tr.validated_intent['matched_action_id'], 'box.unlock.player')
        self.assertTrue(s.world.boxes['box_player'].open)
        self.assertEqual(tr.visual_backend_calls, 0)

    def test_demote_forced_shake_to_damage(self):
        from puca_dungeon.interpret import normalize_intent
        raw = {
            'classification': 'MATCH_AUTHORED_ACTION',
            'matched_action_id': 'box.damage',
            'understood': True,
            'action': {'class': 'BREAK', 'target_ref': 'one of the boxes', 'method': 'force'},
            'ambiguities': [], 'needs_clarification': False,
        }
        intent = normalize_intent(raw, player_text='grab one of the boxes and shake it')
        self.assertNotEqual(intent.matched_action_id, 'box.damage')
        self.assertIn(intent.classification, ('GENERAL_WORLD_ACTION', 'NEEDS_CLARIFICATION'))
        self.assertEqual(intent.method, 'shake')

    def test_the_box_is_ambiguous_for_hit(self):
        s, _ = self.session()
        # Override fixture to simulate LLM matching damage with vague target
        s.interpreter.table['hit the box'] = {
            'classification': 'MATCH_AUTHORED_ACTION',
            'matched_action_id': 'box.damage',
            'understood': True,
            'action': {'class': 'BREAK', 'target_ref': 'the box', 'method': 'hit'},
            'ambiguities': [], 'needs_clarification': False,
        }
        tr = s.submit('hit the box')
        self.assertTrue(tr.resolution['needs_clarification'] or tr.grounding['ambiguous'])
        self.assertNotEqual(tr.grounding['bindings'].get('target'), 'box_player')

    def test_ambiguous_shake_clarifies(self):
        s, _ = self.session()
        tr = s.submit('shake one of the boxes')
        self.assertTrue(tr.validated_intent['needs_clarification'] or tr.grounding['ambiguous'])
        self.assertTrue(tr.resolution['needs_clarification'])
        self.assertFalse(tr.resolution['grounded'])
        self.assertIsNone(tr.resolution['feasible'])
        self.assertIsNone(tr.resolution['success'])
        self.assertEqual(tr.pressure['stall_delta'], 0)
        self.assertIn('which', tr.narrator_output.lower())

    def test_hit_box_no_silent_named_and_no_invented_tool(self):
        s, _ = self.session()
        tr = s.submit('hit the box')
        self.assertTrue(tr.resolution['needs_clarification'])
        self.assertNotEqual(tr.grounding['bindings'].get('target'), 'box_player')
        self.assertIsNone(tr.validated_intent.get('tool'))
        self.assertNotIn('tool', tr.grounding['bindings'])

    def test_hit_my_box_grounds(self):
        s, _ = self.session()
        tr = s.submit('hit my box')
        self.assertEqual(tr.grounding['bindings'].get('target'), 'box_player')
        self.assertFalse(tr.resolution['needs_clarification'])
        self.assertTrue(tr.resolution['interacted'])

    def test_lick_performed(self):
        s, _ = self.session()
        tr = s.submit('lick the box')
        self.assertIn('lick', tr.narrator_output.lower())
        self.assertTrue(tr.resolution['success'])
        self.assertNotIn('think about', tr.narrator_output.lower())

    def test_cartwheel_silly(self):
        s, _ = self.session()
        before = s.world.guidance_level
        tr = s.submit('do a cartwheel')
        self.assertEqual(tr.validated_intent['classification'], 'SILLY_BUT_VALID')
        self.assertIn('cartwheel', tr.narrator_output.lower())
        self.assertGreater(s.world.guidance_level, before)

    def test_perception_box_count(self):
        s, _ = self.session()
        tr = s.submit('how many boxes are there?')
        self.assertEqual(tr.validated_intent['classification'], 'PERCEPTION_QUERY')
        self.assertIn('6', tr.narrator_output)
        self.assertLessEqual(tr.pressure['world_time_delta'], 5)

    def test_named_box_query(self):
        s, _ = self.session()
        tr = s.submit('which one has my name on it?')
        self.assertIn("Glen's box", tr.narrator_output)

    def test_inventory_query_and_meta(self):
        s, _ = self.session()
        tr = s.submit('what am I carrying?')
        self.assertIn('key', tr.narrator_output.lower())
        tr2 = s.submit('open inventory')
        self.assertEqual(tr2.validated_intent['classification'], 'META_REQUEST')
        self.assertIn('key', tr2.narrator_output.lower())

    def test_press_x_meta_reanchor(self):
        s, _ = self.session()
        before_g = s.world.guidance_level
        tr = s.submit('press X')
        self.assertEqual(tr.validated_intent['classification'], 'META_REQUEST')
        self.assertGreaterEqual(s.world.guidance_level, before_g)
        self.assertNotIn('dungeon accepts', tr.narrator_output.lower())

    def test_helicopter_understood_infeasible(self):
        s, _ = self.session()
        tr = s.submit('summon a helicopter')
        self.assertTrue(tr.validated_intent['understood'])
        self.assertFalse(tr.resolution['feasible'])
        self.assertFalse(tr.resolution['success'])

    def test_uninterpretable_no_stall(self):
        s, _ = self.session()
        before_stall = s.world.stall_time_seconds
        before_g = s.world.guidance_level
        tr = s.submit('asdfgh')
        self.assertEqual(tr.validated_intent['classification'], 'UNINTERPRETABLE')
        self.assertEqual(s.world.stall_time_seconds, before_stall)
        self.assertEqual(tr.pressure['world_time_delta'], 0)
        self.assertGreater(s.world.guidance_level, before_g)

    def test_wait_advances_stall(self):
        s, _ = self.session()
        before = s.world.stall_time_seconds
        tr = s.submit('wait')
        self.assertGreater(s.world.stall_time_seconds, before)
        self.assertGreater(tr.pressure['world_time_delta'], 0)

    def test_inspect_no_trap_leak_in_intent(self):
        s, _ = self.session()
        tr = s.submit('look closely at the boxes')
        self.assertNotEqual(tr.validated_intent.get('intended_effect'), 'discover_trap')
        self.assertIn(tr.validated_intent.get('intended_effect'), ('inspect', 'discover_information', None))

    def test_search_traps_explicit(self):
        s, _ = self.session()
        s.world.player.search_bonus = 25
        tr = s.submit('check the boxes for traps')
        self.assertEqual(tr.validated_intent['matched_action_id'], 'box.search')
        self.assertTrue(any(b.trap_discovered for b in s.world.boxes.values()))

    def test_walk_past(self):
        s, _ = self.session()
        tr = s.submit('walk past the table')
        self.assertEqual(s.world.encounter, 'junction')
        self.assertEqual(tr.image['decision'], 'REGENERATE')

    def test_authored_actions_sent_to_interpreter(self):
        s, interp = self.session()
        s.submit('wait')
        self.assertTrue(interp.calls)
        ids = {a['id'] for a in interp.calls[0]['authored_actions']}
        self.assertIn('box.unlock.player', ids)
        self.assertIn('move.passage_ahead', ids)

    def test_guidance_resets_on_meaningful_action(self):
        s, _ = self.session()
        s.submit('asdfgh')
        self.assertGreater(s.world.guidance_level, 0)
        s.submit('use my key on my box')
        self.assertEqual(s.world.guidance_level, 0)

    def test_no_generic_dungeon_accepts(self):
        s, _ = self.session()
        for phrase in (
            'do a cartwheel', 'lick the box', 'sing to the boxes', 'summon a helicopter', 'press X',
        ):
            tr = s.submit(phrase)
            self.assertNotIn('dungeon accepts the attempt', tr.narrator_output.lower())

    def test_debug_shows_guidance_and_authored(self):
        s, _ = self.session()
        tr = s.submit('how many boxes are there?')
        dump = tr.format_debug()
        self.assertIn('authored_actions', dump)
        self.assertIn('classification=', dump)
        self.assertIn('GUIDANCE', dump)
        self.assertEqual(tr.visual_backend_calls, 0)


@unittest.skipUnless(
    os.environ.get('PUCA_LIVE_OLLAMA') == '1' and ollama_reachable(),
    'Set PUCA_LIVE_OLLAMA=1 with Ollama running for live smoke',
)
class LiveOllamaSmokeTests(unittest.TestCase):
    def test_ollama_interprets_key_use(self):
        from puca_dungeon.interpret import OllamaInterpreter
        s = GameSession(player_name='Glen', seed=91, debug=True, interpreter=OllamaInterpreter())
        tr = s.submit('use my key on my box')
        self.assertTrue(tr.validated_intent['understood'])
        self.assertNotEqual(tr.validated_intent['classification'], 'UNINTERPRETABLE')
        self.assertNotEqual(tr.validated_intent['action_class'], 'OTHER')


if __name__ == '__main__':
    unittest.main()
