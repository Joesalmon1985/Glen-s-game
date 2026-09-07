"""Institution timeline and bodily drift for the Level 1 facility."""
from __future__ import annotations

from puca_dungeon.enactment import advance_pressures_for_time, qualitative_pressures
from puca_dungeon.facility_models import (
    DOOR_FORCE_AT,
    FOOD_DONE_FORCE,
    PHASE_CELL_IDLE,
    PHASE_DONE,
    PHASE_DOOR,
    PHASE_FOOD,
    PHASE_REMOVAL,
    PHASE_RETURN,
    PHASE_SLEEP,
    PHASE_SLIT,
    PHASE_WASH,
    SLEEP_FORCE_FATIGUE,
    SLIT_AT,
    WASH_DONE_FORCE,
    FacilityState,
)


def after_facility_action(world, resolution, *, book_turn: bool = False) -> list[dict]:
    """Advance time, pressures, and institution. Return world_events."""
    events: list[dict] = []
    facility: FacilityState = world.facility
    # Book turns advance outer time slowly
    cost = int(getattr(resolution, 'time_cost', 30) or 30)
    if book_turn:
        cost = max(5, cost // 4)
    if getattr(resolution, 'advance_time', True):
        world.world_time_seconds = int(world.world_time_seconds or 0) + cost
        advance_pressures_for_time(facility.pressures, cost)

    t = int(world.world_time_seconds or 0)
    phase = facility.phase

    # Bodily notice events for narrator
    q = qualitative_pressures(facility.pressures)
    if facility.pressures.hygiene_discomfort >= 55 and not facility.washed:
        events.append({
            'type': 'body_notice',
            'about': 'hygiene',
            'text': 'The smell under the blanket is mostly you.' if facility.room_id == 'cell'
            else 'Your skin feels unclean enough to distract.',
        })
    if facility.pressures.hunger >= 60 and not facility.fed:
        events.append({
            'type': 'body_notice',
            'about': 'hunger',
            'text': 'Your stomach tightens hard enough to interrupt a thought.',
        })
    if facility.pressures.fatigue >= 70:
        events.append({
            'type': 'body_notice',
            'about': 'fatigue',
            'text': 'Exhaustion makes the edges of the room soft.',
        })

    # Phase machine
    if phase == PHASE_CELL_IDLE and t >= SLIT_AT:
        _enter_phase(facility, PHASE_SLIT, t)
        facility.slit_open = True
        facility.staff_present = True
        facility.staff_count = 1
        door = facility.entity('door')
        if door:
            door.state['slit_open'] = True
            facility.set_entity(door)
        facility.last_npc_utterance = '… keth … back … varr …'
        facility.last_understood = 'back'
        events.append({
            'type': 'slit_opens',
            'npc_raw': facility.last_npc_utterance,
            'understood': 'something like “back” / “away”',
            'text': (
                'The slit opens. A person outside speaks. Most of it is noise. '
                'Gesture and repetition push one meaning through: back. Away.'
            ),
        })

    elif phase == PHASE_SLIT:
        if facility.cooperated_door or (t - facility.phase_entered_at) >= 90:
            _enter_phase(facility, PHASE_DOOR, t)
            events.append({
                'type': 'door_procedure',
                'text': 'The door procedure begins. They want distance from the door.',
            })

    elif phase == PHASE_DOOR:
        elapsed = t - facility.phase_entered_at
        if not facility.cooperated_door and elapsed >= 60:
            facility.door_escalation += 1
            facility.staff_count = min(3, 1 + facility.door_escalation)
            facility.pressures.physical_restraint = min(
                100, facility.pressures.physical_restraint + 20,
            )
            events.append({
                'type': 'door_escalate',
                'staff_count': facility.staff_count,
                'text': 'Instruction repeats. Gestures sharpen. Another figure arrives.',
            })
        if facility.cooperated_door or elapsed >= (DOOR_FORCE_AT - SLIT_AT) or facility.door_escalation >= 2:
            _enter_phase(facility, PHASE_REMOVAL, t)
            facility.room_id = 'corridor'
            facility.pressures.physical_restraint = max(50, facility.pressures.physical_restraint)
            facility.pressures.fear = min(100, facility.pressures.fear + 25)
            events.append({
                'type': 'forced_removal',
                'text': (
                    'The door opens under their rules. Hands find your arms. '
                    'The corridor begins whether you agree or not.'
                ),
            })

    elif phase == PHASE_REMOVAL:
        if (t - facility.phase_entered_at) >= 40:
            _enter_phase(facility, PHASE_WASH, t)
            facility.room_id = 'washroom'
            events.append({
                'type': 'arrive_wash',
                'text': 'They bring you to water and a basin. The institution intends washing.',
            })

    elif phase == PHASE_WASH:
        elapsed = t - facility.phase_entered_at
        if facility.washed or elapsed >= WASH_DONE_FORCE:
            if not facility.washed:
                facility.washed = True
                facility.pressures.hygiene_discomfort = 12
                events.append({
                    'type': 'washed',
                    'forced': True,
                    'text': 'Resistance fails. You are washed anyway. The air smells less like you.',
                })
            _enter_phase(facility, PHASE_FOOD, t)
            facility.room_id = 'mess'
            events.append({
                'type': 'arrive_food',
                'text': 'Next: a table, a bowl, heat rising from food.',
            })

    elif phase == PHASE_FOOD:
        elapsed = t - facility.phase_entered_at
        if facility.fed or elapsed >= FOOD_DONE_FORCE:
            if not facility.fed and facility.pressures.hunger >= 70:
                facility.fed = True
                facility.pressures.hunger = 8
                events.append({
                    'type': 'fed',
                    'forced_by_body': True,
                    'text': 'Whether by choice or stomach, the bowl empties.',
                })
            elif not facility.fed:
                facility.fed = True
                facility.pressures.hunger = 20
                events.append({
                    'type': 'fed',
                    'forced': True,
                    'text': 'They do not leave the food as a debate forever.',
                })
            _enter_phase(facility, PHASE_RETURN, t)
            facility.room_id = 'cell'
            facility.staff_present = False
            facility.staff_count = 0
            facility.slit_open = False
            facility.pressures.physical_restraint = 0
            facility.pressures.fatigue = min(100, facility.pressures.fatigue + 25)
            door = facility.entity('door')
            if door:
                door.state['slit_open'] = False
                facility.set_entity(door)
            events.append({
                'type': 'return_cell',
                'text': (
                    'They return you to the same cell. Whatever you moved is still moved. '
                    'You are cleaner, fed, and much more tired.'
                ),
            })

    elif phase == PHASE_RETURN:
        _enter_phase(facility, PHASE_SLEEP, t)
        events.append({
            'type': 'sleep_pressure',
            'text': 'The bed, once bleak, begins to look like an argument you will lose.',
        })

    elif phase == PHASE_SLEEP:
        if facility.slept or facility.pressures.fatigue >= SLEEP_FORCE_FATIGUE:
            if not facility.slept:
                facility.slept = True
                events.append({
                    'type': 'sleep',
                    'involuntary': True,
                    'text': 'A magnificent plan to stay awake. You wake later with your face against the wall.',
                })
            facility.phase = PHASE_DONE
            facility.pressures.fatigue = 5

    # Interrupt reading if slit/door events fire while book engaged
    if facility.book_engaged and any(
        e.get('type') in ('slit_opens', 'door_procedure', 'forced_removal') for e in events
    ):
        events.append({
            'type': 'book_interrupt',
            'text': (
                'Something knocks. Not in the corridor you were imagining. '
                'Again. The page is still under your thumb.'
            ),
        })

    resolution.world_events = list(getattr(resolution, 'world_events', None) or []) + events
    for ev in events:
        if ev.get('text'):
            resolution.facts.append(ev['text'])
    world.facility = facility
    # Sync visible entities
    world.visible_entities = [e.id for e in facility.entities_in_room()]
    return events


def _enter_phase(facility: FacilityState, phase: str, t: int) -> None:
    facility.phase = phase
    facility.phase_entered_at = t
