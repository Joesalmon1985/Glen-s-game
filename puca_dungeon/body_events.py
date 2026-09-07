"""Body-event facts: wounds without RPG score vocabulary."""
from __future__ import annotations

from typing import Any, Optional, Union

from puca_dungeon.models import AdventureSheet, _default_body_state

SheetLike = Union[AdventureSheet, dict]


def _get(sheet: SheetLike, key: str, default=None):
    if isinstance(sheet, dict):
        return sheet.get(key, default)
    return getattr(sheet, key, default)


def _set(sheet: SheetLike, key: str, value) -> None:
    if isinstance(sheet, dict):
        sheet[key] = value
    else:
        setattr(sheet, key, value)


def _ensure_body_state(sheet: SheetLike) -> dict:
    body = _get(sheet, 'body_state')
    if not isinstance(body, dict):
        body = _default_body_state()
        _set(sheet, 'body_state', body)
    else:
        for key, val in _default_body_state().items():
            body.setdefault(key, val)
    return body


def _severity_for_amount(amount: int) -> str:
    n = abs(int(amount or 0))
    if n <= 0:
        return 'none'
    if n == 1:
        return 'light'
    if n == 2:
        return 'moderate'
    if n <= 4:
        return 'serious'
    return 'critical'


def _site_for_source(source: str) -> str:
    src = (source or '').lower()
    if 'head' in src or 'face' in src:
        return 'head'
    if 'arm' in src or 'hand' in src or 'grip' in src:
        return 'arm'
    if 'leg' in src or 'foot' in src:
        return 'leg'
    if 'chest' in src or 'torso' in src or 'body' in src:
        return 'torso'
    if 'enemy' in src or 'combat' in src or 'blade' in src or 'claw' in src:
        return 'torso'
    return 'torso'


def stamina_loss_to_body_event(
    amount: int,
    source: str,
    sheet: SheetLike,
) -> dict:
    """Map internal score loss to a structured body fact (no score names)."""
    severity = _severity_for_amount(amount)
    site = _site_for_source(source)
    body = _ensure_body_state(sheet)
    event = {
        'kind': 'body_event',
        'type': 'wound',
        'site': site,
        'severity': severity,
        'source': str(source or 'unknown'),
        'pain': severity if severity != 'none' else 'none',
        'bleeding': 'light' if severity in ('moderate', 'serious') else (
            'heavy' if severity == 'critical' else 'none'
        ),
        'alive': bool(_get(sheet, 'alive', True)),
    }
    if severity in ('serious', 'critical'):
        event['locomotion'] = 'impaired'
    elif severity == 'moderate':
        event['locomotion'] = body.get('locomotion') or 'normal'
    else:
        event['locomotion'] = body.get('locomotion') or 'normal'
    return event


def apply_injury(sheet: SheetLike, injury_dict: dict) -> dict:
    """Append an injury and update qualitative body_state. Returns the stored injury."""
    injury = dict(injury_dict or {})
    injury.setdefault('kind', 'injury')
    injuries = list(_get(sheet, 'injuries') or [])
    injuries.append(injury)
    _set(sheet, 'injuries', injuries)

    body = _ensure_body_state(sheet)
    severity = str(injury.get('severity') or 'light')
    pain_rank = {'none': 0, 'light': 1, 'moderate': 2, 'serious': 3, 'critical': 4}
    bleed_rank = {'none': 0, 'light': 1, 'heavy': 2}

    new_pain = str(injury.get('pain') or severity)
    if pain_rank.get(new_pain, 0) >= pain_rank.get(str(body.get('pain') or 'none'), 0):
        body['pain'] = new_pain

    new_bleed = str(injury.get('bleeding') or 'none')
    if bleed_rank.get(new_bleed, 0) >= bleed_rank.get(str(body.get('bleeding') or 'none'), 0):
        body['bleeding'] = new_bleed

    if injury.get('locomotion'):
        body['locomotion'] = injury['locomotion']
    elif severity in ('serious', 'critical'):
        body['locomotion'] = 'impaired'

    if injury.get('grip'):
        body['grip'] = injury['grip']
    elif str(injury.get('site') or '') in ('arm', 'hand') and severity in ('serious', 'critical'):
        body['grip'] = 'weak'

    _set(sheet, 'body_state', body)
    return injury


def qualitative_body_summary(sheet: SheetLike) -> list[str]:
    """Short narrator-ready facts; no score vocabulary."""
    facts: list[str] = []
    body = _ensure_body_state(sheet)
    pain = str(body.get('pain') or 'none')
    bleeding = str(body.get('bleeding') or 'none')
    locomotion = str(body.get('locomotion') or 'normal')
    grip = str(body.get('grip') or 'firm')

    if pain not in ('', 'none'):
        facts.append(f'You feel {pain} pain.')
    if bleeding not in ('', 'none'):
        facts.append(f'You are bleeding ({bleeding}).')
    if locomotion not in ('', 'normal'):
        facts.append(f'Your movement is {locomotion}.')
    if grip not in ('', 'firm'):
        facts.append(f'Your grip feels {grip}.')

    for injury in _get(sheet, 'injuries') or []:
        if not isinstance(injury, dict):
            continue
        site = injury.get('site')
        severity = injury.get('severity')
        if site and severity:
            facts.append(f'A {severity} wound marks your {site}.')
        elif site:
            facts.append(f'You bear a wound on your {site}.')

    if not bool(_get(sheet, 'alive', True)):
        facts.append('You are dead.')

    return facts


def combat_hit_player_facts(enemy_name: str, amount: int) -> list[dict]:
    """Structured facts when an enemy lands a blow on the player."""
    severity = _severity_for_amount(amount)
    name = (enemy_name or 'the enemy').strip() or 'the enemy'
    return [
        {
            'kind': 'world_event',
            'type': 'enemy_hit_player',
            'actor': name,
            'target': 'player',
            'severity': severity,
        },
        {
            'kind': 'body_event',
            'type': 'wound',
            'site': 'torso',
            'severity': severity,
            'source': name,
            'pain': severity if severity != 'none' else 'none',
            'bleeding': 'light' if severity in ('moderate', 'serious') else (
                'heavy' if severity == 'critical' else 'none'
            ),
        },
    ]


def combat_hit_enemy_facts(enemy_name: str) -> list[dict]:
    """Structured facts when the player lands a blow on an enemy."""
    name = (enemy_name or 'the enemy').strip() or 'the enemy'
    return [
        {
            'kind': 'world_event',
            'type': 'player_hit_enemy',
            'actor': 'player',
            'target': name,
            'severity': 'moderate',
        },
    ]
