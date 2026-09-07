"""Resolve player intentions in the Level 1 facility world."""
from __future__ import annotations

import re
from typing import Any, Optional

from puca_dungeon.enactment import (
    ENACTMENT_ABORTED,
    ENACTMENT_COMPROMISED,
    ENACTMENT_DIRECT,
    ENACTMENT_INVERTED,
    decide_enactment,
    qualitative_pressures,
    truncate_speech,
    wanted_action_from_intent,
)
from puca_dungeon.facility_models import (
    PHASE_CELL_IDLE,
    PHASE_DOOR,
    PHASE_DONE,
    PHASE_FOOD,
    PHASE_REMOVAL,
    PHASE_RETURN,
    PHASE_SLEEP,
    PHASE_SLIT,
    PHASE_WASH,
    Entity,
    FacilityState,
)
from puca_dungeon.models import Intent
from puca_dungeon.resolve import Resolution
from puca_dungeon.rng import GameRNG


BOOK_EXIT_PATTERNS = (
    r'\bput\s+(the\s+)?book\s+down\b',
    r'\bclose\s+(the\s+)?book\b',
    r'\bstop\s+reading\b',
    r'\benough\s+of\s+this\b',
    r'\blook\s+away\b',
    r'\bput\s+it\s+down\b',
    r'\bclose\s+it\b',
)


def wants_book_exit(text: str) -> bool:
    t = (text or '').lower()
    return any(re.search(p, t) for p in BOOK_EXIT_PATTERNS)


def wants_book_enter(text: str, intent: Intent) -> bool:
    t = (text or '').lower()
    ac = (intent.action_class or '').lower()
    if 'book' in t and any(w in t for w in ('read', 'open', 'look', 'pick', 'examine')):
        return True
    if ac in ('read', 'examine', 'look', 'open', 'use') and (intent.target or '').lower() in ('book', 'the book'):
        return True
    if 'read' in ac and 'book' in t:
        return True
    return False


def _entity_ref(text: str, facility: FacilityState) -> Optional[str]:
    t = (text or '').lower()
    for eid in ('book', 'cup', 'bed', 'door', 'bowl', 'basin', 'slit'):
        if eid in t or eid.replace('_', ' ') in t:
            if eid == 'slit':
                return 'door'
            return eid
    target = (getattr(Intent, 'target', None))
    return None


def _match_entity(intent: Intent, text: str, facility: FacilityState) -> Optional[str]:
    t = (text or '').lower()
    tgt = (intent.target or '').lower().replace('the ', '')
    for eid, raw in facility.entities.items():
        name = str((raw or {}).get('name') or eid).lower()
        if eid in t or name in t or eid == tgt or name == tgt:
            return eid
        if eid == 'door' and ('slit' in t or 'door' in t):
            return 'door'
    return None


def _here(facility: FacilityState, eid: str) -> bool:
    ent = facility.entity(eid)
    if not ent:
        return False
    return ent.location == facility.room_id


