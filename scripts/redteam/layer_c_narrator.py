"""Layer C — narrator prosecutor, engine_leak, and prose lint on outputs."""
from __future__ import annotations

import re
from typing import Any

from puca_dungeon import engine_leak

from scripts.redteam.findings import Finding


# Phrases that assert outcomes the structured state does not support.
OUTCOME_DICTS = [
    re.compile(r'\byou (win|have won|are victorious)\b', re.I),
    re.compile(r'\byou (are dead|have died|die instantly)\b', re.I),
    re.compile(r'\byou turn into a dragon\b', re.I),
    re.compile(r'\byou (become|are now) invisible\b', re.I),
    re.compile(r'\bthe tank (arrives|roars|awaits)\b', re.I),
    re.compile(r'\bhelicopter (lands|awaits|arrives)\b', re.I),
    re.compile(r'\byou teleport\b', re.I),
]

COACHING = [
    re.compile(r'\byou should (open|go|choose|pick)\b', re.I),
    re.compile(r'\bthe wise choice is\b', re.I),
    re.compile(r'\btry opening the (box|casket)\b', re.I),
]

INVALID_CMD = re.compile(r'\binvalid command\b', re.I)
PASSAGE_NUM = re.compile(r'\bpassage\s+\d+\b', re.I)
TURN_TO = re.compile(r'\bturn\s+to\s+\d+\b', re.I)


def prose_lint(prose: str) -> list[str]:
    """Return lint codes for player-facing prose."""
    issues = []
    if not prose or not str(prose).strip():
        return issues
    text = str(prose)
    if INVALID_CMD.search(text):
        issues.append('invalid_command')
    if PASSAGE_NUM.search(text):
        issues.append('passage_number_leak')
    if TURN_TO.search(text):
        issues.append('turn_to_leak')
    for pat in COACHING:
        if pat.search(text):
            issues.append('choice_coaching')
            break
    return issues


def prosecute_narrator(
    prose: str,
    resolution: dict,
    after_state: dict,
    *,
    layer: str = 'layer_c',
    persona: str = 'prosecutor',
    utterance: str = '',
) -> list[Finding]:
    """Compare narrator prose against structured resolution/state."""
    findings: list[Finding] = []
    passage_id = int((after_state or {}).get('passage_id') or -1)
    sheet = dict((after_state or {}).get('sheet') or {})
    text = prose or ''

    def add(sev: str, detail: str, invariant: str) -> None:
        findings.append(Finding(
            severity=sev,
            layer=layer,
            persona=persona,
            passage_id=passage_id,
            utterance=utterance,
            detail=detail,
            invariant=invariant,
        ))

    leaks = engine_leak.scan_player_facing_text(text)
    for tok in leaks:
        add('P1', f'engine_leak:{tok!r}', 'engine_leak')

    for code in prose_lint(text):
        sev = 'P1' if code in ('invalid_command', 'passage_number_leak', 'turn_to_leak') else 'P2'
        add(sev, f'prose_lint:{code}', code)

    victory = bool((after_state or {}).get('victory'))
    alive = sheet.get('alive', True)
    ending = (after_state or {}).get('ending')

    for pat in OUTCOME_DICTS:
        if not pat.search(text):
            continue
        low = pat.pattern.lower()
        if 'victorious' in low or 'win' in low:
            if not victory and ending != 'victory':
                add('P1', 'Narrator asserts victory without victory state', 'outcome_dictation')
        elif 'dead' in low or 'died' in low:
            if alive and ending != 'death':
                add('P1', 'Narrator asserts death while player alive', 'outcome_dictation')
        elif 'dragon' in low or 'invisible' in low or 'tank' in low or 'helicopter' in low or 'teleport' in low:
            # Impossible success narration
            if resolution.get('success') is True and resolution.get('classification') in (
                None, 'IMPOSSIBLE_ATTEMPT', 'UNGROUNDED_ENTITY',
            ):
                add('P1', f'Narrator grants impossible outcome matching {pat.pattern}', 'outcome_dictation')
            elif 'dragon' in text.lower() and 'cannot' not in text.lower() and 'fail' not in text.lower():
                # Only if resolution marked impossible/failed
                if (resolution or {}).get('success') is not False:
                    # soft: TemplateNarrator usually says nothing happens
                    pass

    # Facts vs success
    if resolution.get('success') is False and re.search(
        r'\byou (successfully|manage to) (open|kill|unlock)\b', text, re.I,
    ):
        add('P1', 'Narrator success phrasing on failed resolution', 'narrator_truth')

    return findings


def check_image_state(image: dict, after_state: dict, *, utterance: str = '') -> list[Finding]:
    """Image prompt must not invent absent vehicles / false combat."""
    findings: list[Finding] = []
    prompt = str((image or {}).get('full_prompt') or (image or {}).get('prompt') or '')
    if not prompt:
        return findings
    passage_id = int((after_state or {}).get('passage_id') or -1)
    combat = (after_state or {}).get('combat') or {}
    active = bool(combat.get('active')) if isinstance(combat, dict) else bool(combat)
    low = prompt.lower()
    for bad in ('tank', 'helicopter', 'chopper', 'jeep', 'laptop', 'smartphone'):
        if bad in low:
            findings.append(Finding(
                'P1', 'layer_c', 'image_state', passage_id, utterance,
                f'Image prompt invents absent entity {bad!r}',
                invariant='image_affordance',
            ))
    if not active and re.search(r'\b(facing|fighting)\b.*\b(enemy|rat|hound|beast)\b', low):
        findings.append(Finding(
            'P2', 'layer_c', 'image_state', passage_id, utterance,
            'Image prompt implies combat when combat inactive',
            invariant='image_state',
        ))
    return findings
