"""Python-owned resolution. Interprets never decide outcomes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from puca_dungeon.encounters import encounter2
from puca_dungeon.ground import Grounding
from puca_dungeon.models import (
    CLUE_TEXT, DISABLE_DC, EncounterId, Intent, OPEN_LOCK_DC, SEARCH_DC,
    WorldState,
)
from puca_dungeon.rng import GameRNG


@dataclass
class Resolution:
    intent_understood: bool = True
    grounded: bool = True
    feasible: bool = True
    success: bool = False
    facts: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    damage_events: list = field(default_factory=list)
    state_transitions: list = field(default_factory=list)
    rejection_reason: str = ''
    affordances_used: list = field(default_factory=list)
    interacted: bool = False          # plausible state interaction attempted
    meaningful_effort: bool = False   # search/pick/disable/combat/etc.
    addressed_threat: bool = False
    situation_changed: bool = False
    combat_round: bool = False
    image_dirty: bool = False

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
        }


def resolve(world: WorldState, intent: Intent, grounding: Grounding, rng: GameRNG) -> Resolution:
    res = Resolution(intent_understood=intent.understood)
    if not intent.understood:
        res.feasible = False
        res.rejection_reason = 'intent_not_understood'
        res.facts.append('You act, but the world finds no clear purchase on what you meant.')
        return res

    cls = intent.action_class.upper()
    target = grounding.bindings.get('target')
    tool = grounding.bindings.get('tool')

    if world.encounter == EncounterId.DEAD.value or not world.player.alive:
        res.feasible = False
        res.rejection_reason = 'player_dead'
        res.facts.append('You are dead. The dungeon does not answer.')
        return res

    # Junction encounter
    if world.encounter == EncounterId.JUNCTION.value:
        return _resolve_junction(world, intent, grounding, rng, res)

    # Pursuer social/combat when present
    if cls in ('ATTACK', 'WARN', 'GIVE', 'NEGOTIATE', 'SURRENDER', 'HIDE', 'FLEE') and (
            world.pursuer.state in ('present', 'hostile', 'allied') or cls == 'FLEE'):
        return _resolve_pursuer_action(world, intent, grounding, rng, res)

    handlers = {
        'WAIT': _wait,
        'SIT': _sit,
        'LOOK': _look,
        'INSPECT': _inspect,
        'SEARCH': _search,
        'USE': _use_key,
        'UNLOCK': _use_key,
        'PICK_LOCK': _pick_lock,
        'DISABLE': _disable_trap,
        'BREAK': _break_box,
        'STRIKE': _strike,
        'MOVE': _move,
        'FLEE': _flee,
        'SPEAK': _speak,
        'SHOUT': _shout,
        'LICK': _lick,
        'MANIPULATE': _manipulate,
        'ATTACK': _resolve_pursuer_action,
        'OTHER': _other,
    }
    handler = handlers.get(cls, _other)
    return handler(world, intent, grounding, rng, res)


def _skill_check(rng: GameRNG, bonus: int, dc: int, label: str, res: Resolution) -> bool:
    roll = rng.roll_d20()
    total = roll + bonus
    ok = total >= dc
    res.checks.append({'label': label, 'roll': roll, 'bonus': bonus, 'total': total, 'dc': dc, 'success': ok})
    return ok


def _fire_trap(world: WorldState, box, rng: GameRNG, res: Resolution, reason: str) -> None:
    if box.trap_fired or box.trap_disabled or not box.trap_present:
        return
    box.trap_fired = True
    dmg = rng.randint(4, 10)
    world.player.hp = max(0, world.player.hp - dmg)
    res.damage_events.append({'source': 'poison_dart', 'amount': dmg, 'reason': reason, 'box': box.id})
    res.facts.append(f'A poison dart shoots from {box.label} and strikes you for {dmg} damage.')
    res.state_transitions.append(f'{box.id}.trap_fired=true')
    res.situation_changed = True
    res.image_dirty = True
    res.interacted = True
    if world.player.hp <= 0:
        world.player.alive = False
        world.encounter = EncounterId.DEAD.value
        res.facts.append('The poison stills your heart. You die.')
        res.state_transitions.append('player.alive=false')


def _wait(world, intent, grounding, rng, res):
    res.success = True
    res.facts.append('You wait. The stone table and its boxes remain silent.')
    return res


def _sit(world, intent, grounding, rng, res):
    res.success = True
    res.facts.append('You sit near the stone table. Time stretches in the damp air.')
    return res


def _look(world, intent, grounding, rng, res):
    res.success = True
    res.meaningful_effort = True
    res.interacted = True
    res.facts.append(
        'Six locked boxes rest on a stone table. One is marked with your name. '
        'The passage continues deeper ahead; the way you entered lies behind.')
    return res


def _inspect(world, intent, grounding, rng, res):
    target = grounding.bindings.get('target')
    res.interacted = True
    res.meaningful_effort = True
    if target == 'clue_note':
        if world.clue_get_no_mess or 'sukumvit_clue' in world.player.knowledge:
            res.success = True
            res.facts.append(CLUE_TEXT)
        else:
            res.feasible = True
            res.success = False
            res.facts.append('You have no note to read.')
        return res
    if target == 'junction':
        res.facts.append('You are still at the boxes, not yet at a junction.')
        res.success = False
        return res
    # careful inspect of boxes can function like a weaker search redirect
    return _search(world, intent, grounding, rng, res)


def _search(world, intent, grounding, rng, res):
    res.affordances_used.append('search_traps')
    res.interacted = True
    res.meaningful_effort = True
    ok = _skill_check(rng, world.player.search_bonus, SEARCH_DC, 'Search traps', res)
    if ok:
        for box in world.boxes.values():
            if box.trap_present and not box.trap_discovered:
                box.trap_discovered = True
                res.state_transitions.append(f'{box.id}.trap_discovered=true')
        res.success = True
        res.situation_changed = True
        res.facts.append(
            'Your careful search finds a needle-fine poison dart mechanism set into each locked box.')
    else:
        res.success = False
        res.facts.append('You study the boxes carefully but notice nothing unusual about the locks.')
    return res


def _use_key(world, intent, grounding, rng, res):
    res.affordances_used.append('use_key')
    res.interacted = True
    res.meaningful_effort = True
    tool = grounding.bindings.get('tool')
    target = grounding.bindings.get('target')
    if tool != 'trial_key_player':
        res.feasible = False
        res.rejection_reason = 'no_key'
        res.facts.append('You have no suitable key ready.')
        return res
    if target == 'boxes':
        target = 'box_player'
    box = world.boxes.get(target or '')
    if not box:
        # ambiguous / failed grounding: try other_box semantics if ref says so
        res.feasible = False
        res.grounded = False
        res.rejection_reason = 'ungrounded_box'
        res.facts.append('It is unclear which box you mean.')
        return res
    if box.destroyed or box.open:
        res.success = False
        res.facts.append(f'{box.label} is already open or ruined.')
        return res
    if box.is_player_box:
        box.open = True
        box.locked = False
        res.success = True
        res.situation_changed = True
        res.image_dirty = True
        if not box.contents_taken:
            world.player.gold += 2
            box.contents_taken = True
            world.clue_get_no_mess = True
            if 'sukumvit_clue' not in world.player.knowledge:
                world.player.knowledge.append('sukumvit_clue')
            res.facts.append(
                f'Your key turns smoothly in {box.label}. Inside you find 2 gold pieces and a folded note.')
            res.facts.append(CLUE_TEXT)
            res.state_transitions.extend([
                'box_player.open=true', 'player.gold+=2', 'clue_get_no_mess=true',
            ])
        else:
            res.facts.append(f'{box.label} is already empty.')
        return res
    # Wrong box: trap fires
    res.success = False
    res.facts.append(f'Your key does not fit {box.label}.')
    _fire_trap(world, box, rng, res, reason='wrong_key')
    return res


def _pick_lock(world, intent, grounding, rng, res):
    res.affordances_used.append('open_lock')
    res.interacted = True
    res.meaningful_effort = True
    target = grounding.bindings.get('target')
    if target in (None, 'boxes'):
        target = next((b for b in world.boxes if not world.boxes[b].is_player_box), None)
        grounding.bindings['target'] = target
    box = world.boxes.get(target or '')
    if not box:
        res.grounded = False
        res.rejection_reason = 'ungrounded_box'
        res.facts.append('You cannot tell which lock to pick.')
        return res
    if box.open or box.destroyed:
        res.success = False
        res.facts.append(f'{box.label} offers no lock to pick.')
        return res
    if box.trap_present and not box.trap_disabled and not box.trap_fired:
        _fire_trap(world, box, rng, res, reason='pick_without_disable')
        if not world.player.alive:
            return res
    ok = _skill_check(rng, world.player.open_lock_bonus, OPEN_LOCK_DC, 'Open Lock', res)
    if ok:
        box.open = True
        box.locked = False
        res.success = True
        res.situation_changed = True
        res.image_dirty = True
        res.facts.append(f'You pick the lock on {box.label}. It is empty of anything useful.')
        res.state_transitions.append(f'{box.id}.open=true')
    else:
        res.success = False
        res.facts.append(f'The lock on {box.label} resists your picks.')
    return res


def _disable_trap(world, intent, grounding, rng, res):
    res.affordances_used.append('disable_device')
    res.interacted = True
    res.meaningful_effort = True
    # Prefer discovered unddisabled traps
    candidates = [b for b in world.boxes.values() if b.trap_discovered and not b.trap_disabled and not b.trap_fired]
    if not candidates:
        # If none discovered, attempt fails without leaking
        any_known = any(b.trap_discovered for b in world.boxes.values())
        res.success = False
        if not any_known:
            res.facts.append('You find no trap mechanism you can work on.')
        else:
            res.facts.append('There is no remaining armed trap you can reach.')
        return res
    box = candidates[0]
    target = grounding.bindings.get('target')
    if target and target in world.boxes and world.boxes[target].trap_discovered:
        box = world.boxes[target]
    ok = _skill_check(rng, world.player.disable_bonus, DISABLE_DC, 'Disable Device', res)
    if ok:
        box.trap_disabled = True
        res.success = True
        res.situation_changed = True
        res.facts.append(f'You disable the dart trap on {box.label}.')
        res.state_transitions.append(f'{box.id}.trap_disabled=true')
    else:
        res.success = False
        res.facts.append(f'You work at the trap on {box.label}, but the mechanism stays live.')
    return res


def _break_box(world, intent, grounding, rng, res):
    res.affordances_used.append('hardness_hp')
    res.interacted = True
    res.meaningful_effort = True
    target = grounding.bindings.get('target')
    if target in (None, 'boxes', 'box'):
        target = 'box_player'
    box = world.boxes.get(target or '')
    if not box:
        res.grounded = False
        res.rejection_reason = 'ungrounded_box'
        res.facts.append('You swing at empty air; no box is clearly targeted.')
        return res
    if box.destroyed or box.open:
        res.success = False
        res.facts.append(f'{box.label} is already open or smashed.')
        return res
    # Damage vs hardness 10: each serious blow deals 1d8, reduced by hardness
    roll = rng.randint(1, 8)
    dealt = max(0, roll - box.hardness)
    # Allow gradual progress: use raw roll against hp when using dedicated smash, but honor hardness
    # Source: Hardness 10, 10 hp — need damage exceeding hardness. Boost with sword pommel: still hard.
    # For POC playability with hardness 10, accumulate "effort chips" OR deal damage as max(1, roll-5) for weapons
    tool = grounding.bindings.get('tool')
    base = rng.randint(1, 8)
    if tool == 'sword' or (intent.tool and 'pommel' in str(intent.tool).lower()):
        base = rng.randint(2, 10)
    dealt = max(0, base - box.hardness)
    if dealt <= 0:
        # Chip damage for repeated legitimate smash attempts so hardness/hp matter without impossibility
        dealt = 1 if base >= 6 else 0
    box.hp -= dealt
    res.checks.append({'label': 'Smash', 'damage_roll': base, 'hardness': box.hardness, 'dealt': dealt, 'hp_left': box.hp})
    res.situation_changed = True
    res.image_dirty = True
    if box.hp <= 0:
        box.destroyed = True
        box.open = True
        box.locked = False
        res.success = True
        res.facts.append(f'You smash {box.label} apart.')
        res.state_transitions.append(f'{box.id}.destroyed=true')
        if box.is_player_box and not box.contents_taken:
            # Contents may be damaged; still grant clue/gold but messier
            world.player.gold += 2
            box.contents_taken = True
            world.clue_get_no_mess = False
            if 'sukumvit_clue' not in world.player.knowledge:
                world.player.knowledge.append('sukumvit_clue')
            res.facts.append('Among the splinters you recover 2 gp and a torn note.')
            res.facts.append(CLUE_TEXT)
        if box.trap_present and not box.trap_disabled and not box.trap_fired:
            _fire_trap(world, box, rng, res, reason='smash_triggers')
    else:
        res.success = False
        res.facts.append(f'You batter {box.label} (hardness {box.hardness}). It holds; {box.hp} integrity remains.')
    return res


def _strike(world, intent, grounding, rng, res):
    target = grounding.bindings.get('target')
    res.interacted = True
    res.meaningful_effort = True
    if target == 'stone_wall':
        res.feasible = True
        res.success = False
        res.facts.append(
            'You strike the stone wall. It does not break. Your hand and pride ache; the passage is unchanged.')
        res.rejection_reason = 'insufficient_force'
        return res
    return _break_box(world, intent, grounding, rng, res)


def _move(world, intent, grounding, rng, res):
    res.affordances_used.append('movement')
    res.interacted = True
    res.meaningful_effort = True
    dest = grounding.bindings.get('destination') or intent.destination or 'passage_ahead'
    if dest == 'passage_behind':
        res.success = False
        res.facts.append('The sealed contest gate bars retreat. Only the dungeon ahead remains.')
        return res
    if world.pursuer.state == 'hostile' and dest == 'passage_ahead':
        # Can still flee via FLEE; MOVE while threatened is risky but allowed as flee-like
        pass
    if dest in ('passage_ahead', 'west', 'passage_west', 'right', 'passage_right', 'onward'):
        facts = encounter2.enter_junction(world)
        res.success = True
        res.situation_changed = True
        res.addressed_threat = world.pursuer.state in ('present', 'hostile', 'approaching', 'close')
        res.image_dirty = True
        res.facts.extend(facts)
        res.state_transitions.append('encounter=junction')
        return res
    res.success = False
    res.facts.append('You find no clear path that way.')
    return res


def _flee(world, intent, grounding, rng, res):
    intent.destination = intent.destination or 'passage_ahead'
    grounding.bindings['destination'] = 'passage_ahead'
    res.addressed_threat = True
    return _move(world, intent, grounding, rng, res)


def _speak(world, intent, grounding, rng, res):
    res.success = True
    utterance = intent.utterance or ''
    if intent.intended_effect == 'magical_effect' or 'abracadabra' in utterance.lower():
        res.facts.append('You speak mystic nonsense at the boxes. Nothing happens.')
        return res
    res.facts.append('Your words echo briefly and fade into the stone.')
    if world.pursuer.state in ('present', 'hostile'):
        res.interacted = True
        res.addressed_threat = True
        res.facts.append(f'{world.pursuer.name} eyes you, unimpressed by idle talk.')
    return res


def _shout(world, intent, grounding, rng, res):
    res.success = True
    res.facts.append('Your shout rolls down the tunnel and returns as a hollow mockery.')
    return res


def _lick(world, intent, grounding, rng, res):
    res.interacted = True
    res.success = True
    res.facts.append(
        'You lick a cold iron-bound box. It tastes of dust, metal, and poor decisions. Nothing else happens.')
    return res


def _manipulate(world, intent, grounding, rng, res):
    res.interacted = True
    if (intent.method or '').lower() == 'draw' or grounding.bindings.get('target') == 'sword':
        if 'sword_drawn' not in world.flags:
            world.flags['sword_drawn'] = True
            res.situation_changed = True
            res.image_dirty = True
        res.success = True
        res.facts.append('You draw your sword. Steel glints in the torchlight.')
        if world.pursuer.state in ('present', 'hostile'):
            res.addressed_threat = True
        return res
    res.success = True
    res.facts.append('You fiddle with your gear. The dungeon waits.')
    return res


def _other(world, intent, grounding, rng, res):
    res.success = True
    res.facts.append(
        'You follow through on the impulse. The dungeon accepts the attempt without useful change.')
    return res


def _resolve_junction(world, intent, grounding, rng, res):
    cls = intent.action_class.upper()
    res.interacted = True
    if cls in ('INSPECT', 'SEARCH', 'LOOK') or grounding.bindings.get('target') == 'junction':
        res.meaningful_effort = True
        facts = encounter2.inspect_junction(world)
        res.success = True
        res.situation_changed = True
        res.facts.extend(facts)
        return res
    if cls == 'MOVE':
        dest = grounding.bindings.get('destination') or intent.destination
        res.success = True
        res.facts.append(f'You start toward the {dest or "passage"}. Further dungeon content is not in this POC.')
        world.flags['junction_exit'] = dest or 'west'
        return res
    if cls in ('WAIT', 'SIT'):
        res.success = True
        res.facts.append('You linger at the painted arrow. Distant drips mark the time.')
        return res
    res.success = True
    res.facts.append('At the junction, that action has little purchase in this POC stub.')
    return res


def _resolve_pursuer_action(world, intent, grounding, rng, res):
    cls = intent.action_class.upper()
    p = world.pursuer
    res.interacted = True
    res.addressed_threat = True
    res.meaningful_effort = True

    if p.state not in ('present', 'hostile', 'allied') and cls != 'FLEE':
        res.feasible = True
        res.success = False
        res.rejection_reason = 'no_challenger'
        res.facts.append('There is no challenger here to face.')
        res.addressed_threat = False
        return res

    if cls == 'WARN':
        p.warned_about_traps = True
        p.disposition = 'wary'
        res.success = True
        res.situation_changed = True
        res.facts.append(
            f'You warn {p.name} that the boxes are trapped. He hesitates, glancing at the table.')
        return res
    if cls == 'GIVE':
        if 'trial_key_player' in world.player.inventory:
            world.player.inventory.remove('trial_key_player')
            p.offered_key = True
            p.disposition = 'curious'
            res.success = True
            res.situation_changed = True
            res.facts.append(f'You offer your key. {p.name} takes it, suspicious but no longer swinging.')
            if p.state == 'hostile':
                p.state = 'present'
                p.disposition = 'neutral'
            return res
        res.success = False
        res.facts.append('You have no key left to offer.')
        return res
    if cls == 'NEGOTIATE':
        p.allied = True
        p.state = 'allied'
        p.disposition = 'allied'
        res.success = True
        res.situation_changed = True
        res.facts.append(f'Against the odds, {p.name} agrees to a wary alliance — for now.')
        return res
    if cls == 'SURRENDER':
        res.success = True
        res.facts.append(f'You surrender. {p.name} binds your wrists. The trial ends for you in shame, not death.')
        world.flags['surrendered'] = True
        world.encounter = EncounterId.DONE.value
        return res
    if cls == 'HIDE':
        roll = rng.roll_d20()
        res.checks.append({'label': 'Hide', 'roll': roll, 'dc': 14, 'success': roll >= 14})
        if roll >= 14 and p.state != 'hostile':
            res.success = True
            res.facts.append(f'You slip into shadow. {p.name} curses, searching.')
        else:
            res.success = False
            res.facts.append(f'{p.name} spots you at once.')
            p.state = 'hostile'
            p.disposition = 'hostile'
        return res
    if cls == 'FLEE':
        return _flee(world, intent, grounding, rng, res)
    if cls == 'ATTACK' or p.state == 'hostile':
        return _combat_round(world, intent, rng, res, player_initiates=(cls == 'ATTACK'))
    res.success = True
    res.facts.append(f'{p.name} watches you carefully.')
    return res


def _combat_round(world, intent, rng, res, player_initiates=True):
    res.combat_round = True
    res.addressed_threat = True
    res.meaningful_effort = True
    res.interacted = True
    p = world.pursuer
    p.state = 'hostile'
    p.disposition = 'hostile'
    # Player attack
    if player_initiates or True:
        roll = rng.roll_d20()
        total = roll + world.player.attack_bonus
        hit = total >= 13
        res.checks.append({'label': 'Player attack', 'roll': roll, 'bonus': world.player.attack_bonus,
                           'total': total, 'ac': 13, 'success': hit})
        if hit:
            dmg = rng.randint(1, 8) + 1
            p.hp = max(0, p.hp - dmg)
            res.damage_events.append({'source': 'player', 'amount': dmg})
            res.facts.append(f'You strike {p.name} for {dmg} damage.')
            if p.hp <= 0:
                p.state = 'dead'
                res.success = True
                res.situation_changed = True
                res.image_dirty = True
                res.facts.append(f'{p.name} falls. The passage is yours again.')
                return res
        else:
            res.facts.append(f'Your blow misses {p.name}.')
    # Enemy attack
    eroll = rng.roll_d20()
    etotal = eroll + p.attack_bonus
    ehit = etotal >= world.player.armor_class
    res.checks.append({'label': 'Challenger attack', 'roll': eroll, 'bonus': p.attack_bonus,
                       'total': etotal, 'ac': world.player.armor_class, 'success': ehit})
    if ehit:
        dmg = rng.randint(p.damage[0], p.damage[1])
        world.player.hp = max(0, world.player.hp - dmg)
        res.damage_events.append({'source': 'challenger', 'amount': dmg})
        res.facts.append(f'{p.name} hits you for {dmg} damage.')
        if world.player.hp <= 0:
            world.player.alive = False
            world.encounter = EncounterId.DEAD.value
            res.facts.append('You collapse. Deathtrap Dungeon claims another contestant.')
            res.situation_changed = True
            return res
    else:
        res.facts.append(f'{p.name} swings wide.')
    res.success = player_initiates
    res.situation_changed = True
    res.image_dirty = True
    return res
