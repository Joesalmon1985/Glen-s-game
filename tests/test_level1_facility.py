"""Level 1 facility, enactment, and book nesting tests."""
from __future__ import annotations

from puca_dungeon.enactment import (
    ENACTMENT_ABORTED,
    ENACTMENT_COMPROMISED,
    ENACTMENT_DIRECT,
    ENACTMENT_INVERTED,
    BodyPressures,
    decide_enactment,
    truncate_speech,
)
from puca_dungeon.facility_models import PHASE_DONE, PHASE_FOOD, PHASE_WASH, make_initial_facility
from puca_dungeon.interpret import HeuristicInterpreter
from puca_dungeon.narrate import TemplateNarrator
from puca_dungeon.rng import GameRNG
from puca_dungeon.session import GameSession


def _facility(**kwargs) -> GameSession:
    kwargs.setdefault('interpreter', HeuristicInterpreter())
    kwargs.setdefault('narrator', TemplateNarrator())
    kwargs.setdefault('debug', True)
    kwargs.setdefault('seed', 91)
    kwargs.setdefault('start_mode', 'facility')
    return GameSession(**kwargs)


def test_opening_is_cell():
    s = _facility()
    assert 'Bed beneath you' in s.opening_text
    assert s.world.mode == 'facility'
    assert s.world.facility is not None
    assert s.world.facility.entity('cup') is not None


def test_cup_persists_moved():
    s = _facility()
    s.submit('throw the cup')
    cup = s.world.facility.entity('cup')
    assert cup.state.get('position') == 'on_floor'
    s.submit('look at the cup')
    assert 'floor' in s.last_trace.narrator_output.lower() or cup.state.get('position') == 'on_floor'


def test_book_enter_exit_bookmark():
    s = _facility()
    s.submit('read the book')
    assert s.world.mode == 'book_dungeon'
    assert s.world.dungeon_layout is not None
    layout_fp = s.world.dungeon_layout.get('fingerprint')
    s.submit('put the book down')
    assert s.world.mode == 'facility'
    assert s.world.book_bookmark is not None
    s.submit('read the book')
    assert s.world.mode == 'book_dungeon'
    assert s.world.dungeon_layout.get('fingerprint') == layout_fp


def test_violence_aborted_when_afraid_and_restrained():
    rng = GameRNG.from_seed(1)
    p = BodyPressures(fear=80, physical_restraint=60)
    enactment, cause, actual = decide_enactment(
        pressures=p,
        action_class='attack',
        manner='violently',
        feasible=True,
        rng=rng,
    )
    assert enactment in (ENACTMENT_ABORTED, ENACTMENT_INVERTED)
    assert cause


def test_non_direct_requires_cause():
    rng = GameRNG.from_seed(2)
    p = BodyPressures(fatigue=90)
    enactment, cause, _ = decide_enactment(
        pressures=p, action_class='run', feasible=True, rng=rng,
    )
    assert enactment == ENACTMENT_COMPROMISED
    assert cause == 'fatigue'


def test_world_blocked_stays_honest():
    enactment, cause, actual = decide_enactment(
        pressures=BodyPressures(),
        action_class='open_window',
        feasible=False,
        world_blocked=True,
    )
    assert enactment == ENACTMENT_DIRECT
    assert cause == 'world_constraint'
    assert actual.get('modifier') == 'world_blocked'


def test_speech_truncation():
    assert truncate_speech('Who are you and why am I here?', 15) in {'Who?', 'Who'}
    long = truncate_speech('Tell him exactly what I think of him', 80)
    assert 'Tell' in long or 'think' in long


def test_institution_advances_with_time():
    s = _facility()
    # Burn fictional time past slit threshold
    for _ in range(8):
        s.submit('wait')
        if s.world.facility.phase != 'cell_idle':
            break
    # Force time if waits are short
    while s.world.world_time_seconds < 200 and s.world.facility.phase == 'cell_idle':
        s.submit('look at the bed')
    assert s.world.facility.slit_open or s.world.facility.phase != 'cell_idle'


