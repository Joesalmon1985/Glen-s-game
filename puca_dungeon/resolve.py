"""Python-owned resolution for the Fighting Fantasy passage graph."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

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
        }


def _passage_field(passage: PassageLike, key: str, default=None):
    if isinstance(passage, dict):
        return passage.get(key, default)
    return getattr(passage, key, default)


def _choice_labels(passage: PassageLike) -> list[str]:
    labels = []
    for choice in _passage_field(passage, 'choices') or []:
        if not isinstance(choice, dict):
            continue
        label = (choice.get('label') or '').strip()
        if label:
            labels.append(label)
    return labels


def _clarification_from_choices(passage: PassageLike) -> str:
    labels = _choice_labels(passage)
    if not labels:
        return 'What do you do?'
    if len(labels) == 1:
        return f'Do you mean: {labels[0]}?'
    joined = '; '.join(labels)
    return f'Which will you do? {joined}'


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
        if str(owned).lower() == item_l:
            return True
    if item_l in ('gold', 'gold_pieces') and int(sheet.gold or 0) > 0:
        return True
    if item_l in ('provision', 'provisions') and int(sheet.provisions or 0) > 0:
        return True
    if item_l == 'potion' and sheet.potion and not sheet.potion_used:
        return True
    return False


def _check_choice_conditions(
    world: WorldState,
    choice: dict,
    rng: GameRNG,
    res: Resolution,
) -> tuple[bool, Optional[int]]:
    """Return (ok, override_turn_to). override_turn_to used for luck/skill fail branches."""
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
                return False, None
        elif op in ('flag', 'has_flag', 'set_flag'):
            flag = cond.get('flag') or cond.get('id') or ''
            expected = cond.get('value', True)
            actual = world.sheet.flags.get(flag)
            if actual != expected and not (expected is True and bool(actual)):
                res.facts.append('That path is not open to you yet.')
                res.rejection_reason = 'flag_gate'
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
                f'You Test your Luck (rolled {roll} vs Luck {new_luck + 1}). '
                + ('Lucky!' if lucky else 'Unlucky.')
            )
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
                f'You Test your Skill (rolled {roll} vs Skill {world.sheet.skill}). '
                + ('Success.' if ok else 'Failure.')
            )
            if ok:
                turn_to = cond.get('success_to', choice.get('to_success', turn_to))
            else:
                fail_to = cond.get('fail_to', choice.get('to_fail') or choice.get('fail_to'))
                if fail_to is None:
                    res.facts.append('Your skill is not enough for that attempt.')
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
    elif op == 'add_item':
        item = effect.get('item') or effect.get('id')
        if item and item not in sheet.inventory:
            sheet.inventory.append(item)
            res.state_transitions.append(f'inventory+={item}')
            res.facts.append(f'You take the {str(item).replace("_", " ")}.')
    elif op == 'remove_item':
        item = effect.get('item') or effect.get('id')
        if item in sheet.inventory:
            sheet.inventory.remove(item)
            res.state_transitions.append(f'inventory-={item}')
    elif op == 'set_flag':
        flag = effect.get('flag') or effect.get('id')
        if flag:
            value = effect.get('value', True)
            sheet.flags[flag] = value
            res.state_transitions.append(f'flag.{flag}={value!r}')
    elif op == 'add_knowledge':
        fact = effect.get('fact') or effect.get('id') or effect.get('knowledge')
        if fact and fact not in sheet.knowledge:
            sheet.knowledge.append(fact)
            res.state_transitions.append(f'knowledge+={fact}')
    elif op == 'lose_stamina':
        amount = int(effect.get('amount', 0) or 0)
        apply_stamina_loss(sheet, amount)
        res.damage_events.append({'source': 'passage', 'amount': amount})
        res.state_transitions.append(f'stamina-={amount}')
        res.facts.append(f'You lose {amount} STAMINA.')
    elif op == 'gain_stamina':
        amount = int(effect.get('amount', 0) or 0)
        sheet.stamina = min(int(sheet.stamina_initial or 0), int(sheet.stamina or 0) + amount)
        if sheet.stamina > 0:
            sheet.alive = True
        res.state_transitions.append(f'stamina+={amount}')
    elif op == 'lose_skill':
        amount = int(effect.get('amount', 1) or 1)
        sheet.skill = max(0, int(sheet.skill or 0) - amount)
        res.state_transitions.append(f'skill-={amount}')
        res.facts.append(f'You lose {amount} SKILL.')
    elif op == 'lose_luck':
        amount = int(effect.get('amount', 1) or 1)
        sheet.luck = max(0, int(sheet.luck or 0) - amount)
        res.state_transitions.append(f'luck-={amount}')
        res.facts.append(f'You lose {amount} LUCK.')
    elif op == 'death':
        sheet.alive = False
        sheet.stamina = 0
        world.ending = 'death'
        world.victory = False
        res.state_transitions.append('ending=death')
        res.facts.append('You have died.')
    elif op == 'victory':
        world.victory = True
        world.ending = 'victory'
        res.state_transitions.append('ending=victory')
        res.facts.append('Victory!')


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
    passage = get_passage(int(to_id))

    for effect in passage.effects_on_enter or []:
        _apply_effect(world, effect, res)

    world.passage_id = int(passage.id)

    if passage.combat:
        world.combat = _combat_from_passage(passage.combat)
        res.state_transitions.append(f'combat={world.combat.enemy_name}')
        res.facts.append(
            f'Combat begins: {world.combat.enemy_name} '
            f'(SKILL {world.combat.enemy_skill}, STAMINA {world.combat.enemy_stamina}).'
        )
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
    res.interacted = True
    res.meaningful_effort = True
    res.success = True if res.success is not False else res.success
    res.feasible = True
    res.productive_for_guidance = True
    res.guidance_delta = -999
    res.facts.append(f'Entered passage {passage.id}.')
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


def _resolve_combat(
    world: WorldState,
    intent: Intent,
    rng: GameRNG,
    res: Resolution,
) -> Resolution:
    combat = world.combat
    cls = (intent.action_class or '').upper()
    matched = (intent.matched_action_id or '').lower()

    is_flee = cls == 'FLEE' or matched == 'combat.flee' or (intent.intended_effect or '') == 'escape'
    is_attack = (
        cls in ('ATTACK', 'FIGHT', 'STRIKE')
        or matched == 'combat.attack'
        or (intent.intended_effect or '') == 'harm'
    )

    if is_flee:
        if combat.flee_to is None:
            res.feasible = False
            res.success = False
            res.facts.append('There is no escape from this fight.')
            res.rejection_reason = 'cannot_flee'
            return res
        combat.active = False
        res.addressed_threat = True
        res.facts.append(f'You flee from {combat.enemy_name or "the enemy"}.')
        return goto_passage(world, int(combat.flee_to), rng, res)

    if not is_attack:
        res.feasible = True
        res.success = False
        res.guidance_delta = max(res.guidance_delta, 1)
        res.facts.append(
            f'{combat.enemy_name or "The enemy"} still threatens you. '
            'You must fight' + (' or flee.' if combat.flee_to is not None else '.')
        )
        return res

    res.combat_round = True
    res.addressed_threat = True
    res.meaningful_effort = True
    res.interacted = True
    res.affordances_used.append('combat_attack')
    combat.round = int(combat.round or 0) + 1

    winner, player_as, enemy_as = combat_round(world.sheet.skill, combat.enemy_skill, rng)
    res.checks.append({
        'label': f'Combat round {combat.round}',
        'player_as': player_as,
        'enemy_as': enemy_as,
        'winner': winner,
    })

    if winner == 'player':
        combat.enemy_stamina = max(0, int(combat.enemy_stamina) - 2)
        res.damage_events.append({'source': 'player', 'amount': 2, 'target': 'enemy'})
        res.facts.append(
            f'Round {combat.round}: your Attack Strength {player_as} beats '
            f'{combat.enemy_name}\'s {enemy_as}. {combat.enemy_name} loses 2 STAMINA '
            f'(now {combat.enemy_stamina}).'
        )
    elif winner == 'enemy':
        apply_stamina_loss(world.sheet, 2)
        res.damage_events.append({'source': 'enemy', 'amount': 2, 'target': 'player'})
        res.facts.append(
            f'Round {combat.round}: {combat.enemy_name}\'s Attack Strength {enemy_as} beats '
            f'yours ({player_as}). You lose 2 STAMINA (now {world.sheet.stamina}).'
        )
    else:
        res.facts.append(
            f'Round {combat.round}: Attack Strengths tie ({player_as}). No wounds this round.'
        )

    res.situation_changed = True
    res.image_dirty = True
    res.success = winner == 'player'
    res.feasible = True
    res.productive_for_guidance = True
    res.guidance_delta = -999

    if combat.enemy_stamina <= 0:
        combat.active = False
        res.facts.append(f'{combat.enemy_name} is defeated.')
        if combat.win_to is not None:
            return goto_passage(world, int(combat.win_to), rng, res)
        res.facts.append('The fight is over.')
        return res

    if not world.sheet.alive:
        combat.active = False
        world.ending = 'death'
        world.victory = False
        res.facts.append('Your STAMINA falls to zero. You are dead.')
        if combat.lose_to is not None:
            return goto_passage(world, int(combat.lose_to), rng, res)
        res.situation_changed = True
        res.image_dirty = True
        return res

    return res


def _use_item(world: WorldState, intent: Intent, res: Resolution) -> Resolution:
    target = (intent.target or intent.tool or '').lower()
    effect = (intent.intended_effect or '').lower()
    matched = (intent.matched_action_id or '').lower()
    utterance = (intent.utterance or '').lower()
    blob = f'{target} {effect} {matched} {utterance}'

    res.interacted = True
    res.meaningful_effort = True
    res.grounded = True

    if matched == 'item.use_potion' or 'potion' in blob:
        result = drink_potion(world.sheet)
        res.affordances_used.append('use_potion')
        if not result.get('ok'):
            res.feasible = False
            res.success = False
            reason = result.get('reason', 'cannot_use')
            res.rejection_reason = reason
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
        res.situation_changed = True
        res.productive_for_guidance = True
        res.guidance_delta = -999
        res.facts.append(f'You drink your potion and restore your {restores}.')
        res.state_transitions.append(f'potion_used restores={restores}')
        return res

    if matched == 'item.eat_provision' or 'provision' in blob or 'food' in blob or 'eat' in blob:
        result = eat_provision(world.sheet)
        res.affordances_used.append('eat_provision')
        if not result.get('ok'):
            res.feasible = False
            res.success = False
            res.rejection_reason = result.get('reason', 'cannot_eat')
            if result.get('reason') == 'no_provisions':
                res.facts.append('You have no provisions left.')
            else:
                res.facts.append('You cannot eat a provision now.')
            return res
        res.feasible = True
        res.success = True
        res.situation_changed = True
        res.productive_for_guidance = True
        res.guidance_delta = -999
        res.facts.append(
            f'You eat a provision and restore {result.get("restored", 0)} STAMINA '
            f'(now {result.get("stamina")}; {result.get("provisions")} provisions left).'
        )
        return res

    res.feasible = True
    res.success = False
    res.guidance_delta = max(res.guidance_delta, 1)
    res.facts.append('You fiddle with your gear, but nothing useful comes of it here.')
    return res


def _perception_query(world: WorldState, intent: Intent, passage: PassageLike, res: Resolution) -> Resolution:
    sheet = world.sheet
    res.feasible = True
    res.success = True
    res.grounded = True
    res.interacted = True
    res.meaningful_effort = True
    res.productive_for_guidance = True
    res.guidance_delta = -999

    focus = (intent.query_focus or intent.intended_effect or intent.target or '').lower()
    blob = ' '.join(filter(None, [intent.utterance, intent.target, intent.method, focus])).lower()

    if any(x in blob or x in focus for x in ('stamina', 'skill', 'luck', 'sheet', 'score', 'stats')):
        res.facts.append(
            f'Adventure Sheet — SKILL {sheet.skill}, STAMINA {sheet.stamina}/{sheet.stamina_initial}, '
            f'LUCK {sheet.luck}, Gold {sheet.gold}, Provisions {sheet.provisions}.'
        )
        return res
    if any(x in blob or x in focus for x in ('inventory', 'carry', 'carrying', 'possessions', 'holding')):
        inv = ', '.join(str(i).replace('_', ' ') for i in sheet.inventory) or 'nothing of note'
        potion = ''
        if sheet.potion and not sheet.potion_used:
            potion = f'; potion: {sheet.potion}'
        res.facts.append(f'You are carrying: {inv}{potion}.')
        return res
    if any(x in blob or x in focus for x in ('see', 'look', 'around', 'where', 'passage', 'text')):
        text = (_passage_field(passage, 'text') or '').strip()
        if text:
            snippet = text if len(text) <= 280 else text[:277] + '...'
            res.facts.append(snippet)
        else:
            res.facts.append(f'You are at passage {world.passage_id}.')
        return res
    if world.combat.active:
        c = world.combat
        res.facts.append(
            f'You are fighting {c.enemy_name} (SKILL {c.enemy_skill}, STAMINA {c.enemy_stamina}).'
        )
        return res

    labels = _choice_labels(passage)
    inv = ', '.join(str(i).replace('_', ' ') for i in sheet.inventory) or 'little'
    cue = f' Obvious paths: {"; ".join(labels)}.' if labels else ''
    res.facts.append(
        f'Passage {world.passage_id}. SKILL {sheet.skill}, STAMINA {sheet.stamina}, '
        f'LUCK {sheet.luck}. You carry {inv}.{cue}'
    )
    return res


def _meta_request(world: WorldState, intent: Intent, passage: PassageLike, res: Resolution) -> Resolution:
    res.feasible = True
    res.grounded = True
    res.guidance_delta = 1
    res.success = False
    res.rejection_reason = 'non_diegetic'
    labels = _choice_labels(passage)
    cue = f' Your real options remain: {"; ".join(labels)}.' if labels else ''
    res.facts.append(
        'That request belongs outside this adventure.'
        f'{cue}'
    )
    return res


def _dismiss(world: WorldState, intent: Intent, res: Resolution, bump_guidance: bool = True) -> Resolution:
    res.feasible = True
    res.grounded = True
    res.success = True
    res.interacted = True
    if bump_guidance:
        res.guidance_delta = max(res.guidance_delta, 1)
    said = (intent.utterance or intent.method or intent.action_class or 'that').strip()
    res.facts.append(
        f'You attempt “{said[:120]}”, but it does not change your place in the dungeon. '
        'The passage remains as it is.'
    )
    return res


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
        res.rejection_reason = 'player_dead'
        res.facts.append('You are dead. The dungeon does not answer.')
        res.advance_time = False
        return res

    if world.ending == 'victory' or world.victory:
        res.feasible = False
        res.success = True
        res.facts.append('Your adventure is already complete.')
        res.advance_time = False
        return res

    # 1. Uninterpretable
    if not intent.understood or classification == 'UNINTERPRETABLE' or cls == 'UNINTERPRETABLE':
        res.intent_understood = False
        res.grounded = False
        res.feasible = None
        res.success = None
        res.advance_time = False
        res.guidance_delta = 1
        res.rejection_reason = 'intent_not_understood'
        res.facts.append('Your words do not resolve into any clear action the world can meet.')
        return res

    # 2. Clarification
    if (
        grounding.ambiguous
        or classification == 'NEEDS_CLARIFICATION'
        or (intent.needs_clarification and grounding.grounded is False)
    ):
        res.grounded = False
        res.feasible = None
        res.success = None
        res.needs_clarification = True
        res.advance_time = False
        prompt = grounding.clarification_prompt or _clarification_from_choices(passage)
        for item in grounding.ambiguous:
            if isinstance(item, dict) and item.get('prompt'):
                prompt = item['prompt']
                break
        res.clarification_prompt = prompt
        res.facts.append(prompt)
        return res

    # 3. Turn-to / authored choice
    wants_turn = (
        classification == 'MATCH_AUTHORED_ACTION'
        or cls == 'TURN_TO'
        or intent.turn_to is not None
        or grounding.bindings.get('turn_to') is not None
        or (
            intent.matched_action_id
            and intent.matched_action_id not in (
                'combat.attack', 'combat.flee', 'item.use_potion', 'item.eat_provision',
            )
        )
    )
    if wants_turn and not (
        intent.matched_action_id in ('combat.attack', 'combat.flee', 'item.use_potion', 'item.eat_provision')
    ):
        followed = _follow_turn_to(world, intent, grounding, rng, passage, res)
        if followed is not None:
            return followed

    # 4. Combat
    if world.combat.active:
        return _resolve_combat(world, intent, rng, res)

    # 5. Potion / provision
    matched = (intent.matched_action_id or '').lower()
    if (
        matched in ('item.use_potion', 'item.eat_provision')
        or cls == 'USE'
        or (cls in ('EAT', 'DRINK') )
    ):
        return _use_item(world, intent, res)

    # 6. Perception
    if classification == 'PERCEPTION_QUERY' or cls in ('PERCEIVE', 'QUERY', 'LOOK'):
        return _perception_query(world, intent, passage, res)

    # 7. Meta
    if classification == 'META_REQUEST' or cls == 'META':
        return _meta_request(world, intent, passage, res)

    # 8. Silly / unmappable world action — stay on passage
    if classification in ('SILLY_BUT_VALID', 'GENERAL_WORLD_ACTION') or cls in (
        'BODILY', 'CARTWHEEL', 'OTHER', 'GENERAL_WORLD_ACTION', 'MOVE', 'WAIT', 'SIT',
        'SPEAK', 'SHOUT', 'MANIPULATE',
    ):
        return _dismiss(world, intent, res, bump_guidance=True)

    return _dismiss(world, intent, res, bump_guidance=True)
