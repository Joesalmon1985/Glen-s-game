"""Level 1 facility: persistent rooms and entities."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from puca_dungeon.enactment import BodyPressures


# Institution phases driven by fictional time + events
PHASE_CELL_IDLE = 'cell_idle'
PHASE_SLIT = 'slit'
PHASE_DOOR = 'door_procedure'
PHASE_REMOVAL = 'removal'
PHASE_WASH = 'wash'
PHASE_FOOD = 'food'
PHASE_RETURN = 'return_cell'
PHASE_SLEEP = 'sleep'
PHASE_DONE = 'done'

# Time thresholds (seconds of fictional time)
SLIT_AT = 180          # ~3 minutes
DOOR_FORCE_AT = 420    # escalate if not cooperating
WASH_DONE_FORCE = 120  # within wash phase
FOOD_DONE_FORCE = 120
SLEEP_FORCE_FATIGUE = 90


@dataclass
class Entity:
    id: str
    name: str
    location: str  # room id or 'inventory' or 'destroyed'
    description: str = ''
    movable: bool = True
    broken: bool = False
    state: dict = field(default_factory=dict)
    contents: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'Entity':
        return cls(
            id=str(data.get('id') or ''),
            name=str(data.get('name') or ''),
            location=str(data.get('location') or ''),
            description=str(data.get('description') or ''),
            movable=bool(data.get('movable', True)),
            broken=bool(data.get('broken', False)),
            state=dict(data.get('state') or {}),
            contents=list(data.get('contents') or []),
        )


@dataclass
class Room:
    id: str
    name: str
    description: str
    exits: dict = field(default_factory=dict)  # dir -> room_id (often locked by phase)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'Room':
        return cls(
            id=str(data.get('id') or ''),
            name=str(data.get('name') or ''),
            description=str(data.get('description') or ''),
            exits=dict(data.get('exits') or {}),
        )


@dataclass
class FacilityState:
    phase: str = PHASE_CELL_IDLE
    room_id: str = 'cell'
    rooms: dict = field(default_factory=dict)  # id -> Room dict
    entities: dict = field(default_factory=dict)  # id -> Entity dict
    pressures: BodyPressures = field(default_factory=BodyPressures)
    slit_open: bool = False
    staff_present: bool = False
    staff_count: int = 0
    washed: bool = False
    fed: bool = False
    slept: bool = False
    cooperated_door: bool = False
    door_escalation: int = 0
    last_npc_utterance: str = ''
    last_understood: str = ''
    book_engaged: bool = False
    phase_entered_at: int = 0  # world_time_seconds when phase began
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'phase': self.phase,
            'room_id': self.room_id,
            'rooms': dict(self.rooms),
            'entities': dict(self.entities),
            'pressures': self.pressures.to_dict(),
            'slit_open': self.slit_open,
            'staff_present': self.staff_present,
            'staff_count': self.staff_count,
            'washed': self.washed,
            'fed': self.fed,
            'slept': self.slept,
            'cooperated_door': self.cooperated_door,
            'door_escalation': self.door_escalation,
            'last_npc_utterance': self.last_npc_utterance,
            'last_understood': self.last_understood,
            'book_engaged': self.book_engaged,
            'phase_entered_at': self.phase_entered_at,
            'notes': list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'FacilityState':
        data = data or {}
        return cls(
            phase=str(data.get('phase') or PHASE_CELL_IDLE),
            room_id=str(data.get('room_id') or 'cell'),
            rooms=dict(data.get('rooms') or {}),
            entities=dict(data.get('entities') or {}),
            pressures=BodyPressures.from_dict(data.get('pressures')),
            slit_open=bool(data.get('slit_open', False)),
            staff_present=bool(data.get('staff_present', False)),
            staff_count=int(data.get('staff_count', 0) or 0),
            washed=bool(data.get('washed', False)),
            fed=bool(data.get('fed', False)),
            slept=bool(data.get('slept', False)),
            cooperated_door=bool(data.get('cooperated_door', False)),
            door_escalation=int(data.get('door_escalation', 0) or 0),
            last_npc_utterance=str(data.get('last_npc_utterance') or ''),
            last_understood=str(data.get('last_understood') or ''),
            book_engaged=bool(data.get('book_engaged', False)),
            phase_entered_at=int(data.get('phase_entered_at', 0) or 0),
            notes=list(data.get('notes') or []),
        )

    def entity(self, eid: str) -> Optional[Entity]:
        raw = self.entities.get(eid)
        if not raw:
            return None
        return Entity.from_dict(raw) if isinstance(raw, dict) else raw

    def set_entity(self, ent: Entity) -> None:
        self.entities[ent.id] = ent.to_dict()

    def entities_in_room(self, room_id: Optional[str] = None) -> list[Entity]:
        rid = room_id or self.room_id
        out = []
        for raw in self.entities.values():
            ent = Entity.from_dict(raw) if isinstance(raw, dict) else raw
            if ent.location == rid:
                out.append(ent)
        return out


def make_initial_facility() -> FacilityState:
    rooms = {
        'cell': Room(
            id='cell',
            name='cell',
            description=(
                'Bed beneath you. Cup beside it. A book face-down on the floor. '
                'The door has no handle on this side. A narrow slit sits at eye height. '
                'Your mouth tastes stale. Your skin feels worse.'
            ),
            exits={},
        ).to_dict(),
        'corridor': Room(
            id='corridor',
            name='corridor',
            description='A plain corridor. Hands on your arms. The institution moves at its own pace.',
            exits={},
        ).to_dict(),
        'washroom': Room(
            id='washroom',
            name='washroom',
            description='Water. A basin. Soap that smells medicinal. Staff wait without patience.',
            exits={},
        ).to_dict(),
        'mess': Room(
            id='mess',
            name='mess',
            description='A narrow table. A bowl of something warm. A spoon.',
            exits={},
        ).to_dict(),
    }
    entities = {
        'bed': Entity(
            id='bed', name='bed', location='cell',
            description='A narrow bed with thin bedding.',
            movable=False,
            state={'bedding': 'on_bed'},
        ).to_dict(),
        'cup': Entity(
            id='cup', name='cup', location='cell',
            description='A plain cup, half-full of water.',
            state={'has_water': True, 'position': 'beside_bed'},
        ).to_dict(),
        'book': Entity(
            id='book', name='book', location='cell',
            description='A badly printed book, face-down on the floor.',
            state={'open': False, 'face_down': True},
        ).to_dict(),
        'door': Entity(
            id='door', name='door', location='cell',
            description='A heavy door with no inner handle and a narrow observation slit.',
            movable=False,
            state={'locked': True, 'slit_open': False},
        ).to_dict(),
        'bowl': Entity(
            id='bowl', name='bowl', location='mess',
            description='A bowl of warm food.',
            state={'full': True},
        ).to_dict(),
        'basin': Entity(
            id='basin', name='basin', location='washroom',
            description='A washbasin with lukewarm water.',
            movable=False,
            state={'water': True},
        ).to_dict(),
    }
    return FacilityState(
        phase=PHASE_CELL_IDLE,
        room_id='cell',
        rooms=rooms,
        entities=entities,
        pressures=BodyPressures(),
    )


OPENING_TEXT = (
    'Bed beneath you. Cup beside it. A book face-down on the floor.\n\n'
    'The door has no handle on this side. A narrow slit sits at eye height.\n\n'
    'Your mouth tastes stale. Your skin feels worse.'
)
