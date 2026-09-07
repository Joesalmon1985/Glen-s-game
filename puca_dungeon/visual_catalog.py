"""Load the facility sprite catalog (graphics only; no game logic)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG_PATH = _ROOT / 'assets' / 'sprites' / 'catalog.json'
DEFAULT_ASSETS_ROOT = _ROOT / 'assets' / 'sprites'


@lru_cache(maxsize=4)
def load_catalog(path: Optional[str] = None) -> dict[str, Any]:
    catalog_path = Path(path) if path else DEFAULT_CATALOG_PATH
    if not catalog_path.is_file():
        raise FileNotFoundError(f'Sprite catalog missing: {catalog_path}')
    data = json.loads(catalog_path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Sprite catalog must be a JSON object')
    return data


def assets_root(catalog: Optional[dict] = None, root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    return DEFAULT_ASSETS_ROOT


def iter_sprite_jobs(catalog: Optional[dict] = None) -> list[dict[str, Any]]:
    """Flatten catalog into generateable sprite jobs for the batch CLI."""
    cat = catalog or load_catalog()
    style = str(cat.get('style') or '')
    negative = str(cat.get('negative_prompt') or '')
    jobs: list[dict[str, Any]] = []

    def add(kind: str, sprite_id: str, entry: dict) -> None:
        file_rel = str(entry.get('file') or '')
        prompt = str(entry.get('prompt') or '')
        if not file_rel or not prompt:
            return
        jobs.append({
            'kind': kind,
            'id': sprite_id,
            'file': file_rel,
            'prompt': prompt,
            'style': style,
            'negative_prompt': negative,
            'size': list(entry.get('size') or ([512, 512] if kind == 'background' else [96, 96])),
        })

    for sid, entry in (cat.get('backgrounds') or {}).items():
        add('background', str(sid), dict(entry or {}))
    for sid, entry in (cat.get('props') or {}).items():
        add('prop', str(sid), dict(entry or {}))
    for sid, entry in (cat.get('characters') or {}).items():
        add('character', str(sid), dict(entry or {}))
    return jobs


def clear_catalog_cache() -> None:
    load_catalog.cache_clear()


def dump_facility_draft() -> dict[str, Any]:
    """Draft inventory from facility_models + cast ids for catalog review.

    Does not invent art prompts — lists rooms, entities/state keys, and cast
    roles the authored catalog should cover.
    """
    from puca_dungeon.characters import STAFF_IDS, SUBJECT_IDS
    from puca_dungeon.facility_models import _default_entities, _default_rooms

    rooms = _default_rooms()
    entities = _default_entities()
    entity_rows = []
    for eid, raw in entities.items():
        state = dict((raw or {}).get('state') or {})
        entity_rows.append({
            'id': eid,
            'name': (raw or {}).get('name'),
            'location': (raw or {}).get('location'),
            'movable': bool((raw or {}).get('movable', True)),
            'state_keys': sorted(state.keys()),
            'default_state': state,
        })
    return {
        'source': 'facility_models + characters',
        'rooms': [
            {'id': rid, 'name': (raw or {}).get('name'), 'description': (raw or {}).get('description')}
            for rid, raw in rooms.items()
        ],
        'entities': entity_rows,
        'cast_roles': {
            'player': 'sarel',
            'staff_ids': list(STAFF_IDS),
            'subject_ids': list(SUBJECT_IDS),
            'player_pose_hints': ['wary', 'wounded', 'fallen', 'triumphant'],
            'staff_sprite_hints': ['staff_orderly', 'staff_anxious', 'staff_senior'],
        },
        'note': (
            'Review against assets/sprites/catalog.json. '
            'Use scripts/generate_sprites.py --dump-draft to print this JSON.'
        ),
    }


def jobs_for_room(room_id: str, catalog: Optional[dict] = None) -> list[dict[str, Any]]:
    """Sprite jobs needed to paint one room (background + layout-referenced assets)."""
    cat = catalog or load_catalog()
    layout = dict((cat.get('layouts') or {}).get(room_id) or {})
    if not layout:
        return []
    needed: set[str] = set()
    bg = str(layout.get('background') or room_id)
    needed.add(bg)
    # Props/characters that can appear in this room's slots
    slot_names = set((layout.get('slots') or {}).keys())
    for prop_id in (cat.get('props') or {}):
        base = prop_id.split('_')[0]
        if prop_id in slot_names or base in slot_names or any(
            prop_id.startswith(f'{slot}_') or prop_id == slot for slot in slot_names
        ):
            needed.add(prop_id)
    for char_id in (cat.get('characters') or {}):
        if 'player' in slot_names and char_id.startswith('player_'):
            needed.add(char_id)
        if any(s.startswith('staff_') for s in slot_names) and char_id.startswith('staff_'):
            needed.add(char_id)
    return [job for job in iter_sprite_jobs(cat) if job['id'] in needed]
