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

_BOOK_ENTER_ACS = frozenset({'read', 'examine', 'look', 'open'})
_BOOK_EXCLUDE = frozenset({
    'throw', 'kick', 'destroy', 'hide', 'burn', 'tear', 'rip', 'smash', 'attack',
})
_RESIST_SLEEP_ACS = frozenset({
    'resist_sleep', 'stay_awake', 'fight_sleep', 'remain_awake', 'keep_awake',
})
_STAND_FIRM_ACS = frozenset({
    'stand_firm', 'maintain_position', 'refuse', 'resist', 'hold_ground',
})
_COOPERATE_DOOR_RE = re.compile(
    r'\b('
    r'step\s+back|back\s+away|move\s+back|give\s+(the\s+)?door\s+space|'
    r'retreat|cooperate|obey'
    r')\b',
    re.I,
)
_NEGATED_BACK_RE = re.compile(
    r'\b('
    r'will\s+not|won\'?t|do\s+not|don\'?t|never|refuse\s+to|'
    r'not\s+(?:going\s+to\s+)?(?:back|step|move|retreat|give)'
    r')\b',
    re.I,
)
_BEDDING_MOVE_RE = re.compile(
    r'\b('
    r'bedding|blanket|blankets|sheet|sheets|'
    r'pull|strip|move|throw|drag|yank'
    r')\b',
    re.I,
)
_SLEEP_RE = re.compile(
    r'\b('
    r'sleep|lie\s+down|lie\s+on|rest|nap|doze'
    r')\b',
    re.I,
)
_RESIST_SLEEP_RE = re.compile(
    r'\b('
    r'fight\s+sleep|resist\s+sleep|stay\s+awake|remain\s+awake|'
    r'keep\s+awake|refuse\s+to\s+sleep|not\s+sleep|don\'?t\s+sleep|'
    r'will\s+not\s+sleep|won\'?t\s+sleep'
    r')\b',
    re.I,
)
_REFUSE_WASH_RE = re.compile(
    r'\b('
    r'refuse|resist|won\'?t|will\s+not|don\'?t|do\s+not|no\b|'
    r'throw\s+water|escape'
    r')\b',
    re.I,
)
_COOPERATE_WASH_RE = re.compile(
    r'\b(wash|clean|soap|bathe|cooperate|obey)\b',
    re.I,
)


def _word(text: str, word: str) -> bool:
    return bool(re.search(rf'\b{re.escape(word)}\b', text or '', re.I))


def _method(intent: Intent) -> str:
    return (intent.method or '').lower().strip()


def _effect(intent: Intent) -> str:
    return (intent.intended_effect or '').lower().strip()


def _ac(intent: Intent) -> str:
    return (intent.action_class or '').lower().strip()


def wants_book_exit(text: str) -> bool:
    t = (text or '').lower()
    return any(re.search(p, t) for p in BOOK_EXIT_PATTERNS)


def wants_book_enter(text: str, intent: Intent) -> bool:
    """Enter book only for read/open/examine — never throw/kick/destroy."""
    t = (text or '').lower()
    ac = _ac(intent)
    method = _method(intent)
    effect = _effect(intent)
    tokens = {ac, method, effect}
    if tokens & _BOOK_EXCLUDE:
        return False
    if any(_word(t, w) for w in _BOOK_EXCLUDE):
        return False
    tgt = (intent.target or '').lower().replace('the ', '').strip()
    bookish = _word(t, 'book') or tgt in ('book',)
    if not bookish:
        return False
    if ac in _BOOK_ENTER_ACS or method in _BOOK_ENTER_ACS:
        return True
    if any(_word(t, w) for w in ('read', 'open', 'examine')):
        return True
    # "look at/in the book" — not bare look around
    if _word(t, 'look') and _word(t, 'book'):
        return True
    if 'read' in ac and _word(t, 'book'):
        return True
    return False


def _resists_sleep(text: str, intent: Intent) -> bool:
    ac = _ac(intent)
    method = _method(intent)
    effect = _effect(intent)
    if ac in _RESIST_SLEEP_ACS or method in _RESIST_SLEEP_ACS:
        return True
    if any(x in effect for x in ('resist_sleep', 'stay_awake', 'remain_awake', 'fight_sleep')):
        return True
    if _RESIST_SLEEP_RE.search(text or ''):
        return True
    # "fight sleep" / "fight the sleep" via fight + sleep without bedding move
    if _word(text, 'fight') and _word(text, 'sleep'):
        return True
    return False


