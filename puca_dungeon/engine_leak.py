"""Detect engine / RPG term leakage in player-facing prose."""
from __future__ import annotations

import re
from typing import Iterable, List


FORBIDDEN_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r'\bSKILL\b', re.IGNORECASE),
    re.compile(r'\bSTAMINA\b', re.IGNORECASE),
    re.compile(r'\bLUCK\b', re.IGNORECASE),
    re.compile(r'\bHP\b'),
    re.compile(r'\bAC\b'),
    re.compile(r'\bDC\b'),
    re.compile(r'\battack\s+roll\b', re.IGNORECASE),
    re.compile(r'\bsaving\s+throw\b', re.IGNORECASE),
    re.compile(r'\bskill\s+check\b', re.IGNORECASE),
    re.compile(r'\blose\s+\d+\s+STAMINA\b', re.IGNORECASE),
    re.compile(r'\bgain\s+\d+\s+STAMINA\b', re.IGNORECASE),
    re.compile(r'\bPassage\s+\d+\b', re.IGNORECASE),
    re.compile(r'\bturn\s+to\s+\d+\b', re.IGNORECASE),
    re.compile(r'\bRound\s+\d+\s*:', re.IGNORECASE),
    re.compile(r'\bAdventure\s+Sheet\b', re.IGNORECASE),
    re.compile(r'\bAttack\s+Strength\b', re.IGNORECASE),
    re.compile(r'\bTest\s+your\s+(?:Luck|Skill)\b', re.IGNORECASE),
    re.compile(r'\b(?:combat|item)\.[a-z][a-z0-9_]*\b', re.IGNORECASE),
    # Authored action ids as bare snake_case tokens (e.g. open_named_box).
    re.compile(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}\b'),
    re.compile(r'\b\d+d\d+\b', re.IGNORECASE),  # dice notation
    re.compile(r'\+\d+\s+(?:to\s+)?(?:hit|damage|AC|HP)\b', re.IGNORECASE),
]


def scan_player_facing_text(text: str) -> list[str]:
    """Return distinct forbidden substrings matched in player-facing text."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for pattern in FORBIDDEN_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(0)
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(token)
    return found


def assert_clean(text: str) -> None:
    """Raise AssertionError if player-facing text contains engine leaks."""
    hits = scan_player_facing_text(text)
    if hits:
        preview = ', '.join(repr(h) for h in hits[:8])
        raise AssertionError(f'engine leak in player-facing text: {preview}')


def any_leaks(texts: Iterable[str]) -> list[str]:
    """Scan multiple strings; return unique leak tokens across all."""
    seen: set[str] = set()
    out: list[str] = []
    for text in texts:
        for token in scan_player_facing_text(text or ''):
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(token)
    return out
