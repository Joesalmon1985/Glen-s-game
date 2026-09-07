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
