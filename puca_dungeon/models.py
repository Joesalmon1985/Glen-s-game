"""Core models: intent, entities, world state."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class EncounterId(str, Enum):
    WALK_BOXES = 'walk_boxes'  # Encounter 1
    JUNCTION = 'junction'      # Encounter 2 stub
    DEAD = 'dead'
    DONE = 'done'


class PursuerState(str, Enum):
    ABSENT = 'absent'
    APPROACHING = 'approaching'
    CLOSE = 'close'
    PRESENT = 'present'
    HOSTILE = 'hostile'
    DEAD = 'dead'
    ALLIED = 'allied'
    FLED = 'fled'


class BoxId(str, Enum):
    PLAYER = 'box_player'
    A = 'box_a'
    B = 'box_b'
    C = 'box_c'
    D = 'box_d'
    E = 'box_e'


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
class BoxState:
    id: str
    label: str  # display / name on box
    is_player_box: bool = False
    open: bool = False
    locked: bool = True
    trap_present: bool = True
    trap_discovered: bool = False
    trap_disabled: bool = False
    trap_fired: bool = False
    hardness: int = 10
    hp: int = 10
    destroyed: bool = False
    contents_taken: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PlayerState:
    name: str = 'Adventurer'
    location: str = EncounterId.WALK_BOXES.value
    gold: int = 0
    hp: int = 20
    max_hp: int = 20
    alive: bool = True
    inventory: list = field(default_factory=lambda: ['trial_key_player', 'sword'])
    knowledge: list = field(default_factory=list)
    search_bonus: int = 0
    disable_bonus: int = 0
    open_lock_bonus: int = 0
    attack_bonus: int = 2
    armor_class: int = 14

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Pursuer:
    """POC addition: anti-stall challenger inspired by prior contestants, not canonical text."""
    state: str = PursuerState.ABSENT.value
    kind: str = 'barbarian'
    name: str = 'Grimnak'
    location: Optional[str] = None
    disposition: str = 'neutral'
    hp: int = 18
    max_hp: int = 18
    attack_bonus: int = 4
    damage: tuple = (1, 8)
    warned_about_traps: bool = False
    offered_key: bool = False
    allied: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data['damage'] = list(self.damage)
        return data


@dataclass
class WorldState:
    encounter: str = EncounterId.WALK_BOXES.value
    player: PlayerState = field(default_factory=PlayerState)
    boxes: dict = field(default_factory=dict)
    pursuer: Pursuer = field(default_factory=Pursuer)
    world_time_seconds: int = 0
    pursuer_trigger_at: int = 90   # Stage 1 after this much stall/futile time
    pursuer_close_at: int = 150
    pursuer_arrive_at: int = 210
    pursuer_escalate_at: int = 270
    stall_time_seconds: int = 0    # accumulated unproductive fictional time
    clue_get_no_mess: bool = False
    junction_inspected: bool = False
    pending_intents: list = field(default_factory=list)
    image_key: str = ''
    last_image_prompt: str = ''
    visible_entities: list = field(default_factory=list)
    flags: dict = field(default_factory=dict)
    turn_index: int = 0
    guidance_level: int = 0  # 0–4; hidden from normal play; separate from world pressure

    def to_dict(self) -> dict:
        return {
            'encounter': self.encounter,
            'player': self.player.to_dict(),
            'boxes': {k: v.to_dict() for k, v in self.boxes.items()},
            'pursuer': self.pursuer.to_dict(),
            'world_time_seconds': self.world_time_seconds,
            'pursuer_trigger_at': self.pursuer_trigger_at,
            'pursuer_close_at': self.pursuer_close_at,
            'pursuer_arrive_at': self.pursuer_arrive_at,
            'pursuer_escalate_at': self.pursuer_escalate_at,
            'stall_time_seconds': self.stall_time_seconds,
            'clue_get_no_mess': self.clue_get_no_mess,
            'junction_inspected': self.junction_inspected,
            'pending_intents': self.pending_intents,
            'image_key': self.image_key,
            'last_image_prompt': self.last_image_prompt,
            'visible_entities': list(self.visible_entities),
            'flags': dict(self.flags),
            'turn_index': self.turn_index,
            'guidance_level': self.guidance_level,
        }

    def clone(self) -> 'WorldState':
        return world_from_dict(self.to_dict())


def world_from_dict(data: dict) -> WorldState:
    player = PlayerState(**data['player'])
    boxes = {k: BoxState(**v) for k, v in data['boxes'].items()}
    p = data['pursuer']
    pursuer = Pursuer(
        state=p['state'], kind=p.get('kind', 'barbarian'), name=p.get('name', 'Grimnak'),
        location=p.get('location'), disposition=p.get('disposition', 'neutral'),
        hp=p.get('hp', 18), max_hp=p.get('max_hp', 18), attack_bonus=p.get('attack_bonus', 4),
        damage=tuple(p.get('damage', (1, 8))), warned_about_traps=p.get('warned_about_traps', False),
        offered_key=p.get('offered_key', False), allied=p.get('allied', False),
    )
    return WorldState(
        encounter=data['encounter'], player=player, boxes=boxes, pursuer=pursuer,
        world_time_seconds=data.get('world_time_seconds', 0),
        pursuer_trigger_at=data.get('pursuer_trigger_at', 90),
        pursuer_close_at=data.get('pursuer_close_at', 150),
        pursuer_arrive_at=data.get('pursuer_arrive_at', 210),
        pursuer_escalate_at=data.get('pursuer_escalate_at', 270),
        stall_time_seconds=data.get('stall_time_seconds', 0),
        clue_get_no_mess=data.get('clue_get_no_mess', False),
        junction_inspected=data.get('junction_inspected', False),
        pending_intents=list(data.get('pending_intents') or []),
        image_key=data.get('image_key', ''),
        last_image_prompt=data.get('last_image_prompt', ''),
        visible_entities=list(data.get('visible_entities') or []),
        flags=dict(data.get('flags') or {}),
        turn_index=data.get('turn_index', 0),
        guidance_level=int(data.get('guidance_level', 0) or 0),
    )


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


# Mechanics constants (source-derived for Encounter 1 boxes)
SEARCH_DC = 25
DISABLE_DC = 25
OPEN_LOCK_DC = 35
POISON_DART_DAMAGE = (4, 10)  # 4d something simplified: flat range
CLUE_TEXT = (
    "Sukumvit's clue: 'In Deathtrap Dungeon, trust neither the obvious door "
    "nor the first gift. Keep your key close.'"
)
