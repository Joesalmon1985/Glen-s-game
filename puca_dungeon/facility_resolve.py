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
    else:
        tags = []

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

    room_before = facility.room_id
    if enactment == ENACTMENT_ABORTED:
        res.success = False
        res.intended_effect_achieved = False
        res.facts.append(_abort_fact(cause, intent))
        res.time_cost = 20
        out = res
    elif enactment == ENACTMENT_INVERTED:
        out = _perform_inverted(facility, intent, res, actual_patch, player_text, rng)
    else:
        out = _perform_action(
            facility, intent, res, player_text, rng,
            compromised=(enactment == ENACTMENT_COMPROMISED),
        )
    return _finalise_turn(facility, intent, out, player_text, tags, room_before)


def _finalise_turn(facility, intent, res, player_text, tags, room_before) -> Resolution:
    """Every facility turn ends here: wishes acknowledged, people react, the Voice speaks."""
    from puca_dungeon import npc_mind, voice as _voice
    from puca_dungeon.acknowledge import acknowledge, classify_wish
    arc = facility.arc
    arc.turns = int(getattr(arc, 'turns', 0) or 0) + 1
    structured = res.structured_facts
    types = {f.get('type') for f in structured if isinstance(f, dict)}
    present = [c for c in (arc.present_ids or []) if c in (facility.cast or {})]

    # --- 1. Understood-but-not-enacted wishes -------------------------------------
    wish = classify_wish(player_text)
    body_act = ''
    if wish and 'speech' not in types and 'book_enter' not in types:
        kind, detail = wish
        counts = dict(arc.wish_counts or {})
        counts[kind] = int(counts.get(kind, 0) or 0) + 1
        counts['_total'] = int(counts.get('_total', 0) or 0) + 1
        arc.wish_counts = counts
        ack = acknowledge(
            kind, detail, count_same=counts[kind], count_total=counts['_total'],
            staff_present=bool(facility.staff_present), restrained=facility.pressures.physical_restraint >= 40,
            room=facility.room_id,
        )
        # Replace the generic default fact with the specific acknowledgement
        res.facts = [f for f in res.facts if not (isinstance(f, str) and (
            f.startswith('Nothing useful comes of') or f.startswith('That does not change what they want')
            or f.startswith('Reality does not stretch') or f == 'Nothing happens.'
            or f.startswith('You try it.')
        ))]
        structured.append({'type': 'understood_not_enacted', 'kind': kind, 'detail': detail, 'text': ack['text']})
        if 'absurdity' not in tags:
            tags = list(tags) + ['absurdity']
            arc.tendencies = apply_tags(arc.tendencies, ['absurdity'])
        if ack['visible']:
            body_act = ack['body_act']
        res.intended_effect_achieved = False
        res.time_cost = max(res.time_cost, 20)

    # --- 2. Witnesses remember; one ambient beat --------------------------------------
    event_text = ''
    if 'aggression' in tags:
        event_text = 'Sarel tried to attack.'
    elif body_act:
        event_text = f'Sarel {body_act}.'
    elif 'defiance' in tags:
        event_text = 'Sarel refused an instruction.'
    elif 'compliance' in tags:
        event_text = 'Sarel complied.'
    elif 'warmth' in tags:
        event_text = 'Sarel was kind.'
    if present:
        npc_mind.witness(facility.cast, present, event_text, tags=tags)
        if 'npc_beat' not in types or body_act:
            seed = arc.turns
            beats = npc_mind.ambient(
                facility.cast, present, phase=facility.phase,
                language_ability=facility.pressures.language_ability, tags=tags,
                enactment=res.enactment, ask=str(arc.last_ask or ''), seed=seed, arc=arc,
            )
            for b in beats[:1]:
                structured.append(b.to_fact(facility.cast))
        # Subjects introduce themselves by name once they have spoken
        for f in structured:
            if isinstance(f, dict) and f.get('type') == 'npc_beat' and f.get('speaker') in ('iven', 'nessa', 'ruan') and f.get('kind') == 'speech':
                arc.learn_name(str(f['speaker']))

    # --- 3. The Voice --------------------------------------------------------------
    vstate = dict(arc.voice_state or {})
    present_names = []
    for c in present:
        present_names.append(facility.character_name(c) if c in (arc.known_names or []) or c in ('iven', 'nessa', 'ruan')
                             else {'orderly_quiet': 'the big orderly', 'orderly_anxious': 'the younger orderly',
                                   'senior_researcher': 'the collared woman'}.get(c, 'the attendant'))
    line = None
    addressed = next((f for f in structured if isinstance(f, dict) and f.get('type') == 'voice_addressed'), None)
    if addressed is not None:
        line = _voice.reply(
            str(addressed.get('text') or player_text), state=vstate, tendencies=arc.tendencies,
            room=facility.room_id, present_names=present_names, knows=[str(arc.last_ask or '')],
        )
        if line is None:
            line = _voice.VoiceLine('…', 'silence')
    else:
        force = ''
        for f in structured:
            if isinstance(f, dict) and f.get('type') == 'speech':
                force = str(f.get('force') or '')
        line = _voice.comment(
            state=vstate, tendencies=arc.tendencies, phase=facility.phase, room=facility.room_id,
            enactment=res.enactment, tags=tags, force=force, present_names=present_names,
            ask=str(arc.last_ask or ''), fear=facility.pressures.fear, fatigue=facility.pressures.fatigue,
            hunger=facility.pressures.hunger, discoveries=list(arc.discoveries or []),
            turn_seed=arc.turns, first_turn=(arc.turns == 1), new_scene=False,
        )
    arc.voice_state = vstate
    if line is not None and line.text and line.text != '…':
        structured.append(line.to_fact())
    elif line is not None and line.kind == 'silence':
        structured.append({'type': 'voice', 'kind': 'silence', 'text': 'Nothing answers. Which is not the same as no one listening.'})
    res.structured_facts = structured
    return res


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

    # Wishes the world cannot honour literally (talk to the cup, sing, dance, become a bird)
    # are acknowledged in _finalise_turn — never routed through speech.
    from puca_dungeon.acknowledge import classify_wish as _classify_wish
    _wish = _classify_wish(player_text)
    if _wish and _wish[0] in ('talk_object', 'dance', 'babble', 'transform', 'feed_everyone', 'make_food',
                              'vehicle', 'phase', 'magic', 'romance', 'lick', 'dig', 'meta'):
        res.intended_effect_achieved = False
        res.meaningful_effort = False
        res.time_cost = 30
        return res

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
        if facility.staff_present:
            res.facts.append('You wait. They wait better; they have had practice.')
        elif facility.room_id == 'cell':
            res.facts.append('You wait. The cell keeps its quiet.')
        else:
            res.facts.append('You wait.')
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
    if facility.staff_present:
        res.facts.append('You try it. It changes nothing they can see, and they are the ones watching.')
    else:
        res.facts.append('You try it. The room does not take sides.')
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
    res.facts.append(_look_around_text(facility))
    present = list(getattr(getattr(facility, 'arc', None), 'present_ids', None) or [])
    if present:
        from puca_dungeon.compose_turn import person_phrase
        known = set(getattr(facility.arc, 'known_names', None) or [])
        names = [person_phrase(facility.cast, cid, known_names=known) for cid in present]
        if len(names) == 1:
            res.facts.append(f'{names[0][0].upper() + names[0][1:]} is here, watching you look.')
        else:
            res.facts.append('People: ' + ', '.join(names) + '.')
        if 'senior_researcher' in present:
            res.facts.append('The collar on the woman is fitted like a second skin. Nobody explains it.')
    res.structured_facts.append({
        'type': 'perception', 'kind': 'visible_entities', 'entities': visible,
        'people': present,
    })
    res.intended_effect_achieved = True
    return res