def resolve_facility(
    world,
    intent: Intent,
    grounding,
    rng: GameRNG,
    player_text: str = '',
) -> Resolution:
    facility: FacilityState = world.facility
    res = Resolution(
        intent_understood=bool(intent.understood),
        grounded=True,
        feasible=True,
        success=True,
        attempted=True,
        intended_effect_achieved=False,
        advance_time=True,
        time_cost=30,
    )
    wanted = wanted_action_from_intent(intent)
    res.wanted_action = wanted

    pressures = facility.pressures
    institutional = facility.phase in (
        PHASE_REMOVAL, PHASE_WASH, PHASE_FOOD, PHASE_DOOR,
    ) and facility.staff_present

    enactment, cause, actual_patch = decide_enactment(
        pressures=pressures,
        action_class=intent.action_class or '',
        manner=intent.manner,
        classification=intent.classification,
        feasible=True,
        world_blocked=False,
        institutional_force=institutional and facility.physical_control_active()
        if hasattr(facility, 'physical_control_active') else (
            institutional and pressures.physical_restraint >= 40
        ),
        rng=rng,
    )

    # Book enter/exit handled by session; signal via facts
    if wants_book_exit(player_text):
        res.facts.append('You put the book aside.')
        res.structured_facts.append({'type': 'book_exit', 'kind': 'mode'})
        res.enactment = ENACTMENT_DIRECT
        res.actual_action = {'action_class': 'close_book', 'performed': True}
        res.enactment_cause = ''
        res.intended_effect_achieved = True
        res.state_changed = True
        return res

    if wants_book_enter(player_text, intent) and _here(facility, 'book') and facility.phase in (
        PHASE_CELL_IDLE, PHASE_RETURN, PHASE_SLEEP, PHASE_SLIT,
    ):
        res.facts.append('You turn to the book.')
        res.structured_facts.append({'type': 'book_enter', 'kind': 'mode'})
        res.enactment = ENACTMENT_DIRECT
        res.actual_action = {'action_class': 'read_book', 'performed': True}
        res.intended_effect_achieved = True
        res.state_changed = True
        res.show_passage_text = False
        return res

    # Apply enactment gating before world mutations
    res.enactment = enactment
    res.enactment_cause = cause
    res.actual_action = dict(actual_patch)
    res.structured_facts.append({
        'type': 'enactment',
        'enactment': enactment,
        'cause': cause or None,
        'wanted': wanted,
        'actual': dict(actual_patch),
    })
    res.structured_facts.append({
        'type': 'body_pressures',
        'qualitative': qualitative_pressures(pressures),
    })

    if enactment == ENACTMENT_ABORTED:
        res.success = False
        res.intended_effect_achieved = False
        res.facts.append(_abort_fact(cause, intent))
        res.time_cost = 20
        return res

    if enactment == ENACTMENT_INVERTED:
        # Perform the inverted actual action instead
        return _perform_inverted(facility, intent, res, actual_patch, player_text, rng)

    # Compromised or direct — attempt the intended action with modifiers
    return _perform_action(facility, intent, res, player_text, rng, compromised=(enactment == ENACTMENT_COMPROMISED))


def _abort_fact(cause: str, intent: Intent) -> str:
    if cause == 'fear':
        return 'Your body refuses to complete the motion.'
    if cause == 'physical_restraint':
        return 'Hands already hold you; the attempt goes nowhere.'
    if cause == 'fatigue':
        return 'Exhaustion cuts the attempt short.'
    if cause == 'external_threat':
        return 'The corridor and the people in it leave you no room to enact that.'
    return 'You cannot make yourself finish that.'


def _perform_inverted(facility, intent, res, actual_patch, player_text, rng) -> Resolution:
    ac = str(actual_patch.get('action_class') or '')
    if ac == 'apologise':
        spoken = truncate_speech('Sorry.', facility.pressures.language_ability)
        res.facts.append(f'Your mouth produces: “{spoken}”')
        res.structured_facts.append({'type': 'speech', 'intended': intent.utterance or player_text, 'spoken': spoken})
        res.success = True
        res.intended_effect_achieved = False
        return res
    if ac == 'sleep':
        facility.slept = True
        facility.phase = PHASE_DONE
        facility.pressures.fatigue = 10
        res.facts.append('You lose the argument with sleep.')
        res.structured_facts.append({'type': 'sleep', 'involuntary': True})
        res.state_changed = True
        res.situation_changed = True
        res.intended_effect_achieved = False
        return res
    if ac == 'eat':
        return _eat(facility, res, involuntary=True)
    res.facts.append('Something else happens instead of what you intended.')
    res.intended_effect_achieved = False
    return res


