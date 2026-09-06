"""Encounter-1 POC pressure: fictional-time pursuer, not a verb blacklist."""
from __future__ import annotations

from puca_dungeon.models import EncounterId, Intent, PursuerState, WorldState
from puca_dungeon.resolve import Resolution
from puca_dungeon.time_model import time_cost


def action_is_productive(intent: Intent, resolution: Resolution, world: WorldState) -> bool:
    """
    Productive if the action attempted a plausible state interaction, consumed
    meaningful effort, addressed an active threat, or changed the situation.
    Failed legitimate attempts still count as productive.
    """
    if resolution.situation_changed or resolution.addressed_threat:
        return True
    if resolution.meaningful_effort or resolution.interacted:
        if resolution.affordances_used or resolution.checks:
            return True
        if intent.action_class.upper() in {
            'SEARCH', 'INSPECT', 'LOOK', 'USE', 'UNLOCK', 'PICK_LOCK', 'DISABLE',
            'BREAK', 'STRIKE', 'MOVE', 'FLEE', 'ATTACK', 'WARN', 'GIVE', 'NEGOTIATE',
            'SURRENDER', 'HIDE', 'MANIPULATE',
        }:
            return True
        if intent.action_class.upper() in {'LICK', 'TOUCH'}:
            return True
    return False


def apply_time_and_pressure(world: WorldState, intent: Intent, resolution: Resolution) -> dict:
    """Advance fictional time and pursuer stages. Returns debug pressure info."""
    info = {
        'world_time_delta': 0, 'stall_delta': 0,
        'pursuer_before': world.pursuer.state,
        'pursuer_after': world.pursuer.state,
        'events': [],
        'productive': False,
    }
    if world.encounter != EncounterId.WALK_BOXES.value:
        delta = time_cost(intent, resolution.to_dict())
        world.world_time_seconds += delta
        info['world_time_delta'] = delta
        info['pursuer_after'] = world.pursuer.state
        return info

    delta = time_cost(intent, resolution.to_dict())
    world.world_time_seconds += delta
    info['world_time_delta'] = delta

    productive = action_is_productive(intent, resolution, world)
    info['productive'] = productive
    if not productive:
        world.stall_time_seconds += delta
        info['stall_delta'] = delta

    stall = world.stall_time_seconds
    p = world.pursuer
    before = p.state

    if p.state == PursuerState.ABSENT.value and stall >= world.pursuer_trigger_at:
        p.state = PursuerState.APPROACHING.value
        info['events'].append('distant_footsteps')
        resolution.facts.append('Far behind you, faint footsteps echo in the entrance tunnel.')
        resolution.image_dirty = True
    elif p.state == PursuerState.APPROACHING.value and stall >= world.pursuer_close_at:
        p.state = PursuerState.CLOSE.value
        info['events'].append('footsteps_close')
        resolution.facts.append('The footsteps are closer now — leather, iron, heavy breath.')
        resolution.image_dirty = True
    elif p.state == PursuerState.CLOSE.value and stall >= world.pursuer_arrive_at:
        p.state = PursuerState.PRESENT.value
        p.location = EncounterId.WALK_BOXES.value
        p.disposition = 'aggressive'
        if 'challenger' not in world.visible_entities:
            world.visible_entities.append('challenger')
        info['events'].append('challenger_arrives')
        resolution.facts.append(
            f'A scarred {p.kind}, {p.name}, strides into the chamber — one of the contestants who entered before you. '
            'He levels a notched axe. "That table\'s mine if you dawdle."')
        resolution.situation_changed = True
        resolution.image_dirty = True
    elif p.state == PursuerState.PRESENT.value and stall >= world.pursuer_escalate_at and not productive:
        p.state = PursuerState.HOSTILE.value
        p.disposition = 'hostile'
        info['events'].append('challenger_escalates')
        resolution.facts.append(
            f'{p.name} snarls and raises his weapon. "Enough waiting. Die, then."')
        resolution.image_dirty = True
        world.flags['pursuer_will_attack'] = True

    info['pursuer_after'] = p.state
    if before != p.state:
        info['events'].append(f'pursuer_state:{before}->{p.state}')
    return info


def maybe_hostile_attack(world: WorldState, intent: Intent, resolution: Resolution, rng) -> None:
    """If pursuer is hostile and player did not address the threat, swing."""
    if world.pursuer.state != PursuerState.HOSTILE.value:
        return
    if resolution.addressed_threat or intent.action_class.upper() in {
        'ATTACK', 'FLEE', 'HIDE', 'SURRENDER', 'WARN', 'GIVE', 'NEGOTIATE', 'MOVE',
    }:
        return
    from puca_dungeon.resolve import _combat_round
    _combat_round(world, intent, rng, resolution, player_initiates=False)
