"""Intent-fidelity gate: irreversible mutations must match semantic intention."""
from __future__ import annotations

from typing import Any, Optional, Union

from puca_dungeon.models import Intent

IntentLike = Union[Intent, dict]

MOVE_CLASSES = frozenset({
    'MOVE', 'FLEE', 'TURN_TO', 'GO', 'ENTER', 'LEAVE', 'CLIMB', 'JUMP', 'RUN',
})
ATTACK_CLASSES = frozenset({
    'ATTACK', 'STRIKE', 'FIGHT', 'HIT', 'SLASH', 'STAB', 'KILL',
})
LOOK_CLASSES = frozenset({
    'LOOK', 'PERCEIVE', 'INSPECT', 'SEARCH', 'EXAMINE', 'QUERY', 'WATCH', 'LISTEN',
})
CONSUME_CLASSES = frozenset({
    'DRINK', 'EAT', 'CONSUME', 'QUAFF', 'USE',
})


def _intent_get(intent: IntentLike, key: str, default=None):
    if isinstance(intent, dict):
        return intent.get(key, default)
    return getattr(intent, key, default)


def _blob(intent: IntentLike) -> str:
    parts = [
        _intent_get(intent, 'action_class'),
        _intent_get(intent, 'target'),
        _intent_get(intent, 'tool'),
        _intent_get(intent, 'method'),
        _intent_get(intent, 'intended_effect'),
        _intent_get(intent, 'manner'),
        _intent_get(intent, 'destination'),
        _intent_get(intent, 'utterance'),
        _intent_get(intent, 'matched_action_id'),
        _intent_get(intent, 'notes'),
    ]
    return ' '.join(str(p or '') for p in parts).lower()


def _action_class(intent: IntentLike) -> str:
    return str(_intent_get(intent, 'action_class') or '').strip().upper()


def _matched_id(intent: IntentLike) -> str:
    return str(_intent_get(intent, 'matched_action_id') or '').strip().lower()


def _is_look(intent: IntentLike) -> bool:
    cls = _action_class(intent)
    classification = str(_intent_get(intent, 'classification') or '').upper()
    if classification == 'PERCEPTION_QUERY':
        return True
    if cls in LOOK_CLASSES:
        return True
    return False


def _clearly_potion_or_drink(intent: IntentLike) -> bool:
    blob = _blob(intent)
    matched = _matched_id(intent)
    cls = _action_class(intent)

    if matched in ('item.use_potion', 'item.eat_provision'):
        return True
    if any(tok in blob for tok in ('potion', 'drink', 'quaff', 'sip', 'provision', 'food', 'eat', 'swallow')):
        # Key / unlock language must not count as consume.
        if 'key' in blob and 'potion' not in blob and 'drink' not in blob and 'provision' not in blob:
            return False
        if matched in ('use_key', 'item.use_key') or 'use_key' in blob:
            return False
        return True
    if cls in ('DRINK', 'EAT', 'QUAFF', 'CONSUME'):
        return True
    if cls == 'USE' and ('potion' in blob or 'provision' in blob):
        return True
    return False


def _allows_move(intent: IntentLike) -> bool:
    cls = _action_class(intent)
    if cls in MOVE_CLASSES:
        return True
    if _intent_get(intent, 'destination'):
        return True
    if _intent_get(intent, 'turn_to') is not None:
        return True
    matched = _matched_id(intent)
    if matched.startswith('combat.flee') or matched == 'combat.flee':
        return True
    # Matched authored movement (turn_to ops / leave / continue).
    details_hint = matched
    if any(tok in details_hint for tok in ('continue', 'leave', 'north', 'south', 'east', 'west', 'go_', 'move_')):
        return True
    classification = str(_intent_get(intent, 'classification') or '').upper()
    if classification == 'MATCH_AUTHORED_ACTION' and matched and matched not in (
        'combat.attack', 'item.use_potion', 'item.eat_provision',
    ):
        # Authored graph transitions are movement/transition-like.
        return True
    return False


def _allows_attack(intent: IntentLike) -> bool:
    cls = _action_class(intent)
    if cls in ATTACK_CLASSES:
        return True
    if _matched_id(intent) == 'combat.attack':
        return True
    effect = str(_intent_get(intent, 'intended_effect') or '').lower()
    if effect in ('harm', 'kill', 'wound', 'damage'):
        return True
    return False


def intent_fidelity_allows(
    intent: IntentLike,
    mutation_kind: str,
    details: Optional[dict] = None,
) -> bool:
    """Return True if intent semantically supports the irreversible mutation.

    mutation_kind:
      consume_item | move | damage | spend | transition | relationship | kill | permanent_alter
    """
    kind = (mutation_kind or '').strip().lower()
    details = details or {}

    if _is_look(intent):
        if kind in ('move', 'consume_item', 'damage', 'kill', 'spend', 'transition', 'permanent_alter'):
            return False

    if kind == 'consume_item':
        # Potion/provision only — never treat key / use_key as consume.
        blob = _blob(intent)
        matched = _matched_id(intent)
        if matched in ('use_key', 'item.use_key') or (
            'key' in blob and 'potion' not in blob and 'drink' not in blob and 'provision' not in blob
        ):
            return False
        item = str(details.get('item') or details.get('tool') or '').lower()
        if item and 'key' in item and 'potion' not in item:
            return False
        return _clearly_potion_or_drink(intent)

    if kind == 'move':
        return _allows_move(intent)

    if kind in ('damage', 'kill'):
        return _allows_attack(intent)

    if kind == 'spend':
        # Spending gold/provisions/luck requires an intent that mentions spend/pay/use resource.
        blob = _blob(intent)
        if any(tok in blob for tok in ('pay', 'spend', 'gold', 'buy', 'bribe', 'offer', 'provision', 'potion')):
            return True
        return _clearly_potion_or_drink(intent)

    if kind == 'transition':
        return _allows_move(intent) or str(
            _intent_get(intent, 'classification') or ''
        ).upper() == 'MATCH_AUTHORED_ACTION'

    if kind == 'relationship':
        cls = _action_class(intent)
        classification = str(_intent_get(intent, 'classification') or '').upper()
        if classification == 'SOCIAL_ACTION':
            return True
        return cls in (
            'SPEAK', 'SHOUT', 'GIVE', 'WARN', 'NEGOTIATE', 'SURRENDER',
            'THREATEN', 'ASK', 'REPLY',
        )

    if kind == 'permanent_alter':
        # Permanent alters require clear intentional effect, not perception/meta.
        classification = str(_intent_get(intent, 'classification') or '').upper()
        if classification in ('PERCEPTION_QUERY', 'META_INPUT', 'META_REQUEST', 'NO_ACTIONABLE_INTENT'):
            return False
        if _is_look(intent):
            return False
        effect = str(_intent_get(intent, 'intended_effect') or '').lower()
        if effect in ('', 'look', 'see', 'know', 'ask'):
            return bool(_allows_move(intent) or _allows_attack(intent) or _clearly_potion_or_drink(intent))
        return True

    # Unknown kind: refuse rather than silently allow irreversible mutation.
    return False
