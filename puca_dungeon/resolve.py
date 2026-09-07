"""Python-owned resolution for the Fighting Fantasy passage graph."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

from puca_dungeon import body_events, discourse, fidelity, time_model
from puca_dungeon.content_loader import get_passage
from puca_dungeon.ff_rules import (
    apply_stamina_loss,
    combat_round,
    drink_potion,
    eat_provision,
    test_luck,
    test_skill,
)
from puca_dungeon.ground import Grounding
from puca_dungeon.models import CombatState, Intent, WorldState
from puca_dungeon.rng import GameRNG

PassageLike = Union[dict, Any]


@dataclass
class Resolution:
    intent_understood: bool = True
    grounded: Optional[bool] = None
    feasible: Optional[bool] = None
    success: Optional[bool] = None
    facts: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    damage_events: list = field(default_factory=list)
    state_transitions: list = field(default_factory=list)
    rejection_reason: str = ''
    affordances_used: list = field(default_factory=list)
    interacted: bool = False
    meaningful_effort: bool = False
    addressed_threat: bool = False
    situation_changed: bool = False
    combat_round: bool = False
    image_dirty: bool = False
    needs_clarification: bool = False
    clarification_prompt: str = ''
    advance_time: bool = True
    guidance_delta: int = 0
    productive_for_guidance: bool = False
    passage_entered: Optional[int] = None
    show_passage_text: bool = False
    # Reality-repair fields
    attempted: bool = False
    intended_effect_achieved: bool = False
    state_changed: bool = False
    time_cost: int = 0
    none_reason: str = ''
    requested_entity: Optional[str] = None
    structured_facts: list = field(default_factory=list)
    world_events: list = field(default_factory=list)
    # Intention vs enactment (narrator dual-truth)
    enactment: str = 'direct'  # direct | compromised | aborted | inverted
    wanted_action: dict = field(default_factory=dict)
    actual_action: dict = field(default_factory=dict)
    enactment_cause: str = ''

    def to_dict(self) -> dict:
        return {
            'intent_understood': self.intent_understood,
            'grounded': self.grounded,
            'feasible': self.feasible,
            'success': self.success,
            'facts': list(self.facts),
            'checks': list(self.checks),
            'damage_events': list(self.damage_events),
            'state_transitions': list(self.state_transitions),
            'rejection_reason': self.rejection_reason,
            'affordances_used': list(self.affordances_used),
            'interacted': self.interacted,
            'meaningful_effort': self.meaningful_effort,
            'addressed_threat': self.addressed_threat,
            'situation_changed': self.situation_changed,
            'combat_round': self.combat_round,
            'image_dirty': self.image_dirty,
            'needs_clarification': self.needs_clarification,
            'clarification_prompt': self.clarification_prompt,
            'advance_time': self.advance_time,
            'guidance_delta': self.guidance_delta,
            'productive_for_guidance': self.productive_for_guidance,
            'passage_entered': self.passage_entered,
            'show_passage_text': self.show_passage_text,
            'attempted': self.attempted,
            'intended_effect_achieved': self.intended_effect_achieved,
            'state_changed': self.state_changed,
            'time_cost': self.time_cost,
            'none_reason': self.none_reason,
            'requested_entity': self.requested_entity,
            'structured_facts': list(self.structured_facts),
            'world_events': list(self.world_events),
            'enactment': self.enactment,
            'wanted_action': dict(self.wanted_action or {}),
            'actual_action': dict(self.actual_action or {}),
            'enactment_cause': self.enactment_cause,
        }


def _passage_field(passage: PassageLike, key: str, default=None):
    if isinstance(passage, dict):
        return passage.get(key, default)
    return getattr(passage, key, default)


def _find_choice(passage: PassageLike, action_id: Optional[str], turn_to: Optional[int]) -> Optional[dict]:
    choices = _passage_field(passage, 'choices') or []
    if action_id:
        for choice in choices:
            if isinstance(choice, dict) and str(choice.get('id') or '') == str(action_id):
                return choice
    if turn_to is not None:
        for choice in choices:
            if isinstance(choice, dict) and choice.get('to') == turn_to:
                return choice
    return None


def _sheet_has_item(sheet, item: str) -> bool:
    item_l = (item or '').lower()
    for owned in sheet.inventory or []:
        name = owned.get('name') if isinstance(owned, dict) else owned
        if str(name).lower() == item_l or item_l in str(name).lower():
            return True
    if item_l in ('gold', 'gold_pieces') and int(sheet.gold or 0) > 0:
        return True
    if item_l in ('provision', 'provisions') and int(sheet.provisions or 0) > 0:
        return True
    if item_l == 'potion' and sheet.potion and not sheet.potion_used:
        return True
    if item_l in ('key', 'keys', 'iron_key'):
        for owned in sheet.inventory or []:
            name = str(owned.get('name') if isinstance(owned, dict) else owned).lower()
            if 'key' in name:
                return True
    return False


def _add_structured(res: Resolution, fact: dict) -> None:
    if isinstance(fact, dict):
        res.structured_facts.append(fact)


def _mark_noop_attempt(res: Resolution, *, understood: bool = True, grounded: bool = True) -> None:
    """Attempt happened; intended effect and state did not change."""
    res.intent_understood = understood
    res.grounded = grounded
    res.feasible = True
    res.success = False
    res.attempted = True
    res.intended_effect_achieved = False
    res.state_changed = False
    res.interacted = True


def _check_choice_conditions(
    world: WorldState,
    choice: dict,
    rng: GameRNG,
    res: Resolution,
) -> tuple[bool, Optional[int]]:
    """Return (ok, override_turn_to). Internal checks keep rolls; facts stay diegetic."""
    conditions = choice.get('conditions') or []
    if isinstance(conditions, dict):
        conditions = [conditions]
    turn_to = choice.get('to')
    for cond in conditions:
        if not isinstance(cond, dict):
            continue
        op = str(cond.get('op') or cond.get('type') or '').lower()
        if op in ('has_item', 'item'):
            item = cond.get('item') or cond.get('id') or ''
            if not _sheet_has_item(world.sheet, str(item)):
                res.facts.append(f'You do not have {item or "what you need"}.')
                res.rejection_reason = 'missing_item'
                res.none_reason = 'missing_item'
                return False, None
        elif op in ('flag', 'has_flag', 'set_flag'):
            flag = cond.get('flag') or cond.get('id') or ''
            expected = cond.get('value', True)
            actual = world.sheet.flags.get(flag)
            if actual != expected and not (expected is True and bool(actual)):
                res.facts.append('That path is not open to you yet.')
                res.rejection_reason = 'flag_gate'
                res.none_reason = 'flag_gate'
                return False, None
        elif op in ('luck_test', 'test_luck'):
            lucky, roll, new_luck = test_luck(world.sheet, rng)
            res.checks.append({
                'label': 'Test Luck',
                'roll': roll,
                'luck': new_luck + 1,
                'success': lucky,
            })
            res.facts.append(
                'Fortune smiles on you.' if lucky else 'Fortune turns against you.'
            )
            _add_structured(res, {
                'kind': 'world_event',
                'type': 'fortune_test',
                'success': lucky,
            })
            if lucky:
                turn_to = cond.get('success_to', choice.get('to_success', turn_to))
            else:
                fail_to = cond.get('fail_to', choice.get('to_fail') or choice.get('fail_to'))
                if fail_to is None:
                    res.facts.append('Fortune does not favour that choice.')
                    res.rejection_reason = 'luck_failed'
                    return False, None
                turn_to = fail_to
        elif op in ('skill_test', 'test_skill'):
            ok, roll = test_skill(world.sheet, rng)
            res.checks.append({
                'label': 'Test Skill',
                'roll': roll,
                'skill': world.sheet.skill,
                'success': ok,
            })
            res.facts.append(
                'Your training holds.' if ok else 'Your training fails you here.'
            )
            _add_structured(res, {
                'kind': 'world_event',
                'type': 'ability_test',
                'success': ok,
            })
            if ok:
                turn_to = cond.get('success_to', choice.get('to_success', turn_to))
            else:
                fail_to = cond.get('fail_to', choice.get('to_fail') or choice.get('fail_to'))
                if fail_to is None:
                    res.facts.append('You cannot force that attempt through.')
                    res.rejection_reason = 'skill_failed'
                    return False, None
                turn_to = fail_to
    return True, turn_to


def _apply_effect(world: WorldState, effect: dict, res: Resolution) -> None:
    if not isinstance(effect, dict):
        return
    op = str(effect.get('op') or effect.get('type') or '').lower()
    sheet = world.sheet

    if op == 'add_gold':
        amount = int(effect.get('amount', 0) or 0)
        sheet.gold = int(sheet.gold or 0) + amount
        res.state_transitions.append(f'gold+={amount}')
        res.facts.append(f'You gain {amount} gold piece(s).')
        res.state_changed = True
    elif op == 'add_item':
        item = effect.get('item') or effect.get('id')
        if item and item not in sheet.inventory:
            sheet.inventory.append(item)
            res.state_transitions.append(f'inventory+={item}')
            res.facts.append(f'You take the {str(item).replace("_", " ")}.')
            res.state_changed = True
    elif op == 'remove_item':
        item = effect.get('item') or effect.get('id')
        if item in sheet.inventory:
            sheet.inventory.remove(item)
            res.state_transitions.append(f'inventory-={item}')
            res.state_changed = True
    elif op == 'set_flag':
        flag = effect.get('flag') or effect.get('id')
        if flag:
            value = effect.get('value', True)
            sheet.flags[flag] = value
            res.state_transitions.append(f'flag.{flag}={value!r}')
            res.state_changed = True
    elif op == 'add_knowledge':
        fact = effect.get('fact') or effect.get('id') or effect.get('knowledge')
        if fact and fact not in sheet.knowledge:
            sheet.knowledge.append(fact)
            res.state_transitions.append(f'knowledge+={fact}')
            res.state_changed = True
    elif op == 'lose_stamina':
        amount = int(effect.get('amount', 0) or 0)
        apply_stamina_loss(sheet, amount)
        body = body_events.stamina_loss_to_body_event(amount, 'passage', sheet)
        body_events.apply_injury(sheet, body)
        res.damage_events.append({'source': 'passage', 'amount': amount})
        res.state_transitions.append(f'stamina-={amount}')
        res.structured_facts.extend(body_events.combat_hit_player_facts('the dungeon', amount))
        for line in body_events.qualitative_body_summary(sheet)[-2:]:
            res.facts.append(line)
        res.state_changed = True
    elif op == 'gain_stamina':
        amount = int(effect.get('amount', 0) or 0)
        sheet.stamina = min(int(sheet.stamina_initial or 0), int(sheet.stamina or 0) + amount)
        if sheet.stamina > 0:
            sheet.alive = True
        res.state_transitions.append(f'stamina+={amount}')
        res.facts.append('You feel strength return to your limbs.')
        _add_structured(res, {'kind': 'body_event', 'type': 'recover', 'severity': 'moderate'})
        res.state_changed = True
    elif op == 'lose_skill':
        amount = int(effect.get('amount', 1) or 1)
        sheet.skill = max(0, int(sheet.skill or 0) - amount)
        res.state_transitions.append(f'skill-={amount}')
        res.facts.append('Your edge feels dulled.')
        res.state_changed = True
    elif op == 'lose_luck':
        amount = int(effect.get('amount', 1) or 1)
        sheet.luck = max(0, int(sheet.luck or 0) - amount)
        res.state_transitions.append(f'luck-={amount}')
        res.facts.append('A chill of ill omen settles on you.')
        res.state_changed = True
    elif op == 'death':
        sheet.alive = False
        sheet.stamina = 0
        world.ending = 'death'
        world.victory = False
        res.state_transitions.append('ending=death')
        res.facts.append('You have died.')
        res.state_changed = True
    elif op == 'victory':
        world.victory = True
        world.ending = 'victory'
        res.state_transitions.append('ending=victory')
        res.facts.append('Victory!')
        res.state_changed = True


def _combat_from_passage(combat: dict) -> CombatState:
    enemies = combat.get('enemies') if isinstance(combat.get('enemies'), list) else []
    first = enemies[0] if enemies and isinstance(enemies[0], dict) else {}
    name = (
        combat.get('enemy_name')
        or combat.get('name')
        or first.get('name')
        or 'Enemy'
    )
    skill = int(
        combat.get('enemy_skill')
        or combat.get('skill')
        or first.get('skill')
        or 0
    )
    stamina = int(
        combat.get('enemy_stamina')
        or combat.get('stamina')
        or first.get('stamina')
        or 0
    )
    return CombatState(
        active=True,
        enemy_name=str(name),
        enemy_skill=skill,
        enemy_stamina=stamina,
        enemy_stamina_initial=stamina,
        win_to=combat.get('win_to'),
        lose_to=combat.get('lose_to'),
        flee_to=combat.get('flee_to'),
        round=0,
    )


def goto_passage(world: WorldState, to_id: int, rng: GameRNG, res: Resolution) -> Resolution:
    """Enter a numbered passage: apply enter effects, set combat/ending, mark display."""
    del rng  # reserved for enter-time random effects
    passage = get_passage(int(to_id))

    for effect in passage.effects_on_enter or []:
        _apply_effect(world, effect, res)

    world.passage_id = int(passage.id)

    # Authoritative visibles for this passage (book/dungeon)
    ents = list(_passage_field(passage, 'entities') or [])
    world.visible_entities = [str(e) for e in ents]

    if passage.combat:
        world.combat = _combat_from_passage(passage.combat)
        res.state_transitions.append(f'combat={world.combat.enemy_name}')
        enemy = world.combat.enemy_name or 'an enemy'
        res.facts.append(f'{enemy} bars your way.')
        _add_structured(res, {
            'kind': 'world_event',
            'type': 'combat_begins',
            'enemy': enemy,
        })
    else:
        world.combat = CombatState()

    ending = (passage.ending or '').strip().lower() if passage.ending else ''
    if ending:
        world.ending = ending
        world.victory = ending == 'victory'
        if ending in ('death', 'defeat', 'lose'):
            world.sheet.alive = False
            world.sheet.stamina = 0
            world.ending = 'death'
            world.victory = False

    if not world.sheet.alive:
        world.ending = world.ending or 'death'
        world.victory = False

    res.show_passage_text = True
    res.passage_entered = int(passage.id)
    res.image_dirty = True
    res.situation_changed = True
    res.state_changed = True
    res.interacted = True
    res.meaningful_effort = True
    res.attempted = True
    res.intended_effect_achieved = True
    res.success = True if res.success is not False else res.success
    res.feasible = True
    res.productive_for_guidance = True
    res.guidance_delta = -999
    # Debug marker only — narrator filters this
    res.state_transitions.append(f'passage_id={passage.id}')
    return res


def _follow_turn_to(
    world: WorldState,
    intent: Intent,
    grounding: Grounding,
    rng: GameRNG,
    passage: PassageLike,
    res: Resolution,
) -> Optional[Resolution]:
    if not fidelity.intent_fidelity_allows(intent, 'move') and not fidelity.intent_fidelity_allows(
        intent, 'transition',
    ):
        res.feasible = False
        res.success = False
        res.attempted = True
        res.intended_effect_achieved = False
        res.none_reason = 'intent_fidelity_blocked'
        res.rejection_reason = 'intent_fidelity_blocked'
        res.facts.append('That is not what you set out to do.')
        return res

    to_id = grounding.bindings.get('turn_to')
    if to_id is None:
        to_id = intent.turn_to
    action_id = grounding.bindings.get('matched_action_id') or intent.matched_action_id

    choice = _find_choice(passage, action_id, to_id if to_id is not None else None)
    if choice is not None:
        ok, resolved_to = _check_choice_conditions(world, choice, rng, res)
        if not ok:
            res.feasible = False
            res.success = False
            res.grounded = True
            res.attempted = True
            res.intended_effect_achieved = False
            res.interacted = True
            return res
        if resolved_to is not None:
            to_id = resolved_to
        elif to_id is None:
            to_id = choice.get('to')

    if to_id is None:
        return None

    res.affordances_used.append('turn_to')
    res.grounded = True
    return goto_passage(world, int(to_id), rng, res)


def _is_combat_attack_intent(intent: Intent) -> bool:
    cls = (intent.action_class or '').upper()
    matched = (intent.matched_action_id or '').lower()
    if cls in ('ATTACK', 'FIGHT', 'STRIKE'):
        return True
    if matched == 'combat.attack':
        return True
    effect = (intent.intended_effect or '').lower()
    return effect in ('harm', 'kill', 'wound', 'damage')


def _is_combat_flee_intent(intent: Intent) -> bool:
    cls = (intent.action_class or '').upper()
    matched = (intent.matched_action_id or '').lower()
    if cls == 'FLEE' or matched == 'combat.flee':
        return True
    return (intent.intended_effect or '') == 'escape'


def _resolve_combat_attack(
    world: WorldState,
    intent: Intent,
    rng: GameRNG,
    res: Resolution,
) -> Resolution:
    combat = world.combat
    res.combat_round = True
    res.addressed_threat = True
    res.meaningful_effort = True
    res.interacted = True
    res.attempted = True
    res.affordances_used.append('combat_attack')
    combat.round = int(combat.round or 0) + 1

    winner, player_as, enemy_as = combat_round(world.sheet.skill, combat.enemy_skill, rng)
    res.checks.append({
        'label': f'Combat round {combat.round}',
        'player_as': player_as,
        'enemy_as': enemy_as,
        'winner': winner,
    })

    enemy = combat.enemy_name or 'the enemy'
    if winner == 'player':
        combat.enemy_stamina = max(0, int(combat.enemy_stamina) - 2)
        res.damage_events.append({'source': 'player', 'amount': 2, 'target': 'enemy'})
        res.structured_facts.extend(body_events.combat_hit_enemy_facts(enemy))
        res.facts.append(f'You land a solid blow on {enemy}.')
        res.intended_effect_achieved = True
        res.success = True
    elif winner == 'enemy':
        apply_stamina_loss(world.sheet, 2)
        body = body_events.stamina_loss_to_body_event(2, f'combat:{enemy}', world.sheet)
        body_events.apply_injury(world.sheet, body)
        res.damage_events.append({'source': 'enemy', 'amount': 2, 'target': 'player'})
        res.structured_facts.extend(body_events.combat_hit_player_facts(enemy, 2))
        res.facts.append(f'{enemy} strikes you hard.')
        for line in body_events.qualitative_body_summary(world.sheet)[-1:]:
            res.facts.append(line)
        res.intended_effect_achieved = False
        res.success = False
    else:
        res.facts.append(f'You and {enemy} trade blows without finding an opening.')
        _add_structured(res, {
            'kind': 'world_event',
            'type': 'combat_tie',
            'enemy': enemy,
        })
        res.intended_effect_achieved = False
        res.success = False

    res.situation_changed = True
    res.state_changed = True
    res.image_dirty = True
    res.feasible = True
    res.productive_for_guidance = True
    res.guidance_delta = -999

    if combat.enemy_stamina <= 0:
        combat.active = False
        res.facts.append(f'{enemy} falls.')
        _add_structured(res, {'kind': 'world_event', 'type': 'enemy_defeated', 'enemy': enemy})
        if combat.win_to is not None:
            return goto_passage(world, int(combat.win_to), rng, res)
        res.facts.append('The fight is over.')
        return res

    if not world.sheet.alive:
        combat.active = False
        world.ending = 'death'
        world.victory = False
        res.facts.append('Your wounds overcome you. You are dead.')
        _add_structured(res, {'kind': 'world_event', 'type': 'player_died', 'cause': 'combat'})
        if combat.lose_to is not None:
            return goto_passage(world, int(combat.lose_to), rng, res)
        res.situation_changed = True
        res.image_dirty = True
        return res

    return res


def _resolve_combat_flee(
    world: WorldState,
    intent: Intent,
    rng: GameRNG,
    res: Resolution,
) -> Resolution:
    del intent
    combat = world.combat
    if combat.flee_to is None:
        res.feasible = False
        res.success = False
        res.attempted = True
        res.intended_effect_achieved = False
        res.facts.append('There is no escape from this fight.')
        res.rejection_reason = 'cannot_flee'
        res.none_reason = 'cannot_flee'
        return res
    combat.active = False
    res.addressed_threat = True
    res.attempted = True
    res.facts.append(f'You flee from {combat.enemy_name or "the enemy"}.')
    return goto_passage(world, int(combat.flee_to), rng, res)


def _use_item(world: WorldState, intent: Intent, res: Resolution) -> Resolution:
    target = (intent.target or intent.tool or '').lower()
    effect = (intent.intended_effect or '').lower()
    matched = (intent.matched_action_id or '').lower()
    utterance = (intent.utterance or '').lower()
    blob = f'{target} {effect} {matched} {utterance} {intent.tool or ""}'

    res.interacted = True
    res.meaningful_effort = True
    res.grounded = True
    res.attempted = True

    # Key use — never consume potion
    if 'key' in blob and 'potion' not in blob and matched not in ('item.use_potion', 'item.eat_provision'):
        if not _sheet_has_item(world.sheet, 'key'):
            res.feasible = False
            res.success = False
            res.intended_effect_achieved = False
            res.none_reason = 'missing_item'
            res.requested_entity = 'key'
            res.facts.append('You have no key.')
            _add_structured(res, {'kind': 'world_event', 'type': 'entity_absent', 'entity': 'key'})
            return res
        res.feasible = True
        res.success = False
        res.intended_effect_achieved = False
        res.state_changed = False
        res.facts.append(
            'You try the key. Nothing here yields to it without a clearer aim.'
        )
        _add_structured(res, {
            'kind': 'world_event',
            'type': 'key_attempt',
            'success': False,
        })
        return res

    wants_potion = matched == 'item.use_potion' or (
        'potion' in blob and 'key' not in blob
    )
    wants_provision = matched == 'item.eat_provision' or (
        'provision' in blob or 'food' in blob or (
            (intent.action_class or '').upper() in ('EAT',) and 'potion' not in blob
        )
    )

    if wants_potion:
        if not fidelity.intent_fidelity_allows(intent, 'consume_item', {'item': 'potion'}):
            res.feasible = False
            res.success = False
            res.intended_effect_achieved = False
            res.none_reason = 'intent_fidelity_blocked'
            res.rejection_reason = 'intent_fidelity_blocked'
            res.facts.append('You stop short of drinking — that is not what you meant to do.')
            return res
        result = drink_potion(world.sheet)
        res.affordances_used.append('use_potion')
        if not result.get('ok'):
            res.feasible = False
            res.success = False
            res.intended_effect_achieved = False
            reason = result.get('reason', 'cannot_use')
            res.rejection_reason = reason
            res.none_reason = reason
            if reason == 'potion_already_used':
                res.facts.append('You have already drunk your potion.')
            elif reason == 'no_potion':
                res.facts.append('You have no potion to drink.')
            else:
                res.facts.append('You cannot drink a potion now.')
            return res
        restores = result.get('restores')
        res.feasible = True
        res.success = True
        res.intended_effect_achieved = True
        res.situation_changed = True
        res.state_changed = True
        res.productive_for_guidance = True
        res.guidance_delta = -999
        res.facts.append('You drink your potion and feel renewed.')
        _add_structured(res, {
            'kind': 'body_event',
            'type': 'potion_drunk',
            'restores': restores,
        })
        res.state_transitions.append(f'potion_used restores={restores}')
        return res

    if wants_provision:
        if not fidelity.intent_fidelity_allows(intent, 'consume_item', {'item': 'provision'}):
            res.feasible = False
            res.success = False
            res.intended_effect_achieved = False
            res.none_reason = 'intent_fidelity_blocked'
            res.rejection_reason = 'intent_fidelity_blocked'
            res.facts.append('You do not eat — that was not your intent.')
            return res
        result = eat_provision(world.sheet)
        res.affordances_used.append('eat_provision')
        if not result.get('ok'):
            res.feasible = False
            res.success = False
            res.intended_effect_achieved = False
            res.rejection_reason = result.get('reason', 'cannot_eat')
            res.none_reason = res.rejection_reason
            if result.get('reason') == 'no_provisions':
                res.facts.append('You have no provisions left.')
            else:
                res.facts.append('You cannot eat a provision now.')
            return res
        res.feasible = True
        res.success = True
        res.intended_effect_achieved = True
        res.situation_changed = True
        res.state_changed = True
        res.productive_for_guidance = True
        res.guidance_delta = -999
        res.facts.append('You eat a provision and recover some strength.')
        _add_structured(res, {
            'kind': 'body_event',
            'type': 'provision_eaten',
            'restored': result.get('restored'),
        })
        return res

    res.feasible = True
    res.success = False
    res.intended_effect_achieved = False
    res.state_changed = False
    res.facts.append('You handle your gear, but nothing useful comes of it here.')
    return res


def _perception_query(world: WorldState, intent: Intent, passage: PassageLike, res: Resolution) -> Resolution:
    sheet = world.sheet
    res.feasible = True
    res.success = True
    res.grounded = True
    res.attempted = True
    res.intended_effect_achieved = True
    res.interacted = True
    res.meaningful_effort = True
    res.productive_for_guidance = True
    res.guidance_delta = -999
    # Looking around does not advance a turn_to / leave the passage
    res.show_passage_text = False
    res.passage_entered = None

    focus = (intent.query_focus or intent.intended_effect or intent.target or '').lower()
    blob = ' '.join(filter(None, [intent.utterance, intent.target, intent.method, focus])).lower()

    if any(x in blob or x in focus for x in ('inventory', 'carry', 'carrying', 'possessions', 'holding')):
        inv = ', '.join(
            str(i.get('name') if isinstance(i, dict) else i).replace('_', ' ')
            for i in sheet.inventory
        ) or 'nothing of note'
        potion = ''
        if sheet.potion and not sheet.potion_used:
            potion = '; a potion ready to drink'
        res.facts.append(f'You are carrying: {inv}{potion}.')
        _add_structured(res, {'kind': 'perception', 'type': 'inventory'})
        return res

    if any(x in blob or x in focus for x in ('stamina', 'skill', 'luck', 'sheet', 'score', 'stats')):
        # Qualitative only — no score names
        res.facts.append(
            'You take stock of yourself: fit enough to fight, but the Trial will still test you.'
        )
        for line in body_events.qualitative_body_summary(sheet):
            res.facts.append(line)
        _add_structured(res, {'kind': 'perception', 'type': 'body'})
        return res

    # Default look-around: stay on passage, perception facts, no turn_to
    text = (_passage_field(passage, 'text') or '').strip()
    if text:
        snippet = text if len(text) <= 280 else text[:277].rsplit(' ', 1)[0] + '...'
        res.facts.append(snippet)
    else:
        res.facts.append('You look carefully at your surroundings.')

    entities = list(_passage_field(passage, 'entities') or []) or list(world.visible_entities or [])
    if entities:
        shown = ', '.join(str(e).replace('_', ' ') for e in entities[:6])
        res.facts.append(f'You notice: {shown}.')
        _add_structured(res, {
            'kind': 'perception',
            'type': 'visible_entities',
            'entities': list(entities),
        })

    if world.combat.active:
        c = world.combat
        res.facts.append(f'{c.enemy_name or "An enemy"} still threatens you.')
        _add_structured(res, {
            'kind': 'perception',
            'type': 'combat_threat',
            'enemy': c.enemy_name,
        })

    return res


def _meta_request(world: WorldState, intent: Intent, passage: PassageLike, res: Resolution) -> Resolution:
    del world, intent, passage
    res.feasible = True
    res.grounded = True
    res.attempted = False
    res.success = False
    res.intended_effect_achieved = False
    res.guidance_delta = 0
    res.rejection_reason = 'non_diegetic'
    res.none_reason = 'non_diegetic'
    res.facts.append('That request belongs outside this adventure.')
    return res


def _handle_ungrounded(intent: Intent, grounding: Grounding, res: Resolution) -> Resolution:
    entity = (
        grounding.bindings.get('requested_entity')
        or intent.target
        or intent.tool
        or 'that'
    )
    res.intent_understood = True
    res.grounded = False
    res.feasible = False
    res.success = False
    res.attempted = False
    res.intended_effect_achieved = False
    res.state_changed = False
    res.requested_entity = str(entity)
    res.none_reason = 'entity_absent'
    res.rejection_reason = 'entity_absent'
    res.advance_time = True
    res.facts.append(f'There is no {entity} here.')
    _add_structured(res, {
        'kind': 'world_event',
        'type': 'entity_absent',
        'entity': str(entity),
    })
    return res


def _handle_go_home(intent: Intent, grounding: Grounding, res: Resolution) -> Resolution:
    dest = grounding.bindings.get('requested_destination') or intent.destination or 'home'
    res.intent_understood = True
    res.grounded = False
    res.feasible = False
    res.success = False
    res.attempted = True
    res.intended_effect_achieved = False
    res.state_changed = False
    res.none_reason = 'destination_absent'
    res.rejection_reason = 'destination_absent'
    res.advance_time = True
    res.facts.append(f'There is no way {dest} from here.')
    _add_structured(res, {
        'kind': 'world_event',
        'type': 'destination_absent',
        'destination': str(dest),
    })
    return res


def _dismiss(world: WorldState, intent: Intent, res: Resolution) -> Resolution:
    """No-op attempt for social / impossible / systemic flourishes — never success=True."""
    del world
    classification = (intent.classification or '').upper()
    cls = (intent.action_class or '').upper()
    said = (intent.utterance or intent.method or '').strip()
    method = (intent.method or '').lower()

    _mark_noop_attempt(res, understood=True, grounded=True)
    res.advance_time = True
    res.guidance_delta = 0

    if classification == 'IMPOSSIBLE_ATTEMPT' or cls in ('IMPOSSIBLE', 'SUMMON', 'TRANSFORM', 'CAST'):
        res.grounded = False
        res.none_reason = 'impossible_here'
        if 'dragon' in (said or method).lower() or 'summon' in (said or method).lower():
            res.facts.append('No dragon answers. The stone stays exactly as it was.')
        else:
            res.facts.append('Nothing answers that impossible wish. The place is unchanged.')
        _add_structured(res, {
            'kind': 'world_event',
            'type': 'impossible_attempt',
            'utterance': said[:80] if said else cls,
        })
        return res

    if classification == 'SOCIAL_ACTION' or cls in (
        'SPEAK', 'SHOUT', 'SING', 'NEGOTIATE', 'WARN', 'GIVE', 'SURRENDER',
    ):
        res.none_reason = 'no_social_uptake'
        if method in ('seduce', 'charm', 'flirt') or 'seduce' in (said or '').lower():
            res.facts.append('Your advance finds no willing partner here.')
        elif method == 'sing' or 'sing' in (said or '').lower():
            res.facts.append('Your song fades into damp stone. Nothing answers.')
        else:
            res.facts.append('Your words hang in the air unanswered.')
        _add_structured(res, {
            'kind': 'world_event',
            'type': 'social_no_uptake',
            'method': method or cls.lower(),
        })
        return res

    if classification in ('SYSTEMIC_ACTION', 'GENERAL_WORLD_ACTION') or cls in (
        'BODILY', 'CARTWHEEL', 'OTHER', 'MOVE', 'WAIT', 'SIT', 'MANIPULATE', 'LICK',
    ):
        res.none_reason = 'no_effect'
        low = (said or method or '').lower()
        if 'lick' in low or cls == 'LICK':
            res.facts.append('You taste cold iron and dust. Nothing changes.')
        elif cls == 'MOVE' or any(w in low for w in ('run', 'move', 'go back', 'turn around', 'dig', 'tunnel')):
            res.facts.append(
                'You pace and turn, but this stretch offers no new route from that alone.'
            )
        elif any(w in low for w in ('bribe', 'gold', 'pay', 'buy', 'merchant', 'guard')):
            res.facts.append('There is no one here to take a bribe, and nothing changes hands.')
        elif any(w in low for w in ('wait', 'sit')):
            res.facts.append('You settle for a moment. The stone does not answer.')
        else:
            # Never echo raw player text — it can smuggle passage numbers / sheet jargon.
            res.facts.append('Nothing in the world shifts for that.')
        _add_structured(res, {
            'kind': 'world_event',
            'type': 'systemic_noop',
            'action_class': cls,
        })
        return res

    res.none_reason = 'no_effect'
    res.facts.append('Nothing in the world shifts for that.')
    return res


def _finalize_time(intent: Intent, res: Resolution) -> None:
    cost = int(time_model.time_cost(intent, res.to_dict()))
    res.time_cost = cost
    if res.advance_time is False:
        res.time_cost = 0


def resolve(
    world: WorldState,
    intent: Intent,
    grounding: Grounding,
    rng: GameRNG,
    passage: PassageLike,
) -> Resolution:
    res = Resolution(intent_understood=intent.understood, grounded=grounding.grounded)
    classification = (intent.classification or '').upper()
    cls = (intent.action_class or '').upper()

    if not world.sheet.alive or world.ending == 'death':
        res.feasible = False
        res.success = False
        res.attempted = False
        res.rejection_reason = 'player_dead'
        res.none_reason = 'player_dead'
        res.facts.append('You are dead. The dungeon does not answer.')
        res.advance_time = False
        _finalize_time(intent, res)
        return res

    if world.ending == 'victory' or world.victory:
        res.feasible = False
        res.success = True
        res.facts.append('Your adventure is already complete.')
        res.advance_time = False
        _finalize_time(intent, res)
        return res

    # 1. Uninterpretable
    if not intent.understood or classification == 'UNINTERPRETABLE' or cls == 'UNINTERPRETABLE':
        res.intent_understood = False
        res.grounded = False
        res.feasible = None
        res.success = None
        res.attempted = False
        res.advance_time = False
        res.guidance_delta = 0
        res.rejection_reason = 'intent_not_understood'
        res.none_reason = 'intent_not_understood'
        res.facts.append('Your words do not resolve into any clear action the world can meet.')
        _finalize_time(intent, res)
        return res

    # 2. Ungrounded entity (tank/helicopter/etc.)
    if classification == 'UNGROUNDED_ENTITY' or 'entity_absent' in (grounding.failed or []):
        # Destination-absent is handled separately
        if 'destination_absent' not in (grounding.failed or []):
            out = _handle_ungrounded(intent, grounding, res)
            _finalize_time(intent, out)
            return out

    # notes==requested_entity without failed entity_absent still means absent vehicle
    if grounding.notes == 'requested_entity' and classification != 'IMPOSSIBLE_ATTEMPT':
        if 'destination_absent' not in (grounding.failed or []):
            out = _handle_ungrounded(intent, grounding, res)
            _finalize_time(intent, out)
            return out

    # 3. Go home / absent destination — never remap to west/east
    if (
        'destination_absent' in (grounding.failed or [])
        or (intent.destination or '').lower() in ('home', 'house', 'outside', 'town')
        or (intent.intended_effect or '').lower() == 'go_home'
    ):
        out = _handle_go_home(intent, grounding, res)
        _finalize_time(intent, out)
        return out

    # 4. Clarification — only genuine ambiguity (never full choice menus)
    if grounding.ambiguous and (
        classification == 'NEEDS_CLARIFICATION' or intent.needs_clarification
    ):
        res.grounded = False
        res.feasible = None
        res.success = None
        res.attempted = False
        res.needs_clarification = True
        res.advance_time = False
        prompt = grounding.clarification_prompt or ''
        for item in grounding.ambiguous:
            if isinstance(item, dict) and item.get('prompt'):
                prompt = item['prompt']
                break
        if not prompt:
            prompt = 'What exactly do you intend to do?'
        res.clarification_prompt = prompt
        res.facts.append(prompt)
        # Exclusive discourse if options are real ambiguity candidates (not all passage labels)
        options = []
        for item in grounding.ambiguous:
            if isinstance(item, dict):
                for cand in item.get('candidates') or []:
                    if cand:
                        options.append({'id': str(cand), 'label': str(cand)})
        if options and len(options) <= 6:
            discourse.set_pending_exclusive(world, prompt, options)
        _finalize_time(intent, res)
        return res

    # 5. Authored turn-to / matched action
    wants_turn = (
        classification == 'MATCH_AUTHORED_ACTION'
        or cls == 'TURN_TO'
        or (
            intent.matched_action_id
            and intent.matched_action_id not in (
                'combat.attack', 'combat.flee', 'item.use_potion', 'item.eat_provision',
            )
            and grounding.bindings.get('turn_to') is not None
        )
        or grounding.bindings.get('turn_to') is not None
    )
    if wants_turn and intent.matched_action_id not in (
        'combat.attack', 'combat.flee', 'item.use_potion', 'item.eat_provision',
    ):
        if grounding.grounded is False and classification == 'MATCH_AUTHORED_ACTION':
            res.feasible = False
            res.success = False
            res.attempted = False
            res.none_reason = 'authored_action_absent'
            res.facts.append('That option is not available here.')
            _finalize_time(intent, res)
            return res
        followed = _follow_turn_to(world, intent, grounding, rng, passage, res)
        if followed is not None:
            _finalize_time(intent, followed)
            return followed

    # 6. Combat active: attack/flee only for attack intents; else attempt + world_react
    if world.combat.active:
        if _is_combat_flee_intent(intent):
            out = _resolve_combat_flee(world, intent, rng, res)
            _finalize_time(intent, out)
            return out
        if _is_combat_attack_intent(intent):
            out = _resolve_combat_attack(world, intent, rng, res)
            _finalize_time(intent, out)
            return out
        # Social / sing / perceive / impossible / other — do NOT convert to attack
        if classification == 'PERCEPTION_QUERY' or cls in ('PERCEIVE', 'QUERY', 'LOOK'):
            out = _perception_query(world, intent, passage, res)
            # Perception during combat still costs time; enemy may react via world_react
            out.advance_time = True
            _finalize_time(intent, out)
            return out
        if classification in ('META_INPUT', 'META_REQUEST'):
            out = _meta_request(world, intent, passage, res)
            _finalize_time(intent, out)
            return out
        out = _dismiss(world, intent, res)
        out.advance_time = True
        _finalize_time(intent, out)
        return out

    # 7. Potion / provision / key
    matched = (intent.matched_action_id or '').lower()
    if (
        matched in ('item.use_potion', 'item.eat_provision')
        or cls in ('USE', 'EAT', 'DRINK')
        or (intent.tool or '').lower() in ('key', 'potion')
        or (intent.target or '').lower() in ('potion', 'provision', 'key')
    ):
        out = _use_item(world, intent, res)
        _finalize_time(intent, out)
        return out

    # 8. Perception
    if classification == 'PERCEPTION_QUERY' or cls in ('PERCEIVE', 'QUERY', 'LOOK'):
        out = _perception_query(world, intent, passage, res)
        _finalize_time(intent, out)
        return out

    # 9. Meta
    if classification in ('META_INPUT', 'META_REQUEST') or cls == 'META':
        out = _meta_request(world, intent, passage, res)
        _finalize_time(intent, out)
        return out

    # 10. Impossible / social / systemic dismissals
    if classification in (
        'IMPOSSIBLE_ATTEMPT', 'SOCIAL_ACTION', 'SYSTEMIC_ACTION',
        'GENERAL_WORLD_ACTION', 'NO_ACTIONABLE_INTENT',
    ) or cls in (
        'BODILY', 'CARTWHEEL', 'OTHER', 'GENERAL_WORLD_ACTION', 'MOVE', 'WAIT', 'SIT',
        'SPEAK', 'SHOUT', 'SING', 'MANIPULATE', 'IMPOSSIBLE', 'SUMMON', 'TRANSFORM',
    ):
        out = _dismiss(world, intent, res)
        _finalize_time(intent, out)
        return out

    out = _dismiss(world, intent, res)
    _finalize_time(intent, out)
    return out
