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

    def to_dict(self) -> dict:
        return {
            'bindings': dict(self.bindings),
            'ambiguous': list(self.ambiguous),
            'failed': list(self.failed),
            'notes': self.notes,
        }


def ground_intent(intent: Intent, world: WorldState) -> Grounding:
    g = Grounding()
    _bind_target(intent, world, g)
    _bind_tool(intent, world, g)
    if intent.destination:
        dest = intent.destination.lower()
        if dest in ('passage_ahead', 'ahead', 'forward', 'onward', 'deeper', 'tunnel'):
            g.bindings['destination'] = 'passage_ahead'
        elif dest in ('passage_behind', 'back', 'retreat'):
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
    return g


def _bind_tool(intent: Intent, world: WorldState, g: Grounding) -> None:
    tool = (intent.tool or '').lower()
    if not tool:
        return
    if 'key' in tool or tool == 'supplied_key':
        if 'trial_key_player' in world.player.inventory:
            g.bindings['tool'] = 'trial_key_player'
        else:
            g.failed.append('tool:trial_key_player')
    elif 'sword' in tool or 'pommel' in tool:
        g.bindings['tool'] = 'sword'
    elif 'lockpick' in tool or tool == 'lockpicks':
        g.bindings['tool'] = 'lockpicks'  # assumed thieves' tools available for POC
    elif tool in ('fist', 'hands', 'hand'):
        g.bindings['tool'] = 'fist'
    else:
        g.bindings['tool'] = tool


def _bind_target(intent: Intent, world: WorldState, g: Grounding) -> None:
    target = (intent.target or '').lower().strip()
    if not target:
        return
    if target in ('named_box', 'my_box', 'player_box', 'box_player'):
        g.bindings['target'] = 'box_player'
        g.bindings['target_ref'] = target
        return
    if target in ('other_box', 'another_box', 'wrong_box'):
        other = _first_other_box(world)
        if other:
            g.bindings['target'] = other
            g.bindings['target_ref'] = target
        else:
            g.failed.append('other_box')
        return
    if target in ('boxes', 'box', 'the_boxes', 'locked_boxes'):
        # Prefer named if singular "box" with my key context handled elsewhere
        if target == 'box' and intent.tool and 'key' in (intent.tool or '').lower():
            g.bindings['target'] = 'box_player'
        else:
            g.bindings['target'] = 'boxes'
        g.bindings['target_ref'] = target
        return
    if target in ('trap', 'dart_trap'):
        # Ground to a discovered trap if any, else boxes generally
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
    if target in ('junction', 'arrow', 'tracks'):
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
    g.failed.append(f'target:{target}')
    g.bindings['target_ref'] = target


def _first_other_box(world: WorldState) -> Optional[str]:
    for box_id, box in world.boxes.items():
        if not box.is_player_box and not box.destroyed:
            return box_id
    return None