def _perform_action(facility, intent, res, player_text, rng, *, compromised: bool) -> Resolution:
    text = (player_text or '').lower()
    ac = (intent.action_class or '').lower()
    classification = intent.classification or ''
    eid = _match_entity(intent, player_text, facility)

    # Perception
    if classification == 'PERCEPTION_QUERY' or ac in ('look', 'examine', 'inspect', 'search'):
        return _perceive(facility, res, eid)

    # Speech / social
    if classification == 'SOCIAL_ACTION' or ac in ('talk', 'speak', 'ask', 'say', 'tell', 'shout', 'yell', 'threaten', 'apologise'):
        return _speak(facility, intent, res, player_text, compromised=compromised)

    # Movement / back away (door procedure)
    if any(w in text for w in ('back', 'away', 'step back', 'retreat')) or ac in ('retreat', 'move'):
        if facility.phase in (PHASE_SLIT, PHASE_DOOR) and facility.room_id == 'cell':
            facility.cooperated_door = True
            facility.pressures.physical_restraint = max(0, facility.pressures.physical_restraint - 10)
            res.facts.append('You give the door space.')
            res.structured_facts.append({'type': 'cooperate_door'})
            res.intended_effect_achieved = True
            res.state_changed = True
            res.time_cost = 15
            return res

    # Sleep / lie down
    if any(w in text for w in ('sleep', 'lie down', 'lie on', 'rest', 'bed')) or ac in ('sleep', 'rest'):
        if facility.room_id == 'cell' and _here(facility, 'bed'):
            if facility.pressures.fatigue >= 50 or facility.phase in (PHASE_RETURN, PHASE_SLEEP):
                facility.slept = True
                facility.phase = PHASE_DONE
                facility.pressures.fatigue = 8
                res.facts.append('You let the bed take your weight. Sleep follows.')
                res.structured_facts.append({'type': 'sleep', 'involuntary': False})
                res.intended_effect_achieved = True
                res.state_changed = True
                res.situation_changed = True
                return res
            res.facts.append('You lie on the bed. Sleep does not come yet.')
            bed = facility.entity('bed')
            if bed:
                bed.state['occupied'] = True
                facility.set_entity(bed)
            res.intended_effect_achieved = True
            res.state_changed = True
            return res

    # Drink / cup
    if eid == 'cup' or 'cup' in text or ac in ('drink', 'throw'):
        return _cup_action(facility, intent, res, text, compromised=compromised)

    # Bed / bedding
    if eid == 'bed' or 'bed' in text or 'blanket' in text or 'bedding' in text:
        return _bed_action(facility, intent, res, text)

    # Door
    if eid == 'door' or 'door' in text or 'slit' in text:
        return _door_action(facility, intent, res, text)

    # Wash cooperation / resistance
    if facility.phase == PHASE_WASH:
        if any(w in text for w in ('wash', 'clean', 'soap', 'cooperate', 'obey')):
            facility.washed = True
            facility.pressures.hygiene_discomfort = 10
            res.facts.append('You wash. The worst of the smell leaves with the water.')
            res.structured_facts.append({'type': 'washed'})
            res.intended_effect_achieved = True
            res.state_changed = True
            return res
        if any(w in text for w in ('refuse', 'no', 'resist', 'throw water', 'escape')):
            if compromised or facility.pressures.physical_restraint >= 50:
                facility.washed = True
                facility.pressures.hygiene_discomfort = 15
                res.facts.append('Refusal fails. The washing happens anyway.')
                res.structured_facts.append({'type': 'washed', 'forced': True})
                res.enactment = ENACTMENT_COMPROMISED
                res.enactment_cause = res.enactment_cause or 'physical_restraint'
                res.intended_effect_achieved = False
                res.state_changed = True
                return res
            res.facts.append('You resist the washing. Staff do not look impressed.')
            facility.door_escalation += 1
            facility.pressures.physical_restraint = min(100, facility.pressures.physical_restraint + 20)
            res.intended_effect_achieved = True
            res.state_changed = True
            return res

    # Food
    if facility.phase == PHASE_FOOD or eid == 'bowl' or 'food' in text or 'bowl' in text or 'eat' in ac:
        if any(w in text for w in ('eat', 'taste', 'drink soup', 'consume')) or ac == 'eat':
            return _eat(facility, res, involuntary=False)
        if any(w in text for w in ('refuse', 'throw', 'push away', 'hide')):
            if facility.pressures.hunger >= 85:
                return _eat(facility, res, involuntary=True)
            bowl = facility.entity('bowl')
            if bowl and 'throw' in text:
                bowl.location = facility.room_id
                bowl.state['full'] = False
                bowl.state['spilled'] = True
                facility.set_entity(bowl)
                res.facts.append('The bowl hits the floor. Food spreads.')
            else:
                res.facts.append('You refuse the food. Your stomach disagrees quietly.')
            res.intended_effect_achieved = True
            res.state_changed = True
            return res

    # Violence
    if classification and 'attack' in (intent.action_class or '').lower() or any(
        w in text for w in ('punch', 'hit', 'attack', 'kill', 'strike')
    ):
        # If we reached here, enactment was direct/compromised
        if facility.staff_present:
            facility.pressures.fear = min(100, facility.pressures.fear + 15)
            facility.pressures.physical_restraint = min(100, facility.pressures.physical_restraint + 25)
            res.facts.append(
                'The attempt is messy and short. Staff tighten their hold.'
                if not compromised else
                'What reaches them is little more than a twitch. They notice anyway.'
            )
            res.success = False
            res.intended_effect_achieved = False
            res.state_changed = True
            return res
        res.facts.append('There is no one here to hit.')
        res.structured_facts.append({'type': 'entity_absent', 'entity': 'target'})
        res.success = False
        res.none_reason = 'entity_absent'
        res.enactment = ENACTMENT_DIRECT
        res.enactment_cause = 'world_constraint'
        return res

    # Wait / nonsense / general
    # Wait / nonsense / general
    if ac in ('wait', 'other') or text.strip() in ('wait', 'wait.', '…'):
        res.facts.append('Time passes. The room does not hurry.')
        res.intended_effect_achieved = True
        res.time_cost = 60
        return res

    if classification == 'IMPOSSIBLE_ATTEMPT':
        res.facts.append('Reality does not stretch that far.')
        res.structured_facts.append({'type': 'impossible_attempt'})
        res.success = False
        res.intended_effect_achieved = False
        res.none_reason = 'impossible_here'
        return res

    # Self examine
    if 'myself' in text or 'self' in text or ac == 'examine_self':
        q = qualitative_pressures(facility.pressures)
        res.facts.append(
            f'Your body reports: {q["hygiene"]} skin, {q["hunger"]} gut, {q["fatigue"]} limbs.'
        )
        res.intended_effect_achieved = True
        return res

    # Default: small time pass with bodily notice
    res.facts.append('You do something minor. The room remains the room.')
    res.intended_effect_achieved = True
    res.meaningful_effort = False
    res.time_cost = 45
    return res


