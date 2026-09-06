"""Bind intent references to current-world entity ids."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from puca_dungeon.models import Intent, WorldState, EncounterId


@dataclass
class Grounding:
    bindings: dict = field(default_factory=dict)
    ambiguous: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    notes: str = ''
    grounded: Optional[bool] = None  # None = not yet judged; False = failed/ambiguous; True = ok

    def to_dict(self) -> dict:
        return {
            'bindings': dict(self.bindings),
            'ambiguous': list(self.ambiguous),
            'failed': list(self.failed),
            'notes': self.notes,
            'grounded': self.grounded,
            'candidates': list(self.bindings.get('target_candidates') or []),
        }


def ground_intent(intent: Intent, world: WorldState) -> Grounding:
    g = Grounding()
    _bind_target(intent, world, g)
    _bind_tool(intent, world, g)
    if intent.destination:
        dest = intent.destination.lower()
        if dest in ('passage_ahead', 'ahead', 'forward', 'onward', 'deeper', 'tunnel'):
            g.bindings['destination'] = 'passage_ahead'
        elif dest in ('passage_behind', 'back', 'retreat', 'entrance', 'behind'):
            g.bindings['destination'] = 'passage_behind'
        elif dest in ('west', 'passage_west'):
            g.bindings['destination'] = 'passage_west'
        elif dest in ('right', 'passage_right'):
            g.bindings['destination'] = 'passage_right'
        else:
            g.bindings['destination'] = dest
    if intent.target and intent.target.lower() in ('challenger', 'barbarian', 'npc', 'pursuer', 'grimnak'):
        if world.pursuer.state in ('present', 'hostile', 'allied'):
            g.bindings['target'] = 'challenger'
        elif intent.action_class in ('ATTACK', 'WARN', 'GIVE', 'NEGOTIATE', 'SURRENDER'):
            g.failed.append('challenger_not_present')

    # Embodied non-destructive actions may target "a box" generically without picking which
    cls = intent.action_class.upper()
    if g.ambiguous and cls in ('LICK', 'TOUCH', 'TASTE') and 'box' in (intent.target or '').lower():
        g.ambiguous.clear()
        g.bindings.pop('target_candidates', None)
        g.bindings['target'] = 'boxes'
        g.bindings['target_ref'] = intent.target

    if intent.needs_clarification and not g.bindings.get('target') and cls in (
        'BREAK', 'STRIKE', 'SHAKE', 'USE', 'UNLOCK', 'PICK_LOCK', 'MANIPULATE',
    ):
        if not g.ambiguous and world.encounter == EncounterId.WALK_BOXES.value:
            candidates = [b.id for b in _alive_boxes(world)]
            if len(candidates) > 1:
                g.ambiguous.append({
                    'ref': intent.target or 'box',
                    'candidates': candidates,
                    'prompt': 'Which box?',
                })
                g.bindings['target_candidates'] = candidates

    if g.ambiguous or g.failed:
        g.grounded = False
    elif intent.needs_clarification and not g.bindings.get('target') and _target_required(intent):
        g.grounded = False
    else:
        # Grounded if required refs resolved or no entity refs needed
        if _target_required(intent) and 'target' not in g.bindings and 'destination' not in g.bindings:
            if intent.classification in ('PERCEPTION_QUERY', 'META_REQUEST', 'UNINTERPRETABLE', 'SILLY_BUT_VALID'):
                g.grounded = True  # no entity required
            elif intent.action_class in (
                'WAIT', 'SIT', 'LOOK', 'SHOUT', 'SPEAK', 'HIDE', 'BODILY', 'CARTWHEEL', 'TURN',
                'PERCEIVE', 'META', 'IMPOSSIBLE',
            ):
                g.grounded = True
            else:
                g.grounded = 'target' in g.bindings or intent.action_class in ('FLEE', 'MOVE')
        else:
            g.grounded = True
    return g


def _target_required(intent: Intent) -> bool:
    cls = intent.action_class.upper()
    if intent.classification in ('PERCEPTION_QUERY', 'META_REQUEST', 'UNINTERPRETABLE'):
        return False
    if cls in (
        'WAIT', 'SIT', 'LOOK', 'SHOUT', 'SPEAK', 'HIDE', 'FLEE', 'MOVE', 'BODILY',
        'CARTWHEEL', 'TURN', 'PERCEIVE', 'META', 'IMPOSSIBLE', 'SURRENDER',
    ):
        return False
    return bool(intent.target) or cls in (
        'USE', 'UNLOCK', 'BREAK', 'STRIKE', 'PICK_LOCK', 'DISABLE', 'LICK', 'SHAKE',
        'SEARCH', 'INSPECT', 'MANIPULATE', 'ATTACK', 'WARN', 'GIVE', 'NEGOTIATE',
    )


def _bind_tool(intent: Intent, world: WorldState, g: Grounding) -> None:
    tool = (intent.tool or '').lower().strip()
    if not tool:
        return
    # Do not invent weapons from empty tool — only bind what was stated
    if 'key' in tool or tool == 'supplied_key':
        if 'trial_key_player' in world.player.inventory:
            g.bindings['tool'] = 'trial_key_player'
        else:
            g.failed.append('tool:trial_key_player')
    elif 'sword' in tool or 'pommel' in tool:
        g.bindings['tool'] = 'sword'
    elif 'lockpick' in tool or tool == 'lockpicks':
        g.bindings['tool'] = 'lockpicks'
    elif tool in ('fist', 'hands', 'hand'):
        g.bindings['tool'] = 'fist'
    else:
        g.bindings['tool'] = tool


def _alive_boxes(world: WorldState) -> list:
    return [b for b in world.boxes.values() if not b.destroyed]


def _bind_target(intent: Intent, world: WorldState, g: Grounding) -> None:
    target = (intent.target or '').lower().strip()
    if not target:
        return

    # Explicit named / player box
    if _is_player_box_ref(target):
        g.bindings['target'] = 'box_player'
        g.bindings['target_ref'] = target
        return

    if target in ('other_box', 'another_box', 'wrong_box') or _is_other_box_ref(target):
        other = _first_other_box(world)
        if other:
            g.bindings['target'] = other
            g.bindings['target_ref'] = target
        else:
            g.failed.append('other_box')
        return

    # Plural / group — bind as boxes group (search/inspect)
    if target in ('boxes', 'the_boxes', 'locked_boxes', 'all_boxes'):
        g.bindings['target'] = 'boxes'
        g.bindings['target_ref'] = target
        return

    # Singular ambiguous box references — do NOT silently pick named box
    ambiguous_box_refs = {
        'box', 'the box', 'a box', 'one box', 'any box', 'some box', 'a locked box',
        'the_box', 'a_box', 'one_box', 'any_box', 'some_box',
        'one of the boxes', 'one of the box', 'one of boxes',
    }
    if target in ambiguous_box_refs or (
            target.startswith('the ') and target.endswith(' box') and 'name' not in target and 'my' not in target):
        candidates = [b.id for b in _alive_boxes(world)]
        if len(candidates) > 1:
            g.ambiguous.append({
                'ref': target,
                'candidates': candidates,
                'prompt': 'Which box?',
            })
            g.bindings['target_candidates'] = candidates
            g.bindings['target_ref'] = target
            return
        if len(candidates) == 1:
            g.bindings['target'] = candidates[0]
            g.bindings['target_ref'] = target
            return

    if 'one of' in target and 'box' in target:
        candidates = [b.id for b in _alive_boxes(world)]
        g.ambiguous.append({
            'ref': target,
            'candidates': candidates,
            'prompt': 'Which box?',
        })
        g.bindings['target_candidates'] = candidates
        g.bindings['target_ref'] = target
        return

    if target in ('trap', 'dart_trap'):
        for box in world.boxes.values():
            if box.trap_discovered and not box.trap_disabled:
                g.bindings['target'] = box.id
                g.bindings['target_ref'] = 'trap'
                return
        g.bindings['target'] = 'boxes'
        g.bindings['target_ref'] = 'trap'
        return

    if target in ('stone_wall', 'wall'):
        g.bindings['target'] = 'stone_wall'
        return
    if target in ('clue_note', 'note', 'clue'):
        g.bindings['target'] = 'clue_note'
        return
    if target in ('junction', 'arrow', 'tracks', 'dusty_floor', 'floor'):
        g.bindings['target'] = 'junction'
        return
    if target == 'sword':
        g.bindings['target'] = 'sword'
        return
    if target in ('challenger', 'grimnak', 'barbarian'):
        g.bindings['target'] = 'challenger'
        return

    # Match box labels
    for box in world.boxes.values():
        if target in box.label.lower() or target == box.id:
            g.bindings['target'] = box.id
            return

    # Soft match: contains "box" with player name
    pname = world.player.name.lower()
    if pname and pname in target and 'box' in target:
        g.bindings['target'] = 'box_player'
        g.bindings['target_ref'] = target
        return

    g.failed.append(f'target:{target}')
    g.bindings['target_ref'] = target


def _is_player_box_ref(target: str) -> bool:
    t = target.lower()
    return t in (
        'named_box', 'my_box', 'player_box', 'box_player', 'my box', 'the named box',
        'box with my name', 'the box with my name', 'the box with my name on it',
        'box with my name on it', 'mine',
    ) or 'my name' in t or t.startswith('my ') and 'box' in t


def _is_other_box_ref(target: str) -> bool:
    t = target.lower()
    return any(x in t for x in ('another', 'other box', 'different box', 'someone else'))


def _first_other_box(world: WorldState) -> Optional[str]:
    for box_id, box in world.boxes.items():
        if not box.is_player_box and not box.destroyed:
            return box_id
    return None
