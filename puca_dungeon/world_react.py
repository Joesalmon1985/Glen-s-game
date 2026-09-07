"""World reactions after a resolved player action (time, NPC opportunity, hazards)."""
from __future__ import annotations

from typing import Any, Optional, Union

from puca_dungeon import body_events, exposure, time_model
from puca_dungeon.content_loader import get_passage
from puca_dungeon.ff_rules import apply_stamina_loss
from puca_dungeon.models import Intent, WorldState

IntentLike = Union[Intent, dict]
ResolutionLike = Any

DEFAULT_OPPORTUNITY_DAMAGE = 2


def _intent_get(intent: IntentLike, key: str, default=None):
    if isinstance(intent, dict):
        return intent.get(key, default)
    return getattr(intent, key, default)


def _action_class(intent: IntentLike) -> str:
    return str(_intent_get(intent, 'action_class') or '').strip().upper()


def _matched_id(intent: IntentLike) -> str:
    return str(_intent_get(intent, 'matched_action_id') or '').strip().lower()


def _player_attacked_or_fled(intent: IntentLike, resolution: ResolutionLike) -> bool:
    cls = _action_class(intent)
    matched = _matched_id(intent)
    if cls in ('ATTACK', 'FIGHT', 'STRIKE', 'FLEE'):
        return True
    if matched in ('combat.attack', 'combat.flee'):
        return True
    effect = str(_intent_get(intent, 'intended_effect') or '').lower()
    if effect in ('harm', 'escape', 'flee'):
        return True
    affordances = []
    if hasattr(resolution, 'affordances_used'):
        affordances = list(getattr(resolution, 'affordances_used') or [])
    elif isinstance(resolution, dict):
        affordances = list(resolution.get('affordances_used') or [])
    if 'combat_attack' in affordances or 'combat_flee' in affordances:
        return True
    if getattr(resolution, 'combat_round', False) or (
        isinstance(resolution, dict) and resolution.get('combat_round')
    ):
        return True
    return False


def _advance_time_flag(resolution: ResolutionLike) -> bool:
    if hasattr(resolution, 'advance_time'):
        return bool(getattr(resolution, 'advance_time'))
    if isinstance(resolution, dict):
        return bool(resolution.get('advance_time', True))
    return True


def _ensure_list_attr(resolution: ResolutionLike, name: str) -> list:
    if isinstance(resolution, dict):
        val = resolution.get(name)
        if not isinstance(val, list):
            val = []
            resolution[name] = val
        return val
    val = getattr(resolution, name, None)
    if not isinstance(val, list):
        val = []
        try:
            setattr(resolution, name, val)
        except Exception:
            # Dataclass without the field: stash on __dict__ if possible.
            try:
                resolution.__dict__[name] = val
            except Exception:
                return []
    return val


def _as_intent(intent: IntentLike) -> Intent:
    if isinstance(intent, Intent):
        return intent
    data = dict(intent or {})
    return Intent(
        action_class=str(data.get('action_class') or 'OTHER'),
        target=data.get('target'),
        tool=data.get('tool'),
        method=data.get('method'),
        intended_effect=data.get('intended_effect'),
        manner=data.get('manner'),
        destination=data.get('destination'),
        turn_to=data.get('turn_to'),
        utterance=data.get('utterance'),
        sequence=list(data.get('sequence') or []),
        raw=dict(data.get('raw') or data),
        understood=bool(data.get('understood', True)),
        notes=str(data.get('notes') or ''),
        classification=str(data.get('classification') or 'GENERAL_WORLD_ACTION'),
        matched_action_id=data.get('matched_action_id'),
        confidence=data.get('confidence'),
        ambiguities=list(data.get('ambiguities') or []),
        needs_clarification=bool(data.get('needs_clarification', False)),
        query_focus=data.get('query_focus'),
    )


def _resolution_dict_for_time(resolution: ResolutionLike) -> dict:
    if isinstance(resolution, dict):
        return resolution
    if hasattr(resolution, 'to_dict'):
        try:
            return resolution.to_dict()
        except Exception:
            pass
    return {
        'advance_time': _advance_time_flag(resolution),
        'intent_understood': getattr(resolution, 'intent_understood', True),
        'combat_round': getattr(resolution, 'combat_round', False),
    }


