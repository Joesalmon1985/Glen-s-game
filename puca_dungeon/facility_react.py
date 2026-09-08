"""Institution timeline and bodily drift for the opening facility arc."""
from __future__ import annotations

from puca_dungeon.arc_state import situation_for_phase
from puca_dungeon.characters import (
    name_of,
    present_staff_ids,
    record_memory,
    subjects_for_window,
    unmet_subjects,
)
from puca_dungeon.enactment import advance_pressures_for_time, qualitative_pressures
from puca_dungeon.facility_models import (
    DAY2_RETRIEVE_AT,
    DOOR_FORCE_AT,
    FOOD_DONE_FORCE,
    HEAVEN_FORCE,
    HELL_FORCE,
    PHASE_CELL_IDLE,
    PHASE_CONTRACT,
    PHASE_CONTRACT_PROCESSING,
    PHASE_DAY2_WAKE,
    PHASE_DEATH_QUESTIONS,
    PHASE_DONE,
    PHASE_DOOR,
    PHASE_EXPLANATION,
    PHASE_FOOD,
    PHASE_HEAVEN,
    PHASE_HEAVEN_EXPIRE,
    PHASE_HEAVEN_MEMORIES,
    PHASE_HELL,
    PHASE_HELL_MEMORIES,
    PHASE_INTERVIEW,
    PHASE_MEMORY_INSTABILITY,
    PHASE_PREP_TRANSFER,
    PHASE_REMOVAL,
    PHASE_RESEARCH,
    PHASE_RETRIEVAL,
    PHASE_RETURN,
    PHASE_SECOND_OFFER,
    PHASE_SLEEP,
    PHASE_SLIT,
    PHASE_WASH,
    SLEEP_FORCE_FATIGUE,
    SLIT_AFTER_TURNS,
    SLIT_AT,
    WASH_DONE_FORCE,
    FacilityState,
)
from puca_dungeon.scene_change import emit_scene_change


def _set_presence(facility: FacilityState, ids: list[str], window: str = '') -> None:
    from puca_dungeon.npc_knowledge import get_knowledge, note_encounter
    extra = subjects_for_window(facility.arc.encounter_schedule, window) if window else []
    present = list(dict.fromkeys(list(ids) + extra))
    previous = set(getattr(facility.arc, 'present_ids', None) or [])
    facility.arc.present_ids = present
    for cid in present:
        if cid in ('iven', 'nessa', 'ruan'):
            facility.arc.mark_met(cid)
        if cid not in previous:
            k = get_knowledge(facility, cid)
            note_encounter(facility, cid, returning=bool(k.intro_done))
    facility.staff_present = any(
        cid in present for cid in (
            'orderly_quiet', 'orderly_anxious', 'senior_researcher',
            'attendant_a', 'attendant_b',
        )
    )
    facility.staff_count = sum(
        1 for cid in present
        if cid in ('orderly_quiet', 'orderly_anxious', 'senior_researcher')
    )
    conv = getattr(facility.arc, 'conversation', None) or {}
    cur = str(conv.get('interlocutor_id') or '')
    if cur and cur not in present:
        from puca_dungeon.conversation import set_interlocutor
        set_interlocutor(facility, '')


def _lead(resolution, facility, text: str, *, room: str | None = None, ask: str = '', kind: str = 'scene_change'):
    emit_scene_change(
        resolution, facility, text=text,
        from_room=facility.room_id, to_room=room or facility.room_id,
        ask=ask, kind=kind,
    )


