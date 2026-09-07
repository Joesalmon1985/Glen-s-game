"""Deterministic prose lint for player-facing / pack text."""
from __future__ import annotations

import re
from typing import Iterable


# Common UTF-8→cp1252 / mojibake fragments seen in OCR dumps and bad CLI output.
_MOJIBAKE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ('mojibake_emdash', re.compile(r'ÔÇö|â€”|â€“')),
    ('mojibake_quotes', re.compile(r'â€œ|â€|â€˜|â€™|ÔÇ£|ÔÇØ')),
    ('mojibake_ellipsis', re.compile(r'â€¦|ÔÇª')),
    ('mojibake_generic', re.compile(r'Ã.|Â.|â.+')),
]

_BROKEN_PUNCT = [
    ('double_space_before_punct', re.compile(r'\s{2,}[,.;:!?]') ),
    ('space_before_punct', re.compile(r'\s+[,.;:!?]')),
    ('repeated_punct', re.compile(r'([!?.,]){3,}')),
    ('bare_replacement_char', re.compile(r'\ufffd|�')),
]

_ENGINE_LEAK = [
    ('skill_leak', re.compile(r'\bSKILL\b')),
    ('stamina_leak', re.compile(r'\bSTAMINA\b')),
    ('luck_leak', re.compile(r'\bLUCK\b')),
    ('attack_strength_leak', re.compile(r'\bAttack\s+Strength\b', re.I)),
]

_STOCK_PHRASES = (
    'nothing in the world shifts for it',
    'nothing of note follows from that',
    'your words hang in the air unanswered',
    'what do you do?',
    'the room remains the room',
    'the room does not hurry',
    'despite your intention',
    'wanted_action',
    'facility phase',
)


def lint_text(text: str, *, stock_repeat_threshold: int = 2) -> list[dict]:
    """Return lint findings for a single string."""
    findings: list[dict] = []
    raw = text or ''
    if not raw:
        return findings

    for label, pat in _MOJIBAKE_PATTERNS:
        for m in pat.finditer(raw):
            findings.append({
                'kind': label,
                'match': m.group(0),
                'span': [m.start(), m.end()],
            })

    for label, pat in _BROKEN_PUNCT:
        for m in pat.finditer(raw):
            findings.append({
                'kind': label,
                'match': m.group(0),
                'span': [m.start(), m.end()],
            })

    for label, pat in _ENGINE_LEAK:
        for m in pat.finditer(raw):
            findings.append({
                'kind': label,
                'match': m.group(0),
                'span': [m.start(), m.end()],
            })

    lower = raw.lower()
    for phrase in _STOCK_PHRASES:
        count = lower.count(phrase)
        if count >= stock_repeat_threshold:
            findings.append({
                'kind': 'repeated_stock_phrase',
                'phrase': phrase,
                'count': count,
            })

    return findings


def lint_texts(texts: Iterable[str], **kwargs) -> list[dict]:
    out: list[dict] = []
    for i, text in enumerate(texts):
        for hit in lint_text(text, **kwargs):
            hit = {**hit, 'index': i}
            out.append(hit)
    return out


def has_mojibake(text: str) -> bool:
    return any(h['kind'].startswith('mojibake') for h in lint_text(text))


def has_engine_leak(text: str) -> bool:
    return any(
        h['kind'].endswith('_leak') for h in lint_text(text)
    )
