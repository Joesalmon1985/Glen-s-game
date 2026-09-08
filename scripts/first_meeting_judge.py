"""Judge a player-visible first-meeting transcript (no engine state)."""
from __future__ import annotations

import re
from typing import Any


def _split_turns(transcript: str) -> list[dict]:
    turns = []
    chunks = re.split(r'\n(?=(?:##?\s*)?(?:Turn|T)\s*\d+)', transcript.strip())
    for ch in chunks:
        m = re.search(r'PLAYER:\s*(.+)', ch)
        player = m.group(1).strip() if m else ''
        prose = re.sub(r'(?:##?\s*)?(?:Turn|T)\s*\d+[^\n]*', '', ch)
        prose = re.sub(r'PLAYER:\s*.+', '', prose).strip()
        if player or prose:
            turns.append({'player': player, 'prose': prose})
    return turns


def judge_first_meeting_transcript(transcript: str, *, true_names: list[str] | None = None) -> dict[str, Any]:
    """Answer the TEST G questions from prose only. Fail closed on name-before-intro."""
    text = transcript or ''
    low = text.lower()
    names = [n for n in (true_names or []) if n]
    turns = _split_turns(text)
    people_cues = len(re.findall(
        r'\b(older person|broad person|younger|sharp-eyed|gentle-faced|folder|collar|sleeves rolled)\b',
        low,
    ))

    first_name = None
    name_before_intro = False
    first_look = turns[0]['prose'] if turns else ''
    for n in names:
        if re.search(rf'(?<![A-Za-z]){re.escape(n)}(?![A-Za-z])', first_look):
            name_before_intro = True
        for turn in turns[1:]:
            if re.search(rf'(?<![A-Za-z]){re.escape(n)}(?![A-Za-z])', turn.get('prose') or ''):
                first_name = n
                break
        if first_name:
            break

    asked = bool(re.search(r'\b(where|why|who|name|eat|dead|work)\b', low))
    uncertain = bool(re.search(r'\b(unfamiliar|uncertain|almost|might mean|you catch)\b', low))
    reads_like_meeting = bool(
        re.search(
            r'\b(i[’\']m |i am |you catch the name|says it slowly|touch(?:es)? two fingers|the word is clear)\b',
            low,
        )
        and not re.search(r'\b(NEW CHARACTER|dialogue subsystem|trust meter)\b', low)
    )
    scene_shift = bool(re.search(r'\b(taken into|you wake|corridor|washroom)\b', low))
    same_scene = not scene_shift or bool(re.search(r'\binterview room|closes the door|folder\b', low))

    report = {
        'how_many_people': max(1, min(3, people_cues or 1)),
        'how_distinguished': bool(people_cues),
        'first_name_learned': first_name,
        'how_learned': 'self_introduction' if first_name else None,
        'asked': asked,
        'language_uncertain': uncertain,
        'name_before_intro': name_before_intro,
        'same_physical_scene': same_scene,
        'reads_like_two_people_meeting': reads_like_meeting,
        'turns': len(turns),
        'ok': (
            not name_before_intro
            and asked
            and reads_like_meeting
            and (first_name is not None)
        ),
    }
    return report