def _wants_bedding_move(text: str, intent: Intent) -> bool:
    t = text or ''
    ac = _ac(intent)
    method = _method(intent)
    if _word(t, 'bedding') or _word(t, 'blanket') or _word(t, 'blankets'):
        if any(_word(t, w) for w in ('pull', 'strip', 'move', 'throw', 'drag', 'floor', 'yank')):
            return True
        if method in ('pull', 'move', 'throw', 'strip', 'drag') or ac in ('move', 'throw', 'pull'):
            return True
    if _word(t, 'floor') and any(_word(t, w) for w in ('bedding', 'blanket', 'sheet')):
        return True
    if method in ('pull', 'move') and 'bed' in (intent.target or '').lower():
        # "pull bedding" often targets bed/bedding
        if any(x in t for x in ('bedding', 'blanket', 'floor')):
            return True
    return False


def _stands_firm(text: str, intent: Intent) -> bool:
    ac = _ac(intent)
    method = _method(intent)
    effect = _effect(intent)
    if ac in _STAND_FIRM_ACS or method in _STAND_FIRM_ACS:
        return True
    if any(x in effect for x in ('maintain_position', 'stand_firm', 'refuse', 'hold_ground')):
        return True
    if _NEGATED_BACK_RE.search(text or ''):
        return True
    return False


def _cooperates_door(text: str, intent: Intent) -> bool:
    if _stands_firm(text, intent):
        return False
    ac = _ac(intent)
    method = _method(intent)
    if ac in ('retreat', 'cooperate', 'obey') or method in ('retreat', 'step_back', 'back_away'):
        return True
    if _COOPERATE_DOOR_RE.search(text or ''):
        return True
    return False


def _refuses_wash(text: str, intent: Intent) -> bool:
    ac = _ac(intent)
    method = _method(intent)
    effect = _effect(intent)
    if ac in ('refuse', 'resist') or method in ('refuse', 'resist'):
        return True
    if any(x in effect for x in ('not_wash', 'refuse', 'resist', 'avoid_wash')):
        return True
    if _REFUSE_WASH_RE.search(text or '') and (
        _word(text, 'wash') or _word(text, 'clean') or _word(text, 'bath')
        or 'wash' in effect or facility_wash_context(text)
    ):
        return True
    # Bare refuse during wash phase handled by caller with phase check
    if _REFUSE_WASH_RE.search(text or '') and not _COOPERATE_WASH_RE.search(text or ''):
        return True
    return False


def facility_wash_context(text: str) -> bool:
    return bool(_COOPERATE_WASH_RE.search(text or ''))


def _match_entity(intent: Intent, text: str, facility: FacilityState) -> Optional[str]:
    t = (text or '').lower()
    tgt = (intent.target or '').lower().replace('the ', '').strip()
    # Prefer explicit entity names; bedding maps to bed
    if _word(t, 'bedding') or _word(t, 'blanket') or tgt in ('bedding', 'blanket'):
        if 'bed' in facility.entities:
            return 'bed'
    for eid, raw in facility.entities.items():
        name = str((raw or {}).get('name') or eid).lower()
        if eid == tgt or name == tgt:
            return eid
        if _word(t, eid) or (name and _word(t, name)):
            return eid
        if eid == 'door' and (_word(t, 'slit') or _word(t, 'door')):
            return 'door'
    return None


def _here(facility: FacilityState, eid: str) -> bool:
    ent = facility.entity(eid)
    if not ent:
        return False
    return ent.location == facility.room_id


def _accessible(facility: FacilityState, eid: str) -> bool:
    """Present in the current room or carried."""
    ent = facility.entity(eid)
    if not ent:
        return False
    return ent.location in (facility.room_id, 'inventory')


