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
