"""Core models: intent, adventure sheet, combat, world state (Fighting Fantasy)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


CLASSIFICATIONS = (
    'MATCH_AUTHORED_ACTION',
    'SYSTEMIC_ACTION',
    'AUTHORED_CANDIDATE',
    'IMPOSSIBLE_ATTEMPT',
    'UNGROUNDED_ENTITY',
    'META_INPUT',
    'META_REQUEST',  # compat alias of META_INPUT
    'PERCEPTION_QUERY',
    'SOCIAL_ACTION',
    'COMPOUND_ACTION',
    'NEEDS_CLARIFICATION',
    'NO_ACTIONABLE_INTENT',
    'GENERAL_WORLD_ACTION',  # compat
    'UNINTERPRETABLE',
)

# META_REQUEST is kept as a classification string for older callers;
# treat it as equivalent to META_INPUT in validation / routing.
META_CLASSIFICATIONS = frozenset({'META_INPUT', 'META_REQUEST'})


def _default_body_state() -> dict:
    return {
        'locomotion': 'normal',
        'pain': 'none',
        'bleeding': 'none',
        'grip': 'firm',
    }


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
    query_focus: Optional[str] = None  # for PERCEPTION_QUERY / META_INPUT

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
    injuries: list = field(default_factory=list)
    body_state: dict = field(default_factory=_default_body_state)

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
    world_time_seconds: int = 0
    pending_discourse: Optional[dict] = None
    # pending_discourse: {shape:'binary'|'exclusive_choice', prompt, options:[{id,label}], antecedent}
    visible_entities: list = field(default_factory=list)
    aftermath: dict = field(default_factory=dict)
    # Dual-mode Level 1 + book dungeon
    mode: str = 'facility'  # facility | book_dungeon
    facility: Any = None
    dungeon_layout: Optional[dict] = None
    book_bookmark: Optional[dict] = None  # {world, layout} snapshot while reading
    layout_seed: Optional[int] = None

    def to_dict(self) -> dict:
        return world_to_dict(self)

    def clone(self) -> 'WorldState':
        return world_from_dict(self.to_dict())


def world_to_dict(world: WorldState) -> dict:
    facility = world.facility
    facility_dict = None
    if facility is not None:
        facility_dict = facility.to_dict() if hasattr(facility, 'to_dict') else dict(facility)
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
        'world_time_seconds': int(world.world_time_seconds or 0),
        'pending_discourse': (
            dict(world.pending_discourse) if isinstance(world.pending_discourse, dict) else None
        ),
        'visible_entities': list(world.visible_entities or []),
        'aftermath': dict(world.aftermath or {}),
        'mode': str(world.mode or 'facility'),
        'facility': facility_dict,
        'dungeon_layout': dict(world.dungeon_layout) if world.dungeon_layout else None,
        'book_bookmark': dict(world.book_bookmark) if world.book_bookmark else None,
        'layout_seed': world.layout_seed,
    }


def _inventory_names(inventory: list) -> list[str]:
    names: list[str] = []
    for item in inventory or []:
        if isinstance(item, dict):
            name = item.get('name') or item.get('id') or item.get('label') or ''
            if name:
                names.append(str(name))
        elif item is not None:
            names.append(str(item))
    return names


def _qualitative_body(sheet: AdventureSheet) -> dict:
    body = dict(sheet.body_state or {})
    for key in ('locomotion', 'pain', 'bleeding', 'grip'):
        body.setdefault(key, _default_body_state()[key])
    return {
        'locomotion': body.get('locomotion', 'normal'),
        'pain': body.get('pain', 'none'),
        'bleeding': body.get('bleeding', 'none'),
        'grip': body.get('grip', 'firm'),
        'injury_count': len(sheet.injuries or []),
    }


def _discourse_summary(pending: Optional[dict]) -> Optional[dict]:
    if not isinstance(pending, dict):
        return None
    shape = str(pending.get('shape') or '')
    options = pending.get('options') or []
    labels = []
    for opt in options:
        if isinstance(opt, dict):
            label = opt.get('label') or opt.get('id') or ''
            if label:
                labels.append(str(label))
        elif opt:
            labels.append(str(opt))
    return {
        'shape': shape,
        'prompt': str(pending.get('prompt') or ''),
        'option_labels': labels,
        'awaiting_reply': True,
    }


def world_from_dict(data: dict) -> WorldState:
    sheet_data = data.get('sheet') or {}
    combat_data = data.get('combat') or {}
    body_raw = sheet_data.get('body_state')
    if isinstance(body_raw, dict) and body_raw:
        body_state = dict(_default_body_state())
        body_state.update(body_raw)
    else:
        body_state = _default_body_state()
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
        injuries=list(sheet_data.get('injuries') or []),
        body_state=body_state,
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
    pending = data.get('pending_discourse')
    if pending is not None and not isinstance(pending, dict):
        pending = None
    facility_raw = data.get('facility')
    facility = None
    if isinstance(facility_raw, dict):
        from puca_dungeon.facility_models import FacilityState
        facility = FacilityState.from_dict(facility_raw)
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
        world_time_seconds=int(data.get('world_time_seconds', 0) or 0),
        pending_discourse=dict(pending) if isinstance(pending, dict) else None,
        visible_entities=list(data.get('visible_entities') or []),
        aftermath=dict(data.get('aftermath') or {}),
        mode=str(data.get('mode') or 'facility'),
        facility=facility,
        dungeon_layout=dict(data['dungeon_layout']) if isinstance(data.get('dungeon_layout'), dict) else None,
        book_bookmark=dict(data['book_bookmark']) if isinstance(data.get('book_bookmark'), dict) else None,
        layout_seed=int(data['layout_seed']) if data.get('layout_seed') is not None else None,
    )


def public_perception(
    world: WorldState,
    passage: Any = None,
    stage: str = 'full',
) -> dict:
    """What the interpreter may see.

    stage 'neutral' / 'A': no authored menu cues, no sheet combat numbers.
    stage 'full' (default): debug-oriented; sheet numbers allowed, combat still qualitative.
    """
    stage_key = (stage or 'full').strip().lower()
    neutral = stage_key in ('neutral', 'a', 'stage_a', 'stage-a')
    sheet = world.sheet
    inventory_names = _inventory_names(sheet.inventory)

    perception: dict = {
        'passage_id': world.passage_id,
        'ending': world.ending or None,
        'victory': world.victory,
        'world_time_seconds': int(world.world_time_seconds or 0),
        'visible_entities': list(world.visible_entities or []),
        'body_state': _qualitative_body(sheet),
        'combat': None,
        'discourse': _discourse_summary(world.pending_discourse),
    }

    if neutral:
        perception['sheet'] = {
            'name': sheet.name,
            'inventory': inventory_names,
            'potion_available': bool(sheet.potion and not sheet.potion_used),
            'alive': sheet.alive,
            'body_state': _qualitative_body(sheet),
        }
    else:
        perception['sheet'] = {
            'name': sheet.name,
            'skill': sheet.skill,
            'stamina': sheet.stamina,
            'stamina_initial': sheet.stamina_initial,
            'luck': sheet.luck,
            'gold': sheet.gold,
            'provisions': sheet.provisions,
            'inventory': list(sheet.inventory),
            'inventory_names': inventory_names,
            'potion': sheet.potion if not sheet.potion_used else None,
            'potion_available': bool(sheet.potion and not sheet.potion_used),
            'knowledge': list(sheet.knowledge),
            'alive': sheet.alive,
            'body_state': _qualitative_body(sheet),
            'injuries': list(sheet.injuries or []),
        }

    if world.combat.active:
        c = world.combat
        # Prefer qualitative combat even in full/debug; never expose SKILL/STAMINA here for stage A.
        perception['combat'] = {
            'enemy_name': c.enemy_name,
            'active': True,
            'can_flee': c.flee_to is not None,
        }
        if not neutral:
            perception['combat']['round'] = c.round
            perception['combat']['enemy_hurt'] = (
                int(c.enemy_stamina_initial or 0) > 0
                and int(c.enemy_stamina or 0) < int(c.enemy_stamina_initial or 0)
            )

    if passage is not None:
        text = passage.get('text') if isinstance(passage, dict) else getattr(passage, 'text', '')
        choices = passage.get('choices') if isinstance(passage, dict) else getattr(passage, 'choices', [])
        image_seed = (
            passage.get('image_seed') if isinstance(passage, dict)
            else getattr(passage, 'image_seed', '')
        )
        atmosphere = (
            passage.get('atmosphere') if isinstance(passage, dict)
            else getattr(passage, 'atmosphere', None)
        )
        if atmosphere is None:
            atmosphere = image_seed or ''
        passage_block: dict = {
            'id': (
                passage.get('id') if isinstance(passage, dict)
                else getattr(passage, 'id', world.passage_id)
            ),
            'text': text or '',
            'atmosphere': atmosphere or '',
            'visible_atmosphere': atmosphere or '',
        }
        if not neutral:
            passage_block['image_seed'] = image_seed or ''
            passage_block['choice_labels'] = [
                (c.get('label') if isinstance(c, dict) else getattr(c, 'label', ''))
                for c in (choices or [])
            ]
            passage_block['choice_ids'] = [
                (c.get('id') if isinstance(c, dict) else getattr(c, 'id', ''))
                for c in (choices or [])
            ]
            passage_block['has_tests'] = bool(
                passage.get('tests') if isinstance(passage, dict)
                else getattr(passage, 'tests', None)
            )
        perception['passage'] = passage_block

    if world.aftermath:
        # Aftermath may inform image/narrator; keep values qualitative-facing.
        perception['aftermath_keys'] = sorted(str(k) for k in world.aftermath.keys())

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
