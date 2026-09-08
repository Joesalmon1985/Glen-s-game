"""Load and validate face-package manifests. No character names."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from puca_dungeon.portrait.errors import PortraitError

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PORTRAITS_ROOT = _ROOT / 'assets' / 'portraits'
CANVAS_SIZE = (768, 768)
FACE_PROFILE_IDS = ('face_001', 'face_002', 'face_003', 'face_004', 'face_005')

REQUIRED_Z_SLOTS = ('head',)
IDENTITY_KEYS = (
    'hair_back', 'ears', 'head', 'nose', 'mouth_base', 'facial_hair',
    'wrinkles', 'freckles', 'scars', 'hair_front', 'other',
)
EXPRESSION_GROUPS = ('eyes', 'gaze', 'brows', 'mouths', 'eyelids')


def portraits_root(root: Optional[Path] = None) -> Path:
    return Path(root) if root is not None else DEFAULT_PORTRAITS_ROOT


def manifest_path(visual_profile_id: str, root: Optional[Path] = None) -> Path:
    return portraits_root(root) / visual_profile_id / 'manifest.json'


def _expect_object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise PortraitError(f'{label} must be a JSON object')
    return value


@lru_cache(maxsize=16)
def load_manifest(visual_profile_id: str, root: Optional[str] = None) -> dict[str, Any]:
    pid = str(visual_profile_id or '').strip()
    if not pid:
        raise PortraitError('visual_profile_id is required')
    if '/' in pid or '\\' in pid or '..' in pid:
        raise PortraitError(f'Invalid visual_profile_id: {pid!r}')
    base = portraits_root(Path(root) if root else None)
    path = base / pid / 'manifest.json'
    if not path.is_file():
        raise PortraitError(f'Unknown visual_profile_id {pid!r} (missing {path})')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise PortraitError(f'Malformed manifest for {pid}: {exc}') from exc
    data = _expect_object(data, f'{pid} manifest')
    schema = int(data.get('schema_version') or 0)
    if schema != 1:
        raise PortraitError(f'{pid}: unsupported schema_version {schema!r} (expected 1)')
    if str(data.get('visual_profile_id') or '') != pid:
        raise PortraitError(
            f'{pid}: visual_profile_id in manifest does not match directory name'
        )
    canvas = _expect_object(data.get('canvas'), f'{pid}.canvas')
    width = int(canvas.get('width') or 0)
    height = int(canvas.get('height') or 0)
    if (width, height) != CANVAS_SIZE:
        raise PortraitError(
            f'{pid}: canvas must be {CANVAS_SIZE[0]}×{CANVAS_SIZE[1]}, got {width}×{height}'
        )
    identity = _expect_object(data.get('identity'), f'{pid}.identity')
    expressions = _expect_object(data.get('expressions'), f'{pid}.expressions')
    z_order = data.get('z_order')
    if not isinstance(z_order, list) or not z_order:
        raise PortraitError(f'{pid}: z_order must be a non-empty list')
    z_names = [str(item) for item in z_order]
    for required in REQUIRED_Z_SLOTS:
        if required not in z_names:
            raise PortraitError(f'{pid}: z_order missing required slot {required!r}')
    if 'head' not in identity or not identity.get('head'):
        raise PortraitError(f'{pid}: identity.head is required')
    brows = expressions.get('brows')
    if brows is not None:
        brows = _expect_object(brows, f'{pid}.expressions.brows')
        if 'left' in brows:
            _expect_object(brows.get('left'), f'{pid}.expressions.brows.left')
        if 'right' in brows:
            _expect_object(brows.get('right'), f'{pid}.expressions.brows.right')
    data['_root'] = str(path.parent)
    data['_z_order'] = z_names
    return data


def clear_manifest_cache() -> None:
    load_manifest.cache_clear()


def package_dir(visual_profile_id: str, root: Optional[Path] = None) -> Path:
    return portraits_root(root) / visual_profile_id


def resolve_layer_file(manifest: dict, relative: str) -> Path:
    rel = str(relative or '').replace('\\', '/')
    if not rel or rel.startswith('/') or '..' in rel.split('/'):
        raise PortraitError(f'Invalid layer path: {relative!r}')
    return Path(manifest['_root']) / rel
