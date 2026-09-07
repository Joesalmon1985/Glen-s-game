"""Synthetic facility worlds covering rooms, prop states, and staff/player poses."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Optional

from puca_dungeon.facility_models import FacilityState, make_initial_facility
from puca_dungeon.ff_rules import make_adventure_sheet
from puca_dungeon.models import WorldState
from puca_dungeon.rng import GameRNG
from puca_dungeon.scene_compose import (
    _player_sprite_id,
    _prop_sprite_for_entity,
    _staff_sprite_ids,
)
from puca_dungeon.visual_catalog import load_catalog


@dataclass
class FixtureScene:
    fixture_id: str
    room_id: str
    world: WorldState
    expected_sprite_ids: set[str]
    label: str = ''

    def to_dict(self) -> dict:
        return {
            'fixture_id': self.fixture_id,
            'room_id': self.room_id,
            'label': self.label,
            'expected_sprite_ids': sorted(self.expected_sprite_ids),
        }


def _base_world(seed: int = 91) -> WorldState:
    rng = GameRNG.from_seed(seed)
    fac = make_initial_facility(rng)
    sheet = make_adventure_sheet(rng)
    return WorldState(sheet=sheet, facility=fac, mode='facility', passage_id=0)


def _set_entity_state(fac: FacilityState, eid: str, **updates: Any) -> None:
    ent = fac.entity(eid)
    if ent is None:
        return
    for key, value in updates.items():
        if key == 'broken':
            ent.broken = bool(value)
        elif key == 'location':
            ent.location = str(value)
        else:
            ent.state[key] = value
    fac.set_entity(ent)


def _expected_from_world(world: WorldState, catalog: Optional[dict] = None) -> set[str]:
    cat = catalog or load_catalog()
    fac = world.facility
    assert fac is not None
    room_id = str(fac.room_id or 'cell')
    layouts = cat.get('layouts') or {}
    layout = dict(layouts.get(room_id) or {})
    bg = str(layout.get('background') or room_id)
    expected = {bg}
    for entity in fac.entities_in_room():
        sprite_id, _slot = _prop_sprite_for_entity(entity, fac)
        if sprite_id:
            expected.add(sprite_id)
    for sid in _staff_sprite_ids(fac):
        expected.add(sid)
    expected.add(_player_sprite_id(world))
    return expected


def fixture_for_room(
    room_id: str,
    *,
    staff_count: int = 0,
    crowded: bool = True,
    seed: int = 91,
) -> FixtureScene:
    world = _base_world(seed)
    fac = world.facility
    assert fac is not None
    fac.room_id = room_id
    fac.staff_present = staff_count > 0
    fac.staff_count = staff_count
    if staff_count:
        present = []
        if staff_count >= 1:
            present.append('orderly_quiet')
        if staff_count >= 2:
            present.append('senior_researcher')
        fac.arc.present_ids = present

    # Ensure room-local entities keep their default locations; nothing to move for corridor/interview/prep
    label = f'{room_id}_staff{staff_count}' + ('_crowded' if crowded else '_sparse')
    if not crowded:
        # Move non-essential props out for sparse (cell keeps door)
        for eid in list(fac.entities.keys()):
            ent = fac.entity(eid)
            if ent is None:
                continue
            if ent.location == room_id and eid not in ('door', 'bed', 'basin', 'bowl', 'heaven_bed', 'hell_mat'):
                if room_id == 'cell' and eid in ('cup', 'book'):
                    ent.location = 'inventory'
                    fac.set_entity(ent)

    expected = _expected_from_world(world)
    return FixtureScene(
        fixture_id=label,
        room_id=room_id,
        world=world,
        expected_sprite_ids=expected,
        label=label,
    )


def cell_state_variants(seed: int = 91) -> list[FixtureScene]:
    """Cover prop state → sprite_id mapping for the cell."""
    out: list[FixtureScene] = []

    def add(fid: str, mutator) -> None:
        world = _base_world(seed)
        fac = world.facility
        assert fac is not None
        mutator(world, fac)
        out.append(FixtureScene(
            fixture_id=fid,
            room_id='cell',
            world=world,
            expected_sprite_ids=_expected_from_world(world),
            label=fid,
        ))

    add('cell_default', lambda w, f: None)
    add('cell_cup_empty', lambda w, f: _set_entity_state(f, 'cup', has_water=False))
    add('cell_cup_broken_floor', lambda w, f: (
        _set_entity_state(f, 'cup', broken=True, position='on_floor', has_water=False)
    ))
    add('cell_book_open', lambda w, f: _set_entity_state(f, 'book', open=True, face_down=False))
    add('cell_book_closed', lambda w, f: _set_entity_state(f, 'book', open=False, face_down=False))
    add('cell_bedding_floor', lambda w, f: _set_entity_state(f, 'bed', bedding='on_floor'))
    add('cell_slit_open', lambda w, f: (
        setattr(f, 'slit_open', True),
        _set_entity_state(f, 'door', slit_open=True),
    ))
    add('cell_staff2', lambda w, f: (
        setattr(f, 'staff_present', True),
        setattr(f, 'staff_count', 2),
        setattr(f.arc, 'present_ids', ['orderly_anxious', 'senior_researcher']),
    ))
    add('cell_player_wounded', lambda w, f: (
        setattr(w.sheet, 'injuries', ['bruise']),
        w.sheet.body_state.update({'pain': 'mild'}),
    ))
    add('cell_player_fallen', lambda w, f: setattr(w.sheet, 'alive', False))
    return out


def all_fixtures(catalog: Optional[dict] = None, seed: int = 91) -> list[FixtureScene]:
    cat = catalog or load_catalog()
    rooms = list((cat.get('layouts') or {}).keys())
    fixtures: list[FixtureScene] = []
    fixtures.extend(cell_state_variants(seed=seed))
    for room_id in rooms:
        if room_id == 'cell':
            continue
        fixtures.append(fixture_for_room(room_id, staff_count=0, crowded=True, seed=seed))
        fixtures.append(fixture_for_room(room_id, staff_count=1, crowded=True, seed=seed))
        if room_id in ('mess', 'washroom', 'heaven', 'hell'):
            fixtures.append(fixture_for_room(room_id, staff_count=2, crowded=True, seed=seed))
    # Deduplicate by fixture_id
    seen: set[str] = set()
    unique: list[FixtureScene] = []
    for fx in fixtures:
        if fx.fixture_id in seen:
            continue
        seen.add(fx.fixture_id)
        unique.append(fx)
    return unique


def apply_layout_override(catalog: dict, room_id: str, slots: dict[str, list[int]]) -> dict:
    """Return a deep-copied catalog with layout slots replaced for one room."""
    cat = deepcopy(catalog)
    layouts = cat.setdefault('layouts', {})
    layout = dict(layouts.get(room_id) or {})
    layout['slots'] = {k: list(v) for k, v in slots.items()}
    if 'background' not in layout:
        layout['background'] = room_id
    layouts[room_id] = layout
    return cat


def layout_delta_variants(
    base_slots: dict[str, list[int]],
    *,
    suggested: Optional[list[dict[str, list[int]]]] = None,
    deltas: tuple[int, ...] = (-32, -16, 16, 32),
) -> list[tuple[str, dict[str, list[int]]]]:
    """Build named layout slot variants for bakeoffs."""
    variants: list[tuple[str, dict[str, list[int]]]] = [
        ('current', {k: list(v) for k, v in base_slots.items()}),
    ]
    focus = [k for k in ('player', 'staff_0', 'staff_1', 'bed', 'cup', 'door', 'book') if k in base_slots]
    if not focus:
        focus = list(base_slots.keys())[:4]

    for slot in focus[:4]:
        x0, y0 = int(base_slots[slot][0]), int(base_slots[slot][1])
        for d in deltas:
            slots = {k: list(v) for k, v in base_slots.items()}
            slots[slot] = [x0 + d, y0]
            variants.append((f'{slot}_x{d:+d}', slots))
            slots_y = {k: list(v) for k, v in base_slots.items()}
            slots_y[slot] = [x0, y0 + d]
            variants.append((f'{slot}_y{d:+d}', slots_y))

    for i, nudge in enumerate(suggested or []):
        slots = {k: list(v) for k, v in base_slots.items()}
        for key, delta in nudge.items():
            if key not in slots:
                continue
            slots[key] = [
                int(slots[key][0]) + int(delta[0]),
                int(slots[key][1]) + int(delta[1]),
            ]
        variants.append((f'vlm_nudge_{i}', slots))
    return variants