def _perceive(facility, res, eid) -> Resolution:
    if eid:
        ent = facility.entity(eid)
        if not ent or ent.location not in (facility.room_id, 'inventory'):
            res.facts.append(f'There is no {eid} here.')
            res.structured_facts.append({'type': 'entity_absent', 'entity': eid})
            res.success = False
            res.none_reason = 'entity_absent'
            return res
        extra = ''
        if eid == 'cup':
            extra = ' It is empty.' if not ent.state.get('has_water') else ' Water still sits in it.'
            if ent.state.get('position'):
                extra += f' It is {ent.state["position"].replace("_", " ")}.'
        if eid == 'book':
            extra = ' Face-down, badly printed.' if ent.state.get('face_down') else ' Open to a page.'
        if eid == 'door':
            extra = ' The slit is open.' if facility.slit_open else ' The slit is shut.'
            extra += ' No handle on this side.'
        if eid == 'bed':
            bedding = ent.state.get('bedding', 'on_bed')
            extra = f' Bedding is {bedding.replace("_", " ")}.'
        res.facts.append(f'{ent.description}{extra}')
        res.structured_facts.append({
            'type': 'perception', 'entity': eid, 'location': ent.location, 'state': dict(ent.state),
        })
        res.intended_effect_achieved = True
        res.time_cost = 20
        return res

    room = facility.rooms.get(facility.room_id) or {}
    visible = [e.name for e in facility.entities_in_room()]
    res.facts.append(str(room.get('description') or 'You look around.'))
    res.structured_facts.append({
        'type': 'perception', 'kind': 'visible_entities', 'entities': visible,
    })
    res.intended_effect_achieved = True
    return res


def _speak(facility, intent, res, player_text, *, compromised: bool) -> Resolution:
    intended = intent.utterance or player_text
    spoken = truncate_speech(intended, facility.pressures.language_ability)
    if compromised and facility.pressures.fatigue >= 60:
        spoken = spoken.lower()
    res.facts.append(f'You manage: “{spoken}”' if spoken else 'No useful sound comes out.')
    res.structured_facts.append({
        'type': 'speech',
        'intended': intended,
        'spoken': spoken,
        'understood_by_npc': bool(spoken) and facility.staff_present,
    })
    if facility.staff_present and facility.phase in (PHASE_SLIT, PHASE_DOOR):
        # Staff still want backing away
        res.facts.append('The person outside repeats a short sound and a gesture: back.')
        facility.last_npc_utterance = '… … back …'
        facility.last_understood = 'back / away'
        res.structured_facts.append({
            'type': 'npc_speech',
            'raw': facility.last_npc_utterance,
            'understood': facility.last_understood,
        })
    elif not facility.staff_present:
        res.facts.append('No one answers.')
        res.structured_facts.append({'type': 'social_no_uptake'})
    res.intended_effect_achieved = True
    res.time_cost = 25
    return res


