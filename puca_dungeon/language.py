"""Language ability rises only when Sarel attempts to communicate."""
from __future__ import annotations

import re
from typing import Any

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
    # Do not treat look/wait/sleep as speech even if an utterance field is filled
    if ac.lower() in ('wait', 'look', 'examine', 'inspect', 'search', 'sleep', 'rest'):
        return False
    if classification.upper() == 'PERCEPTION_QUERY':
        return False
    if _SPEECH_WORDS.search(text):
        return True
    return False


def practice_language(pressures: BodyPressures, attempts: int) -> tuple[int, int]:
    """Apply one attempted use. Returns (new_attempts, delta_applied).

    Truncated speech still counts. Diminishing returns. Never jumps to fluent
    from calendar time — caller must only invoke this on an attempt.
    """
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


def intelligible_staff_speech(raw: str, understood: str, language_ability: int) -> str:
    """How much of an NPC sentence Sarel can currently catch."""
    if language_ability >= 55:
        return raw if raw and '…' not in raw else understood
    if language_ability >= 35:
        return understood
    return understood.split('/')[0].strip() if understood else '…'
