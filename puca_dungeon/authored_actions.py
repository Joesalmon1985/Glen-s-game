"""Public-safe authored action descriptors for the interpreter.

These are internal semantic targets, not player-facing menus.
They must not reveal undiscovered secrets (hidden traps, pursuer timers, etc.).
"""
from __future__ import annotations

from puca_dungeon.models import EncounterId, WorldState


def build_authored_actions(world: WorldState) -> list[dict]:
    """Return currently resolvable authored interactions visible from public state."""
    actions: list[dict] = []

    if world.encounter == EncounterId.WALK_BOXES.value:
        actions.extend(_box_chamber_actions(world))
    elif world.encounter == EncounterId.JUNCTION.value:
        actions.extend(_junction_actions(world))

    if world.pursuer.state in ('present', 'hostile', 'allied'):
        actions.extend(_challenger_actions(world))
    elif world.pursuer.state in ('approaching', 'close'):
        actions.append({
            'id': 'react.footsteps',
            'description': 'React to approaching footsteps heard behind (flee, hide, prepare).',
            'entities': ['passage_behind'],
            'tools': [],
            'operation': 'react_to_pursuit',
        })

    # Compact payload for the LLM (ids + short description + operation)
    return [
        {
            'id': a['id'],
            'description': a['description'],
            'operation': a.get('operation'),
            'entities': a.get('entities') or [],
            'tools': a.get('tools') or [],
        }
        for a in actions
    ]

def _box_chamber_actions(world: WorldState) -> list[dict]:
    player_box = world.boxes.get('box_player')
    has_key = 'trial_key_player' in world.player.inventory
    any_trap_visible = any(b.trap_discovered for b in world.boxes.values())

    actions = [
        {
            'id': 'box.unlock.player',
            'description': 'Use the supplied iron key on the box that bears the player name.',
            'entities': ['box_player', player_box.label if player_box else "player's named box"],
            'tools': ['trial_key_player'] if has_key else [],
            'operation': 'unlock_with_key',
            'requires_tool': 'trial_key_player',
        },
        {
            'id': 'box.unlock.other',
            'description': 'Use the supplied iron key on a box that is not the named player box.',
            'entities': ['other_box'],
            'tools': ['trial_key_player'] if has_key else [],
            'operation': 'unlock_with_key',
            'requires_tool': 'trial_key_player',
        },
        {
            'id': 'box.inspect',
            'description': 'Inspect, examine, or look closely at the boxes, locks, or table.',
            'entities': ['boxes', 'stone_table'],
            'tools': [],
            'operation': 'inspect',
        },
        {
            'id': 'box.search',
            'description': 'Carefully search the boxes or locks for hidden mechanisms or information.',
            'entities': ['boxes'],
            'tools': [],
            'operation': 'search',
        },
        {
            'id': 'box.lock.pick',
            'description': 'Pick the lock on a box without using the supplied key.',
            'entities': ['box'],
            'tools': ['lockpicks'],
            'operation': 'pick_lock',
        },
        {
            'id': 'box.damage',
            'description': 'Hit, smash, break, or otherwise damage a box to force it open.',
            'entities': ['box'],
            'tools': ['sword', 'fist'],
            'operation': 'damage_box',
        },
        {
            'id': 'move.passage_ahead',
            'description': 'Leave the table and continue deeper into the dungeon passage.',
            'entities': ['passage_ahead'],
            'tools': [],
            'operation': 'move',
        },
        {
            'id': 'move.passage_behind',
            'description': 'Turn back toward the entrance / way you came.',
            'entities': ['passage_behind'],
            'tools': [],
            'operation': 'move',
        },
    ]

    if any_trap_visible:
        actions.append({
            'id': 'box.trap.disable',
            'description': 'Disable a trap mechanism already discovered on a box.',
            'entities': ['trap', 'box'],
            'tools': [],
            'operation': 'disable_trap',
        })

    return actions


def _junction_actions(world: WorldState) -> list[dict]:
    floor_entity = 'floor_tracks' if world.junction_inspected else 'dusty_floor'
    return [
        {
            'id': 'junction.inspect',
            'description': f'Inspect the junction, painted arrow, or {floor_entity.replace("_", " ")}.',
            'entities': ['junction', 'white_arrow_west', floor_entity],
            'tools': [],
            'operation': 'inspect',
        },
        {
            'id': 'move.passage_west',
            'description': 'Take the west passage indicated by the painted arrow.',
            'entities': ['passage_west'],
            'tools': [],
            'operation': 'move',
        },
        {
            'id': 'move.passage_right',
            'description': 'Take the right-hand passage.',
            'entities': ['passage_right'],
            'tools': [],
            'operation': 'move',
        },
    ]