def _enemy_opportunity_attack(
    world: WorldState,
    resolution: ResolutionLike,
) -> list[dict]:
    """Hostile actor strikes when the player spends the round on something else."""
    combat = world.combat
    if not combat.active or not world.sheet.alive:
        return []

    amount = DEFAULT_OPPORTUNITY_DAMAGE
    apply_stamina_loss(world.sheet, amount)
    enemy = combat.enemy_name or 'the enemy'
    events = body_events.combat_hit_player_facts(enemy, amount)
    body_event = body_events.stamina_loss_to_body_event(
        amount, source=f'opportunity:{enemy}', sheet=world.sheet,
    )
    body_events.apply_injury(world.sheet, {
        'site': body_event.get('site'),
        'severity': body_event.get('severity'),
        'pain': body_event.get('pain'),
        'bleeding': body_event.get('bleeding'),
        'locomotion': body_event.get('locomotion'),
        'source': enemy,
        'cause': 'opportunity_attack',
    })
    events.append(body_event)
    events.append({
        'kind': 'world_event',
        'type': 'enemy_opportunity_attack',
        'actor': enemy,
        'target': 'player',
        'note': 'enemy_acted_while_player_did_not_fight_or_flee',
    })

    damage_events = _ensure_list_attr(resolution, 'damage_events')
    damage_events.append({
        'source': 'enemy_opportunity',
        'amount': amount,
        'target': 'player',
    })

    if not world.sheet.alive:
        combat.active = False
        world.ending = 'death'
        world.victory = False
        events.append({
            'kind': 'world_event',
            'type': 'player_died',
            'cause': 'enemy_opportunity_attack',
            'actor': enemy,
        })

    # Mark situation dirty without rewriting the player's action as ATTACK.
    if hasattr(resolution, 'situation_changed'):
        resolution.situation_changed = True
    elif isinstance(resolution, dict):
        resolution['situation_changed'] = True
    if hasattr(resolution, 'image_dirty'):
        resolution.image_dirty = True
    elif isinstance(resolution, dict):
        resolution['image_dirty'] = True

    return events


def after_player_action(
    world: WorldState,
    intent: IntentLike,
    resolution: ResolutionLike,
    rng: Any = None,
) -> ResolutionLike:
    """Apply world-time advance, enemy opportunity, and passage hazards.

    Mutates ``resolution`` to include ``world_events`` (and structured facts).
    Does not rewrite the player's action into an attack.
    """
    del rng  # reserved for future contested reactions
    world_events = _ensure_list_attr(resolution, 'world_events')
    structured = _ensure_list_attr(resolution, 'structured_facts')
    intent_obj = _as_intent(intent)
    advance = _advance_time_flag(resolution)

    # 1) Hostile opportunity if combat is live and the player did not fight/flee.
    if (
        world.combat.active
        and advance
        and world.sheet.alive
        and not _player_attacked_or_fled(intent_obj, resolution)
    ):
        opp = _enemy_opportunity_attack(world, resolution)
        world_events.extend(opp)
        structured.extend(opp)

    # 2) Advance fictional world clock.
    if advance:
        cost = int(time_model.time_cost(intent_obj, _resolution_dict_for_time(resolution)))
        if cost > 0:
            world.world_time_seconds = int(world.world_time_seconds or 0) + cost
            world_events.append({
                'kind': 'world_event',
                'type': 'time_advanced',
                'seconds': cost,
                'world_time_seconds': world.world_time_seconds,
            })

    # 3) Passage hazards / exposure.
    try:
        passage = get_passage(world.passage_id)
    except Exception:
        passage = None
    if passage is not None:
        hazard_facts = exposure.resolve_hazard_triggers(
            world,
            passage,
            intent_obj,
            time_advanced=advance,
        )
        if hazard_facts:
            world_events.extend(hazard_facts)
            structured.extend(hazard_facts)
            # Apply body injuries implied by hazard body_events.
            for fact in hazard_facts:
                if isinstance(fact, dict) and fact.get('kind') == 'body_event':
                    body_events.apply_injury(world.sheet, fact)

    return resolution