def after_facility_action(world, resolution, *, book_turn: bool = False) -> list[dict]:
    """Advance time, pressures, and institution. Return world_events."""
    events: list[dict] = []
    facility: FacilityState = world.facility
    cost = int(getattr(resolution, 'time_cost', 30) or 30)
    if book_turn:
        cost = max(5, cost // 4)
    if getattr(resolution, 'advance_time', True):
        world.world_time_seconds = int(world.world_time_seconds or 0) + cost
        advance_pressures_for_time(facility.pressures, cost)

    t = int(world.world_time_seconds or 0)
    phase = facility.phase
    q = qualitative_pressures(facility.pressures)
    try:
        from puca_dungeon.npc_knowledge import flush_pending_intros
        for intro in flush_pending_intros(facility):
            events.append(intro)
            text = str(intro.get('text') or '').strip()
            if text and text not in (getattr(resolution, 'facts', None) or []):
                resolution.facts.append(text)
    except Exception:
        pass

    if facility.pressures.hygiene_discomfort >= 55 and not facility.washed:
        events.append({
            'type': 'body_notice', 'about': 'hygiene',
            'text': 'The smell under the blanket is mostly you.' if facility.room_id == 'cell'
            else 'Your skin feels unclean enough to distract.',
        })
    if facility.pressures.hunger >= 60 and not facility.fed:
        events.append({
            'type': 'body_notice', 'about': 'hunger',
            'text': 'Your stomach tightens hard enough to interrupt a thought.',
        })
    if facility.pressures.fatigue >= 70 and phase in (
        PHASE_CELL_IDLE, PHASE_RETURN, PHASE_SLEEP, PHASE_DAY2_WAKE,
    ):
        events.append({
            'type': 'body_notice', 'about': 'fatigue',
            'text': 'Exhaustion makes the edges of the room soft.',
        })

    # --- Day 1 ---
    # Wake slit: after N facility responses (not book enter / book dungeon turns).
    if phase == PHASE_CELL_IDLE:
        structured = list(getattr(resolution, 'structured_facts', None) or [])
        entered_book = any(
            isinstance(f, dict) and f.get('type') == 'book_enter' for f in structured
        )
        in_book = bool(facility.book_engaged) or entered_book or book_turn
        if not in_book:
            facility.cell_idle_turns = int(facility.cell_idle_turns or 0) + 1
        if (
            not in_book
            and int(facility.cell_idle_turns or 0) >= SLIT_AFTER_TURNS
        ):
            _enter_phase(facility, PHASE_SLIT, t)
            facility.slit_open = True
            _set_presence(facility, ['orderly_quiet'], 'wash_corridor')
            door = facility.entity('door')
            if door:
                door.state['slit_open'] = True
                facility.set_entity(door)
            from puca_dungeon.npc_knowledge import narrator_reference
            speaker_ref = narrator_reference(facility, 'orderly_quiet')
            facility.last_npc_utterance = 'back'
            facility.last_understood = 'back / away'
            facility.arc.scene_id = 'slit'
            facility.arc.last_ask = 'step away from the door'
            try:
                from puca_dungeon import discourse as _discourse
                world.last_npc_referent = 'orderly_quiet'
                _discourse.set_pending_binary(
                    world,
                    'The slit is open. They want you to step back from the door.',
                    {
                        'action_class': 'retreat',
                        'method': 'step_back',
                        'intended_effect': 'give_door_space',
                        'classification': 'SYSTEMIC_ACTION',
                        'understood': True,
                        'utterance': 'step back',
                    },
                )
                if isinstance(world.pending_discourse, dict):
                    world.pending_discourse['reject_intent'] = {
                        'action_class': 'stand_firm',
                        'method': 'stand_firm',
                        'intended_effect': 'maintain_position',
                        'classification': 'SYSTEMIC_ACTION',
                        'understood': True,
                        'utterance': 'I will not back away',
                    }
            except Exception:
                pass
            _lead(
                resolution, facility,
                (
                    f'The observation slit in the door opens. {speaker_ref.capitalize()} outside speaks slowly. '
                    f'You catch enough: back. Away. They want you to step away from the door.'
                ),
                ask='step away from the door',
                kind='slit_opens',
            )
            events.append({
                'type': 'slit_opens',
                'npc_raw': facility.last_npc_utterance,
                'understood': 'something like “back” / “away”',
                'text': resolution.facts[0] if resolution.facts else '',
            })

    elif phase == PHASE_SLIT:
        if facility.cooperated_door or (t - facility.phase_entered_at) >= 90:
            _enter_phase(facility, PHASE_DOOR, t)
            facility.arc.scene_id = 'door'
            facility.arc.last_ask = 'stay away from the door'
            _lead(
                resolution, facility,
                'The door procedure begins. They will not enter while you stand against it. Stay away from the door.',
                ask='stay away from the door',
                kind='door_procedure',
            )
            events.append({'type': 'door_procedure', 'text': resolution.facts[0] if resolution.facts else ''})

    elif phase == PHASE_DOOR:
        elapsed = t - facility.phase_entered_at
        if not facility.cooperated_door and elapsed >= 60:
            facility.door_escalation += 1
            facility.staff_count = min(3, 1 + facility.door_escalation)
            _set_presence(facility, present_staff_ids(facility.staff_count))
            facility.pressures.physical_restraint = min(
                100, facility.pressures.physical_restraint + 20,
            )
            events.append({
                'type': 'door_escalate',
                'staff_count': facility.staff_count,
                'text': (
                    'The person at the door abandons the hope that another gesture will work. '
                    'A short call carries into the corridor. Footsteps answer. '
                    'Another figure arrives — larger, ready to enter whether you move or not.'
                ),
            })
        if facility.cooperated_door or elapsed >= (DOOR_FORCE_AT - SLIT_AT) or facility.door_escalation >= 2:
            _enter_phase(facility, PHASE_REMOVAL, t)
            facility.pressures.physical_restraint = max(50, facility.pressures.physical_restraint)
            facility.pressures.fear = min(100, facility.pressures.fear + 25)
            _set_presence(facility, ['orderly_quiet', 'orderly_anxious'])
            _lead(
                resolution, facility,
                (
                    'You leave the cell. The door opens under their rules. Hands find your arms. '
                    'You are in the corridor now.'
                ),
                room='corridor',
                kind='forced_removal',
            )
            events.append({'type': 'forced_removal', 'text': resolution.facts[0] if resolution.facts else ''})

    elif phase == PHASE_REMOVAL:
        if (t - facility.phase_entered_at) >= 40:
            _enter_phase(facility, PHASE_WASH, t)
            _set_presence(facility, ['orderly_quiet', 'orderly_anxious'], 'wash_corridor')
            facility.arc.scene_id = 'wash'
            facility.arc.last_ask = 'wash'
            _lead(
                resolution, facility,
                'They take you out of the corridor and into a washroom. Water. A basin. They intend to wash you.',
                room='washroom',
                ask='wash',
                kind='arrive_wash',
            )
            events.append({'type': 'arrive_wash', 'text': resolution.facts[0] if resolution.facts else ''})

    elif phase == PHASE_WASH:
        elapsed = t - facility.phase_entered_at
        if facility.washed or elapsed >= WASH_DONE_FORCE:
            if not facility.washed:
                facility.washed = True
                facility.pressures.hygiene_discomfort = 12
                facility.arc.wash_style = facility.arc.wash_style or 'forced'
                events.append({
                    'type': 'washed', 'forced': True,
                    'text': (
                        'Resistance fails. You are washed anyway. '
                        'The air smells less like you. Your skin is immediately, unmistakably cleaner.'
                    ),
                })
                resolution.enactment = 'compromised'
                resolution.enactment_cause = resolution.enactment_cause or 'institutional_force'
                resolution.intended_effect_achieved = False
                resolution.actual_action = {
                    **(dict(getattr(resolution, 'actual_action', None) or {})),
                    'action_class': 'wash', 'performed': True, 'modifier': 'forced',
                }
                resolution.state_changed = True
            _enter_phase(facility, PHASE_FOOD, t)
            _set_presence(facility, ['orderly_quiet', 'orderly_anxious'], 'meal')
            facility.arc.scene_id = 'meal'
            facility.arc.last_ask = 'eat'
            _lead(
                resolution, facility,
                'They take you from the washroom to a mess room. A table. A bowl. Heat rising from food. They want you to eat.',
                room='mess',
                ask='eat',
                kind='arrive_food',
            )
            events.append({'type': 'arrive_food', 'text': resolution.facts[0] if resolution.facts else ''})

    elif phase == PHASE_FOOD:
        elapsed = t - facility.phase_entered_at
        if facility.fed or elapsed >= FOOD_DONE_FORCE:
            if not facility.fed and facility.pressures.hunger >= 70:
                facility.fed = True
                facility.pressures.hunger = 8
                events.append({
                    'type': 'fed', 'forced_by_body': True,
                    'text': 'Whether by choice or stomach, the bowl empties. Hunger eases at once.',
                })
            elif not facility.fed:
                facility.fed = True
                facility.pressures.hunger = 20
                events.append({
                    'type': 'fed', 'forced': True,
                    'text': 'They do not leave the food as a debate forever. Hunger eases a little.',
                })
            _enter_phase(facility, PHASE_RETURN, t)
            _set_presence(facility, ['orderly_quiet'], 'return_escort')
            facility.slit_open = False
            facility.pressures.physical_restraint = 0
            facility.pressures.fatigue = min(100, facility.pressures.fatigue + 25)
            door = facility.entity('door')
            if door:
                door.state['slit_open'] = False
                facility.set_entity(door)
            facility.arc.scene_id = 'return'
            facility.staff_present = False
            facility.staff_count = 0
            facility.arc.present_ids = subjects_for_window(
                facility.arc.encounter_schedule, 'return_escort',
            )
            company = ''
            if facility.arc.present_ids:
                from puca_dungeon.npc_knowledge import narrator_reference
                labels = [narrator_reference(facility, cid) for cid in facility.arc.present_ids]
                company = (
                    f' Someone else is already here: {", ".join(labels)}. '
                    'They watch you without explaining anything.'
                )
            _lead(
                resolution, facility,
                (
                    'They take you back to the same cell. Whatever you moved is still moved. '
                    'You are cleaner, and much more tired.'
                    + (' You are less hungry.' if facility.fed else '')
                    + company
                ),
                room='cell',
                kind='return_cell',
            )
            events.append({'type': 'return_cell', 'text': resolution.facts[0] if resolution.facts else ''})

    elif phase == PHASE_RETURN:
        _enter_phase(facility, PHASE_SLEEP, t)
        facility.arc.last_ask = ''
        events.append({
            'type': 'sleep_pressure',
            'text': 'The bed, once bleak, begins to look like an argument you will lose. This is still the same cell. Day 1 is ending.',
        })

    elif phase == PHASE_SLEEP:
        if (
            facility.slept
            or facility.pressures.fatigue >= SLEEP_FORCE_FATIGUE
            or (t - facility.phase_entered_at) >= 90
        ):
            if not facility.slept:
                facility.slept = True
                events.append({
                    'type': 'sleep', 'involuntary': True,
                    'text': 'A magnificent plan to stay awake. You wake later with your face against the wall.',
                })
            _wake_day2(facility, world, resolution, t, events)

    elif phase == PHASE_DONE:
        # Legacy saves / inverted sleep used to park here. Continue the arc.
        _wake_day2(facility, world, resolution, t, events)

    # --- Day 2+ ---
    elif phase == PHASE_DAY2_WAKE:
        if (t - facility.phase_entered_at) >= 15:
            _enter_phase(facility, PHASE_RETRIEVAL, t)
            _set_presence(facility, ['orderly_quiet', 'orderly_anxious'], 'day2_retrieval')
            facility.arc.day = 2
            facility.arc.scene_id = 'retrieval'
            _lead(
                resolution, facility,
                'Morning. The collection is more formal. They take you from the cell into the corridor, then toward another room.',
                room='corridor',
                kind='retrieval',
            )
            events.append({'type': 'retrieval', 'text': resolution.facts[0] if resolution.facts else ''})

    elif phase == PHASE_RETRIEVAL:
        if (t - facility.phase_entered_at) >= 35:
            _enter_phase(facility, PHASE_INTERVIEW, t)
            _set_presence(facility, ['senior_researcher', 'orderly_quiet'], 'interview_waiting')
            world.last_npc_referent = 'senior_researcher'
            from puca_dungeon.npc_knowledge import narrator_reference
            senior_ref = narrator_reference(facility, 'senior_researcher')
            facility.arc.scene_id = 'interview'
            facility.arc.last_ask = 'answer their questions'
            _lead(
                resolution, facility,
                (
                    f'You are taken into an interview room. {senior_ref.capitalize()} sits opposite you. '
                    f'They wear a precisely fitted collar as naturally as clothing. '
                    f'No one explains it. They begin to ask questions with pictures and slow words.'
                ),
                room='interview',
                ask='answer their questions',
                kind='arrive_interview',
            )
            events.append({'type': 'arrive_interview', 'text': resolution.facts[0] if resolution.facts else ''})

    elif phase == PHASE_INTERVIEW:
        if facility.arc.interview_index >= 4 or (t - facility.phase_entered_at) >= 150:
            _enter_phase(facility, PHASE_MEMORY_INSTABILITY, t)
            facility.arc.scene_id = 'memory_instability'
            events.append({
                'type': 'memory_instability',
                'text': 'A smell in the room prompts something. A name produces an image. The memories arrive without being asked for. Some feel vivid. Some feel wrong.',
            })

    elif phase == PHASE_MEMORY_INSTABILITY:
        if (t - facility.phase_entered_at) >= 40:
            _enter_phase(facility, PHASE_DEATH_QUESTIONS, t)
            facility.arc.scene_id = 'death'
            facility.arc.last_ask = 'what happened when you died'
            events.append({
                'type': 'death_questions',
                'text': 'The questioning changes. They ask what happened when you died. If you say you do not remember dying, they continue anyway: darkness, waking, warmth, pain, voices, light.',
            })

    elif phase == PHASE_DEATH_QUESTIONS:
        if (t - facility.phase_entered_at) >= 40:
            _enter_phase(facility, PHASE_HEAVEN_MEMORIES, t)
            facility.arc.scene_id = 'heaven_memories'
            events.append({
                'type': 'heaven_memories',
                'text': 'Warmth. Sunlight. Clean bedding. Food. Running water. Safety. They treat these as evidence. You are not told whether they are memories, dreams, or made things.',
            })

    elif phase == PHASE_HEAVEN_MEMORIES:
        if (t - facility.phase_entered_at) >= 40:
            _enter_phase(facility, PHASE_HELL_MEMORIES, t)
            facility.arc.scene_id = 'hell_memories'
            facility.arc.fear_of_hell = min(100, facility.arc.fear_of_hell + 25)
            facility.pressures.fear = min(100, facility.pressures.fear + 15)
            events.append({
                'type': 'hell_memories',
                'text': 'Then they ask about the other place. Heat or cold. Foul air. Noise. Thirst. The conviction that it will never end. Fear of that place settles somewhere you cannot file away.',
            })

    elif phase == PHASE_HELL_MEMORIES:
        if (t - facility.phase_entered_at) >= 40:
            _enter_phase(facility, PHASE_EXPLANATION, t)
            _set_presence(facility, ['senior_researcher'], 'afterlife_break')
            facility.arc.scene_id = 'explanation'
            events.append({
                'type': 'explanation',
                'text': (
                    'They explain, in slow words: you continued after death. Consciousness can persist. '
                    'They maintain environments for that. Heaven is reward. Hell is permanent exclusion. '
                    'They do not present this as a threat. They present it as reality.'
                ),
            })

    elif phase == PHASE_EXPLANATION:
        if (t - facility.phase_entered_at) >= 45:
            _offer_contract(world, facility, resolution, t, events, first=True)

    elif phase == PHASE_CONTRACT:
        # Wait for player; restated ask is added below
        pass

    elif phase == PHASE_PREP_TRANSFER:
        if (t - facility.phase_entered_at) >= 25:
            _enter_heaven(facility, world, resolution, t, events)

    elif phase == PHASE_HEAVEN:
        facility.arc.heaven_turns += 1
        facility.arc.heaven_experienced = True
        if facility.arc.heaven_turns >= 2 or (t - facility.phase_entered_at) >= HEAVEN_FORCE:
            _enter_phase(facility, PHASE_HEAVEN_EXPIRE, t)
            facility.arc.scene_id = 'heaven_expire'
            facility.arc.last_ask = ''
            _lead(
                resolution, facility,
                'They tell you the entitlement is complete. The day in Heaven is over. They intend to take you.',
                ask='',
                kind='heaven_expires',
            )
            events.append({'type': 'heaven_expires', 'text': resolution.facts[0] if resolution.facts else ''})
            _enter_hell(facility, world, resolution, t, events)

    elif phase == PHASE_HEAVEN_EXPIRE:
        _enter_hell(facility, world, resolution, t, events)

    elif phase == PHASE_HELL:
        facility.arc.hell_turns += 1
        facility.arc.hell_experienced = True
        facility.arc.fear_of_hell = min(100, facility.arc.fear_of_hell + 8)
        if facility.arc.hell_turns >= 2 or (t - facility.phase_entered_at) >= HELL_FORCE:
            _ensure_subjects_met(facility, resolution, events)
            _enter_phase(facility, PHASE_SECOND_OFFER, t)
            _set_presence(facility, ['senior_researcher'])
            world.last_npc_referent = 'senior_researcher'
            facility.arc.scene_id = 'second_offer'
            _offer_contract(world, facility, resolution, t, events, first=False)

    elif phase == PHASE_SECOND_OFFER:
        pass

    elif phase == PHASE_CONTRACT_PROCESSING:
        if (t - facility.phase_entered_at) >= 40:
            _enter_research(facility, world, resolution, t, events)

    elif phase == PHASE_RESEARCH:
        facility.arc.situation_line = situation_for_phase(
            PHASE_RESEARCH, 'research_quarters',
            'You are a registered research subject. The next work has not begun.',
        )

    # Restate pending asks — never while the subject is inside the book
    entered_book = any(
        isinstance(f, dict) and f.get('type') == 'book_enter'
        for f in (getattr(resolution, 'structured_facts', None) or [])
    )
    if (
        facility.arc.last_ask
        and not facility.book_engaged
        and not entered_book
        and not book_turn
        and phase in (
            PHASE_SLIT, PHASE_DOOR, PHASE_WASH, PHASE_FOOD, PHASE_CONTRACT, PHASE_SECOND_OFFER,
        )
    ):
        restated = f'They are still waiting: {facility.arc.last_ask}'
        if restated not in (resolution.facts or []):
            events.append({'type': 'restated_ask', 'text': restated, 'ask': facility.arc.last_ask})

    if facility.book_engaged and any(
        e.get('type') in ('slit_opens', 'door_procedure', 'forced_removal', 'retrieval') for e in events
    ):
        events.append({
            'type': 'book_interrupt',
            'text': (
                'The printed corridor breaks. A knock comes from the real room — the cell. '
                'Again. The page is still under your thumb, but the cell is where you are.'
            ),
        })

    resolution.world_events = list(getattr(resolution, 'world_events', None) or []) + events
    for ev in events:
        if ev.get('text') and ev['text'] not in (resolution.facts or []):
            resolution.facts.append(ev['text'])
        if ev.get('type') in (
            'slit_opens', 'door_procedure', 'forced_removal', 'washed', 'fed',
            'retrieval', 'arrive_interview', 'heaven_expires',
        ):
            resolution.image_dirty = True
            resolution.state_changed = True
    # On room change, drop stale same-room furniture dumps that fight the new scene
    room_changed = any(
        isinstance(ev, dict) and ev.get('type') == 'scene_change'
        and ev.get('from_room') and ev.get('to_room')
        and ev.get('from_room') != ev.get('to_room')
        for ev in (resolution.world_events or [])
    )
    if room_changed:
        stale = (
            'a narrow table', 'bowl of something warm', 'soap that smells medicinal',
            'water. a basin', 'plain corridor',
        )
        kept = []
        for f in list(resolution.facts or []):
            if not isinstance(f, str):
                kept.append(f)
                continue
            fl = f.lower().strip()
            # Keep must-lead scene_change texts and action outcomes
            if any(
                isinstance(ev, dict) and ev.get('text') == f and ev.get('must_lead')
                for ev in (resolution.world_events or [])
            ):
                kept.append(f)
                continue
            if fl in stale or fl.startswith('water. a basin'):
                continue
            kept.append(f)
        resolution.facts = kept
    facility.arc.situation_line = situation_for_phase(
        facility.phase, facility.room_id, facility.arc.last_ask,
    )
    try:
        from puca_dungeon.narrative_context import update_after_turn
        flipped = any(
            ev.get('type') in (
                'slit_opens', 'door_procedure', 'forced_removal', 'arrive_wash',
                'washed', 'fed', 'retrieval', 'arrive_interview', 'day2_wake',
                'contract_offer', 'heaven_expires',
            )
            or ev.get('type') == 'scene_change'
            for ev in events
            if isinstance(ev, dict)
        )
        update_after_turn(facility, resolution, scene_flipped=flipped)
    except Exception:
        pass
    world.facility = facility
    if getattr(world, 'mode', 'facility') == 'facility' and not book_turn:
        world.visible_entities = [e.id for e in facility.entities_in_room()]
    return events


def _wake_day2(facility, world, resolution, t, events) -> None:
    if facility.phase == PHASE_DAY2_WAKE:
        return
    _enter_phase(facility, PHASE_DAY2_WAKE, t)
    facility.slept = True
    facility.pressures.fatigue = 15
    facility.arc.day = 2
    facility.arc.scene_id = 'retrieval'
    facility.room_id = 'cell'
    facility.staff_present = False
    facility.staff_count = 0
    _lead(
        resolution, facility,
        'You wake in the same cell. It is a new day. The institution will collect you more formally.',
        room='cell',
        kind='day2_wake',
    )
    events.append({'type': 'day2_wake', 'text': resolution.facts[0] if resolution.facts else ''})


def _offer_contract(world, facility, resolution, t, events, *, first: bool) -> None:
    from puca_dungeon import discourse as _discourse
    if first:
        _enter_phase(facility, PHASE_CONTRACT, t)
        facility.arc.scene_id = 'contract'
        text = (
            'They offer a five-year research agreement: examinations, surgery, neurological procedures, '
            'biopsies, testing, drugs, memory experiments, sleep studies, language assessment, monitoring. '
            'At completion: five years in Heaven. The terms are bureaucratic. Will you agree?'
        )
    else:
        text = (
            'A clean professional arrives in Hell. Calm. They ask whether you wish to reconsider. '
            'The five-year agreement is offered again. Will you agree now?'
        )
    facility.arc.last_ask = 'agree to the five-year research service'
    _lead(resolution, facility, text, ask=facility.arc.last_ask, kind='contract_offer')
    _discourse.set_pending_binary(
        world,
        'Will you agree to the five-year research service?',
        {
            'action_class': 'accept_contract',
            'method': 'accept',
            'intended_effect': 'sign_agreement',
            'classification': 'SOCIAL_ACTION',
            'understood': True,
            'utterance': 'yes',
        },
    )
    if isinstance(world.pending_discourse, dict):
        world.pending_discourse['reject_intent'] = {
            'action_class': 'refuse_contract',
            'method': 'refuse',
            'intended_effect': 'decline_agreement',
            'classification': 'SOCIAL_ACTION',
            'understood': True,
            'utterance': 'no',
        }
    events.append({'type': 'contract_offer', 'first': first, 'text': text})


def _enter_heaven(facility, world, resolution, t, events) -> None:
    _enter_phase(facility, PHASE_HEAVEN, t)
    facility.arc.heaven_experienced = True
    facility.arc.scene_id = 'heaven'
    facility.arc.last_ask = ''
    facility.pressures.physical_restraint = 0
    facility.pressures.hygiene_discomfort = 8
    facility.pressures.hunger = 10
    _set_presence(facility, ['attendant_a'], 'heaven')
    _lead(
        resolution, facility,
        (
            'You lose consciousness during their preparation. You wake somewhere else entirely. '
            'They call it Heaven. It is warm, clean, quiet, and well supplied. '
            'It is physically real. They encourage you to believe only your mind arrived.'
        ),
        room='heaven',
        kind='wake_heaven',
    )
    events.append({'type': 'wake_heaven', 'text': resolution.facts[0] if resolution.facts else ''})


def _enter_hell(facility, world, resolution, t, events) -> None:
    _enter_phase(facility, PHASE_HELL, t)
    facility.arc.hell_experienced = True
    facility.arc.scene_id = 'hell'
    facility.arc.fear_of_hell = min(100, facility.arc.fear_of_hell + 20)
    facility.pressures.fear = min(100, facility.pressures.fear + 20)
    facility.pressures.hygiene_discomfort = 70
    facility.pressures.thirst = 55
    _set_presence(facility, [], 'hell')
    _lead(
        resolution, facility,
        (
            'You are sedated and taken. You wake somewhere else. They call it Hell. '
            'The air is foul. The surface hurts. Someone designed this. There are no demons.'
        ),
        room='hell',
        kind='wake_hell',
    )
    events.append({'type': 'wake_hell', 'text': resolution.facts[0] if resolution.facts else ''})


def _ensure_subjects_met(facility, resolution, events) -> None:
    missing = unmet_subjects(facility.arc.encounter_schedule, facility.arc.met_ids)
    if not missing:
        return
    for cid in missing:
        facility.arc.mark_met(cid)
        if cid not in facility.arc.present_ids:
            facility.arc.present_ids.append(cid)
        from puca_dungeon.npc_knowledge import narrator_reference, note_encounter
        note_encounter(facility, cid, returning=False)
        ref = narrator_reference(facility, cid)
        events.append({
            'type': 'subject_meeting',
            'who': cid,
            'text': f'{ref.capitalize()} is here among the other occupants. You have seen them now.',
        })


def _enter_research(facility, world, resolution, t, events) -> None:
    missing = unmet_subjects(facility.arc.encounter_schedule, facility.arc.met_ids)
    for cid in missing:
        facility.arc.mark_met(cid)
        record_memory(facility.cast, cid, 'Met Sarel at research intake.')
    _enter_phase(facility, PHASE_RESEARCH, t)
    facility.arc.scene_id = 'research'
    facility.arc.last_ask = ''
    facility.staff_present = False
    _set_presence(facility, ['iven', 'nessa', 'ruan'])
    # Book follows if it was in inventory or cell
    book = facility.entity('book')
    if book and book.location in ('cell', 'inventory', facility.room_id):
        book.location = 'research_quarters'
        facility.set_entity(book)
    _lead(
        resolution, facility,
        (
            'They register you as a cooperating research subject. '
            'You are taken to subject quarters in the research wing. The next work has not begun.'
        ),
        room='research_quarters',
        kind='research_intake',
    )
    events.append({'type': 'research_intake', 'text': resolution.facts[0] if resolution.facts else ''})


def enter_processing(world, resolution, *, from_route: str) -> None:
    """Called from resolve when a contract is actually accepted."""
    facility = world.facility
    t = int(world.world_time_seconds or 0)
    _enter_phase(facility, PHASE_CONTRACT_PROCESSING, t)
    facility.arc.scene_id = 'processing'
    facility.arc.last_ask = ''
    _set_presence(facility, ['senior_researcher'])
    emit_scene_change(
        resolution, facility,
        text='The agreement is processed. They do not celebrate. Paperwork, a mark on a file, a corridor.',
        from_room=facility.room_id,
        to_room='corridor',
        kind='contract_processing',
    )
    resolution.world_events = list(getattr(resolution, 'world_events', None) or []) + [
        {'type': 'contract_processing', 'route': from_route},
    ]


def _enter_phase(facility: FacilityState, phase: str, t: int) -> None:
    facility.phase = phase
    facility.phase_entered_at = t
