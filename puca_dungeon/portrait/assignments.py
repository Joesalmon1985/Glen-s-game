"""Cast-id → visual profile / body sprite. Presentation data, not the renderer."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_ASSIGNMENTS_PATH = (
    Path(__file__).resolve().parents[1] / 'content' / 'facility' / 'visual_assignments.json'
)


@lru_cache(maxsize=4)
def load_visual_assignments(path: Optional[str] = None) -> dict[str, dict[str, Any]]:
    target = Path(path) if path else _ASSIGNMENTS_PATH
    if not target.is_file():
        return {}
    data = json.loads(target.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for cid, raw in data.items():
        if cid.startswith('_') or not isinstance(raw, dict):
            continue
        out[str(cid)] = dict(raw)
    return out


def clear_assignment_cache() -> None:
    load_visual_assignments.cache_clear()


def assignment_for(character_id: str, path: Optional[str] = None) -> dict[str, Any]:
    return dict(load_visual_assignments(path).get(str(character_id) or '') or {})


def visual_profile_id(character_id: str, path: Optional[str] = None) -> str:
    raw = assignment_for(character_id, path).get('visual_profile_id') or ''
    return str(raw).strip()


def body_sprite_id(character_id: str, path: Optional[str] = None) -> str:
    raw = assignment_for(character_id, path).get('body_sprite_id') or ''
    return str(raw).strip()