def _mark_visible(res: Resolution) -> None:
    res.image_dirty = True
    res.state_changed = True


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

    # Resist-sleep intents should be visible to decide_enactment
    text_l = (player_text or '').lower()
    if _resists_sleep(text_l, intent):
        if not intent.action_class or intent.action_class.lower() in ('other', 'wait', 'move'):
            intent.action_class = 'resist_sleep'

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
    # Exit only while actually in the book (or facility.book_engaged)
    in_book = bool(getattr(facility, 'book_engaged', False)) or (
        str(getattr(world, 'mode', '') or '') == 'book_dungeon'
    )
    if wants_book_exit(player_text):
        if not in_book:
            # Putting a physical book down in the cell is not a mode exit
            book = facility.entity('book')
            if book and book.location == 'inventory':
                book.location = facility.room_id
                book.state['position'] = 'on_floor'
                book.state['open'] = False
                facility.set_entity(book)
                res.facts.append('You put the book down. It stays closed.')
                res.actual_action = {'action_class': 'put_down', 'target': 'book', 'performed': True}
                res.intended_effect_achieved = True
                _mark_visible(res)
                res.enactment = ENACTMENT_DIRECT
                return res
            res.facts.append('You are not reading.')
            res.intended_effect_achieved = False
            res.enactment = ENACTMENT_DIRECT
            res.actual_action = {'action_class': 'close_book', 'performed': False}
            return res
        res.facts.append('You put the book aside.')
        res.structured_facts.append({'type': 'book_exit', 'kind': 'mode'})
        res.enactment = ENACTMENT_DIRECT
        res.actual_action = {'action_class': 'close_book', 'performed': True}
        res.enactment_cause = ''
        res.intended_effect_achieved = True
        res.state_changed = True
        return res

    if wants_book_enter(player_text, intent) and _accessible(facility, 'book'):
        if facility.phase in (
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
        res.facts.append('The institution leaves you no quiet to open the book.')
        res.structured_facts.append({'type': 'book_blocked', 'phase': facility.phase})
        res.enactment = ENACTMENT_ABORTED
        res.enactment_cause = 'institutional_force'
        res.actual_action = {'action_class': 'read_book', 'performed': False}
        res.intended_effect_achieved = False
        res.success = False
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

    if enactment == ENACTMENT_ABORTED:
        res.success = False
        res.intended_effect_achieved = False
        res.facts.append(_abort_fact(cause, intent))
        res.time_cost = 20
        return res

    if enactment == ENACTMENT_INVERTED:
        return _perform_inverted(facility, intent, res, actual_patch, player_text, rng)

    return _perform_action(
        facility, intent, res, player_text, rng,
        compromised=(enactment == ENACTMENT_COMPROMISED),
    )


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
    ac = _ac(intent)
    method = _method(intent)
    classification = intent.classification or ''
    eid = _match_entity(intent, player_text, facility)

    # Perception — but bare "no" is never perception (handled upstream / discourse)
    if classification == 'PERCEPTION_QUERY' or ac in ('look', 'examine', 'inspect', 'search'):
        if text.strip() in ('no', 'n', 'nope', 'nah'):
            return _refuse_instruction(facility, intent, res)
        return _perceive(facility, res, eid)

    # Speech / social
    if classification == 'SOCIAL_ACTION' or ac in (
        'talk', 'speak', 'ask', 'say', 'tell', 'shout', 'yell', 'threaten', 'apologise',
    ):
        return _speak(facility, intent, res, player_text, compromised=compromised)

    # Bedding move BEFORE sleep / bed occupation (substring "bed" must not steal this)
    if _wants_bedding_move(text, intent) or (
        eid == 'bed' and method in ('pull', 'move', 'throw', 'strip') and _word(text, 'floor')
    ):
        return _bed_action(facility, intent, res, text)

    # Resist sleep — never voluntary sleep
    if _resists_sleep(text, intent):
        return _resist_sleep_action(facility, intent, res)

    # Stand firm / refuse door instruction BEFORE cooperate substring traps
    if _stands_firm(text, intent) and facility.phase in (PHASE_SLIT, PHASE_DOOR):
        return _stand_firm_door(facility, res)

    # Door cooperate — phrase-level only
    if _cooperates_door(text, intent):
        if facility.phase in (PHASE_SLIT, PHASE_DOOR) and facility.room_id == 'cell':
            facility.cooperated_door = True
            facility.pressures.physical_restraint = max(0, facility.pressures.physical_restraint - 10)
            res.facts.append('You give the door space.')
            res.structured_facts.append({'type': 'cooperate_door'})
            res.actual_action = {'action_class': 'retreat', 'performed': True}
            res.intended_effect_achieved = True
            res.state_changed = True
            res.time_cost = 15
            return res

    # Sleep / lie down — word boundaries; never bare "bed"/"bedding"
    if (
        _SLEEP_RE.search(text)
        or ac in ('sleep', 'rest')
        or method in ('sleep', 'lie', 'rest')
    ) and not _resists_sleep(text, intent):
        if facility.room_id == 'cell' and _here(facility, 'bed'):
            if facility.pressures.fatigue >= 50 or facility.phase in (PHASE_RETURN, PHASE_SLEEP):
                facility.slept = True
                facility.phase = PHASE_DONE
                facility.pressures.fatigue = 8
                res.facts.append('You let the bed take your weight. Sleep follows.')
                res.structured_facts.append({'type': 'sleep', 'involuntary': False})
                res.actual_action = {'action_class': 'sleep', 'performed': True}
                res.intended_effect_achieved = True
                res.state_changed = True
                res.situation_changed = True
                return res
            res.facts.append('You lie on the bed. Sleep does not come yet.')
            bed = facility.entity('bed')
            if bed:
                bed.state['occupied'] = True
                facility.set_entity(bed)
            res.actual_action = {'action_class': 'lie_down', 'performed': True}
            res.intended_effect_achieved = True
            res.state_changed = True
            return res

    # Book physical actions (throw / move / pick) — never enter via these
    if eid == 'book' or _word(text, 'book'):
        if ac in ('throw', 'kick', 'move', 'hide', 'take', 'get', 'pick') or method in (
            'throw', 'kick', 'move', 'hide', 'take', 'pick', 'get',
        ) or any(
            _word(text, w) for w in (
                'throw', 'kick', 'hide', 'tear', 'rip', 'pick', 'take', 'put',
            )
        ):
            return _book_physical(facility, intent, res, text)

    # Drink / cup — only when cup is the target (or drink with no other object)
    if eid == 'cup' or _word(text, 'cup') or (
        ac == 'drink' or method == 'drink' or _word(text, 'drink')
    ):
        if eid in (None, 'cup') or _word(text, 'cup') or ac == 'drink' or method == 'drink':
            return _cup_action(facility, intent, res, text, compromised=compromised)

    # Bed examine / other bed actions
    if eid == 'bed' or _word(text, 'bed') or _word(text, 'blanket') or _word(text, 'bedding'):
        return _bed_action(facility, intent, res, text)

    # Door
    if eid == 'door' or _word(text, 'door') or _word(text, 'slit'):
        return _door_action(facility, intent, res, text)

    # Wash — refuse BEFORE cooperate (refuse to wash contains "wash")
    if facility.phase == PHASE_WASH:
        refuses = _refuses_wash(text, intent) or ac in ('refuse', 'resist') or method in ('refuse', 'resist')
        cooperates = bool(_COOPERATE_WASH_RE.search(text)) and not refuses
        if refuses:
            if compromised or facility.pressures.physical_restraint >= 50:
                facility.washed = True
                facility.pressures.hygiene_discomfort = 15
                res.facts.append('Refusal fails. The washing happens anyway.')
                res.structured_facts.append({'type': 'washed', 'forced': True})
                res.enactment = ENACTMENT_COMPROMISED
                res.enactment_cause = res.enactment_cause or 'physical_restraint'
                res.actual_action = {
                    'action_class': 'wash',
                    'performed': True,
                    'modifier': 'forced',
                }
                res.intended_effect_achieved = False
                res.state_changed = True
                return res
            res.facts.append('You resist the washing. Staff do not look impressed.')
            facility.door_escalation += 1
            facility.pressures.physical_restraint = min(100, facility.pressures.physical_restraint + 20)
            res.actual_action = {'action_class': 'refuse_wash', 'performed': True}
            res.intended_effect_achieved = True
            res.state_changed = True
            return res
        if cooperates or ac in ('wash', 'clean', 'cooperate', 'obey'):
            facility.washed = True
            facility.pressures.hygiene_discomfort = 10
            res.facts.append('You wash. The worst of the smell leaves with the water.')
            res.structured_facts.append({'type': 'washed'})
            res.actual_action = {'action_class': 'wash', 'performed': True}
            res.intended_effect_achieved = True
            res.state_changed = True
            return res

    # Food
    if facility.phase == PHASE_FOOD or eid == 'bowl' or _word(text, 'food') or _word(text, 'bowl') or ac == 'eat':
        if any(_word(text, w) for w in ('eat', 'taste', 'consume')) or ac == 'eat' or 'drink soup' in text:
            return _eat(facility, res, involuntary=False)
        if _word(text, 'hide') or method == 'hide' or ac == 'hide':
            return _hide_food(facility, res)
        if any(_word(text, w) for w in ('refuse', 'throw', 'push')) or method in ('refuse', 'throw', 'push'):
            if facility.pressures.hunger >= 85:
                return _eat(facility, res, involuntary=True)
            bowl = facility.entity('bowl')
            if bowl and (
                _word(text, 'throw') or _word(text, 'push') or method in ('throw', 'push')
                or ac in ('throw', 'push')
            ):
                bowl.location = facility.room_id
                bowl.state['full'] = False
                bowl.state['spilled'] = True
                facility.set_entity(bowl)
                res.facts.append('The bowl hits the floor. Food spreads.')
                res.structured_facts.append({'type': 'bowl_spilled'})
                res.actual_action = {'action_class': 'throw', 'target': 'bowl', 'performed': True}
                res.intended_effect_achieved = True
                _mark_visible(res)
                return res
            res.facts.append('You refuse the food. Your stomach disagrees quietly.')
            res.actual_action = {'action_class': 'refuse_food', 'performed': True}
            res.intended_effect_achieved = True
            res.state_changed = True
            return res

    # Violence
    if (
        'attack' in (_ac(intent) or '')
        or any(_word(text, w) for w in ('punch', 'hit', 'attack', 'kill', 'strike', 'fight'))
    ):
        # fight sleep already handled; fight staff falls through
        if _word(text, 'sleep') and not facility.staff_present:
            return _resist_sleep_action(facility, intent, res)
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

    # Wait
    if ac in ('wait',) or text.strip() in ('wait', 'wait.', '…'):
        res.facts.append('Time passes. The room does not hurry.')
        res.actual_action = {'action_class': 'wait', 'performed': True}
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

    # Self examine — sensory, not label dump
    if _word(text, 'myself') or _word(text, 'self') or ac == 'examine_self':
        from puca_dungeon.enactment import salient_sensations
        sensations = salient_sensations(facility.pressures)
        if sensations:
            res.facts.append('You take stock of yourself. ' + ' '.join(sensations[:3]))
        else:
            res.facts.append('You take stock of yourself. Nothing sharp demands attention.')
        res.intended_effect_achieved = True
        return res

    # Bare refuse / no without wash/food context
    if text.strip() in ('no', 'n', 'nope', 'nah') or ac == 'refuse':
        return _refuse_instruction(facility, intent, res)

    # Default: honest non-achievement
    res.facts.append('You do something minor. The room remains the room.')
    res.intended_effect_achieved = False
    res.meaningful_effort = False
    res.time_cost = 45
    return res


def _refuse_instruction(facility, intent, res) -> Resolution:
    if facility.phase in (PHASE_SLIT, PHASE_DOOR):
        return _stand_firm_door(facility, res)
    if facility.phase == PHASE_WASH:
        res.facts.append('You refuse. Staff note it.')
        facility.pressures.physical_restraint = min(100, facility.pressures.physical_restraint + 15)
        res.actual_action = {'action_class': 'refuse', 'performed': True}
        res.intended_effect_achieved = True
        res.state_changed = True
        return res
    if facility.phase == PHASE_FOOD:
        res.facts.append('You refuse the food. Your stomach disagrees quietly.')
        res.actual_action = {'action_class': 'refuse_food', 'performed': True}
        res.intended_effect_achieved = True
        res.state_changed = True
        return res
    res.facts.append('You refuse.')
    res.actual_action = {'action_class': 'refuse', 'performed': True}
    res.intended_effect_achieved = True
    return res


def _stand_firm_door(facility, res) -> Resolution:
    facility.cooperated_door = False
    facility.door_escalation += 1
    facility.pressures.physical_restraint = min(100, facility.pressures.physical_restraint + 15)
    facility.pressures.fear = min(100, facility.pressures.fear + 5)
    res.facts.append('You hold your ground. You do not give the door space.')
    res.structured_facts.append({'type': 'stand_firm', 'refused': 'back_away'})
    res.actual_action = {'action_class': 'stand_firm', 'performed': True}
    res.intended_effect_achieved = True
    res.state_changed = True
    res.time_cost = 15
    return res


def _resist_sleep_action(facility, intent, res) -> Resolution:
    facility.pressures.fatigue = min(100, facility.pressures.fatigue + 5)
    res.facts.append('You fight sleep. Your eyes burn; the bed still waits.')
    res.structured_facts.append({'type': 'resist_sleep'})
    res.actual_action = {'action_class': 'resist_sleep', 'performed': True}
    res.intended_effect_achieved = True
    res.state_changed = True
    res.time_cost = 40
    return res


def _hide_food(facility, res) -> Resolution:
    bowl = facility.entity('bowl')
    if not bowl or bowl.location not in (facility.room_id, 'inventory'):
        # Still in food phase — food is present even if bowl entity missing
        if facility.phase != PHASE_FOOD:
            res.facts.append('There is no food here to hide.')
            res.structured_facts.append({'type': 'entity_absent', 'entity': 'food'})
            res.success = False
            res.intended_effect_achieved = False
            return res
    if bowl:
        bowl.state['hidden'] = True
        bowl.state['position'] = 'hidden'
        # Still in room but concealed poorly
        facility.set_entity(bowl)
    res.facts.append(
        'You try to hide the food. There is nowhere that is not obvious. '
        'The bowl ends up under the table edge, still plainly food.'
    )
    res.structured_facts.append({'type': 'food_hidden', 'successful': False, 'attempted': True})
    res.actual_action = {'action_class': 'hide', 'target': 'food', 'performed': True, 'modifier': 'obvious'}
    res.intended_effect_achieved = False  # cannot truly conceal in this room
    res.enactment = ENACTMENT_COMPROMISED
    res.enactment_cause = res.enactment_cause or 'world_constraint'
    _mark_visible(res)
    return res


def _book_physical(facility, intent, res, text) -> Resolution:
    book = facility.entity('book')
    if not book or book.location not in (facility.room_id, 'inventory'):
        res.facts.append('There is no book here.')
        res.structured_facts.append({'type': 'entity_absent', 'entity': 'book'})
        res.success = False
        res.intended_effect_achieved = False
        return res
    ac = _ac(intent)
    method = _method(intent)
    if ac == 'throw' or method == 'throw' or _word(text, 'throw'):
        book.location = facility.room_id
        book.state['position'] = 'on_floor'
        book.state['open'] = False
        book.state['face_down'] = True
        facility.set_entity(book)
        res.facts.append('The book hits the floor. Pages slap shut. You do not read it.')
        res.structured_facts.append({'type': 'book_thrown'})
        res.actual_action = {'action_class': 'throw', 'target': 'book', 'performed': True}
        res.intended_effect_achieved = True
        _mark_visible(res)
        return res
    if 'put' in text and _word(text, 'bed'):
        book.location = facility.room_id
        book.state['position'] = 'on_bed'
        book.location = facility.room_id
        facility.set_entity(book)
        res.facts.append('You put the book on the bed. It stays closed.')
        res.actual_action = {'action_class': 'move', 'target': 'book', 'performed': True}
        res.intended_effect_achieved = True
        _mark_visible(res)
        return res
    if ac in ('move', 'take', 'get') or method in ('move', 'take', 'pick') or any(
        _word(text, w) for w in ('pick', 'take', 'move')
    ):
        book.state['position'] = 'in_hand'
        book.location = 'inventory'
        facility.set_entity(book)
        res.facts.append('You pick up the book. It stays closed.')
        res.actual_action = {'action_class': 'take', 'target': 'book', 'performed': True}
        res.intended_effect_achieved = True
        _mark_visible(res)
        return res
    if _word(text, 'hide') or ac == 'hide' or method == 'hide':
        book.state['position'] = 'hidden_under_bedding'
        facility.set_entity(book)
        res.facts.append('You shove the book out of sight. A corner still shows.')
        res.actual_action = {'action_class': 'hide', 'target': 'book', 'performed': True}
        res.intended_effect_achieved = True
        _mark_visible(res)
        return res
    res.facts.append(book.description)
    res.intended_effect_achieved = True
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
            if ent.state.get('position'):
                extra += f' It is {str(ent.state["position"]).replace("_", " ")}.'
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
        'target': (intent.target or 'staff') if facility.staff_present else intent.target,
    })
    if facility.staff_present and facility.phase in (PHASE_SLIT, PHASE_DOOR):
        res.facts.append('The person outside repeats a short sound and a gesture: back.')
        facility.last_npc_utterance = '… … back …'
        facility.last_understood = 'back / away'
        res.structured_facts.append({
            'type': 'npc_speech',
            'raw': facility.last_npc_utterance,
            'understood': facility.last_understood,
            'speaker': 'staff',
        })
        res.structured_facts.append({'type': 'discourse_focus', 'referent': 'staff'})
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
    ac = _ac(intent)
    method = _method(intent)
    if _word(text, 'drink') or ac == 'drink' or method == 'drink':
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
    if _word(text, 'throw') or ac == 'throw' or method == 'throw':
        cup.location = facility.room_id
        cup.state['position'] = 'on_floor'
        if any(_word(text, w) for w in ('hard', 'smash', 'break')):
            cup.broken = True
            cup.state['has_water'] = False
            cup.state['water_spilled'] = True
            res.facts.append('The cup hits the wall and cracks. Water goes everywhere.')
        else:
            cup.state['has_water'] = False
            cup.state['water_spilled'] = True
            res.facts.append('The cup skitters across the floor. Water spills.')
        facility.set_entity(cup)
        facility.pressures.hygiene_discomfort = min(100, facility.pressures.hygiene_discomfort + 5)
        res.structured_facts.append({
            'type': 'cup_thrown',
            'position': 'on_floor',
            'water_spilled': True,
            'broken': bool(cup.broken),
        })
        res.actual_action = {'action_class': 'throw', 'target': 'cup', 'performed': True}
        res.intended_effect_achieved = True
        _mark_visible(res)
        return res
    if any(_word(text, w) for w in ('move', 'pick', 'take', 'get')) or ac in ('take', 'get', 'move'):
        cup.state['position'] = 'in_hand'
        cup.location = 'inventory'
        facility.set_entity(cup)
        res.facts.append('You take the cup.')
        res.intended_effect_achieved = True
        _mark_visible(res)
        return res
    res.facts.append(cup.description)
    res.intended_effect_achieved = True
    return res


