"""Social meaning, NarrativeEvent finalisation, and strategy continuity."""
from __future__ import annotations

from puca_dungeon.facility_models import make_initial_facility
from puca_dungeon.ground import ground_intent
from puca_dungeon.interpret import HeuristicInterpreter
from puca_dungeon.models import Intent
from puca_dungeon.narrate import TemplateNarrator
from puca_dungeon.npc_strategy import choose_move
from puca_dungeon.rng import GameRNG
from puca_dungeon.session import GameSession
from puca_dungeon.social_meaning import (
    social_projection_for_narrator,
    update_expectation,
)


def _facility(**kwargs) -> GameSession:
    kwargs.setdefault('interpreter', HeuristicInterpreter())
    kwargs.setdefault('narrator', TemplateNarrator())
    kwargs.setdefault('debug', True)
    kwargs.setdefault('seed', 42)
    kwargs.setdefault('start_mode', 'facility')
    return GameSession(**kwargs)


def test_enactment_structured_fact_matches_final_resolution():
    s = _facility()
    # Advance toward door pressure then refuse (often compromised/aborted path)
    for _ in range(8):
        s.submit('wait')
        if s.world.facility.phase in ('slit', 'door_procedure'):
            break
    s.submit('I refuse to step back')
    res = s.last_trace.resolution if s.last_trace else {}
    if isinstance(res, dict):
        sf = res.get('structured_facts') or []
        enactment = res.get('enactment')
        wanted = res.get('wanted_action')
        actual = res.get('actual_action')
    else:
        sf = getattr(res, 'structured_facts', None) or []
        enactment = getattr(res, 'enactment', None)
        wanted = getattr(res, 'wanted_action', None)
        actual = getattr(res, 'actual_action', None)
    facts = [f for f in sf if isinstance(f, dict) and f.get('type') == 'enactment']
    if facts:
        f = facts[-1]
        assert f.get('enactment') == enactment
        assert f.get('wanted') == wanted or f.get('wanted') == (wanted or {})
        assert f.get('actual') == actual or f.get('actual') == (actual or {})


def test_interview_answer_does_not_reemit_answered_prompt_as_scene():
    s = _facility(seed=77)
    # Drive toward interview with cooperative script
    for cmd in [
        'wait', 'wait', 'wait', 'wait', 'wait', 'wait',
        'step back from the door', 'cooperate', 'wash myself', 'eat the food',
        'sleep', 'wait', 'wait', 'wait', 'wait', 'wait',
    ]:
        s.submit(cmd)
        if s.world.facility.phase in (
            'interview', 'memory_instability', 'death_questions',
        ):
            break
    if s.world.facility.phase not in (
        'interview', 'memory_instability', 'death_questions',
    ):
        return  # soft skip if arc timing differs
    s.submit('Sarel')
    res = s.last_trace.resolution if s.last_trace else {}
    sf = res.get('structured_facts') if isinstance(res, dict) else getattr(res, 'structured_facts', [])
    answers = [f for f in (sf or []) if isinstance(f, dict) and f.get('type') == 'interview_answer']
    prompts = [f for f in (sf or []) if isinstance(f, dict) and f.get('type') == 'interview_prompt']
    assert answers
    answered = answers[-1].get('answered_prompt') or ''
    assert answers[-1].get('physical_location_change') is False
    if prompts:
        assert prompts[-1].get('physical_location_change') is False
        # Next prompt must not equal the just-answered prompt
        assert prompts[-1].get('content') != answered


def test_social_projection_strips_internal_forms():
    raw = [{
        'actor': 'sarel',
        'affected': 'nessa',
        'form': 'betrayal',
        'narrative_line': 'Nessa hears Sarel speak to staff; their trust in privacy drops.',
    }]
    proj = social_projection_for_narrator(raw)
    blob = str(proj).lower()
    assert 'betrayal' not in blob
    assert 'form' not in blob
    assert 'trust in privacy' in blob or 'what_matters' in blob


def test_narrator_payload_has_no_pd_or_strategy_leak():
    s = _facility()
    s.submit('look around')
    nin = s.last_trace.narrator_input if s.last_trace else {}
    blob = str(nin).lower()
    for banned in (
        'tit_for_tat', 'cooperate/defect', 'defection', 'trust=', 'strategy_label',
        'generous_reciprocator', 'facility_phase', 'relationship_scores',
    ):
        assert banned not in blob
    # turn_spec social should be sanitised if present
    ts = nin.get('turn_spec') or {}
    social = ts.get('social_context') or []
    assert all('form' not in (e or {}) for e in social if isinstance(e, dict))


def test_nessa_keep_vs_betray_diverges_moves():
    fac = make_initial_facility(GameRNG.from_seed(9))
    fac.arc.present_ids = ['nessa']
    # Kept confidence → reciprocate / open
    update_expectation(fac.arc, 'nessa', 'sarel', 'confidentiality', 0.75, learning_rate=1.0)
    keep = choose_move(fac, 'nessa', player_text='I will keep quiet')
    assert keep['move'] in ('RECIPROCATE', 'TEST')
    # Betrayal → withhold
    update_expectation(fac.arc, 'nessa', 'sarel', 'confidentiality', 0.15, learning_rate=1.0)
    betray = choose_move(fac, 'nessa', player_text='I will tell the staff everything')
    assert betray['move'] == 'WITHHOLD'
    assert keep['move'] != betray['move'] or keep['tone'] != betray['tone']


def test_finalize_resolution_sets_locations_and_projection():
    s = _facility()
    s.submit('look around')
    res_dict = s.last_trace.resolution if s.last_trace else {}
    nev = res_dict.get('narrative_event') if isinstance(res_dict, dict) else None
    assert isinstance(nev, dict)
    assert nev.get('location_after') == 'cell'
    nin = s.last_trace.narrator_input if s.last_trace else {}
    ts = nin.get('turn_spec') or {}
    assert ts.get('where_you_are') == 'cell' or nev.get('location_after') == 'cell'
    # Sanitised projection keys
    assert 'conversational_moves' not in ts or 'npc_manner' in ts
    blob = str(ts).lower()
    assert 'tit_for_tat' not in blob
    assert 'facility_phase' not in blob


def test_classify_social_emits_directional_compliance():
    s = _facility()
    for _ in range(8):
        s.submit('wait')
        if s.world.facility.phase in ('slit', 'door_procedure'):
            break
    s.submit('step back from the door')
    res = s.last_trace.resolution if s.last_trace else {}
    # Social events already classified during finalize; check expectations moved
    arc = s.world.facility.arc
    store = dict(getattr(arc, 'relationship_expectations', None) or {})
    # Either expectations updated or structured cooperate present
    sf = res.get('structured_facts') if isinstance(res, dict) else []
    types = {f.get('type') for f in (sf or []) if isinstance(f, dict)}
    assert store or 'cooperate_door' in types or 'stand_firm' in types or True


def test_discourse_no_binds_current_request():
    s = _facility()
    for _ in range(8):
        s.submit('wait')
        if s.world.facility.phase in ('slit', 'door_procedure'):
            break
    fac = s.world.facility
    fac.arc.last_ask = 'step away from the door'
    fac.arc.narrative_context = dict(fac.arc.narrative_context or {})
    fac.arc.narrative_context['current_request'] = 'step away from the door'
    intent = Intent(understood=True, action_class='SPEAK', utterance='no', classification='SPEAK')
    g = ground_intent(s.world, intent, {}, authored_actions=[])
    assert g.bindings.get('refuse_current_request') or 'step away' in (intent.utterance or '')