def _look_around_text(facility) -> str:
    """Room description from current entity state — never the frozen opening string."""
    rid = facility.room_id
    if rid != 'cell':
        room = facility.rooms.get(rid) or {}
        return str(room.get('description') or 'You look around.')
    bits = []
    bed = facility.entity('bed')
    cup = facility.entity('cup')
    book = facility.entity('book')
    bits.append('Four walls, close enough that you could touch two at once.')
    if bed:
        bits.append('The bed is a shelf with a blanket' + (', and the blanket is on the floor.' if bed.state.get('bedding') == 'on_floor' else ' on it.'))
    if cup and cup.location == 'cell':
        if getattr(cup, 'broken', False):
            bits.append('The cup is in pieces by the wall.')
        elif cup.state.get('position') == 'on_floor':
            bits.append('The cup lies on its side on the floor' + (', water darkening the stone.' if cup.state.get('water_spilled') else '.'))
        else:
            bits.append('The cup ' + ('still has water in it.' if cup.state.get('has_water') else 'is empty.'))
    elif cup and cup.location == 'inventory':
        bits.append('The cup is in your hand.')
    if book and book.location == 'cell':
        pos = str(book.state.get('position') or '')
        if pos == 'hidden_under_bedding':
            bits.append('A corner of the book shows under the bedding.')
        elif pos == 'on_bed':
            bits.append('The book sits on the bed, closed.')
        else:
            bits.append('The book is on the floor, ' + ('face-down' if book.state.get('face_down') else 'face-up') + ', badly printed.')
    elif book and book.location == 'inventory':
        bits.append('The book is in your hands.')
    bits.append('The door has no handle on this side. ' + ('The slit in it is open.' if facility.slit_open else 'Its slit is shut.'))
    return ' '.join(bits)