def _cup_action(facility, intent, res, text, *, compromised: bool) -> Resolution:
    cup = facility.entity('cup')
    if not cup or cup.location not in (facility.room_id, 'inventory'):
        res.facts.append('There is no cup here.')
        res.structured_facts.append({'type': 'entity_absent', 'entity': 'cup'})
        res.success = False
        res.none_reason = 'entity_absent'
        return res
    ac = (intent.action_class or '').lower()
    if 'drink' in text or ac == 'drink':
        if cup.state.get('has_water'):
            cup.state['has_water'] = False
            facility.pressures.thirst = max(0, facility.pressures.thirst - 25)
            facility.set_entity(cup)
            res.facts.append('You drink. The water is flat and welcome.')
            res.intended_effect_achieved = True
            res.state_changed = True
        else:
            res.facts.append('The cup is empty.')
            res.intended_effect_achieved = False
        return res
    if 'throw' in text or ac == 'throw':
        cup.location = facility.room_id
        cup.state['position'] = 'on_floor'
        if 'hard' in text or 'smash' in text or 'break' in text:
            cup.broken = True
            cup.state['has_water'] = False
            res.facts.append('The cup hits the wall and cracks. Water goes everywhere.')
        else:
            cup.state['has_water'] = False
            res.facts.append('The cup skitters across the floor. Water spills.')
        facility.set_entity(cup)
        facility.pressures.hygiene_discomfort = min(100, facility.pressures.hygiene_discomfort + 5)
        res.intended_effect_achieved = True
        res.state_changed = True
        return res
    if 'move' in text or 'pick' in text or ac in ('take', 'get', 'move'):
        cup.state['position'] = 'in_hand'
        cup.location = 'inventory'
        facility.set_entity(cup)
        res.facts.append('You take the cup.')
        res.intended_effect_achieved = True
        res.state_changed = True
        return res
    res.facts.append(cup.description)
    res.intended_effect_achieved = True
    return res


def _bed_action(facility, intent, res, text) -> Resolution:
    bed = facility.entity('bed')
    if not bed:
        res.facts.append('There is no bed here.')
        return res
    if any(w in text for w in ('throw', 'floor', 'pull', 'move bedding', 'strip')):
        bed.state['bedding'] = 'on_floor'
        facility.set_entity(bed)
        facility.pressures.hygiene_discomfort = min(100, facility.pressures.hygiene_discomfort + 5)
        res.facts.append('The bedding ends up on the floor. The smell follows it.')
        res.intended_effect_achieved = True
        res.state_changed = True
        return res
    res.facts.append(bed.description + f' Bedding is {str(bed.state.get("bedding", "on_bed")).replace("_", " ")}.')
    res.intended_effect_achieved = True
    return res


def _door_action(facility, intent, res, text) -> Resolution:
    door = facility.entity('door')
    if not door:
        res.facts.append('There is no door here.')
        return res
    if any(w in text for w in ('open', 'force', 'kick', 'unlock')):
        res.facts.append('The door has no handle on this side. It does not open for you.')
        res.success = False
        res.intended_effect_achieved = False
        return res
    if 'knock' in text:
        res.facts.append('You knock. The sound is small in the cell.')
        res.intended_effect_achieved = True
        return res
    if 'slit' in text or 'look' in text or 'examine' in text:
        if facility.slit_open:
            res.facts.append('Through the slit: a face, motion, words you only half catch.')
        else:
            res.facts.append('The slit is a dark narrow line at eye height.')
        res.intended_effect_achieved = True
        return res
    res.facts.append(door.description)
    res.intended_effect_achieved = True
    return res


def _eat(facility, res, *, involuntary: bool) -> Resolution:
    bowl = facility.entity('bowl')
    if facility.phase != PHASE_FOOD and (not bowl or bowl.location != facility.room_id):
        res.facts.append('There is no food here.')
        res.structured_facts.append({'type': 'entity_absent', 'entity': 'food'})
        res.success = False
        return res
    facility.fed = True
    facility.pressures.hunger = 5
    if bowl:
        bowl.state['full'] = False
        facility.set_entity(bowl)
    if involuntary:
        res.facts.append(
            'You intend to refuse. Your hand reaches the bowl. When the argument ends, you are holding the spoon.'
        )
        res.enactment = ENACTMENT_COMPROMISED
        res.enactment_cause = 'hunger'
        res.actual_action = {'action_class': 'eat', 'performed': True, 'modifier': 'body_overrode_refusal'}
        res.intended_effect_achieved = False
    else:
        res.facts.append('You eat. Warmth settles where hunger was.')
        res.intended_effect_achieved = True
    res.structured_facts.append({'type': 'fed', 'involuntary': involuntary})
    res.state_changed = True
    return res
