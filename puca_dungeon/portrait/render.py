"""Composite layered face packages. Loads existing PNGs only — no image generation."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from puca_dungeon.portrait.errors import PortraitError
from puca_dungeon.portrait.manifest import (
    CANVAS_SIZE,
    load_manifest,
    resolve_layer_file,
)
from puca_dungeon.portrait.types import (
    BrowState,
    EyeState,
    FacePose,
    Gaze,
    MouthState,
)

_LAYER_CACHE: dict[str, object] = {}
_PORTRAIT_CACHE: dict[tuple, object] = {}


def clear_render_cache() -> None:
    _LAYER_CACHE.clear()
    _PORTRAIT_CACHE.clear()


def _open_rgba(path: Path):
    from PIL import Image

    key = str(path)
    cached = _LAYER_CACHE.get(key)
    if cached is not None:
        return cached
    if not path.is_file():
        raise PortraitError(f'Missing layer file: {path}')
    img = Image.open(path).convert('RGBA')
    if img.size != CANVAS_SIZE:
        raise PortraitError(
            f'Layer {path} is {img.size[0]}×{img.size[1]}, expected {CANVAS_SIZE[0]}×{CANVAS_SIZE[1]}'
        )
    _LAYER_CACHE[key] = img
    return img


def _identity_file(manifest: dict, slot: str) -> Optional[str]:
    identity = manifest.get('identity') or {}
    rel = identity.get(slot)
    if rel:
        return str(rel)
    return None


def _group_file(expressions: dict, group: str, key: str) -> Optional[str]:
    table = expressions.get(group)
    if not isinstance(table, dict):
        return None
    rel = table.get(key)
    if rel:
        return str(rel)
    return None


def _brow_file(expressions: dict, side: str, state: BrowState) -> Optional[str]:
    brows = expressions.get('brows')
    if not isinstance(brows, dict):
        return None
    side_table = brows.get(side)
    if not isinstance(side_table, dict):
        return None
    rel = side_table.get(state.value) or side_table.get(BrowState.NEUTRAL.value)
    return str(rel) if rel else None


def _fallback_expr(expressions: dict, group: str, key: str, fallback: str) -> Optional[str]:
    return _group_file(expressions, group, key) or _group_file(expressions, group, fallback)


def resolve_slot_file(manifest: dict, slot: str, pose: FacePose) -> Optional[str]:
    """Map a z-order slot + pose to a package-relative PNG, or None to skip."""
    expressions = manifest.get('expressions') or {}
    eyes_closed = pose.eye_openness is EyeState.CLOSED

    if slot in (
        'hair_back', 'ears', 'head', 'nose', 'mouth_base', 'facial_hair',
        'wrinkles', 'freckles', 'scars', 'hair_front', 'other',
    ):
        return _identity_file(manifest, slot)

    if slot == 'eye_whites':
        if eyes_closed:
            return _fallback_expr(expressions, 'eyes', EyeState.CLOSED.value, EyeState.CLOSED.value)
        return _fallback_expr(expressions, 'eyes', pose.eye_openness.value, EyeState.OPEN.value)

    if slot == 'irises':
        if eyes_closed:
            return None
        return _fallback_expr(expressions, 'gaze', pose.gaze.value, Gaze.FORWARD.value)

    if slot == 'eyelids':
        return _fallback_expr(expressions, 'eyelids', pose.eye_openness.value, EyeState.OPEN.value)

    if slot == 'mouth':
        return _fallback_expr(expressions, 'mouths', pose.mouth.value, MouthState.NEUTRAL.value)

    if slot == 'left_brow':
        return _brow_file(expressions, 'left', pose.left_brow)

    if slot == 'right_brow':
        return _brow_file(expressions, 'right', pose.right_brow)

    # Unknown slot names are skipped (future overlays).
    return _identity_file(manifest, slot) or _group_file(expressions, slot, pose.fingerprint())


def render_portrait(
    visual_profile_id: str,
    pose: Optional[FacePose] = None,
    *,
    root: Optional[Path] = None,
    use_cache: bool = True,
):
    """Composite a face package. Does not read or write gameplay state."""
    from PIL import Image

    pose = FacePose.coerce(pose)
    pid = str(visual_profile_id or '').strip()
    cache_key = (pid, pose.fingerprint(), str(root or ''))
    if use_cache and cache_key in _PORTRAIT_CACHE:
        return _PORTRAIT_CACHE[cache_key].copy()

    manifest = load_manifest(pid, root=str(root) if root else None)
    out = Image.new('RGBA', CANVAS_SIZE, (0, 0, 0, 0))
    for slot in manifest['_z_order']:
        rel = resolve_slot_file(manifest, str(slot), pose)
        if not rel:
            continue
        path = resolve_layer_file(manifest, rel)
        if not path.is_file():
            # Optional identity layers may be listed in z-order but unused.
            if str(slot) in ('head', 'mouth', 'eye_whites', 'left_brow', 'right_brow'):
                raise PortraitError(f'{pid}: required layer missing for slot {slot}: {path}')
            continue
        layer = _open_rgba(path)
        out.alpha_composite(layer)

    if use_cache:
        _PORTRAIT_CACHE[cache_key] = out
        return out.copy()
    return out


def portrait_to_display_rgb(image, background=(20, 24, 30)):
    """Flatten RGBA onto a dark panel for GUI / contact sheets."""
    from PIL import Image

    rgba = image.convert('RGBA')
    bg = Image.new('RGB', rgba.size, background)
    bg.paste(rgba, mask=rgba.split()[3])
    return bg
