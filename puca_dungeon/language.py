"""Language ability, semantic communication, and exposure learning.

Player English is intended meaning. Ability is hidden. Early core meaning
gets through; domain terms may remain uncertain.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from puca_dungeon.enactment import BodyPressures

_SPEECH_ACS = frozenset({
    'talk', 'speak', 'ask', 'say', 'tell', 'shout', 'scream', 'yell',
    'threaten', 'apologise', 'apologize', 'thank', 'answer', 'reply',
    'demand', 'explain', 'request', 'greet', 'name',
})
_SPEECH_WORDS = re.compile(
    r'\b('
    r'ask|tell|say|speak|talk|shout|scream|yell|threaten|'
    r'apologis|apologiz|thank|answer|reply|demand|explain|'
    r'request|who|why|what|where|please|sorry|hello|help|'
    r'name|called|agree|refuse|yes|no'
    r')\b',
    re.I,
)

# Domain terms that often remain uncertain early
DOMAIN_TERMS = {
    'observation': ['observe', 'watch', 'study', 'monitoring'],
    'continuity': ['continuation', 'continue', 'copy'],
    'contract': ['agreement', 'service', 'five-year'],
    'heaven': ['heaven'],
    'hell': ['hell'],
    'subject': ['subject', 'research subject'],
    'facility': ['facility'],
    'transfer': ['transfer', 'transition'],
}

CORE_SLOTS = frozenset({
    'name', 'who', 'where', 'why', 'here', 'self_name', 'yes', 'no',
    'work', 'eat', 'dead', 'safe',
})


def is_language_attempt(intent: Any, player_text: str = '') -> bool:
    """True when the player tries to communicate, including gesture-supported speech."""
    classification = ''
    ac = ''
    utterance = ''
    if intent is not None:
        if isinstance(intent, dict):
            classification = str(intent.get('classification') or '')
            ac = str(intent.get('action_class') or '')
            utterance = str(intent.get('utterance') or '')
        else:
            classification = str(getattr(intent, 'classification', '') or '')
            ac = str(getattr(intent, 'action_class', '') or '')
            utterance = str(getattr(intent, 'utterance', '') or '')
    if classification.upper() == 'SOCIAL_ACTION':
        return True
    if ac.lower() in _SPEECH_ACS:
        return True
    text = (player_text or utterance or '').strip()
    if not text:
        return False
    if ac.lower() in ('wait', 'look', 'examine', 'inspect', 'search', 'sleep', 'rest'):
        return False
    if classification.upper() == 'PERCEPTION_QUERY':
        return False
    if classification.upper() == 'INTERNAL_THOUGHT':
        return False
    if _SPEECH_WORDS.search(text):
        return True
    return False


def practice_language(pressures: BodyPressures, attempts: int) -> tuple[int, int]:
    """Apply one attempted use. Returns (new_attempts, delta_applied)."""
    attempts = max(0, int(attempts or 0)) + 1
    current = int(pressures.language_ability or 0)
    if current >= 68:
        delta = 0
    elif current >= 50:
        delta = 1 if attempts % 3 == 0 else 0
    elif current >= 35:
        delta = 1 if attempts % 2 == 0 else 0
    else:
        delta = 2 if attempts <= 8 else 1
    if delta:
        pressures.language_ability = min(68, current + delta)
    return attempts, delta


def _memory(facility) -> dict:
    arc = getattr(facility, 'arc', None)
    if arc is None:
        return {'vocabulary': [], 'speaker_familiarity': {}, 'resolved_terms': [], 'uncertain_terms': []}
    mem = dict(getattr(arc, 'language_memory', None) or {})
    mem.setdefault('vocabulary', [])
    mem.setdefault('speaker_familiarity', {})
    mem.setdefault('resolved_terms', [])
    mem.setdefault('uncertain_terms', [])
    return mem


def _save_memory(facility, mem: dict) -> None:
    arc = getattr(facility, 'arc', None)
    if arc is None:
        return
    arc.language_memory = mem


def speaker_familiarity(facility, speaker_id: str) -> int:
    mem = _memory(facility)
    return int((mem.get('speaker_familiarity') or {}).get(speaker_id, 0) or 0)


def note_exposure(facility, speaker_id: str = '', terms: Optional[list] = None) -> None:
    """Hearing a speaker / resolving a term counts as exposure."""
    mem = _memory(facility)
    if speaker_id:
        fam = dict(mem.get('speaker_familiarity') or {})
        fam[speaker_id] = int(fam.get(speaker_id, 0) or 0) + 1
        mem['speaker_familiarity'] = fam
        # Small ability bump from listening, slower than speaking
        pressures = getattr(facility, 'pressures', None)
        if pressures is not None and fam[speaker_id] % 4 == 0:
            current = int(pressures.language_ability or 0)
            if current < 68:
                pressures.language_ability = min(68, current + 1)
    vocab = list(mem.get('vocabulary') or [])
    for t in terms or []:
        key = str(t).lower().strip()
        if key and key not in vocab:
            vocab.append(key)
    mem['vocabulary'] = vocab
    _save_memory(facility, mem)


def resolve_term(facility, term: str) -> None:
    mem = _memory(facility)
    t = (term or '').lower().strip()
    if not t:
        return
    resolved = list(mem.get('resolved_terms') or [])
    if t not in resolved:
        resolved.append(t)
    uncertain = [u for u in (mem.get('uncertain_terms') or []) if u != t]
    vocab = list(mem.get('vocabulary') or [])
    if t not in vocab:
        vocab.append(t)
    mem['resolved_terms'] = resolved
    mem['uncertain_terms'] = uncertain
    mem['vocabulary'] = vocab
    _save_memory(facility, mem)
    pressures = getattr(facility, 'pressures', None)
    if pressures is not None:
        current = int(pressures.language_ability or 0)
        if current < 68:
            pressures.language_ability = min(68, current + 1)


def term_is_uncertain(facility, term: str, language_ability: int, speaker_id: str = '') -> bool:
    t = (term or '').lower().strip()
    if not t or t not in DOMAIN_TERMS:
        return False
    mem = _memory(facility)
    if t in (mem.get('resolved_terms') or []):
        return False
    if t in (mem.get('vocabulary') or []) and language_ability >= 28:
        return False
    fam = speaker_familiarity(facility, speaker_id) if speaker_id else 0
    if fam >= 4 and language_ability >= 25:
        return False
    if language_ability >= 55:
        return False
    return True


def mark_uncertain(facility, term: str) -> None:
    mem = _memory(facility)
    t = (term or '').lower().strip()
    if not t:
        return
    uncertain = list(mem.get('uncertain_terms') or [])
    if t not in uncertain:
        uncertain.append(t)
    mem['uncertain_terms'] = uncertain
    _save_memory(facility, mem)


def communicate_intent(player_text: str, language_ability: int) -> dict:
    """What meaning Sarel gets across. Player English is intention, not phonemes."""
    text = (player_text or '').strip()
    slots: list[str] = []
    missing: list[str] = []
    low = text.lower()
    if re.search(r'\b(name|who are you|who is|called)\b', low):
        slots.append('NAME')
    if re.search(r'\b(where|this place|here)\b', low):
        slots.append('WHERE')
    if re.search(r'\b(why|what for)\b', low):
        slots.append('WHY')
    if re.search(r'\b(i am|i\'m|my name is|sarel)\b', low):
        slots.append('SELF_NAME')
    if re.search(r'\b(work|job|do you)\b', low):
        slots.append('WORK')
    if re.search(r'\b(dead|died|death)\b', low):
        slots.append('DEAD')
    if re.search(r'\b(eat|food|hungry)\b', low):
        slots.append('EAT')
    # Core meaning gets through even at low ability
    communicated = True
    nuance_lost = language_ability < 28
    return {
        'intended': text,
        'communicated': communicated,
        'slots': slots,
        'missing': missing,
        'nuance_lost': nuance_lost,
        'understood_by_npc': True,
    }


def comprehend_npc_meaning(
    facility,
    meaning: str,
    *,
    speaker_id: str = '',
    extra_terms: Optional[list] = None,
) -> dict:
    """How much of an NPC meaning Sarel currently catches."""
    ability = int(getattr(getattr(facility, 'pressures', None), 'language_ability', 15) or 15)
    fam = speaker_familiarity(facility, speaker_id)
    effective = ability + min(12, fam * 2)
    uncertain = []
    blob = (meaning or '').lower()
    candidates = list(DOMAIN_TERMS.keys()) + list(extra_terms or [])
    for term in candidates:
        if term.lower() in blob or any(a in blob for a in DOMAIN_TERMS.get(term, [])):
            if term_is_uncertain(facility, term, effective, speaker_id):
                uncertain.append(term)
                mark_uncertain(facility, term)
    understood = meaning
    if uncertain and effective < 50:
        gloss = meaning
        for t in uncertain:
            gloss = re.sub(rf'\b{re.escape(t)}\b', f'[{t}?]', gloss, flags=re.I)
        understood = gloss
    return {
        'raw_meaning': meaning,
        'understood_meaning': understood,
        'uncertain_terms': uncertain,
        'effective_ability': effective,
    }


def player_facing_comprehension_line(result: dict) -> str:
    uncertain = list(result.get('uncertain_terms') or [])
    meaning = str(result.get('raw_meaning') or '')
    if not uncertain:
        return ''
    term = uncertain[0]
    return (
        f'You understand most of it: {meaning.rstrip(".")}. '
        f'The word that might mean {term} — or something close — stays uncertain.'
    )


def intelligible_staff_speech(raw: str, understood: str, language_ability: int) -> str:
    """Legacy helper — prefer comprehend_npc_meaning for new paths."""
    if language_ability >= 55:
        return raw if raw and '…' not in raw else understood
    if language_ability >= 35:
        return understood
    return understood.split('/')[0].strip() if understood else understood
