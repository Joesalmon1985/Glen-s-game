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
from puca_dungeon.behavior import apply_tags, classify_subject, tag_action
from puca_dungeon.facility_models import (
    PHASE_CELL_IDLE,
    PHASE_CONTRACT,
    PHASE_DAY2_WAKE,
    PHASE_DEATH_QUESTIONS,
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
    Entity,
    FacilityState,
)
from puca_dungeon.language import is_language_attempt, practice_language
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
_STAY_HELL_RE = re.compile(
    r'\b('
    r'stay(\s+here)?|remain|choose\s+hell|prefer\s+hell|'
    r'rather\s+suffer|refuse\s+again|never\s+sign|do\s+not\s+agree'
    r')\b',
    re.I,
)
_ACCEPT_CONTRACT_RE = re.compile(
    r'\b(accept|agree|sign|yes|i\s+will|cooperate)\b',
    re.I,
)
_REFUSE_CONTRACT_RE = re.compile(
    r'\b(refuse|decline|no|will\s+not|won\'?t|never)\b',
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
            PHASE_DAY2_WAKE, PHASE_RESEARCH, PHASE_HEAVEN,
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

    # Language grows only from attempted communication, never from time/chapter
    if is_language_attempt(intent, player_text) and hasattr(facility, 'arc'):
        facility.arc.language_attempts, delta = practice_language(
            facility.pressures, facility.arc.language_attempts,
        )
        if delta:
            res.structured_facts.append({
                'type': 'language_practice',
                'attempts': facility.arc.language_attempts,
                'delta': delta,
            })

    if hasattr(facility, 'arc'):
        tags = tag_action(intent, player_text, enactment)
        facility.arc.tendencies = apply_tags(facility.arc.tendencies, tags)

    # Apply enactment gating before world mutations (structured fact synced AFTER perform)
    res.enactment = enactment
    res.enactment_cause = cause
    res.actual_action = dict(actual_patch)

    if enactment == ENACTMENT_ABORTED:
        res.success = False
        res.intended_effect_achieved = False
        res.facts.append(_abort_fact(cause, intent))
        res.time_cost = 20
        res.structured_facts.append({
            'type': 'enactment',
            'enactment': res.enactment,
            'cause': res.enactment_cause or None,
            'wanted': wanted,
            'actual': dict(getattr(res, 'actual_action', None) or {}),
        })
        return res

    if enactment == ENACTMENT_INVERTED:
        out = _perform_inverted(facility, intent, res, actual_patch, player_text, rng)
        out.structured_facts.append({
            'type': 'enactment',
            'enactment': out.enactment,
            'cause': out.enactment_cause or None,
            'wanted': wanted,
            'actual': dict(getattr(out, 'actual_action', None) or {}),
        })
        return out

    out = _perform_action(
        facility, intent, res, player_text, rng,
        compromised=(enactment == ENACTMENT_COMPROMISED),
    )
    out.structured_facts.append({
        'type': 'enactment',
        'enactment': out.enactment,
        'cause': out.enactment_cause or None,
        'wanted': wanted,
        'actual': dict(getattr(out, 'actual_action', None) or {}),
    })
    return out


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
        facility.phase = PHASE_SLEEP
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

    later = _later_arc_action(facility, intent, res, player_text, ac, text)
    if later is not None:
        return later

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
                facility.phase = PHASE_SLEEP
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
                res.facts.append(
                    'You brace and refuse. Their grip does not argue — it simply continues. '
                    'Water and soap arrive anyway; washing you appears to be routine to them, not punishment.'
                )
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
            if hasattr(facility, 'arc'):
                facility.arc.wash_style = 'verbal'
                facility.arc.flag('verbally_resistant', True)
            facility.door_escalation += 1
            facility.pressures.physical_restraint = min(100, facility.pressures.physical_restraint + 20)
            res.actual_action = {'action_class': 'refuse_wash', 'performed': True}
            res.intended_effect_achieved = True
            res.state_changed = True
            return res
        if cooperates or ac in ('wash', 'clean', 'cooperate', 'obey'):
            facility.washed = True
            facility.pressures.hygiene_discomfort = 10
            if hasattr(facility, 'arc'):
                facility.arc.wash_style = 'cooperated'
            res.facts.append(
                'You wash. The worst of the smell leaves with the water. '
                'Your skin is immediately, unmistakably cleaner.'
            )
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
        ask = getattr(getattr(facility, 'arc', None), 'last_ask', '') or ''
        if ask and facility.staff_present:
            res.facts.append(f'You wait. They are still waiting: {ask}')
        elif facility.staff_present:
            res.facts.append('You wait. The staff do not fill the silence for you.')
        else:
            res.facts.append('You wait. The cell keeps its quiet.')
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

    # Default: honest non-achievement — stay in-scene, not meta
    ask = getattr(getattr(facility, 'arc', None), 'last_ask', '') or ''
    if ask and facility.staff_present:
        res.facts.append(f'That does not change what they want. They are still waiting: {ask}')
    elif facility.staff_present:
        res.facts.append('Nothing useful comes of it. The staff watch without helping.')
    else:
        res.facts.append('Nothing useful comes of that. The cell is unchanged.')
    res.intended_effect_achieved = False
    res.meaningful_effort = False
    res.time_cost = 45
    return res


def _refuse_instruction(facility, intent, res) -> Resolution:
    if facility.phase in (PHASE_CONTRACT, PHASE_SECOND_OFFER, PHASE_EXPLANATION):
        return _handle_contract(facility, res, accept=False, player_text='no')
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
    present = list(getattr(getattr(facility, 'arc', None), 'present_ids', None) or [])
    speaker = facility.character_name(present[0]) if present else 'Someone beyond the door'
    if facility.door_escalation <= 1:
        res.facts.append(
            f'You hold your ground. You do not give the door space. '
            f'{speaker} stops repeating the gesture for a moment, watching you, then turns as if to call for help.'
        )
    else:
        res.facts.append(
            'You hold your ground. You do not give the door space. '
            'They have stopped hoping repetition will work.'
        )
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
    present = list(getattr(getattr(facility, 'arc', None), 'present_ids', None) or [])
    if present:
        names = [facility.character_name(cid) for cid in present]
        res.facts.append('Here: ' + ', '.join(names) + '.')
        if 'senior_researcher' in present:
            res.facts.append(
                f'{facility.character_name("senior_researcher")} wears a precisely fitted collar. '
                'Nobody explains it.'
            )
    if getattr(getattr(facility, 'arc', None), 'last_ask', ''):
        res.facts.append(f'They are still waiting: {facility.arc.last_ask}')
    res.structured_facts.append({
        'type': 'perception', 'kind': 'visible_entities', 'entities': visible,
        'people': present,
    })
    res.intended_effect_achieved = True
    return res


def _speak(facility, intent, res, player_text, *, compromised: bool) -> Resolution:
    intended = intent.utterance or player_text
    spoken = truncate_speech(intended, facility.pressures.language_ability)
    if compromised and facility.pressures.fatigue >= 60:
        spoken = spoken.lower()
    res.facts.append(f'You manage: “{spoken}”' if spoken else 'No useful sound comes out.')
    present = list(getattr(getattr(facility, 'arc', None), 'present_ids', None) or [])
    target = intent.target or (present[0] if present else ('staff' if facility.staff_present else None))
    res.structured_facts.append({
        'type': 'speech',
        'intended': intended,
        'spoken': spoken,
        'understood_by_npc': bool(spoken) and (facility.staff_present or bool(present)),
        'target': target,
    })
    if facility.phase in (PHASE_CONTRACT, PHASE_SECOND_OFFER, PHASE_EXPLANATION):
        return _handle_contract(facility, res, accept=None, player_text=player_text)
    if facility.phase in (
        PHASE_INTERVIEW, PHASE_MEMORY_INSTABILITY, PHASE_DEATH_QUESTIONS,
        PHASE_HEAVEN_MEMORIES, PHASE_HELL_MEMORIES,
    ):
        return _handle_interview_speech(facility, res, player_text)
    if facility.staff_present and facility.phase in (PHASE_SLIT, PHASE_DOOR):
        speaker_id = present[0] if present else 'orderly_quiet'
        from puca_dungeon.social_meaning import resolve_conversational_move
        from puca_dungeon.npc_strategy import apply_move_to_speech_facts
        move = resolve_conversational_move(facility, speaker_id, player_text=player_text)
        speaker = move.get('speaker_name') or facility.character_name(speaker_id)
        ask = getattr(getattr(facility, 'arc', None), 'last_ask', '') or 'step away from the door'
        if move.get('tone') == 'careful' or 'without unnecessary force' in str(move.get('objective') or ''):
            res.facts.append(
                f'{speaker} gestures again, clearer this time: back from the door. '
                f'Then: please. They are still waiting: {ask}.'
            )
            facility.last_understood = 'back / please / away'
        else:
            res.facts.append(
                f'{speaker} repeats a short sound and a gesture: back. They are still waiting: {ask}.'
            )
            facility.last_understood = 'back / away'
        facility.last_npc_utterance = '… … back …'
        res.structured_facts.extend(apply_move_to_speech_facts(
            facility, move,
            raw=facility.last_npc_utterance,
            understood=facility.last_understood,
        ))
        res.structured_facts.append({'type': 'discourse_focus', 'referent': speaker_id})
        res.structured_facts.append({
            'type': 'conversational_move',
            'speaker': speaker_id,
            'surface': move.get('surface') or {},
        })
    elif present:
        cid = present[0]
        from puca_dungeon.social_meaning import resolve_conversational_move
        from puca_dungeon.npc_strategy import apply_move_to_speech_facts
        move = resolve_conversational_move(facility, cid, player_text=player_text)
        nm = move.get('speaker_name') or facility.character_name(cid)
        surface = move.get('surface') or {}
        manner = surface.get('manner') or move.get('tone') or 'guarded'
        if move.get('move') == 'TEST':
            res.facts.append(
                f'{nm} mentions something small and odd — water behind a wall — without explaining why. '
                f'Their manner is {manner}.'
            )
            facility.last_understood = 'a low-risk detail offered as a test'
        elif move.get('move') == 'WITHHOLD':
            res.facts.append(f'{nm} listens. Then: “That\'s all I know.” It plainly isn\'t.')
            facility.last_understood = 'refusal to say more'
        elif move.get('move') == 'RECIPROCATE':
            res.facts.append(
                f'{nm} looks once toward the corridor, then offers a more useful fragment than before.'
            )
            facility.last_understood = 'a careful reciprocation'
        else:
            res.facts.append(
                f'{nm} is here. They listen more than they explain. They appear to want: '
                f'{surface.get("appears_to_want") or move.get("objective") or "information"}.'
            )
        res.structured_facts.extend(apply_move_to_speech_facts(
            facility, move, raw=facility.last_npc_utterance or '…', understood=facility.last_understood or '',
        ))
        res.structured_facts.append({'type': 'discourse_focus', 'referent': cid})
        res.structured_facts.append({
            'type': 'conversational_move',
            'speaker': cid,
            'surface': surface,
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


def _later_arc_action(facility, intent, res, player_text, ac, text):
    phase = facility.phase
    if phase in (PHASE_CONTRACT, PHASE_SECOND_OFFER, PHASE_EXPLANATION) or ac in (
        'accept_contract', 'refuse_contract',
    ):
        stay = bool(_STAY_HELL_RE.search(text or '')) and phase == PHASE_SECOND_OFFER
        if stay or ac == 'refuse_contract':
            return _handle_contract(facility, res, accept=False, player_text=player_text, stay_in_hell=stay)
        if ac == 'accept_contract' or (
            _ACCEPT_CONTRACT_RE.search(text or '') and not _REFUSE_CONTRACT_RE.search(text or '')
        ):
            return _handle_contract(facility, res, accept=True, player_text=player_text)
        if _REFUSE_CONTRACT_RE.search(text or '') or ac in ('refuse',):
            return _handle_contract(facility, res, accept=False, player_text=player_text)
        if phase in (PHASE_CONTRACT, PHASE_SECOND_OFFER):
            res.facts.append(f'They are still waiting: {facility.arc.last_ask or "agree to the five-year research service"}')
            res.actual_action = {'action_class': 'wait', 'performed': True}
            res.intended_effect_achieved = False
            return res

    if phase == PHASE_PREP_TRANSFER:
        if any(_word(text, w) for w in ('scratch', 'mark', 'hide', 'conceal')):
            facility.arc.body_marks.append('a deliberate scratch')
            facility.arc.discover('marked_before_transfer')
            res.facts.append('You mark yourself before they finish. The mark is small and yours.')
            res.intended_effect_achieved = True
            res.state_changed = True
            return res
        if any(_word(text, w) for w in ('inspect', 'look', 'machine', 'examine')):
            facility.arc.discover('recognised_sedation')
            res.facts.append('The machines look like medical equipment, not a door out of the world.')
            res.intended_effect_achieved = True
            return res
        res.facts.append('They continue the preparation. The room hums. Consciousness thins.')
        res.intended_effect_achieved = True
        return res

    if phase in (PHASE_HEAVEN, PHASE_HEAVEN_EXPIRE):
        return _heaven_action(facility, intent, res, text)
    if phase == PHASE_HELL and (
        ac == 'refuse_contract' or _STAY_HELL_RE.search(text or '')
    ):
        facility.phase = PHASE_SECOND_OFFER
        return _handle_contract(facility, res, accept=False, player_text=player_text, stay_in_hell=True)
    if phase in (PHASE_HELL, PHASE_SECOND_OFFER) and ac not in ('accept_contract', 'refuse_contract'):
        if phase == PHASE_HELL:
            return _hell_action(facility, intent, res, text)

    if phase in (
        PHASE_INTERVIEW, PHASE_MEMORY_INSTABILITY, PHASE_DEATH_QUESTIONS,
        PHASE_HEAVEN_MEMORIES, PHASE_HELL_MEMORIES, PHASE_RETRIEVAL,
    ):
        classification = (getattr(intent, 'classification', None) or '')
        if classification == 'PERCEPTION_QUERY' or ac in ('look', 'examine', 'inspect', 'search'):
            return None
        if ac in ('wait',) or (text or '').strip() in ('wait', 'wait.'):
            _advance_interview(facility, res, player_text, skipped=True)
            if facility.phase == PHASE_INTERVIEW:
                _advance_interview(facility, res, player_text, skipped=True)
            return res
        return _handle_interview_speech(facility, res, player_text)

    if phase == PHASE_RESEARCH:
        present = list(facility.arc.present_ids or [])
        if present and (intent.classification == 'SOCIAL_ACTION' or ac in ('talk', 'ask', 'tell')):
            cid = present[0]
            nm = facility.character_name(cid)
            res.facts.append(f'{nm} is in the quarters. They remember how you arrived.')
            res.intended_effect_achieved = True
            return res
    return None


def _handle_interview_speech(facility, res, player_text) -> Resolution:
    return _advance_interview(facility, res, player_text, skipped=False)


def _advance_interview(facility, res, player_text, *, skipped: bool) -> Resolution:
    from puca_dungeon.interview import current_question, fragment_for, load_reference, score_answer
    q = current_question(facility.arc.interview_index)
    if q is None:
        res.facts.append('The questions pause. They watch you.')
        res.intended_effect_achieved = True
        return res
    kind = 'no_answer' if skipped else score_answer(q, player_text, load_reference())
    facility.arc.interview_answers.append({'id': q['id'], 'kind': kind, 'text': player_text})
    answered_prompt = str(q.get('prompt') or '')
    facility.arc.interview_index += 1
    frag = fragment_for(q['id']) if facility.phase in (
        PHASE_INTERVIEW, PHASE_MEMORY_INSTABILITY, PHASE_DEATH_QUESTIONS,
    ) else None
    lines: list[str] = []
    if skipped:
        lines.append('You give them nothing useful for that question.')
    elif kind == 'correct':
        lines.append('They make a small mark. Their face does not change much.')
    elif kind == 'refuse':
        lines.append('They wait, then move to the next object.')
    elif kind == 'invented':
        lines.append('They glance at one another. The next image comes anyway.')
    elif kind == 'incorrect':
        lines.append('That is not the answer they expected. They do not say so.')
    else:
        lines.append('They note the silence and continue.')
    if frag and facility.arc.interview_index >= 3:
        lines.append(frag)
        facility.arc.discover('involuntary_fragment')
        res.structured_facts.append({
            'type': 'memory_cue',
            'content': frag,
            'physical_location_change': False,
            'scope': 'internal',
        })
    next_q = current_question(facility.arc.interview_index)
    if next_q:
        nxt = str(next_q.get('prompt') or '')
        lines.append(nxt)
        res.structured_facts.append({
            'type': 'interview_prompt',
            'question': next_q.get('id'),
            'content': nxt,
            'physical_location_change': False,
            'speaker': 'interviewer',
        })
        facility.arc.last_ask = 'answer their questions'
    res.facts.extend(lines)
    res.structured_facts.append({
        'type': 'interview_answer',
        'question': q['id'],
        'kind': kind,
        'answered_prompt': answered_prompt,
        'physical_location_change': False,
    })
    # Python-owned interviewer move before any free dialogue fluff
    present = list(getattr(getattr(facility, 'arc', None), 'present_ids', None) or [])
    speaker_id = (
        'senior_researcher' if 'senior_researcher' in present
        else (present[0] if present else '')
    )
    if speaker_id:
        try:
            from puca_dungeon.social_meaning import resolve_conversational_move
            from puca_dungeon.npc_strategy import apply_move_to_speech_facts
            move = resolve_conversational_move(facility, speaker_id, player_text=player_text)
            res.structured_facts.extend(apply_move_to_speech_facts(
                facility, move,
                raw=facility.last_npc_utterance or '…',
                understood=facility.last_understood or 'next question',
            ))
            res.structured_facts.append({
                'type': 'conversational_move',
                'speaker': speaker_id,
                'surface': move.get('surface') or {},
            })
        except Exception:
            pass
    res.intended_effect_achieved = not skipped
    res.state_changed = True
    return res


def _handle_contract(facility, res, *, accept, player_text, stay_in_hell: bool = False) -> Resolution:
    from puca_dungeon.facility_react import enter_processing
    # stay_in_hell / explicit refuse at second offer: player intent refuse, Sarel may invert
    if facility.phase == PHASE_SECOND_OFFER and (stay_in_hell or accept is False):
        facility.arc.player_final_intent = 'REFUSE'
        facility.arc.fear_of_hell = min(100, max(facility.arc.fear_of_hell, 70))
        facility.arc.actual_contract_response = 'ACCEPT'
        facility.arc.final_contract_response = 'ACCEPT'
        facility.arc.contract_cause = 'overwhelming_fear_of_hell'
        facility.arc.classification = classify_subject(facility.arc.tendencies, facility.arc.to_dict())
        spoken = truncate_speech('Yes.', facility.pressures.language_ability) or 'Yes'
        res.enactment = ENACTMENT_INVERTED
        res.enactment_cause = 'overwhelming_fear_of_hell'
        res.facts.append(
            'You prepare the refusal. Then something nearby screams again. '
            'Your body reaches the conclusion before you do. '
            f'“{spoken}.” It is out of your mouth before you can drag it back.'
        )
        res.structured_facts.append({
            'type': 'contract',
            'player_final_intent': 'REFUSE',
            'actual_contract_response': 'ACCEPT',
            'cause': 'overwhelming_fear_of_hell',
        })
        res.intended_effect_achieved = False
        res.state_changed = True
        enter_processing(type('W', (), {'facility': facility, 'world_time_seconds': 0})(), res, from_route='hell_overridden')
        # enter_processing expects world-like; patch room on facility directly
        return res

    if accept:
        if not facility.arc.initial_contract_response:
            facility.arc.initial_contract_response = 'ACCEPT'
        facility.arc.final_contract_response = 'ACCEPT'
        facility.arc.actual_contract_response = 'ACCEPT'
        if facility.phase == PHASE_SECOND_OFFER:
            facility.arc.player_final_intent = 'ACCEPT'
        facility.arc.classification = classify_subject(facility.arc.tendencies, facility.arc.to_dict())
        res.facts.append('You agree. They process it without theatre.')
        res.structured_facts.append({'type': 'contract', 'response': 'ACCEPT'})
        res.intended_effect_achieved = True
        res.state_changed = True
        worldish = type('W', (), {'facility': facility, 'world_time_seconds': 0, 'pending_discourse': None})()
        enter_processing(worldish, res, from_route='accept')
        return res

    # First-offer refuse
    facility.arc.initial_contract_response = facility.arc.initial_contract_response or 'REFUSE'
    facility.phase = PHASE_PREP_TRANSFER
    facility.phase_entered_at = -100
    facility.arc.scene_id = 'prep'
    facility.room_id = 'prep'
    facility.arc.last_ask = ''
    res.facts.append(
        'They do not punish you. They explain, calmly, that you may decline. '
        'You may use your remaining favourable continuation now: one day in Heaven. Then it expires. '
        'They take you to a preparation room.'
    )
    res.structured_facts.append({'type': 'contract', 'response': 'REFUSE'})
    res.intended_effect_achieved = True
    res.state_changed = True
    return res


def _heaven_action(facility, intent, res, text) -> Resolution:
    if any(_word(text, w) for w in ('bruise', 'scratch', 'mark', 'nail', 'body', 'myself')):
        marks = facility.arc.body_marks or ['a faint bruise']
        res.facts.append(
            f'The body you have here still carries {marks[0]}. Clothing is different. The mark is not.'
        )
        facility.arc.discover('bodily_continuity')
        res.intended_effect_achieved = True
        return res
    if any(_word(text, w) for w in ('fountain', 'fixture', 'fitting', 'pipe')):
        res.facts.append('The water fixture uses the same fittings you saw in the washroom.')
        facility.arc.discover('shared_architecture')
        res.intended_effect_achieved = True
        return res
    if any(_word(text, w) for w in ('eat', 'fruit', 'food')):
        facility.pressures.hunger = 5
        res.facts.append('The fruit is cold, sweet, and ordinary. Hunger eases.')
        res.intended_effect_achieved = True
        return res
    if any(_word(text, w) for w in ('sleep', 'lie', 'rest')):
        res.facts.append('The bedding is clean. Sleep here is easy and deep.')
        res.intended_effect_achieved = True
        return res
    if any(_word(text, w) for w in ('hide', 'run', 'escape', 'stay', 'refuse')) and facility.phase == PHASE_HEAVEN_EXPIRE:
        res.facts.append('You try to remain. They are prepared for that. The institution removes you if you cannot prevent it.')
        res.intended_effect_achieved = False
        return res
    present = list(facility.arc.present_ids or [])
    if present and any(_word(text, w) for w in ('ask', 'talk', 'who', 'what')):
        nm = facility.character_name(present[0])
        res.facts.append(
            f'{nm} is gentle. When you press, one kindness and one institutional word sit badly together.'
        )
        facility.arc.discover('contradictory_explanation')
        res.intended_effect_achieved = True
        return res
    room = facility.rooms.get('heaven') or {}
    res.facts.append(str(room.get('description') or 'Heaven remains warm and quiet.'))
    res.intended_effect_achieved = True
    return res


def _hell_action(facility, intent, res, text) -> Resolution:
    if any(_word(text, w) for w in ('grate', 'fixture', 'bolt', 'pipe', 'mark')):
        res.facts.append(
            'The grate uses the same bolts as the cell door. A pipe joint carries the washroom stamp.'
        )
        facility.arc.discover('shared_architecture')
        facility.arc.discover('suspected_physical_transfer')
        res.intended_effect_achieved = True
        return res
    if any(_word(text, w) for w in ('bruise', 'scratch', 'body', 'myself', 'nail')):
        marks = facility.arc.body_marks or ['a faint bruise']
        res.facts.append(f'{marks[0].capitalize()} is still on you. Pain continues normally.')
        facility.arc.discover('bodily_continuity')
        res.intended_effect_achieved = True
        return res
    if any(_word(text, w) for w in ('escape', 'run', 'break')):
        facility.pressures.pain = min(100, facility.pressures.pain + 15)
        res.facts.append('The environment punishes haste. There is no obvious way out.')
        res.intended_effect_achieved = False
        res.success = False
        return res
    present = [c for c in (facility.arc.present_ids or []) if c in ('iven', 'nessa', 'ruan')]
    if present and any(_word(text, w) for w in ('ask', 'talk', 'who')):
        nm = facility.character_name(present[0])
        res.facts.append(f'{nm} is among the other occupants. They have been through this.')
        res.intended_effect_achieved = True
        return res
    room = facility.rooms.get('hell') or {}
    res.facts.append(str(room.get('description') or 'Hell remains engineered misery.'))
    res.intended_effect_achieved = True
    return res

