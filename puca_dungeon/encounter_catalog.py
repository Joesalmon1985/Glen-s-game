"""Load authored book-dungeon encounter catalog."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent / 'content' / 'book_dungeon' / 'catalog.json'


def load_catalog(path: Path | None = None) -> dict:
    p = path or CATALOG_PATH
    with p.open(encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict) or 'encounters' not in data:
        raise ValueError(f'Invalid encounter catalog at {p}')
    return data


def encounters_by_id(catalog: dict | None = None) -> dict[str, dict]:
    cat = catalog or load_catalog()
    out: dict[str, dict] = {}
    for enc in cat.get('encounters') or []:
        eid = str(enc.get('id') or '')
        if eid:
            out[eid] = enc
    return out


def encounters_for_role(role: str, catalog: dict | None = None) -> list[dict]:
    cat = catalog or load_catalog()
    return [
        enc for enc in (cat.get('encounters') or [])
        if role in (enc.get('slot_roles') or [])
    ]


def encounter_produces_items(enc: dict) -> list[str]:
    """Return item/capability tags produced (excluding flag:/knowledge: prefixes for items)."""
    items: list[str] = []
    for tag in enc.get('produces') or []:
        s = str(tag)
        if s.startswith('flag:') or s.startswith('knowledge:'):
            continue
        items.append(s)
    for effect in enc.get('effects_on_enter') or []:
        if isinstance(effect, dict) and effect.get('op') == 'add_item':
            item = effect.get('item')
            if item and str(item) not in items:
                items.append(str(item))
    return items


def flatten_requires(enc: dict) -> list[str]:
    """Flatten requires groups into a bag of tags (for reporting)."""
    req = enc.get('requires') or []
    out: list[str] = []
    for group in req:
        if isinstance(group, list):
            out.extend(str(x) for x in group)
        else:
            out.append(str(group))
    return out


def catalog_fingerprint(catalog: dict | None = None) -> str:
    cat = catalog or load_catalog()
    ids = sorted(str(e.get('id')) for e in (cat.get('encounters') or []))
    return ','.join(ids)