def _speak(facility, intent, res, player_text, *, compromised: bool) -> Resolution:
    from puca_dungeon.mediation import mediate
    from puca_dungeon import npc_mind
    intended = intent.utterance or player_text
    present = list(getattr(getattr(facility, 'arc', None), 'present_ids', None) or [])
    utt = mediate(
        intended, facility.pressures.language_ability,
        staff_present=bool(facility.staff_present or present),
        fatigue=facility.pressures.fatigue,
    )
    speech_fact = utt.to_fact()
    if utt.given_name:
        facility.arc.claimed_name = utt.given_name if not utt.is_lie else facility.arc.claimed_name
        facility.arc.flag('gave_false_name' if utt.is_lie else 'gave_name', utt.given_name)
    if utt.is_lie:
        facility.arc.flag('lied', True)
    res.structured_facts.append(speech_fact)

    # Speaking to the Voice: no foreign-language barrier, no NPC uptake
    if utt.addressed_to_voice:
        res.structured_facts.append({'type': 'voice_addressed', 'text': utt.spoken})
        res.actual_action = {'action_class': 'address_voice', 'performed': True}
        res.intended_effect_achieved = True
        res.time_cost = 10
        return res

    # Choose the addressee: explicit target, else the last referent, else the most senior present
    target = None
    tgt = (intent.target or '').strip()
    if tgt and tgt in (facility.cast or {}):
        target = tgt
    if target is None and present:
        for pref in ('senior_researcher', 'nessa', 'iven', 'ruan', 'orderly_quiet', 'orderly_anxious', 'attendant_a', 'attendant_b'):
            if pref in present:
                target = pref
                break
        target = target or present[0]
    speech_fact['target'] = target

    if facility.phase in (PHASE_CONTRACT, PHASE_SECOND_OFFER, PHASE_EXPLANATION):
        if utt.force in ('assent', 'refusal') or _ACCEPT_CONTRACT_RE.search(player_text or '') or _REFUSE_CONTRACT_RE.search(player_text or ''):
            return _handle_contract(facility, res, accept=None, player_text=player_text)
    if facility.phase in (
        PHASE_INTERVIEW, PHASE_MEMORY_INSTABILITY, PHASE_DEATH_QUESTIONS,
        PHASE_HEAVEN_MEMORIES, PHASE_HELL_MEMORIES,
    ) and utt.force in ('statement', 'give_name', 'refusal', 'assent'):
        return _handle_interview_speech(facility, res, player_text)

    if target and target in (facility.cast or {}):
        seed = int(getattr(facility, 'phase_entered_at', 0) or 0) + len(player_text or '')
        beats = npc_mind.reply_to(
            facility.cast, target, utt,
            phase=facility.phase, language_ability=facility.pressures.language_ability,
            ask=str(getattr(facility.arc, 'last_ask', '') or ''), arc=facility.arc, seed=seed,
        )
        for b in beats:
            res.structured_facts.append(b.to_fact(facility.cast))
        res.structured_facts.append({'type': 'discourse_focus', 'referent': target})
        facility.arc.mark_met(target)
        if utt.force in ('threat', 'insult'):
            facility.pressures.physical_restraint = min(100, facility.pressures.physical_restraint + 5)
    elif not facility.staff_present and not present:
        res.facts.append('No one answers. The room takes the words and gives back nothing.')
        res.structured_facts.append({'type': 'social_no_uptake'})
    res.intended_effect_achieved = utt.fidelity in ('full', 'partial')
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
        PHASE_HEAVEN_MEMORIES, PHASE_HELL_MEMORIES,
    ):
        classification = (getattr(intent, 'classification', None) or '')
        if classification == 'PERCEPTION_QUERY' or ac in ('look', 'examine', 'inspect', 'search'):
            return None
        if classification == 'SOCIAL_ACTION' or ac in ('talk', 'speak', 'ask', 'say', 'tell', 'shout', 'yell', 'threaten', 'apologise', 'refuse', 'answer'):
            return None  # _speak decides: answers go to the interview, questions get replies
        if ac in ('wait',) or (text or '').strip() in ('wait', 'wait.', '...'):
            _advance_interview(facility, res, player_text, skipped=True)
            res.actual_action = {'action_class': 'wait', 'performed': True}
            return res
        from puca_dungeon.acknowledge import classify_wish
        if classify_wish(player_text):
            return None  # let the wish be acknowledged; the interview waits a beat
        # Bare content (a name, a place) is an answer
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


