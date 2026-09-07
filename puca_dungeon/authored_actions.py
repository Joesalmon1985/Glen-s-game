"""Public-safe authored action descriptors for the FF gamebook interpreter.

These are internal semantic targets, not player-facing menus.
They must not reveal hidden effects, secret flags, or unrevealed branch numbers
beyond what the current passage already exposes via choice labels.
"""
from __future__ import annotations

from typing import Any, Optional, Union

from puca_dungeon.models import WorldState


PassageLike = Union[dict, Any]


def _passage_field(passage: PassageLike, key: str, default=None):
    if isinstance(passage, dict):
        return passage.get(key, default)
    return getattr(passage, key, default)


def build_authored_actions(world: WorldState, passage: PassageLike) -> list[dict]:
    """Return currently resolvable authored interactions for this passage / combat."""
    actions: list[dict] = []

    if world.combat.active:
        enemy = world.combat.enemy_name or 'enemy'
        actions.append({
            'id': 'combat.attack',
            'description': f'Attack or fight {enemy} this round.',
            'entities': ['enemy', enemy],
            'tools': ['sword'],
            'operation': 'combat_attack',
        })
        if world.combat.flee_to is not None:
            actions.append({
                'id': 'combat.flee',
                'description': f'Try to flee from {enemy}.',
                'entities': ['enemy', enemy],
                'tools': [],
                'operation': 'combat_flee',
                'turn_to': world.combat.flee_to,
            })
    else:
        for choice in _passage_field(passage, 'choices') or []:
            if not isinstance(choice, dict):
                continue
            cid = choice.get('id')
            if not cid:
                continue
            label = choice.get('label') or cid
            aliases = choice.get('aliases') or []
            alias_note = f" (also: {', '.join(aliases[:4])})" if aliases else ''
            action = {
                'id': str(cid),
                'description': f'{label}{alias_note}',
                'entities': [],
                'tools': [],
                'operation': 'turn_to',
                'turn_to': choice.get('to'),
                'label': label,
                'aliases': list(aliases),
            }
            actions.append(action)

    sheet = world.sheet
    if sheet.potion and not sheet.potion_used and sheet.alive:
        actions.append({
            'id': 'item.use_potion',
            'description': 'Drink your potion.',
            'entities': ['potion'],
            'tools': [sheet.potion],
            'operation': 'use_potion',
            'aliases': [
                'drink potion', 'drink my potion', 'use potion',
                'quaff potion', 'drink the potion',
            ],
        })
    if sheet.provisions > 0 and sheet.alive:
        actions.append({
            'id': 'item.eat_provision',
            'description': 'Eat a provision to recover strength.',
            'entities': ['provisions'],
            'tools': [],
            'operation': 'eat_provision',
            'aliases': [
                'eat provision', 'eat a provision', 'eat food',
                'eat provisions', 'consume provision',
            ],
        })

    # Compact payload for the LLM
    compact = []
    for a in actions:
        entry = {
            'id': a['id'],
            'description': a['description'],
            'operation': a.get('operation'),
            'entities': a.get('entities') or [],
            'tools': a.get('tools') or [],
        }
        if a.get('turn_to') is not None:
            entry['turn_to'] = a['turn_to']
        if a.get('aliases'):
            entry['aliases'] = a['aliases']
        compact.append(entry)
    return compact


# Map authored action ids onto canonical intent fields for Python resolve.
# Passage choice ids are added dynamically via intent_overlay_for_action / apply_authored_match.
AUTHORED_TO_INTENT = {
    'combat.attack': {
        'action_class': 'ATTACK',
        'target': 'enemy',
        'tool': 'sword',
        'intended_effect': 'harm',
    },
    'combat.flee': {
        'action_class': 'FLEE',
        'intended_effect': 'escape',
    },
    'item.use_potion': {
        'action_class': 'USE',
        'target': 'potion',
        'tool': 'potion',
        'intended_effect': 'restore',
    },
    'item.eat_provision': {
        'action_class': 'USE',
        'target': 'provision',
        'intended_effect': 'restore_stamina',
    },
}


def intent_overlay_for_action(
    action_id: Optional[str],
    authored_actions: Optional[list[dict]] = None,
) -> Optional[dict]:
    """Resolve static or choice-derived intent overlay including turn_to."""
    if not action_id:
        return None
    if action_id in AUTHORED_TO_INTENT:
        overlay = dict(AUTHORED_TO_INTENT[action_id])
        if authored_actions:
            for a in authored_actions:
                if a.get('id') == action_id and a.get('turn_to') is not None:
                    overlay['turn_to'] = a['turn_to']
                    break
        return overlay
    if authored_actions:
        for a in authored_actions:
            if a.get('id') == action_id:
                overlay = {
                    'action_class': 'TURN_TO',
                    'intended_effect': 'follow_choice',
                    'method': 'turn_to',
                }
                if a.get('turn_to') is not None:
                    overlay['turn_to'] = a['turn_to']
                return overlay
    # Fallback: treat unknown id as a turn_to choice id without known destination
    return {
        'action_class': 'TURN_TO',
        'intended_effect': 'follow_choice',
        'method': 'turn_to',
    }


def apply_authored_match(
    intent_fields: dict,
    matched_action_id: Optional[str],
    authored_actions: Optional[list[dict]] = None,
) -> dict:
    """Overlay canonical fields when an authored action matched."""
    if not matched_action_id:
        return intent_fields
    canon = intent_overlay_for_action(matched_action_id, authored_actions)
    if not canon:
        return intent_fields
    merged = dict(intent_fields)
    for key, value in canon.items():
        if merged.get(key) in (None, '', 'unspecified'):
            merged[key] = value
        elif key in (
            'action_class', 'method', 'intended_effect', 'destination',
            'manner', 'turn_to',
        ):
            merged[key] = value
    if not merged.get('action_class'):
        merged['action_class'] = canon.get('action_class', 'TURN_TO')
    return merged
