"""Fighting Fantasy dice and Adventure Sheet rules."""
from __future__ import annotations

from typing import Any, Optional, Union

from puca_dungeon.models import AdventureSheet

SheetLike = Union[AdventureSheet, dict]


def roll_die(rng: Any, sides: int = 6) -> int:
    """Roll one die with the given number of sides (inclusive 1..sides)."""
    return int(rng.randint(1, int(sides)))


def roll_dice(rng: Any, n: int, sides: int = 6) -> int:
    """Roll n dice and return the sum."""
    total = 0
    for _ in range(int(n)):
        total += roll_die(rng, sides)
    return total


def _formula_roll(rng: Any, formula: dict) -> int:
    dice = int(formula.get('dice', 1) or 1)
    sides = int(formula.get('sides', 6) or 6)
    add = int(formula.get('add', 0) or 0)
    return roll_dice(rng, dice, sides) + add


def make_adventure_sheet(
    rng: Any,
    name: str = 'Adventurer',
    potion_id: Optional[str] = None,
    chargen: Optional[dict] = None,
) -> AdventureSheet:
    """Roll a classic FF Adventure Sheet from chargen.json formulas."""
    if chargen is None:
        from puca_dungeon.content_loader import load_chargen
        chargen = load_chargen()

    skill = _formula_roll(rng, chargen.get('skill') or {'dice': 1, 'sides': 6, 'add': 6})
    stamina = _formula_roll(rng, chargen.get('stamina') or {'dice': 2, 'sides': 6, 'add': 12})
    luck = _formula_roll(rng, chargen.get('luck') or {'dice': 1, 'sides': 6, 'add': 6})
    gold = _formula_roll(rng, chargen.get('gold_pieces') or {'dice': 1, 'sides': 6, 'add': 0})
    provisions = int(chargen.get('provisions', 10) or 10)
    inventory = list(chargen.get('starting_equipment') or ['sword', 'leather_armour', 'backpack'])

    potions = {p['id']: p for p in (chargen.get('potions') or []) if isinstance(p, dict) and p.get('id')}
    if potion_id is None and potions:
        potion_id = next(iter(potions))
    if potion_id and potion_id not in potions and potions:
        # Allow known ids only when chargen lists potions; otherwise keep requested id
        pass

    display_name = (name or 'Adventurer').strip()[:40] or 'Adventurer'
    return AdventureSheet(
        name=display_name,
        skill=skill,
        skill_initial=skill,
        stamina=stamina,
        stamina_initial=stamina,
        luck=luck,
        luck_initial=luck,
        gold=gold,
        provisions=provisions,
        inventory=inventory,
        potion=potion_id,
        potion_used=False,
        knowledge=[],
        flags={},
        alive=True,
    )


def _get(sheet: SheetLike, key: str, default=None):
    if isinstance(sheet, dict):
        return sheet.get(key, default)
    return getattr(sheet, key, default)


def _set(sheet: SheetLike, key: str, value) -> None:
    if isinstance(sheet, dict):
        sheet[key] = value
    else:
        setattr(sheet, key, value)


def test_luck(sheet: SheetLike, rng: Any) -> tuple[bool, int, int]:
    """Test your Luck: 2d6 <= current Luck → lucky; then Luck -= 1.

    Returns (lucky, roll_total, new_luck).
    """
    roll = roll_dice(rng, 2, 6)
    current = int(_get(sheet, 'luck', 0) or 0)
    lucky = roll <= current
    new_luck = max(0, current - 1)
    _set(sheet, 'luck', new_luck)
    return lucky, roll, new_luck


def test_skill(sheet: SheetLike, rng: Any) -> tuple[bool, int]:
    """Test your Skill: 2d6 <= Skill → success. Returns (success, roll_total)."""
    roll = roll_dice(rng, 2, 6)
    skill = int(_get(sheet, 'skill', 0) or 0)
    return roll <= skill, roll


