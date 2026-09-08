"""Narrative scene context continuity and narrator payload hygiene."""
from __future__ import annotations

from puca_dungeon.facility_models import PHASE_DOOR, PHASE_WASH, make_initial_facility
from puca_dungeon.interpret import HeuristicInterpreter
from puca_dungeon.narrate import NARRATOR_SYSTEM, TemplateNarrator, build_narrator_input
from puca_dungeon.narrative_context import (
    NarrativeSceneContext,
    ensure_initial_context,
    get_scene_context,
    refresh_scene_for_phase,
)
from puca_dungeon.rng import GameRNG
from puca_dungeon.session import GameSession


def _facility(**kwargs) -> GameSession:
    kwargs.setdefault('interpreter', HeuristicInterpreter())
    kwargs.setdefault('narrator', TemplateNarrator())
    kwargs.setdefault('debug', True)
    kwargs.setdefault('seed', 91)
    kwargs.setdefault('start_mode', 'facility')
    return GameSession(**kwargs)


def test_initial_scene_context_exists():
    fac = make_initial_facility(GameRNG.from_seed(91))
    ctx = ensure_initial_context(fac)
    assert isinstance(ctx, NarrativeSceneContext)
    assert ctx.scene_label == 'cell waking'
    assert ctx.room_name == 'cell'
    packet = ctx.narrator_packet()
    assert 'facility_phase' not in str(packet).lower()
    assert 'cell_idle' not in str(packet)


def test_narrator_payload_includes_scene_context():
    s = _facility()
    s.submit('look around')
    nin = s.last_trace.narrator_input if s.last_trace else None
    assert nin is not None
    assert 'scene_context' in nin
    sc = nin['scene_context']
    assert sc.get('where') == 'cell'
    assert 'facility_phase' not in str(sc).lower()
    banned = ('sated', 'quenched', 'hygiene aware', 'cell_idle')
    blob = str(sc).lower()
    for b in banned:
        assert b not in blob


def test_scene_persists_across_door_refusals():
    s = _facility()
    # Advance to slit/door
    for _ in range(6):
        s.submit('wait')
        if s.world.facility.phase in ('slit', 'door_procedure', PHASE_DOOR):
            break
    s.submit('I will not back away')
    ctx1 = get_scene_context(s.world.facility)
    label1 = ctx1.scene_label
    s.submit('I will not back away')
    ctx2 = get_scene_context(s.world.facility)
    # Same confrontation scene while still in cell door procedure / slit
    if s.world.facility.room_id == 'cell':
        assert ctx2.scene_label in (
            'slit confrontation', 'cell-door confrontation', label1,
        )
        assert ctx2.beats  # refusals recorded as beats


def test_scene_resets_on_washroom():
    s = _facility()
    for _ in range(20):
        s.submit('wait')
        if s.world.facility.phase == PHASE_WASH or s.world.facility.room_id == 'washroom':
            break
        if s.world.facility.phase in ('slit', 'door_procedure'):
            s.submit('I will not back away')
    assert s.world.facility.room_id in ('washroom', 'corridor', 'cell')
    # Force toward wash if needed
    for _ in range(15):
        if s.world.facility.room_id == 'washroom':
            break
        s.submit('wait')
    if s.world.facility.room_id == 'washroom':
        ctx = get_scene_context(s.world.facility)
        assert ctx.scene_label == 'washroom procedure'
        assert ctx.room_name == 'washroom'
        assert ctx.is_new_scene or 'wash' in ctx.immediate_situation.lower()


def test_narrator_system_forbids_intention_meta():
    lower = NARRATOR_SYSTEM.lower()
    assert 'intention' in lower or 'wanted_action' in lower
    assert 'scene_context' in lower or 'turn_spec' in lower
    assert 'never' in lower
    assert 'trust' in lower or 'strategy' in lower


def test_wait_and_default_facts_not_meta():
    s = _facility()
    s.submit('wait')
    out = (s.last_trace.narrator_output or '') if s.last_trace else ''
    assert 'room does not hurry' not in out.lower()
    assert 'room remains the room' not in out.lower()
    s.submit('flibble the quantum')
    out2 = (s.last_trace.narrator_output or '') if s.last_trace else ''
    assert 'room remains the room' not in out2.lower()


def test_template_narration_avoids_you_mean_to():
    s = _facility()
    # Force a compromised path via wash refuse after restraint
    for _ in range(25):
        fac = s.world.facility
        if fac.phase == PHASE_WASH:
            fac.pressures.physical_restraint = 80
            s.submit('refuse to wash')
            out = (s.last_trace.narrator_output or '') if s.last_trace else ''
            assert 'you mean to' not in out.lower()
            break
        if fac.phase in ('slit', 'door_procedure'):
            s.submit('I will not back away')
        else:
            s.submit('wait')


def test_book_enter_during_slit_excludes_facility_wait():
    s = _facility(seed=102)
    for _ in range(10):
        s.submit('wait')
        if s.world.facility.phase in ('slit', 'door_procedure'):
            break
    assert s.world.facility.phase in ('slit', 'door_procedure')
    s.submit('look at the book')
    assert s.world.mode == 'book_dungeon'
    out = (s.last_trace.narrator_output or '') if s.last_trace else ''
    low = out.lower()
    assert 'still waiting' not in low
    assert 'printed corridor opens' in low or 'somewhere else' in low
    assert 'casket' in low or 'alcove' in low or 'tunnel' in low


def test_book_interrupt_strips_dungeon_bleed():
    s = _facility()
    s.submit('read the book')
    assert s.world.mode == 'book_dungeon'
    # Advance facility time via waits inside book until slit can fire
    for _ in range(12):
        s.submit('wait')
        if s.world.mode == 'facility':
            break
        fac = s.world.facility
        if fac and fac.phase in ('slit', 'door_procedure'):
            break
    # Force interrupt path if still in book
    if s.world.mode == 'book_dungeon':
        s.world.facility.phase = 'cell_idle'
        s.world.world_time_seconds = 200
        s.submit('look around')
    prose = (s.last_trace.narrator_output or '').lower()
    facts = ' '.join(s.last_trace.resolution.get('facts') or []).lower() if s.last_trace else ''
    # After interrupt, should not keep alcove/casket as concurrent cell reality
    if 'slit' in facts or 'knock' in facts or s.world.mode == 'facility':
        assert not (
            ('casket' in prose or 'alcove' in prose)
            and ('observation slit' in prose or 'step away' in prose)
        )


def test_refresh_scene_for_phase_no_engine_labels():
    fac = make_initial_facility(GameRNG.from_seed(7))
    fac.phase = PHASE_DOOR
    fac.arc.present_ids = ['orderly_quiet', 'orderly_anxious']
    fac.staff_present = True
    ctx = refresh_scene_for_phase(fac, new_scene=True, ask='stay away from the door')
    packet = ctx.narrator_packet()
    flat = str(packet)
    assert 'door_procedure' not in flat
    assert 'orderly_quiet' not in flat
    assert packet['open_ask'] == 'stay away from the door'
    assert packet['people_present']
