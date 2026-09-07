"""Hidden behavioural evidence. Never shown as meters."""
from __future__ import annotations

from typing import Any

DIMENSIONS = (
    'warmth', 'hostility', 'aggression', 'empathy', 'curiosity', 'caution',
    'impulsivity', 'defiance', 'compliance', 'deception', 'honesty',
    'patience', 'risk', 'self_preservation', 'protectiveness', 'absurdity',
)


def empty_tendencies() -> dict:
    return {k: 0 for k in DIMENSIONS}


def tag_action(intent: Any, player_text: str, enactment: str) -> list[str]:
    ac = ''
    classification = ''
    if isinstance(intent, dict):
        ac = str(intent.get('action_class') or '').lower()
        classification = str(intent.get('classification') or '').upper()
    elif intent is not None:
        ac = str(getattr(intent, 'action_class', '') or '').lower()
        classification = str(getattr(intent, 'classification', '') or '').upper()
    text = (player_text or '').lower()
    tags: list[str] = []
    if any(w in ac or w in text for w in ('attack', 'punch', 'hit', 'kill', 'fight', 'strike')):
        tags += ['aggression', 'hostility']
    if any(w in ac or w in text for w in ('refuse', 'resist', 'stand_firm', 'will not', "won't")):
        tags.append('defiance')
    if any(w in ac or w in text for w in ('cooperate', 'obey', 'step back', 'wash', 'eat')):
        tags.append('compliance')
    if classification == 'PERCEPTION_QUERY' or ac in ('look', 'examine', 'inspect', 'search'):
        tags.append('curiosity')
    if any(w in text for w in ('hide', 'lie', 'pretend')):
        tags.append('deception')
    if any(w in text for w in ('thank', 'help', 'sorry', 'please', 'share')):
        tags += ['warmth', 'empathy']
    if classification == 'IMPOSSIBLE_ATTEMPT' or any(
        w in text for w in ('dragon', 'helicopter', 'marry', 'become', 'soup', 'invent')
    ):
        tags.append('absurdity')
    if any(w in ac or w in text for w in ('escape', 'run', 'flee', 'break free')):
        tags += ['risk', 'self_preservation']
    if enactment in ('aborted', 'compromised') and 'aggression' in tags:
        tags.append('self_preservation')
    return tags


def apply_tags(tendencies: dict, tags: list[str], *, weight: int = 1) -> dict:
    out = dict(tendencies or empty_tendencies())
    for t in tags:
        if t in out:
            out[t] = max(-20, min(20, int(out[t]) + weight))
    return out


def classify_subject(tendencies: dict, arc: dict) -> str:
    """Internal only — never shown to the player."""
    t = tendencies or {}
    if arc.get('player_final_intent') == 'REFUSE' and arc.get('actual_contract_response') == 'ACCEPT':
        return 'strongly_afterlife_conditioned'
    if arc.get('initial_contract_response') == 'ACCEPT':
        if int(t.get('curiosity', 0) or 0) >= 4:
            return 'cooperative_investigative'
        return 'immediately_compliant'
    if int(t.get('aggression', 0) or 0) >= 6:
        return 'aggressive'
    if int(t.get('defiance', 0) or 0) >= 5:
        return 'initially_resistant'
    if int(t.get('curiosity', 0) or 0) >= 5:
        return 'unusually_investigative'
    if arc.get('heaven_experienced') and arc.get('hell_experienced'):
        return 'afterlife_conditioned'
    return 'behaviourally_mixed'