def _interview_reaction(kind: str, q: dict, player_text: str) -> str:
    qid = q.get('id')
    if kind == 'correct':
        if qid == 'name':
            return 'The collared woman does not write it down. She already has it. She nods as if a box had ticked itself.'
        return 'A small mark on her sheet. Her face gives you nothing, but the pen was quick.'
    if kind == 'refuse':
        return 'She waits exactly long enough to be sure you will not go on. Then she moves to the next object. The refusal is written down too.'
    if kind == 'invented':
        return 'The two of them exchange a look so brief it might be a blink. The next picture comes anyway. You have the sense of having failed something you did not know was a test.'
    if kind == 'incorrect':
        return 'That is not the answer she was expecting. She does not say so. She does not need to; the pause says it.'
    if kind == 'no_answer':
        return 'Your silence goes into the record along with everything else.'
    return ''


def _advance_interview(facility, res, player_text, *, skipped: bool) -> Resolution:
    """Answer the question that was ASKED last turn; then ask the next one.

    Order inside the turn: Sarel's answer → their reaction → (fragment) → next question.
    The question is an institution beat, so it lands after everything else.
    """
    from puca_dungeon.interview import current_question, fragment_for, load_reference, score_answer
    from puca_dungeon.mediation import mediate
    asked = int(getattr(facility.arc, 'interview_asked', -1) if hasattr(facility.arc, 'interview_asked') else -1)
    if asked < 0:
        # Nothing has been asked yet: this turn only asks the first question
        q0 = current_question(0)
        if q0:
            facility.arc.interview_asked = 0
            res.structured_facts.append({'type': 'interview_prompt', 'question': q0['id'], 'content': q0['prompt']})
            res.world_events = list(res.world_events or []) + [{'type': 'interview_question', 'text': q0['prompt']}]
        res.intended_effect_achieved = True
        res.state_changed = True
        return res
    q = current_question(asked)
    if q is None:
        res.facts.append('The questions have stopped. She is watching you instead, which is worse.')
        res.intended_effect_achieved = True
        return res
    kind = 'no_answer' if skipped else score_answer(q, player_text, load_reference())
    facility.arc.interview_answers.append({'id': q['id'], 'kind': kind, 'text': player_text})
    facility.arc.interview_index = asked + 1
    if not skipped:
        utt = mediate(player_text, facility.pressures.language_ability, staff_present=True,
                      fatigue=facility.pressures.fatigue)
        res.structured_facts.append(utt.to_fact())
        if kind in ('invented', 'incorrect') and hasattr(facility.arc, 'flag'):
            facility.arc.flag('interview_mismatch', int(facility.arc.behavior_flags.get('interview_mismatch', 0) or 0) + 1)
    reaction = _interview_reaction(kind, q, player_text)
    if reaction:
        res.structured_facts.append({'type': 'npc_beat', 'speaker': 'senior_researcher',
                                     'speaker_name': facility.character_name('senior_researcher'),
                                     'kind': 'gesture', 'body': reaction, 'weight': 3})
    frag = fragment_for(q['id']) if facility.phase in (
        PHASE_INTERVIEW, PHASE_MEMORY_INSTABILITY, PHASE_DEATH_QUESTIONS,
    ) else None
    if frag and facility.arc.interview_index >= 3:
        res.structured_facts.append({'type': 'memory_fragment', 'text': frag})
        res.world_events = list(res.world_events or []) + [{'type': 'memory_fragment', 'text': frag}]
        facility.arc.discover('involuntary_fragment')
    res.structured_facts.append({'type': 'interview_answer', 'question': q['id'], 'kind': kind})
    # Ask the next one
    nxt = current_question(asked + 1)
    if nxt is not None:
        facility.arc.interview_asked = asked + 1
        res.structured_facts.append({'type': 'interview_prompt', 'question': nxt['id'], 'content': nxt['prompt']})
        res.world_events = list(res.world_events or []) + [{'type': 'interview_question', 'text': nxt['prompt']}]
    else:
        facility.arc.interview_asked = asked + 1
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
            'You mean to say no. You have even prepared the word. '
            'Then something nearby screams again. Your body reaches the conclusion before you do. '
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