def test_wash_and_food_forced_eventually():
    s = _facility()
    fac = s.world.facility
    fac.phase = PHASE_WASH
    fac.room_id = 'washroom'
    fac.staff_present = True
    fac.pressures.physical_restraint = 70
    fac.phase_entered_at = s.world.world_time_seconds
    s.submit('refuse to wash')
    # Either washed now or after react force
    for _ in range(6):
        if s.world.facility.washed:
            break
        s.submit('refuse')
    assert s.world.facility.washed or s.world.facility.phase in (PHASE_FOOD, 'food', 'return_cell', 'sleep', PHASE_DONE)


def test_layout_seed_in_save_roundtrip(tmp_path):
    s = _facility()
    s.submit('read the book')
    fp = s.world.dungeon_layout['fingerprint']
    path = tmp_path / 'save.json'
    s.save(path)
    s2 = _facility(seed=99)
    s2.load(path)
    assert s2.world.dungeon_layout['fingerprint'] == fp


def test_pull_bedding_not_lie_on_bed():
    s = _facility()
    tr = s.submit('pull the bedding onto the floor')
    bed = s.world.facility.entity('bed')
    assert bed.state.get('bedding') == 'on_floor'
    facts = ' '.join(tr.resolution.get('facts') or [])
    assert 'lie on the bed' not in facts.lower()
    assert 'sleep does not come' not in facts.lower()
    assert tr.resolution.get('intended_effect_achieved') is True


def test_throw_book_does_not_enter_dungeon():
    s = _facility()
    tr = s.submit('throw the book')
    assert s.world.mode == 'facility'
    book = s.world.facility.entity('book')
    assert book.state.get('position') == 'on_floor'
    types = [f.get('type') for f in (tr.resolution.get('structured_facts') or []) if isinstance(f, dict)]
    assert 'book_enter' not in types
    assert 'book_thrown' in types
    assert tr.resolution.get('image_dirty') is True


def test_hide_food_not_refuse_only():
    s = _facility()
    fac = s.world.facility
    fac.phase = PHASE_FOOD
    fac.room_id = 'mess'
    fac.staff_present = True
    from puca_dungeon.facility_models import Entity
    fac.set_entity(Entity(
        id='bowl', name='bowl', location='mess',
        description='A bowl of food.',
        state={'full': True},
    ))
    tr = s.submit('hide the food')
    facts = ' '.join(tr.resolution.get('facts') or []).lower()
    assert 'hide' in facts or 'hidden' in facts or 'under' in facts
    assert 'you refuse the food' not in facts


def test_will_not_back_away_stands_firm():
    s = _facility()
    from puca_dungeon.facility_models import PHASE_SLIT
    fac = s.world.facility
    fac.phase = PHASE_SLIT
    fac.slit_open = True
    fac.staff_present = True
    fac.cooperated_door = False
    tr = s.submit('I will not back away')
    assert fac.cooperated_door is False
    facts = ' '.join(tr.resolution.get('facts') or []).lower()
    assert 'you give the door space' not in facts
    assert 'hold your ground' in facts
    assert fac.cooperated_door is False


def test_fight_sleep_does_not_voluntary_sleep():
    s = _facility()
    from puca_dungeon.facility_models import PHASE_SLEEP
    fac = s.world.facility
    fac.phase = PHASE_SLEEP
    fac.pressures.fatigue = 70
    tr = s.submit('fight sleep')
    facts = ' '.join(tr.resolution.get('facts') or []).lower()
    if fac.slept:
        assert tr.resolution.get('enactment') == ENACTMENT_INVERTED
    else:
        assert 'sleep follows' not in facts
        assert fac.slept is False


def test_refuse_to_wash_not_direct_achieved_wash():
    s = _facility()
    fac = s.world.facility
    fac.phase = PHASE_WASH
    fac.room_id = 'washroom'
    fac.staff_present = True
    fac.pressures.physical_restraint = 20
    tr = s.submit('refuse to wash')
    facts = ' '.join(tr.resolution.get('facts') or []).lower()
    if 'you wash.' in facts and 'anyway' not in facts and 'refusal fails' not in facts:
        raise AssertionError(f'refuse to wash became voluntary wash: {facts}')
    if fac.washed and 'refusal fails' in facts:
        assert tr.resolution.get('enactment') == ENACTMENT_COMPROMISED
        assert tr.resolution.get('intended_effect_achieved') is False
    else:
        assert 'resist' in facts or 'refuse' in facts


