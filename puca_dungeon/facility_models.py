"""Level 1 facility: persistent rooms, entities, cast, and opening-arc state."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from puca_dungeon.arc_state import ArcState
from puca_dungeon.characters import generate_cast, schedule_subject_encounters
from puca_dungeon.enactment import BodyPressures
from puca_dungeon.rng import GameRNG


# Institution phases driven by fictional time + events
PHASE_CELL_IDLE = 'cell_idle'
PHASE_SLIT = 'slit'
PHASE_DOOR = 'door_procedure'
PHASE_REMOVAL = 'removal'
PHASE_WASH = 'wash'
PHASE_FOOD = 'food'
PHASE_RETURN = 'return_cell'
PHASE_SLEEP = 'sleep'
PHASE_DONE = 'done'  # legacy alias; sleep now wakes into day2
PHASE_DAY2_WAKE = 'day2_wake'
PHASE_RETRIEVAL = 'retrieval'
PHASE_INTERVIEW = 'interview'
PHASE_MEMORY_INSTABILITY = 'memory_instability'
PHASE_DEATH_QUESTIONS = 'death_questions'
PHASE_HEAVEN_MEMORIES = 'heaven_memories'
PHASE_HELL_MEMORIES = 'hell_memories'
PHASE_EXPLANATION = 'explanation'
PHASE_CONTRACT = 'contract'
PHASE_PREP_TRANSFER = 'prep_transfer'
PHASE_HEAVEN = 'heaven'
PHASE_HEAVEN_EXPIRE = 'heaven_expire'
PHASE_HELL = 'hell'
PHASE_SECOND_OFFER = 'second_offer'
PHASE_CONTRACT_PROCESSING = 'contract_processing'
PHASE_RESEARCH = 'research'

# Time thresholds (seconds of fictional time)
SLIT_AT = 180
DOOR_FORCE_AT = 420
WASH_DONE_FORCE = 120
FOOD_DONE_FORCE = 120
SLEEP_FORCE_FATIGUE = 90
DAY2_RETRIEVE_AT = 25
INTERVIEW_FORCE = 30
PHASE_FORCE = 30
HEAVEN_FORCE = 80
HELL_FORCE = 80


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
    exits: dict = field(default_factory=dict)

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


def _default_rooms() -> dict:
    return {
        'cell': Room(
            id='cell', name='cell',
            description=(
                'Bed beneath you. Cup beside it. A book face-down on the floor. '
                'The door has no handle on this side. A narrow slit sits at eye height. '
                'Your mouth tastes stale. Your skin feels worse.'
            ),
        ).to_dict(),
        'corridor': Room(
            id='corridor', name='corridor',
            description=(
                'A plain corridor. The same bolts as the cell door. '
                'Hands on your arms. The institution moves at its own pace.'
            ),
        ).to_dict(),
        'washroom': Room(
            id='washroom', name='washroom',
            description='Water. A basin. Soap that smells medicinal. Staff wait without patience.',
        ).to_dict(),
        'mess': Room(
            id='mess', name='mess',
            description='A narrow table. A bowl of something warm. A spoon.',
        ).to_dict(),
        'interview': Room(
            id='interview', name='interview',
            description=(
                'A brighter room. A table. Images and objects laid out like a lesson. '
                'A person with a fitted collar sits opposite you.'
            ),
        ).to_dict(),
        'prep': Room(
            id='prep', name='prep',
            description=(
                'Machines hum. Straps hang unused. A tray of clean instruments. '
                'They call this preparation for transition.'
            ),
        ).to_dict(),
        'heaven': Room(
            id='heaven', name='heaven',
            description=(
                'Warm air. Sunlight through leaves. Clean bedding. Fruit. Running water. '
                'Quiet enough to hear birds that may or may not be real. '
                'It is physically here. They encourage you to believe only your mind arrived.'
            ),
        ).to_dict(),
        'hell': Room(
            id='hell', name='hell',
            description=(
                'The air is wrong — heat and a foul sweetness. Light that never rests, or none. '
                'A rough sleeping surface. A grate with the same bolt pattern as the cell. '
                'Someone designed this. There are no demons. Only engineering.'
            ),
        ).to_dict(),
        'research_quarters': Room(
            id='research_quarters', name='research_quarters',
            description=(
                'A small subject room in the research wing. A bed. A desk. The book if you kept it. '
                'You are registered. The next work has not begun.'
            ),
        ).to_dict(),
    }


def _default_entities() -> dict:
    return {
        'bed': Entity(
            id='bed', name='bed', location='cell',
            description='A narrow bed with thin bedding.',
            movable=False, state={'bedding': 'on_bed'},
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
            movable=False, state={'locked': True, 'slit_open': False},
        ).to_dict(),
        'bowl': Entity(
            id='bowl', name='bowl', location='mess',
            description='A bowl of warm food.',
            state={'full': True},
        ).to_dict(),
        'basin': Entity(
            id='basin', name='basin', location='washroom',
            description='A washbasin with lukewarm water.',
            movable=False, state={'water': True},
        ).to_dict(),
        'fruit': Entity(
            id='fruit', name='fruit', location='heaven',
            description='A bowl of clean fruit, cold to the touch.',
            state={'full': True},
        ).to_dict(),
        'fountain': Entity(
            id='fountain', name='fountain', location='heaven',
            description='Running water. The fixture uses the same fittings as the washroom basin.',
            movable=False, state={},
        ).to_dict(),
        'heaven_bed': Entity(
            id='heaven_bed', name='bed', location='heaven',
            description='Soft clean bedding in warm light.',
            movable=False, state={},
        ).to_dict(),
        'grate': Entity(
            id='grate', name='grate', location='hell',
            description='A ventilation grate. The bolts match the cell door.',
            movable=False, state={},
        ).to_dict(),
        'hell_mat': Entity(
            id='hell_mat', name='mat', location='hell',
            description='A sleeping surface that is not meant for sleep.',
            movable=False, state={},
        ).to_dict(),
        'fixture': Entity(
            id='fixture', name='fixture', location='hell',
            description='A pipe joint stamped with the same institutional mark as the washroom.',
            movable=False, state={},
        ).to_dict(),
    }


@dataclass
class FacilityState:
    phase: str = PHASE_CELL_IDLE
    room_id: str = 'cell'
    rooms: dict = field(default_factory=dict)
    entities: dict = field(default_factory=dict)
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
    phase_entered_at: int = 0
    notes: list = field(default_factory=list)
    cast: dict = field(default_factory=dict)
    arc: ArcState = field(default_factory=ArcState)

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
            'cast': dict(self.cast),
            'arc': self.arc.to_dict() if hasattr(self.arc, 'to_dict') else dict(self.arc or {}),
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'FacilityState':
        data = data or {}
        rooms = dict(data.get('rooms') or {})
        if not rooms:
            rooms = _default_rooms()
        entities = dict(data.get('entities') or {})
        if not entities:
            entities = _default_entities()
        return cls(
            phase=str(data.get('phase') or PHASE_CELL_IDLE),
            room_id=str(data.get('room_id') or 'cell'),
            rooms=rooms,
            entities=entities,
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
            cast=dict(data.get('cast') or {}),
            arc=ArcState.from_dict(data.get('arc')),
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

    def character_name(self, cid: str) -> str:
        raw = (self.cast or {}).get(cid) or {}
        return str(raw.get('name') or cid)


def make_initial_facility(rng: Any = None, claimed_name: str = '') -> FacilityState:
    if rng is None:
        rng = GameRNG.from_seed(91)
    cast = generate_cast(rng)
    schedule = schedule_subject_encounters(rng)
    arc = ArcState(
        encounter_schedule=schedule,
        claimed_name=claimed_name,
        situation_line='You wake in a small room. Nothing is happening yet.',
        body_marks=['a faint bruise on the forearm'],
    )
    return FacilityState(
        phase=PHASE_CELL_IDLE,
        room_id='cell',
        rooms=_default_rooms(),
        entities=_default_entities(),
        pressures=BodyPressures(),
        cast=cast,
        arc=arc,
    )


OPENING_TEXT = (
    'Bed beneath you. Cup beside it. A book face-down on the floor.\n\n'
    'The door has no handle on this side. A narrow slit sits at eye height.\n\n'
    'Your mouth tastes stale. Your skin feels worse.\n\n'
    'You are in a small locked room. Nothing is happening yet.'
)