def combat_round(
    player_skill: int,
    enemy_skill: int,
    rng: Any,
) -> tuple[str, int, int]:
    """One FF combat round.

    Returns (winner, player_attack_strength, enemy_attack_strength)
    where winner is 'player' | 'enemy' | 'tie'.
    """
    player_as = roll_dice(rng, 2, 6) + int(player_skill)
    enemy_as = roll_dice(rng, 2, 6) + int(enemy_skill)
    if player_as > enemy_as:
        winner = 'player'
    elif enemy_as > player_as:
        winner = 'enemy'
    else:
        winner = 'tie'
    return winner, player_as, enemy_as


def apply_stamina_loss(sheet: SheetLike, amount: int) -> int:
    """Subtract stamina; at <= 0 mark dead. Returns new stamina."""
    current = int(_get(sheet, 'stamina', 0) or 0)
    new_stamina = current - int(amount)
    _set(sheet, 'stamina', new_stamina)
    if new_stamina <= 0:
        _set(sheet, 'alive', False)
        _set(sheet, 'stamina', 0)
        return 0
    return new_stamina


def drink_potion(sheet: SheetLike, chargen: Optional[dict] = None) -> dict:
    """Drink the starting potion once. Restores the named score to Initial.

    Potion of Fortune also raises Initial Luck by 1 (classic FF), then restores Luck.
    Returns a result dict with ok / reason / restored field.
    """
    if _get(sheet, 'potion_used'):
        return {'ok': False, 'reason': 'potion_already_used'}
    potion_id = _get(sheet, 'potion')
    if not potion_id:
        return {'ok': False, 'reason': 'no_potion'}

    if chargen is None:
        from puca_dungeon.content_loader import load_chargen
        chargen = load_chargen()

    potions = {p['id']: p for p in (chargen.get('potions') or []) if isinstance(p, dict)}
    meta = potions.get(potion_id) or {}
    restores = meta.get('restores') or _guess_restore(potion_id)

    if restores == 'skill':
        _set(sheet, 'skill', int(_get(sheet, 'skill_initial', 0) or 0))
    elif restores == 'stamina':
        _set(sheet, 'stamina', int(_get(sheet, 'stamina_initial', 0) or 0))
        _set(sheet, 'alive', True)
    elif restores == 'luck':
        initial = int(_get(sheet, 'luck_initial', 0) or 0) + 1
        _set(sheet, 'luck_initial', initial)
        _set(sheet, 'luck', initial)
    else:
        return {'ok': False, 'reason': 'unknown_potion', 'potion_id': potion_id}

    _set(sheet, 'potion_used', True)
    return {'ok': True, 'restores': restores, 'potion_id': potion_id}


def _guess_restore(potion_id: str) -> Optional[str]:
    pid = (potion_id or '').lower()
    if 'skill' in pid:
        return 'skill'
    if 'strength' in pid or 'stamina' in pid:
        return 'stamina'
    if 'fortune' in pid or 'luck' in pid:
        return 'luck'
    return None


def eat_provision(sheet: SheetLike, restore: int = 4) -> dict:
    """Eat one provision; restore stamina up to Initial (default +4)."""
    provisions = int(_get(sheet, 'provisions', 0) or 0)
    if provisions <= 0:
        return {'ok': False, 'reason': 'no_provisions'}
    if not _get(sheet, 'alive', True):
        return {'ok': False, 'reason': 'dead'}

    stamina = int(_get(sheet, 'stamina', 0) or 0)
    initial = int(_get(sheet, 'stamina_initial', 0) or 0)
    new_stamina = min(initial, stamina + int(restore))
    _set(sheet, 'stamina', new_stamina)
    _set(sheet, 'provisions', provisions - 1)
    return {
        'ok': True,
        'stamina': new_stamina,
        'provisions': provisions - 1,
        'restored': new_stamina - stamina,
    }