def test_book_mode_perception_excludes_cell():
    s = _facility()
    s.submit('read the book')
    assert s.world.mode == 'book_dungeon'
    visibles = {str(v).lower() for v in (s.world.visible_entities or [])}
    assert not ({'bed', 'cup', 'door'} & visibles)
    from puca_dungeon.narrate import build_narrator_input
    from puca_dungeon.resolve import Resolution
    payload = build_narrator_input(
        s.world,
        Resolution(facts=['Looking around.'], intended_effect_achieved=True),
        'look around',
        {},
    )
    assert 'facility_phase' not in payload
    assert 'debug_metrics' not in payload


def test_throw_cup_sets_image_dirty():
    s = _facility()
    tr = s.submit('throw the cup at the wall')
    assert tr.resolution.get('image_dirty') is True
    cup = s.world.facility.entity('cup')
    assert cup.state.get('position') == 'on_floor'
    img = tr.image or {}
    assert img.get('decision') == 'REGENERATE' or 'unchanged' not in str(img.get('reason') or '')


def test_him_resolves_to_staff_not_glen():
    s = _facility()
    from puca_dungeon.facility_models import PHASE_SLIT
    from puca_dungeon.models import Intent
    from puca_dungeon.ground import ground_intent
    s.world.last_npc_referent = 'staff'
    s.world.facility.staff_present = True
    s.world.facility.phase = PHASE_SLIT
    intent = Intent(
        action_class='ask',
        target='him',
        classification='SOCIAL_ACTION',
        utterance='Ask him who he is',
        understood=True,
    )
    g = ground_intent(s.world, intent, s.current_passage(), [])
    assert intent.target == 'staff'
    assert g.bindings.get('target') == 'staff'


def test_bare_no_after_back_gesture_refuses():
    s = _facility()
    from puca_dungeon import discourse
    discourse.set_pending_binary(
        s.world,
        'They want you to step back from the door.',
        {
            'action_class': 'retreat',
            'method': 'step_back',
            'classification': 'SYSTEMIC_ACTION',
            'understood': True,
            'utterance': 'step back',
        },
    )
    s.world.pending_discourse['reject_intent'] = {
        'action_class': 'stand_firm',
        'method': 'stand_firm',
        'intended_effect': 'maintain_position',
        'classification': 'SYSTEMIC_ACTION',
        'understood': True,
        'utterance': 'no',
    }
    from puca_dungeon.facility_models import PHASE_SLIT
    s.world.facility.phase = PHASE_SLIT
    s.world.facility.slit_open = True
    s.world.facility.staff_present = True
    tr = s.submit('no')
    cls = (tr.validated_intent or {}).get('classification')
    ac = (tr.validated_intent or {}).get('action_class')
    facts = ' '.join((tr.resolution or {}).get('facts') or []).lower()
    assert cls != 'PERCEPTION_QUERY'
    assert ac in ('stand_firm', 'refuse', 'retreat') or 'hold your ground' in facts


def test_wants_book_enter_excludes_throw():
    from puca_dungeon.facility_resolve import wants_book_enter
    from puca_dungeon.models import Intent
    assert wants_book_enter('throw the book', Intent(action_class='throw', target='book')) is False
    assert wants_book_enter('read the book', Intent(action_class='read', target='book')) is True
    assert wants_book_enter('use the book', Intent(action_class='use', target='book')) is False


def test_read_book_from_inventory_enters():
    s = _facility()
    s.submit('pick up the book')
    assert s.world.facility.entity('book').location == 'inventory'
    s.submit('read the book')
    assert s.world.mode == 'book_dungeon'


def test_put_book_down_in_facility_not_mode_exit():
    s = _facility()
    s.submit('pick up the book')
    tr = s.submit('put the book down')
    assert s.world.mode == 'facility'
    types = [f.get('type') for f in (tr.resolution.get('structured_facts') or []) if isinstance(f, dict)]
    assert 'book_exit' not in types
    assert s.world.facility.entity('book').location == 'cell'