def _challenger_actions(world: WorldState) -> list[dict]:
    name = world.pursuer.name
    return [
        {
            'id': 'challenger.attack',
            'description': f'Attack or fight the present challenger ({name}).',
            'entities': ['challenger'],
            'tools': ['sword'],
            'operation': 'attack',
        },
        {
            'id': 'challenger.warn',
            'description': f'Warn {name} about danger at the boxes.',
            'entities': ['challenger'],
            'tools': [],
            'operation': 'warn',
        },
        {
            'id': 'challenger.give_key',
            'description': f'Offer or give the iron key to {name}.',
            'entities': ['challenger'],
            'tools': ['trial_key_player'],
            'operation': 'give',
        },
        {
            'id': 'challenger.negotiate',
            'description': f'Talk, negotiate, or propose alliance with {name}.',
            'entities': ['challenger'],
            'tools': [],
            'operation': 'negotiate',
        },
        {
            'id': 'challenger.hide',
            'description': 'Hide from the challenger.',
            'entities': ['challenger'],
            'tools': [],
            'operation': 'hide',
        },
        {
            'id': 'challenger.flee',
            'description': 'Flee from the challenger down the passage.',
            'entities': ['challenger', 'passage_ahead'],
            'tools': [],
            'operation': 'flee',
        },
    ]


# Map authored action ids onto canonical intent fields for Python resolve.
AUTHORED_TO_INTENT = {
    'box.unlock.player': {
        'action_class': 'USE', 'target': 'named_box', 'tool': 'supplied_key',
        'method': 'unlock', 'intended_effect': 'open',
    },
    'box.unlock.other': {
        'action_class': 'USE', 'target': 'other_box', 'tool': 'supplied_key',
        'method': 'unlock', 'intended_effect': 'open',
    },
    'box.inspect': {
        'action_class': 'INSPECT', 'target': 'boxes', 'method': 'look',
        'intended_effect': 'inspect',
    },
    'box.search': {
        'action_class': 'SEARCH', 'target': 'boxes', 'method': 'careful',
        'intended_effect': 'discover_information',
    },
    'box.trap.disable': {
        'action_class': 'DISABLE', 'target': 'trap', 'method': 'disable_device',
        'intended_effect': 'safe_lock',
    },
    'box.lock.pick': {
        'action_class': 'PICK_LOCK', 'target': 'box', 'tool': 'lockpicks',
        'method': 'pick', 'intended_effect': 'open',
    },
    'box.damage': {
        'action_class': 'BREAK', 'target': 'box', 'method': 'force',
        'intended_effect': 'open_force',
    },
    'move.passage_ahead': {
        'action_class': 'MOVE', 'destination': 'passage_ahead',
        'intended_effect': 'leave_area', 'manner': 'onward',
    },
    'move.passage_behind': {
        'action_class': 'MOVE', 'destination': 'passage_behind',
        'intended_effect': 'retreat',
    },
    'move.passage_west': {
        'action_class': 'MOVE', 'destination': 'passage_west', 'intended_effect': 'leave_area',
    },
    'move.passage_right': {
        'action_class': 'MOVE', 'destination': 'passage_right', 'intended_effect': 'leave_area',
    },
    'junction.inspect': {
        'action_class': 'INSPECT', 'target': 'junction', 'intended_effect': 'inspect',
    },
    'challenger.attack': {
        'action_class': 'ATTACK', 'target': 'challenger', 'tool': 'sword', 'intended_effect': 'harm',
    },
    'challenger.warn': {
        'action_class': 'WARN', 'target': 'challenger', 'intended_effect': 'share_danger',
    },
    'challenger.give_key': {
        'action_class': 'GIVE', 'target': 'challenger', 'tool': 'supplied_key', 'intended_effect': 'bribe',
    },
    'challenger.negotiate': {
        'action_class': 'NEGOTIATE', 'target': 'challenger', 'intended_effect': 'cooperate',
    },
    'challenger.hide': {
        'action_class': 'HIDE', 'intended_effect': 'avoid_notice',
    },
    'challenger.flee': {
        'action_class': 'FLEE', 'destination': 'passage_ahead', 'intended_effect': 'escape',
    },
    'react.footsteps': {
        'action_class': 'FLEE', 'destination': 'passage_ahead', 'intended_effect': 'escape',
    },
}


def apply_authored_match(intent_fields: dict, matched_action_id: str | None) -> dict:
    """Overlay canonical fields when an authored action matched."""
    if not matched_action_id:
        return intent_fields
    canon = AUTHORED_TO_INTENT.get(matched_action_id)
    if not canon:
        return intent_fields
    merged = dict(intent_fields)
    for key, value in canon.items():
        # Prefer canonical action_class/method; keep LLM target_ref if more specific
        if key == 'target' and merged.get('target') and _is_specific_box_ref(merged['target']):
            continue
        if key == 'tool' and merged.get('tool'):
            continue
        if merged.get(key) in (None, '', 'unspecified'):
            merged[key] = value
        elif key in ('action_class', 'method', 'intended_effect', 'destination', 'manner'):
            merged[key] = value
    if not merged.get('action_class'):
        merged['action_class'] = canon.get('action_class', 'MANIPULATE')
    return merged


def _is_specific_box_ref(target: str) -> bool:
    t = target.lower()
    return any(x in t for x in (
        'named', 'my box', 'my name', 'player', 'box_player',
        'ashen', 'bram', 'cora', 'drek', 'elira', 'other', 'another',
    ))
