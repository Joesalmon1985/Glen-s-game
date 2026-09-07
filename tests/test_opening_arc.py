"""Opening facility arc: names, language, contracts, scene changes."""
from __future__ import annotations

from puca_dungeon.characters import STAFF_NAME_POOL, SENIOR_NAME_POOL, generate_cast, schedule_subject_encounters
from puca_dungeon.enactment import BodyPressures
from puca_dungeon.facility_models import PHASE_CONTRACT, PHASE_DAY2_WAKE, PHASE_SECOND_OFFER, make_initial_facility
from puca_dungeon.interpret import HeuristicInterpreter
from puca_dungeon.language import is_language_attempt, practice_language
from puca_dungeon.narrate import TemplateNarrator
from puca_dungeon.rng import GameRNG
from puca_dungeon.session import GameSession


def _session(**kwargs) -> GameSession:
    kwargs.setdefault('interpreter', HeuristicInterpreter())
    kwargs.setdefault('narrator', TemplateNarrator())
    kwargs.setdefault('debug', True)
    kwargs.setdefault('seed', 91)
    kwargs.setdefault('start_mode', 'facility')
    kwargs.setdefault('player_name', 'Sarel')
    return GameSession(**kwargs)


def test_names_shuffled_independently_of_identity():
    a = generate_cast(GameRNG.from_seed(1))
    b = generate_cast(GameRNG.from_seed(2))
    assert a['orderly_quiet']['name'] in STAFF_NAME_POOL
    assert a['orderly_anxious']['name'] in STAFF_NAME_POOL
    assert a['senior_researcher']['name'] in SENIOR_NAME_POOL
    assert a['orderly_quiet']['name'] != a['orderly_anxious']['name']
    assert a['iven']['name'] == 'Iven'
    # Different seeds can assign different cosmetic names to the same identity
    assert (
        a['orderly_quiet']['name'] != b['orderly_quiet']['name']
        or a['senior_researcher']['name'] != b['senior_researcher']['name']
    )


def test_encounter_schedule_covers_second_offer():
    sched = schedule_subject_encounters(GameRNG.from_seed(7))
    for cid in ('iven', 'nessa', 'ruan'):
        assert sched[cid]
        assert any(w != 'never' for w in sched[cid])


def test_wait_only_does_not_raise_language():
    s = _session()
    start = s.world.facility.pressures.language_ability
    for _ in range(6):
        s.submit('wait')
        s.submit('look at the bed')
    assert s.world.facility.pressures.language_ability == start
    assert s.world.facility.arc.language_attempts == 0


def test_speech_raises_language():
    p = BodyPressures(language_ability=15)
    attempts = 0
    for _ in range(10):
        attempts, _ = practice_language(p, attempts)
    assert p.language_ability > 15
    assert attempts == 10
    assert is_language_attempt(None, 'Ask him why I am here')
    assert not is_language_attempt(None, 'wait')
    assert not is_language_attempt(None, 'look at the cup')


def test_sleep_continues_to_day_two():
    s = _session()
    fac = s.world.facility
    fac.phase = 'sleep'
    fac.pressures.fatigue = 95
    s.submit('lie down and sleep')
    assert fac.slept
    assert fac.phase in (PHASE_DAY2_WAKE, 'retrieval', 'interview')
    assert s.world.sheet.alive
    assert s.world.ending != 'sleep'


def test_scene_change_leads_narration():
    s = _session()
    while s.world.facility.phase == 'cell_idle':
        s.submit('wait')
        if s.world.world_time_seconds > 400:
            break
    assert s.world.facility.slit_open or s.world.facility.phase != 'cell_idle'
    prose = (s.last_trace.narrator_output or '').lower()
    facts = ' '.join((s.last_trace.resolution or {}).get('facts') or []).lower()
    blob = prose + ' ' + facts
    assert 'slit' in blob
    assert 'door' in blob or 'back' in blob or 'away' in blob


def test_accept_contract_skips_heaven():
    s = _session()
    fac = s.world.facility
    fac.phase = PHASE_CONTRACT
    fac.arc.last_ask = 'agree to the five-year research service'
    s.submit('yes')
    assert fac.arc.initial_contract_response == 'ACCEPT'
    assert fac.phase in ('contract_processing', 'research', 'corridor')
    assert fac.arc.heaven_experienced is False


def test_refuse_then_stay_in_hell_inverts():
    s = _session()
    fac = s.world.facility
    fac.phase = PHASE_SECOND_OFFER
    fac.room_id = 'hell'
    fac.arc.initial_contract_response = 'REFUSE'
    fac.arc.heaven_experienced = True
    fac.arc.hell_experienced = True
    fac.arc.fear_of_hell = 80
    fac.arc.last_ask = 'agree to the five-year research service'
    fac.staff_present = True
    tr = s.submit('stay here')
    assert fac.arc.player_final_intent == 'REFUSE'
    assert fac.arc.actual_contract_response == 'ACCEPT'
    assert fac.arc.contract_cause == 'overwhelming_fear_of_hell'
    facts = ' '.join((tr.resolution or {}).get('facts') or []).lower()
    assert 'mean to say no' in facts or 'yes' in facts


def test_save_roundtrip_cast_and_arc(tmp_path):
    s = _session(seed=44)
    name = s.world.facility.character_name('orderly_quiet')
    s.world.facility.arc.language_attempts = 3
    path = tmp_path / 'arc.json'
    s.save(path)
    s2 = _session(seed=99)
    s2.load(path)
    assert s2.world.facility.character_name('orderly_quiet') == name
    assert s2.world.facility.arc.language_attempts == 3


def test_glen_orderly_is_addressable():
    s = _session()
    # Force an orderly named Glen
    quiet = s.world.facility.cast['orderly_quiet']
    quiet['name'] = 'Glen'
    s.world.facility.cast['orderly_quiet'] = quiet
    s.world.facility.staff_present = True
    s.world.facility.phase = 'slit'
    s.world.facility.arc.present_ids = ['orderly_quiet']
    from puca_dungeon.models import Intent
    from puca_dungeon.ground import ground_intent
    intent = Intent(
        action_class='ask',
        target='Glen',
        classification='SOCIAL_ACTION',
        utterance='Ask Glen who he is',
        understood=True,
    )
    g = ground_intent(s.world, intent, s.current_passage(), [])
    assert intent.target == 'orderly_quiet'
    assert g.bindings.get('target') == 'orderly_quiet'


def test_make_initial_facility_has_cast():
    fac = make_initial_facility()
    assert 'orderly_quiet' in fac.cast
    assert fac.arc.encounter_schedule
    assert fac.rooms.get('heaven')
    assert fac.rooms.get('research_quarters')