def _bed_action(facility, intent, res, text) -> Resolution:
    bed = facility.entity('bed')
    if not bed:
        res.facts.append('There is no bed here.')
        return res
    if (
        _wants_bedding_move(text, intent)
        or any(_word(text, w) for w in ('throw', 'floor', 'pull', 'strip'))
        or 'move bedding' in text
    ):
        bed.state['bedding'] = 'on_floor'
        facility.set_entity(bed)
        facility.pressures.hygiene_discomfort = min(100, facility.pressures.hygiene_discomfort + 5)
        res.facts.append('The bedding ends up on the floor. The smell follows it.')
        res.structured_facts.append({'type': 'bedding_moved', 'bedding': 'on_floor'})
        res.actual_action = {'action_class': 'move', 'target': 'bedding', 'performed': True}
        res.intended_effect_achieved = True
        _mark_visible(res)
        return res
    res.facts.append(bed.description + f' Bedding is {str(bed.state.get("bedding", "on_bed")).replace("_", " ")}.')
    res.intended_effect_achieved = True
    return res


def _door_action(facility, intent, res, text) -> Resolution:
    door = facility.entity('door')
    if not door:
        res.facts.append('There is no door here.')
        return res
    if any(_word(text, w) for w in ('open', 'force', 'kick', 'unlock')):
        res.facts.append('The door has no handle on this side. It does not open for you.')
        res.success = False
        res.intended_effect_achieved = False
        return res
    if _word(text, 'knock'):
        res.facts.append('You knock. The sound is small in the cell.')
        res.intended_effect_achieved = True
        return res
    if _word(text, 'slit') or _word(text, 'look') or _word(text, 'examine'):
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
