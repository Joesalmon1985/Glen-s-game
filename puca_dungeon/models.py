"""Core models: intent, adventure sheet, combat, world state (Fighting Fantasy)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


CLASSIFICATIONS = (
    'MATCH_AUTHORED_ACTION',
    'GENERAL_WORLD_ACTION',
    'PERCEPTION_QUERY',
    'META_REQUEST',
    'SILLY_BUT_VALID',
    'UNINTERPRETABLE',
    'NEEDS_CLARIFICATION',
)


@dataclass
class Intent:
    """Validated semantic intent. Not a narrow verb enum — free action_class string."""
    action_class: str
    target: Optional[str] = None
    tool: Optional[str] = None
    method: Optional[str] = None
    intended_effect: Optional[str] = None
    manner: Optional[str] = None
    destination: Optional[str] = None
    turn_to: Optional[int] = None
    utterance: Optional[str] = None
    sequence: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    understood: bool = True
    notes: str = ''
    classification: str = 'GENERAL_WORLD_ACTION'
    matched_action_id: Optional[str] = None
    confidence: Optional[float] = None
    ambiguities: list = field(default_factory=list)
    needs_clarification: bool = False
    query_focus: Optional[str] = None  # for PERCEPTION_QUERY / META_REQUEST

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AdventureSheet:
    name: str = 'Adventurer'
    skill: int = 0
    skill_initial: int = 0
    stamina: int = 0
    stamina_initial: int = 0
    luck: int = 0
    luck_initial: int = 0
    gold: int = 0
    provisions: int = 0
    inventory: list = field(default_factory=list)
    potion: Optional[str] = None  # potion id from chargen
    potion_used: bool = False
    knowledge: list = field(default_factory=list)
    flags: dict = field(default_factory=dict)
    alive: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CombatState:
    active: bool = False
    enemy_name: str = ''
    enemy_skill: int = 0
    enemy_stamina: int = 0
    enemy_stamina_initial: int = 0
    win_to: Optional[int] = None
    lose_to: Optional[int] = None
    flee_to: Optional[int] = None
    round: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorldState:
    passage_id: int = 1
    sheet: AdventureSheet = field(default_factory=AdventureSheet)
    combat: CombatState = field(default_factory=CombatState)
    last_image_prompt: str = ''
    guidance_level: int = 0
    rng_seed_note: str = ''
    victory: bool = False
    ending: str = ''  # '', 'death', 'victory', or pack ending label
    pending_intents: list = field(default_factory=list)
    turn_index: int = 0

    def to_dict(self) -> dict:
        return world_to_dict(self)

    def clone(self) -> 'WorldState':
        return world_from_dict(self.to_dict())


def world_to_dict(world: WorldState) -> dict:
    return {
        'passage_id': world.passage_id,
        'sheet': world.sheet.to_dict(),
        'combat': world.combat.to_dict(),
        'last_image_prompt': world.last_image_prompt,
        'guidance_level': world.guidance_level,
        'rng_seed_note': world.rng_seed_note,
        'victory': world.victory,
        'ending': world.ending,
        'pending_intents': list(world.pending_intents),
        'turn_index': world.turn_index,
    }


def world_from_dict(data: dict) -> WorldState:
    sheet_data = data.get('sheet') or {}
    combat_data = data.get('combat') or {}
    sheet = AdventureSheet(
        name=sheet_data.get('name', 'Adventurer'),
        skill=int(sheet_data.get('skill', 0) or 0),
        skill_initial=int(sheet_data.get('skill_initial', 0) or 0),
        stamina=int(sheet_data.get('stamina', 0) or 0),
        stamina_initial=int(sheet_data.get('stamina_initial', 0) or 0),
        luck=int(sheet_data.get('luck', 0) or 0),
        luck_initial=int(sheet_data.get('luck_initial', 0) or 0),
        gold=int(sheet_data.get('gold', 0) or 0),
        provisions=int(sheet_data.get('provisions', 0) or 0),
        inventory=list(sheet_data.get('inventory') or []),
        potion=sheet_data.get('potion'),
        potion_used=bool(sheet_data.get('potion_used', False)),
        knowledge=list(sheet_data.get('knowledge') or []),
        flags=dict(sheet_data.get('flags') or {}),
        alive=bool(sheet_data.get('alive', True)),
    )
    combat = CombatState(
        active=bool(combat_data.get('active', False)),
        enemy_name=str(combat_data.get('enemy_name') or ''),
        enemy_skill=int(combat_data.get('enemy_skill', 0) or 0),
        enemy_stamina=int(combat_data.get('enemy_stamina', 0) or 0),
        enemy_stamina_initial=int(combat_data.get('enemy_stamina_initial', 0) or 0),
        win_to=combat_data.get('win_to'),
        lose_to=combat_data.get('lose_to'),
        flee_to=combat_data.get('flee_to'),
        round=int(combat_data.get('round', 0) or 0),
    )
    return WorldState(
        passage_id=int(data.get('passage_id', 1) or 1),
        sheet=sheet,
        combat=combat,
        last_image_prompt=str(data.get('last_image_prompt') or ''),
        guidance_level=int(data.get('guidance_level', 0) or 0),
        rng_seed_note=str(data.get('rng_seed_note') or ''),
        victory=bool(data.get('victory', False)),
        ending=str(data.get('ending') or ''),
        pending_intents=list(data.get('pending_intents') or []),
        turn_index=int(data.get('turn_index', 0) or 0),
    )


def public_perception(world: WorldState, passage: Any = None) -> dict:
    """What the interpreter may see — no hidden effects, private flags, or secret branches."""
    sheet = world.sheet
    perception: dict = {
        'passage_id': world.passage_id,
        'ending': world.ending or None,
        'victory': world.victory,
        'sheet': {
            'name': sheet.name,
            'skill': sheet.skill,
            'stamina': sheet.stamina,
            'stamina_initial': sheet.stamina_initial,
            'luck': sheet.luck,
            'gold': sheet.gold,
            'provisions': sheet.provisions,
            'inventory': list(sheet.inventory),
            'potion': sheet.potion if not sheet.potion_used else None,
            'potion_available': bool(sheet.potion and not sheet.potion_used),
            'knowledge': list(sheet.knowledge),
            'alive': sheet.alive,
        },
        'combat': None,
    }
    if world.combat.active:
        c = world.combat
        perception['combat'] = {
            'enemy_name': c.enemy_name,
            'enemy_skill': c.enemy_skill,
            'enemy_stamina': c.enemy_stamina,
            'round': c.round,
            'can_flee': c.flee_to is not None,
        }

    if passage is not None:
        text = passage.get('text') if isinstance(passage, dict) else getattr(passage, 'text', '')
        choices = passage.get('choices') if isinstance(passage, dict) else getattr(passage, 'choices', [])
        image_seed = (
            passage.get('image_seed') if isinstance(passage, dict)
            else getattr(passage, 'image_seed', '')
        )
        perception['passage'] = {
            'id': (
                passage.get('id') if isinstance(passage, dict)
                else getattr(passage, 'id', world.passage_id)
            ),
            'text': text or '',
            'image_seed': image_seed or '',
            'choice_labels': [
                (c.get('label') if isinstance(c, dict) else getattr(c, 'label', ''))
                for c in (choices or [])
            ],
            # Choice destination numbers are authoring graph — omit from public perception
            'choice_ids': [
                (c.get('id') if isinstance(c, dict) else getattr(c, 'id', ''))
                for c in (choices or [])
            ],
            'has_tests': bool(
                passage.get('tests') if isinstance(passage, dict)
                else getattr(passage, 'tests', None)
            ),
        }
    return perception


def state_diff(before: dict, after: dict, prefix: str = '') -> list[str]:
    """Concise flattened diff of dict trees."""
    lines = []
    keys = sorted(set(before) | set(after))
    for key in keys:
        path = f'{prefix}{key}' if not prefix else f'{prefix}.{key}'
        b, a = before.get(key, None), after.get(key, None)
        if isinstance(b, dict) and isinstance(a, dict):
            lines.extend(state_diff(b, a, path))
        elif b != a:
            lines.append(f'{path}: {b!r} -> {a!r}')
    return lines
