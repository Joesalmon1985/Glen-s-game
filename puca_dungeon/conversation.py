"""Open speech-act dialogue: meaning extraction, authored intercepts, knowledge query.

Not a closed verb catalogue. Authored intercepts overlay explicit content;
everything else queries the addressee's knowledge, beliefs, and willingness.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from puca_dungeon.characters import CharacterState
from puca_dungeon.facility_models import (
    PHASE_CONTRACT,
    PHASE_DOOR,
    PHASE_EXPLANATION,
    PHASE_REMOVAL,
    PHASE_SECOND_OFFER,
    PHASE_SLIT,
    PHASE_WASH,
)
from puca_dungeon.language import (
    communicate_intent,
    comprehend_npc_meaning,
    note_exposure,
    player_facing_comprehension_line,
    resolve_term,
)
from puca_dungeon.npc_knowledge import (
    bind_overheard_name,
    get_knowledge,
    narrator_reference,
    take_up_name,
    take_up_role,
    true_name,
)


THOUGHT_RE = re.compile(
    r'\b(i wonder|i think|i thought|wonder if|to myself|in my head)\b',
    re.I,
)
SPEECH_FORCE_RE = re.compile(
    r'\b(ask|tell|say|speak|talk|shout|yell|scream|whisper|call|reply|answer|greet)\b',
    re.I,
)
QUESTION_START_RE = re.compile(
    r'^\s*(who|what|why|where|when|how|do|does|did|are|is|were|was|can|could|would|will)\b',
    re.I,
)


@dataclass
class DialogueMeaning:
    speech_act: str = 'statement'  # question|statement|request|clarification|thought
    addressee: Optional[str] = None
    topic_entities: list = field(default_factory=list)
    proposition: str = ''
    context_reference: str = ''
    intended_text: str = ''
    voiced: bool = True

    def to_dict(self) -> dict:
        return {
            'speech_act': self.speech_act,
            'addressee': self.addressee,
            'topic_entities': list(self.topic_entities),
            'proposition': self.proposition,
            'context_reference': self.context_reference,
            'intended_text': self.intended_text,
            'voiced': self.voiced,
        }


def get_conversation(facility) -> dict:
    arc = getattr(facility, 'arc', None)
    if arc is None:
        return {}
    conv = dict(getattr(arc, 'conversation', None) or {})
    conv.setdefault('interlocutor_id', '')
    conv.setdefault('recent_turns', [])
    conv.setdefault('unanswered', [])
    conv.setdefault('introduced_names', [])
    conv.setdefault('misunderstood_terms', [])
    conv.setdefault('statements', [])
    conv.setdefault('stance', '')
    conv.setdefault('topic', '')
    conv.setdefault('side_questions', 0)
    return conv


def save_conversation(facility, conv: dict) -> None:
    arc = getattr(facility, 'arc', None)
    if arc is None:
        return
    arc.conversation = conv


def set_interlocutor(facility, cid: str) -> None:
    conv = get_conversation(facility)
    conv['interlocutor_id'] = cid or ''
    save_conversation(facility, conv)


def conversation_urgency(facility) -> str:
    """Physical pressure on the current beat — independent of whether the player spoke."""
    phase = str(getattr(facility, 'phase', '') or '')
    restraint = int(getattr(getattr(facility, 'pressures', None), 'physical_restraint', 0) or 0)
    if restraint >= 40:
        return 'high'
    if phase in (PHASE_SLIT, PHASE_DOOR, PHASE_WASH, PHASE_REMOVAL):
        return 'high'
    ask = str(getattr(getattr(facility, 'arc', None), 'last_ask', '') or '').lower()
    if ask and phase in (PHASE_SLIT, PHASE_DOOR):
        return 'high'
    return 'low'


def looks_like_thought(player_text: str) -> bool:
    t = (player_text or '').strip()
    if THOUGHT_RE.search(t) and not SPEECH_FORCE_RE.search(t):
        return True
    return False


def looks_like_speech(player_text: str, *, someone_present: bool) -> bool:
    t = (player_text or '').strip()
    if not t:
        return False
    if looks_like_thought(t):
        return False
    if SPEECH_FORCE_RE.search(t):
        return True
    if t.endswith('?') or QUESTION_START_RE.search(t):
        return bool(someone_present)
    return False


def is_voiced_intent(intent, player_text: str, facility) -> bool:
    classification = str(getattr(intent, 'classification', '') or '')
    ac = str(getattr(intent, 'action_class', '') or '').lower()
    present = list(getattr(getattr(facility, 'arc', None), 'present_ids', None) or [])
    someone = bool(present) or bool(getattr(facility, 'staff_present', False))
    if classification == 'INTERNAL_THOUGHT' or ac in ('think', 'wonder'):
        return False
    if looks_like_thought(player_text) and not SPEECH_FORCE_RE.search(player_text or ''):
        return False
    if SPEECH_FORCE_RE.search(player_text or '') or ac in (
        'talk', 'speak', 'ask', 'say', 'tell', 'shout', 'yell', 'scream', 'whisper',
    ):
        return True
    if looks_like_speech(player_text, someone_present=someone):
        return True
    if classification == 'SOCIAL_ACTION':
        return bool(someone)
    return False


def _strip_speech_frame(text: str) -> str:
    t = (text or '').strip()
    t = re.sub(
        r'^\s*(ask|tell|say to|say|speak to|talk to|shout(?: at)?|whisper(?: to)?)\s+'
        r'(her|him|them|the [a-z ]+?|nessa|iven|ruan|[A-Z][a-z]+)\s+',
        '',
        t,
        flags=re.I,
    )
    t = re.sub(r'^\s*(ask|tell|say)\s+(her|him|them)\s+', '', t, flags=re.I)
    t = re.sub(r'^(that|if|whether|about)\s+', '', t, flags=re.I)
    return t.strip()


def extract_dialogue_meaning(facility, intent, player_text: str) -> DialogueMeaning:
    text = (player_text or getattr(intent, 'utterance', None) or '').strip()
    present = list(getattr(getattr(facility, 'arc', None), 'present_ids', None) or [])
    conv = get_conversation(facility)
    addressee = getattr(intent, 'target', None) or conv.get('interlocutor_id') or (
        present[0] if present else None
    )
    if addressee in ('staff',):
        addressee = present[0] if present else 'orderly_quiet'

    voiced = is_voiced_intent(intent, text, facility)
    act = 'thought'
    if voiced:
        if text.endswith('?') or QUESTION_START_RE.search(text) or re.search(
            r'\b(ask|who|what|why|where|whether|how)\b', text, re.I
        ):
            act = 'question'
        elif re.search(r'\b(tell|say)\b', text, re.I) and re.search(
            r'\b(my name|i am|i\'m)\b', text, re.I
        ):
            act = 'statement'
        elif re.search(r'\b(please|stop|wait|back|later)\b', text, re.I) and not text.endswith('?'):
            act = 'request'
        else:
            act = 'statement'
        if re.search(r'\b(mean|means|meant by|what is|what was)\b', text, re.I):
            act = 'clarification'

    residual = _strip_speech_frame(text)
    entities: list[str] = []
    from puca_dungeon.npc_knowledge import get_knowledge as gk, id_for_player_reference
    blob = text.lower()
    named_addressee = None
    for cid in present:
        k = gk(facility, cid)
        hit = False
        if k.name_known and k.known_name and k.known_name.lower() in blob:
            hit = True
        elif k.short_label:
            label = re.sub(r'^(the|a|an)\s+', '', k.short_label.lower())
            if label and label in blob:
                hit = True
        if hit:
            entities.append(cid)
            named_addressee = cid
    if named_addressee:
        addressee = named_addressee
    m = re.search(r'\b(?:ask|tell|say to)\s+(?:the\s+)?([a-z][a-z\- ]{2,40}?)(?:\s+(?:if|whether|who|what|why|where|that|my|i|about)\b|[?,:])', blob)
    if m:
        found = id_for_player_reference(facility, m.group(1).strip())
        if found:
            addressee = found
            if found not in entities:
                entities.append(found)
    # Discourse leftovers
    for word in ('experiment', 'observation', 'heaven', 'hell', 'contract', 'folder', 'door', 'cell'):
        if word in blob and word not in entities:
            entities.append(word)

    ctx = ''
    if re.search(r'\bwhen\b', blob):
        ctx = residual
    return DialogueMeaning(
        speech_act=act if voiced else 'thought',
        addressee=addressee if voiced else None,
        topic_entities=entities,
        proposition=residual or text,
        context_reference=ctx,
        intended_text=text,
        voiced=voiced,
    )


# --- Knowledge answers (NPC content, not player-verb catalogue) ---

_KNOWLEDGE_PROSE = {
    'this_is_a_research_facility': {
        'senior_researcher': (
            '“A research facility.” The next word is unfamiliar. '
            'They see it in your face and try again. “Hospital. Almost.”'
        ),
        'orderly_quiet': '“Medical. Here.” A smaller word follows that you already know: safe.',
        'default': '“Here. Medical.”',
    },
    'this_is_a_medical_place': {
        'orderly_quiet': '“Medical.” Then, slower: “You are safe.”',
        'default': '“Medical place.”',
    },
    'sarel_is_a_subject': {
        'senior_researcher': '“You are here as a subject. Observation.”',
        'default': 'They will not put a simple word on what you are.',
    },
    'official_death_then_continuation': {
        'senior_researcher': 'The answer takes longer. “You died.”',
        'default': 'They look at you as if the question itself were the answer.',
    },
    'eating_is_still_required': {
        'senior_researcher': (
            '“Your body still needs it.” They choose a smaller word. '
            '“Dead is what happened. Eating is still true.”'
        ),
        'orderly_quiet': 'They point at the idea of food, then at you. Eat. Still.',
        'default': 'They insist the body still has to eat, whatever else they believe.',
    },
    'observation_is_the_purpose': {
        'senior_researcher': '“We keep you here to watch. To understand.”',
        'default': 'They say you are being kept to be watched.',
    },
    'was_at_the_cell_slit': {
        'orderly_quiet': 'A short nod. “Door. Night. Yes.”',
        'default': 'They confirm they were the one at the door.',
    },
    'was_not_at_the_cell_slit': {
        'senior_researcher': '“No. Someone else was on the door.”',
        'orderly_anxious': 'A quick shake of the head. Not them.',
        'default': '“That was not me.”',
    },
    'own_name': {},  # handled by intercept
    'simple_instructions': {
        'orderly_quiet': 'They repeat the current instruction more slowly, with the same gesture.',
        'default': 'They give the instruction again, smaller words.',
    },
    'heaven_is_real_to_him': {
        'iven': 'He says Heaven is real — warm, finished work, a promise kept.',
        'default': 'They speak of Heaven as if it were a place they had already been.',
    },
    'work_is_finite': {
        'iven': '“The work ends. Then Heaven.” He believes it.',
        'default': 'They say the work does not last forever.',
    },
    'bodily_continuity_fragments': {
        'nessa': (
            'She keeps her voice low. Something about a mark that survived. '
            'She watches the door while she says it.'
        ),
        'default': 'They hint the body continues even when the story says otherwise.',
    },
    'official_continuity_model': {
        'senior_researcher': '“You died. This is continuation. You are safe.”',
        'default': 'They give the official version: death, then this.',
    },
    'staff_withhold': {
        'nessa': 'She glances at the older person. “They don’t tell you everything.”',
        'default': 'They think the staff are keeping something back.',
    },
}

_TOPIC_ALIASES = {
    'where': ['this_is_a_research_facility', 'this_is_a_medical_place'],
    'here': ['this_is_a_research_facility', 'this_is_a_medical_place'],
    'place': ['this_is_a_research_facility', 'this_is_a_medical_place'],
    'facility': ['this_is_a_research_facility'],
    'hospital': ['this_is_a_research_facility', 'this_is_a_medical_place'],
    'dead': ['official_death_then_continuation', 'eating_is_still_required', 'official_continuity_model'],
    'died': ['official_death_then_continuation', 'official_continuity_model'],
    'death': ['official_death_then_continuation'],
    'eat': ['eating_is_still_required'],
    'food': ['eating_is_still_required'],
    'hungry': ['eating_is_still_required'],
    'why': ['observation_is_the_purpose', 'sarel_is_a_subject', 'official_death_then_continuation'],
    'keeping': ['observation_is_the_purpose', 'sarel_is_a_subject'],
    'observe': ['observation_is_the_purpose'],
    'observation': ['observation_is_the_purpose'],
    'watch': ['observation_is_the_purpose'],
    'night': ['was_at_the_cell_slit', 'was_not_at_the_cell_slit'],
    'outside': ['was_at_the_cell_slit', 'was_not_at_the_cell_slit'],
    'slit': ['was_at_the_cell_slit', 'was_not_at_the_cell_slit'],
    'door': ['was_at_the_cell_slit', 'simple_instructions'],
    'heaven': ['heaven_is_real_to_him', 'official_continuity_model'],
    'work': ['work_is_finite'],
    'everything': ['staff_withhold'],
    'told': ['staff_withhold'],
    'frightened': ['staff_withhold'],
    'afraid': ['staff_withhold'],
    'experiment': ['observation_is_the_purpose', 'this_is_a_research_facility'],
}


def _cast_char(facility, cid: str) -> CharacterState:
    raw = (getattr(facility, 'cast', None) or {}).get(cid) or {}
    return CharacterState.from_dict(raw if isinstance(raw, dict) else None)


def _tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r'[a-z0-9]+', (text or '').lower()) if len(w) > 2}


def _knowledge_keys_for(ch: CharacterState) -> list[str]:
    keys = []
    for bucket in (ch.knowledge, ch.beliefs, ch.may_reveal):
        for item in bucket or []:
            keys.append(str(item))
    return keys


def query_npc_knowledge(facility, speaker_id: str, meaning: DialogueMeaning) -> dict:
    """Long-tail: match proposition to what this NPC knows / will say."""
    ch = _cast_char(facility, speaker_id)
    tokens = _tokenize(meaning.proposition) | _tokenize(meaning.intended_text)
    conceal = {str(x) for x in (ch.must_conceal or [])}
    available = set(_knowledge_keys_for(ch))
    scored: list[tuple[int, str]] = []
    bonus: dict[str, int] = {}
    if tokens & {'eat', 'food', 'hungry'}:
        bonus['eating_is_still_required'] = 6
    if tokens & {'dead', 'died', 'death'} and tokens & {'eat', 'food', 'hungry'}:
        bonus['eating_is_still_required'] = bonus.get('eating_is_still_required', 0) + 4
    if tokens & {'night', 'outside', 'slit', 'door'} and tokens & {'you', 'were', 'person', 'cell'}:
        bonus['was_at_the_cell_slit'] = 4
        bonus['was_not_at_the_cell_slit'] = 4

    for tok in tokens:
        for key in _TOPIC_ALIASES.get(tok, []):
            if key in conceal:
                return {'kind': 'withhold', 'key': key}
            scored.append((3 + bonus.get(key, 0), key))
        for key in available:
            bits = set(key.split('_'))
            overlap = len(tokens & bits)
            if overlap:
                if any(c in key for c in conceal):
                    return {'kind': 'withhold', 'key': key}
                scored.append((overlap + bonus.get(key, 0), key))
    for key, b in bonus.items():
        scored.append((b, key))

    # may_reveal gate: if key not in may_reveal and not simple knowledge, withhold
    scored.sort(reverse=True)
    seen = set()
    for score, key in scored:
        if key in seen or score <= 0:
            continue
        seen.add(key)
        if key in conceal:
            return {'kind': 'withhold', 'key': key}
        if ch.may_reveal and key not in ch.may_reveal and key not in ch.knowledge:
            # Known but not willing
            if key in ch.secrets or key in conceal:
                return {'kind': 'withhold', 'key': key}
        prose_map = _KNOWLEDGE_PROSE.get(key) or {}
        line = prose_map.get(speaker_id) or prose_map.get('default')
        if line:
            return {'kind': 'answer', 'key': key, 'text': line}
        # Fall through to a generic diegetic gloss of the knowledge id
        gloss = key.replace('_', ' ')
        return {'kind': 'answer', 'key': key, 'text': f'They speak to that, briefly: {gloss}.'}

    if meaning.speech_act == 'question':
        return {'kind': 'unknown', 'key': '', 'text': ''}
    return {'kind': 'listen', 'key': '', 'text': ''}


def _name_willingness(facility, speaker_id: str) -> str:
    """give | defer | refuse"""
    urgency = conversation_urgency(facility)
    if urgency == 'high' and speaker_id.startswith('orderly'):
        return 'defer'
    if speaker_id == 'nessa':
        return 'give'
    if speaker_id == 'iven':
        return 'give'
    if speaker_id == 'senior_researcher':
        return 'give'
    if speaker_id.startswith('orderly'):
        return 'give' if urgency != 'high' else 'defer'
    return 'give'


def _asks_name(meaning: DialogueMeaning) -> bool:
    t = f'{meaning.proposition} {meaning.intended_text}'.lower()
    if re.search(r'\b(your name|who are you|who is this|what are you called|call you)\b', t):
        return True
    if re.search(r'\bwho\b', t) and re.search(r'\byou\b', t):
        return True
    return False


def _gives_player_name(meaning: DialogueMeaning) -> Optional[str]:
    t = meaning.intended_text
    m = re.search(r'\b(?:my name is|call me)\s+([A-Za-z][A-Za-z\'\-]+)', t, re.I)
    if m:
        name = m.group(1)
        if name.lower() in ('dead', 'here', 'safe', 'sorry', 'not'):
            return None
        return name
    m = re.search(r"\b(?:i am|i'm)\s+([A-Z][A-Za-z\'\-]+)\b", t)
    if m:
        name = m.group(1)
        if name.lower() in ('dead', 'here', 'safe', 'sorry', 'alone', 'ready', 'not'):
            return None
        return name
    return None


def _asks_where(meaning: DialogueMeaning) -> bool:
    t = f'{meaning.proposition} {meaning.intended_text}'.lower()
    return bool(re.search(r'\b(where am i|where is this|what is this place|where are we)\b', t))


def _asks_why_here(meaning: DialogueMeaning) -> bool:
    t = f'{meaning.proposition} {meaning.intended_text}'.lower()
    return bool(re.search(
        r'\bwhy\b.+\b(here|keeping|keep|brought|bring|watch|watching)\b'
        r'|\bwhy (am i|are we|i\'m) here\b',
        t,
    ))


def _asks_work_role(meaning: DialogueMeaning) -> bool:
    t = f'{meaning.proposition} {meaning.intended_text}'.lower()
    return bool(re.search(
        r'\b(work here|works here|do you work|your (job|work|role)|'
        r'are you (staff|with them)|whether she works|whether he works)\b',
        t,
    ))


def _asks_term_meaning(meaning: DialogueMeaning) -> Optional[str]:
    t = meaning.intended_text
    m = re.search(
        r'\b(?:what (?:does|did|do) (\w+) mean|what (?:is|was) (\w+)|meant by (\w+)|the word (\w+))\b',
        t,
        re.I,
    )
    if not m:
        conv = None
        return None
    term = next((g for g in m.groups() if g), None)
    return term.lower() if term else None


def _answers_interview(meaning: DialogueMeaning, facility) -> bool:
    if meaning.speech_act in ('question', 'clarification'):
        return False
    if _asks_name(meaning) or _asks_where(meaning) or _asks_why_here(meaning) or _gives_player_name(meaning):
        return False
    if SPEECH_FORCE_RE.search(meaning.intended_text) and re.search(
        r'\b(ask|tell her|tell him|tell them)\b', meaning.intended_text, re.I
    ):
        # "tell her my name" is not an interview answer; "Sarel" alone might be
        if _gives_player_name(meaning):
            return False
        if meaning.speech_act == 'question':
            return False
    prompt = str(getattr(getattr(facility, 'arc', None), 'last_ask', '') or '')
    if prompt and prompt.lower() in (
        'answer their questions', 'what happened when you died',
    ):
        # Side questions already excluded. A statement toward the prompt counts.
        if meaning.speech_act == 'statement' and not SPEECH_FORCE_RE.search(meaning.intended_text):
            return True
        if not re.search(r'\b(ask|who|where|why)\b', meaning.intended_text, re.I):
            return True
    return False


def is_interview_answer(facility, meaning: DialogueMeaning) -> bool:
    phase = str(getattr(facility, 'phase', '') or '')
    if phase not in (
        'interview', 'memory_instability', 'death_questions',
        'heaven_memories', 'hell_memories',
    ):
        return False
    return _answers_interview(meaning, facility)


def is_contract_decision(meaning: DialogueMeaning, player_text: str) -> Optional[bool]:
    t = (player_text or '').lower()
    if meaning.speech_act == 'question':
        return None
    if re.search(r'\b(i agree|i accept|i\'ll sign|i will sign|yes,? i (will|agree))\b', t):
        return True
    if re.search(r'\b(i refuse|i (will )?not (agree|sign)|i decline)\b', t):
        return False
    return None


def _intro_name_line(facility, speaker_id: str, name: str, *, language_poor: bool) -> str:
    if speaker_id == 'senior_researcher':
        if language_poor:
            return (
                'They touch two fingers to their chest. '
                f'“{name}.” Then they wait to see if the word landed.'
            )
        return (
            f'“I’m {name}.” They say it slowly, watching for recognition. '
            f'You catch the name easily enough.'
        )
    if speaker_id.startswith('orderly'):
        if language_poor:
            return f'They tap their chest. “{name}.”'
        return f'“{name},” they say, as if the word were part of the work.'
    return f'“I’m {name}.” The word is clear.'


def authored_intercept(facility, speaker_id: str, meaning: DialogueMeaning) -> Optional[dict]:
    """Explicit content overlays — not the complete dialogue set."""
    ability = int(getattr(getattr(facility, 'pressures', None), 'language_ability', 15) or 15)
    poor = ability < 22
    name = true_name(facility, speaker_id)
    k = get_knowledge(facility, speaker_id)

    if _asks_name(meaning) and meaning.addressee == speaker_id:
        will = _name_willingness(facility, speaker_id)
        if will == 'refuse':
            return {
                'kind': 'name_refuse',
                'text': f'{narrator_reference(facility, speaker_id).capitalize()} shakes their head. “It doesn’t matter.”',
                'events': [],
            }
        if will == 'defer':
            return {
                'kind': 'name_defer',
                'text': f'{narrator_reference(facility, speaker_id).capitalize()} hears you. “Later.”',
                'events': [],
            }
        events = []
        if name and not k.name_known:
            events.append(take_up_name(facility, speaker_id, name, source='asked_and_understood'))
        line = _intro_name_line(facility, speaker_id, name, language_poor=poor)
        if conversation_urgency(facility) == 'high':
            line = f'{line} Then the work of the moment continues.'
        return {'kind': 'name_give', 'text': line, 'events': events, 'spoken_name': name}

    given = _gives_player_name(meaning)
    if given:
        ref = narrator_reference(facility, speaker_id)
        if ability < 28:
            return {
                'kind': 'receive_name',
                'text': (
                    f'“{given},” you say. {ref.capitalize()} tries it once, gets the middle wrong, then again. '
                    f'“{given}.”'
                ),
                'events': [],
                'player_name': given,
            }
        return {
            'kind': 'receive_name',
            'text': f'“{given},” you say. {ref.capitalize()} understands both the name and that you offered it.',
            'events': [],
            'player_name': given,
        }

    if _asks_where(meaning):
        q = query_npc_knowledge(facility, speaker_id, meaning)
        if q.get('kind') == 'answer':
            return {'kind': 'where', 'text': q['text'], 'events': [], 'knowledge_key': q.get('key')}
        # Fallback authored where
        if speaker_id == 'senior_researcher':
            return {
                'kind': 'where',
                'text': (
                    '“A research facility.” The next word is unfamiliar. '
                    'They see it in your face and try again. “Hospital. Almost.”'
                ),
                'events': [],
                'knowledge_key': 'this_is_a_research_facility',
                'uncertain': ['facility'] if ability < 40 else [],
            }
        return {
            'kind': 'where',
            'text': '“Facility,” they say. “Medical. You are safe.”',
            'events': [],
        }

    if _asks_why_here(meaning):
        if speaker_id == 'senior_researcher':
            return {
                'kind': 'why',
                'text': 'This answer takes longer. “You died.”',
                'events': [],
                'knowledge_key': 'official_death_then_continuation',
            }
        q = query_npc_knowledge(facility, speaker_id, meaning)
        if q.get('kind') == 'answer':
            return {'kind': 'why', 'text': q['text'], 'events': [], 'knowledge_key': q.get('key')}
        return {
            'kind': 'why',
            'text': 'They search for a small enough word and fail. A gesture: stay. Watch.',
            'events': [],
        }

    if _asks_work_role(meaning):
        ch = _cast_char(facility, speaker_id)
        role_cue = str((ch.appearance or {}).get('role_cue') or ch.role or '')
        events = []
        if role_cue and not k.role_known:
            events.append(take_up_role(facility, speaker_id, role_cue, source='asked_and_understood'))
        if speaker_id.startswith('orderly'):
            text = 'A short nod. Work. Here. The word for the job itself is slower to arrive.'
        elif speaker_id == 'senior_researcher':
            text = f'“I work here.” Then, more carefully: “{role_cue or "research"}.”'
        else:
            text = 'They live here more than they work here. The distinction is not clean.'
        return {'kind': 'role', 'text': text, 'events': events}

    term = _asks_term_meaning(meaning)
    if term:
        resolve_term(facility, term)
        if term in ('observation', 'observe', 'watch'):
            return {
                'kind': 'clarify',
                'text': (
                    f'{narrator_reference(facility, speaker_id).capitalize()} chooses smaller words. '
                    '“To watch. To keep you. To understand.”'
                ),
                'events': [],
                'resolved_term': term,
            }
        if term in ('facility',):
            return {
                'kind': 'clarify',
                'text': 'They try again. “Hospital. Almost. A place that keeps you.”',
                'events': [],
                'resolved_term': term,
            }
        return {
            'kind': 'clarify',
            'text': f'They repeat the idea without the hard word. You follow more of it this time.',
            'events': [],
            'resolved_term': term,
        }

    return None


def _withhold_line(facility, speaker_id: str) -> str:
    ref = narrator_reference(facility, speaker_id)
    if speaker_id == 'nessa':
        return f'{ref.capitalize()} listens. Then: “That’s all I know.” It plainly isn’t.'
    if speaker_id == 'senior_researcher':
        return f'“I’m not discussing that.” {ref.capitalize()}\'s face does not change much.'
    return f'{ref.capitalize()} will not follow you there.'


def _unknown_line(facility, speaker_id: str) -> str:
    ref = narrator_reference(facility, speaker_id)
    return f'“I don’t know.” {ref.capitalize()} does not decorate it.'


def apply_overheard_names(facility, speaker_id: str, spoken_text: str) -> list[dict]:
    events = []
    present = list(getattr(getattr(facility, 'arc', None), 'present_ids', None) or [])
    cast = getattr(facility, 'cast', None) or {}
    for cid in present:
        nm = str((cast.get(cid) or {}).get('name') or '')
        if not nm or cid == speaker_id:
            continue
        if re.search(rf'(?<![A-Za-z]){re.escape(nm)}(?![A-Za-z])', spoken_text):
            ev = bind_overheard_name(facility, nm, speaker_id=speaker_id, present_ids=present)
            if ev:
                events.append(ev)
    return events


def reply_to(facility, speaker_id: str, meaning: DialogueMeaning) -> dict:
    """Python-owned reply: intercept, else knowledge query, else honest don't-know."""
    note_exposure(facility, speaker_id)
    communicate_intent(meaning.intended_text, int(
        getattr(getattr(facility, 'pressures', None), 'language_ability', 15) or 15
    ))

    intercepted = authored_intercept(facility, speaker_id, meaning)
    if intercepted:
        text = intercepted.get('text') or ''
        extra = apply_overheard_names(facility, speaker_id, text)
        intercepted['events'] = list(intercepted.get('events') or []) + extra
        return intercepted

    q = query_npc_knowledge(facility, speaker_id, meaning)
    if q.get('kind') == 'withhold':
        return {'kind': 'withhold', 'text': _withhold_line(facility, speaker_id), 'events': []}
    if q.get('kind') == 'answer':
        text = q.get('text') or ''
        comp = comprehend_npc_meaning(facility, _plain_meaning(q.get('key') or '', text), speaker_id=speaker_id)
        extra_line = player_facing_comprehension_line(comp) if comp.get('uncertain_terms') else ''
        events = apply_overheard_names(facility, speaker_id, text)
        out = {'kind': 'answer', 'text': text, 'events': events, 'knowledge_key': q.get('key')}
        if extra_line:
            out['comprehension'] = extra_line
            out['uncertain_terms'] = comp.get('uncertain_terms')
        return out
    if q.get('kind') == 'unknown':
        return {'kind': 'unknown', 'text': _unknown_line(facility, speaker_id), 'events': []}

    ref = narrator_reference(facility, speaker_id)
    return {
        'kind': 'listen',
        'text': f'{ref.capitalize()} listens more than they explain.',
        'events': [],
    }


def _plain_meaning(key: str, text: str) -> str:
    if 'research' in (text + key).lower() or key == 'this_is_a_research_facility':
        return 'This is a research facility, almost a hospital.'
    if key == 'observation_is_the_purpose':
        return 'They are keeping you here for observation.'
    if key == 'official_death_then_continuation':
        return 'They say you died.'
    if key == 'eating_is_still_required':
        return 'Your body still needs to eat even if they say you died.'
    return re.sub(r'[“”"]', '', text).strip()[:180]


def remember_turn(facility, *, speaker: str, player_text: str, reply_kind: str, summary: str) -> None:
    conv = get_conversation(facility)
    turns = list(conv.get('recent_turns') or [])
    turns.append({
        'speaker': speaker,
        'player': player_text,
        'kind': reply_kind,
        'summary': summary,
    })
    conv['recent_turns'] = turns[-12:]
    conv['topic'] = summary[:80]
    if speaker:
        conv['interlocutor_id'] = speaker
    save_conversation(facility, conv)


def thought_fact(player_text: str) -> str:
    t = (player_text or '').strip().rstrip('?')
    t = re.sub(r'^\s*i wonder\s+', '', t, flags=re.I)
    return f'You wonder that, privately. No one is asked.'
