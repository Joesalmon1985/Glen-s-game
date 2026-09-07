"""Compose facility scenes from pre-generated sprites (graphics only)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from puca_dungeon.models import WorldState
from puca_dungeon.visual_catalog import DEFAULT_ASSETS_ROOT, assets_root, load_catalog

MAGENTA = (255, 0, 255, 255)

# Stable placeholder colours when a sprite PNG is missing
_PLACEHOLDER_COLORS = {
    'background': (42, 48, 58),
    'bed': (90, 70, 55),
    'bed_bedding_floor': (110, 80, 60),
    'cup_full': (120, 160, 190),
    'cup_empty': (150, 150, 150),
    'cup_broken': (170, 100, 100),
    'book_face_down': (80, 60, 40),
    'book_closed': (90, 70, 45),
    'book_open': (100, 80, 50),
    'door_closed': (70, 75, 85),
    'door_slit_open': (55, 60, 70),
    'bowl_full': (160, 120, 70),
    'bowl_empty': (140, 140, 130),
    'basin': (100, 130, 150),
    'fruit': (80, 140, 90),
    'fountain': (90, 150, 170),
    'heaven_bed': (180, 160, 140),
    'grate': (60, 60, 65),
    'hell_mat': (90, 50, 45),
    'fixture': (100, 95, 90),
    'player_wary': (200, 180, 140),
    'player_wounded': (190, 140, 120),
    'player_fallen': (160, 120, 110),
    'player_triumphant': (210, 190, 120),
    'staff_orderly': (130, 140, 155),
    'staff_anxious': (140, 135, 150),
    'staff_senior': (150, 145, 130),
}


@dataclass
class SpriteLayer:
    sprite_id: str
    kind: str  # background | prop | character
    xy: tuple[int, int] = (0, 0)
    z: int = 0

    def to_dict(self) -> dict:
        return {
            'sprite_id': self.sprite_id,
            'kind': self.kind,
            'xy': list(self.xy),
            'z': self.z,
        }


@dataclass
class SceneVisualSpec:
    room_id: str
    layers: list[SpriteLayer] = field(default_factory=list)
    key: str = ''

    def to_dict(self) -> dict:
        return {
            'room_id': self.room_id,
            'key': self.key,
            'layers': [layer.to_dict() for layer in self.layers],
        }


def facility_mode_active(world: WorldState) -> bool:
    return str(getattr(world, 'mode', '') or '') == 'facility' and getattr(world, 'facility', None) is not None


def _player_sprite_id(world: WorldState) -> str:
    sheet = world.sheet
    if not sheet.alive or world.ending == 'death':
        return 'player_fallen'
    if world.victory or world.ending == 'victory':
        return 'player_triumphant'
    body = dict(sheet.body_state or {})
    injuries = list(sheet.injuries or [])
    pain = str(body.get('pain') or 'none')
    bleeding = str(body.get('bleeding') or 'none')
    if injuries or pain not in ('', 'none') or bleeding not in ('', 'none'):
        return 'player_wounded'
    return 'player_wary'


def _prop_sprite_for_entity(entity, fac) -> tuple[str, str]:
    """Return (sprite_id, slot_name) for an in-room entity."""
    eid = entity.id
    state = dict(entity.state or {})

    if eid == 'bed':
        if state.get('bedding') == 'on_floor':
            return 'bed_bedding_floor', 'bed'
        return 'bed', 'bed'
    if eid == 'cup':
        slot = 'cup'
        if str(state.get('position') or '') in ('on_floor', 'floor') or state.get('water_spilled'):
            slot = 'cup_floor'
        if entity.broken:
            return 'cup_broken', slot
        if state.get('has_water') is False:
            return 'cup_empty', slot
        return 'cup_full', slot
    if eid == 'book':
        if state.get('open'):
            return 'book_open', 'book'
        if state.get('face_down'):
            return 'book_face_down', 'book'
        return 'book_closed', 'book'
    if eid == 'door':
        slit = bool(getattr(fac, 'slit_open', False) or state.get('slit_open'))
        return ('door_slit_open' if slit else 'door_closed'), 'door'
    if eid == 'bowl':
        if state.get('full') is False or state.get('spilled'):
            return 'bowl_empty', 'bowl'
        return 'bowl_full', 'bowl'
    if eid == 'basin':
        return 'basin', 'basin'
    if eid == 'fruit':
        return 'fruit', 'fruit'
    if eid == 'fountain':
        return 'fountain', 'fountain'
    if eid == 'heaven_bed':
        return 'heaven_bed', 'heaven_bed'
    if eid == 'grate':
        return 'grate', 'grate'
    if eid == 'hell_mat':
        return 'hell_mat', 'hell_mat'
    if eid == 'fixture':
        return 'fixture', 'fixture'
    # Unknown entity: skip rather than invent art
    return '', ''


def _staff_sprite_ids(fac) -> list[str]:
    if not getattr(fac, 'staff_present', False) and not int(getattr(fac, 'staff_count', 0) or 0):
        present = list(getattr(getattr(fac, 'arc', None), 'present_ids', None) or [])
        staffish = [pid for pid in present if pid in (
            'senior_researcher', 'orderly_quiet', 'orderly_anxious', 'attendant_a', 'attendant_b'
        )]
        if not staffish:
            return []
        ids = staffish
    else:
        count = max(1, int(getattr(fac, 'staff_count', 0) or 0) or (1 if fac.staff_present else 0))
        present = list(getattr(getattr(fac, 'arc', None), 'present_ids', None) or [])
        ids = [pid for pid in present if pid in (
            'senior_researcher', 'orderly_quiet', 'orderly_anxious', 'attendant_a', 'attendant_b'
        )]
        while len(ids) < count:
            ids.append('orderly_quiet')
        ids = ids[: max(count, 1)]

    out: list[str] = []
    for pid in ids[:2]:
        if pid == 'senior_researcher':
            out.append('staff_senior')
        elif pid == 'orderly_anxious':
            out.append('staff_anxious')
        else:
            out.append('staff_orderly')
    return out


def build_visual_spec(world: WorldState, catalog: Optional[dict] = None) -> SceneVisualSpec:
    cat = catalog or load_catalog()
    fac = world.facility
    assert fac is not None
    room_id = str(fac.room_id or 'cell')
    layouts = cat.get('layouts') or {}
    layout = dict(layouts.get(room_id) or layouts.get('cell') or {})
    slots = dict(layout.get('slots') or {})
    bg_key = str(layout.get('background') or room_id)

    layers: list[SpriteLayer] = [
        SpriteLayer(sprite_id=bg_key if bg_key in (cat.get('backgrounds') or {}) else room_id,
                    kind='background', xy=(0, 0), z=0)
    ]
    # Prefer explicit background id from layout
    layers[0].sprite_id = bg_key

    z = 10
    for entity in fac.entities_in_room():
        sprite_id, slot = _prop_sprite_for_entity(entity, fac)
        if not sprite_id:
            continue
        xy = slots.get(slot) or slots.get(entity.id) or [200, 300]
        layers.append(SpriteLayer(
            sprite_id=sprite_id,
            kind='prop',
            xy=(int(xy[0]), int(xy[1])),
            z=z,
        ))
        z += 1

    for i, staff_sprite in enumerate(_staff_sprite_ids(fac)):
        slot_name = f'staff_{i}'
        xy = slots.get(slot_name) or [320 + i * 30, 250]
        layers.append(SpriteLayer(
            sprite_id=staff_sprite,
            kind='character',
            xy=(int(xy[0]), int(xy[1])),
            z=50 + i,
        ))

    player_xy = slots.get('player') or [240, 290]
    layers.append(SpriteLayer(
        sprite_id=_player_sprite_id(world),
        kind='character',
        xy=(int(player_xy[0]), int(player_xy[1])),
        z=60,
    ))

    layers.sort(key=lambda layer: layer.z)
    key_payload = {
        'room': room_id,
        'layers': [layer.to_dict() for layer in layers],
    }
    key = hashlib.sha256(json.dumps(key_payload, sort_keys=True).encode()).hexdigest()
    return SceneVisualSpec(room_id=room_id, layers=layers, key=key)


def visual_fingerprint(world: WorldState) -> str:
    if not facility_mode_active(world):
        return ''
    return build_visual_spec(world).key


def _entry_for_sprite(catalog: dict, sprite_id: str) -> tuple[str, dict]:
    if sprite_id in (catalog.get('backgrounds') or {}):
        return 'background', dict(catalog['backgrounds'][sprite_id])
    if sprite_id in (catalog.get('props') or {}):
        return 'prop', dict(catalog['props'][sprite_id])
    if sprite_id in (catalog.get('characters') or {}):
        return 'character', dict(catalog['characters'][sprite_id])
    return 'prop', {}


def _placeholder_image(sprite_id: str, kind: str, size: tuple[int, int]):
    from PIL import Image, ImageDraw

    color = _PLACEHOLDER_COLORS.get(sprite_id) or _PLACEHOLDER_COLORS.get(kind) or (120, 120, 120)
    if kind == 'background':
        img = Image.new('RGBA', size, color + (255,))
        draw = ImageDraw.Draw(img)
        draw.rectangle([16, 16, size[0] - 17, size[1] - 17], outline=(80, 90, 100, 255), width=3)
        return img
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = max(2, min(size) // 10)
    draw.rounded_rectangle(
        [margin, margin, size[0] - margin - 1, size[1] - margin - 1],
        radius=max(2, min(size) // 8),
        fill=color + (255,),
        outline=(30, 30, 30, 255),
        width=2,
    )
    return img


def chroma_key_magenta(image):
    """Make near-magenta pixels transparent (batch SD sprites use #FF00FF)."""
    from PIL import Image

    rgba = image.convert('RGBA')
    pixels = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if r >= 230 and b >= 230 and g <= 40:
                pixels[x, y] = (r, g, b, 0)
            elif abs(r - 255) <= 40 and abs(b - 255) <= 40 and g <= 60:
                pixels[x, y] = (r, g, b, 0)
    return rgba


def load_sprite_rgba(
    sprite_id: str,
    catalog: dict,
    root: Path,
    canvas_size: tuple[int, int],
    allow_placeholder: bool = True,
):
    from PIL import Image

    kind, entry = _entry_for_sprite(catalog, sprite_id)
    rel = str(entry.get('file') or '')
    path = root / rel if rel else None
    if kind == 'background':
        size = canvas_size
    else:
        raw = entry.get('size') or [96, 96]
        size = (int(raw[0]), int(raw[1]))

    if path is not None and path.is_file():
        img = Image.open(path).convert('RGBA')
        if kind == 'background':
            if img.size != canvas_size:
                img = img.resize(canvas_size, Image.Resampling.NEAREST)
            return img
        img = chroma_key_magenta(img)
        if img.size != size:
            img = img.resize(size, Image.Resampling.NEAREST)
        return img
    if not allow_placeholder:
        raise FileNotFoundError(f'Missing sprite: {sprite_id} ({path})')
    return _placeholder_image(sprite_id, kind, size)


def _draw_debug_overlay(image, spec: SceneVisualSpec):
    """List layer sprite ids in the corner for layout tuning (PUCA_SPRITE_DEBUG=1)."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    lines = [f'{spec.room_id}  {spec.key[:8]}']
    for layer in spec.layers:
        if layer.kind == 'background':
            lines.append(f'bg:{layer.sprite_id}')
        else:
            lines.append(f'{layer.sprite_id}@{layer.xy[0]},{layer.xy[1]}')
    y = 6
    for line in lines[:18]:
        draw.text((7, y + 1), line, fill=(0, 0, 0))
        draw.text((6, y), line, fill=(240, 230, 200))
        y += 12
    return image


def compose_image(
    spec: SceneVisualSpec,
    catalog: Optional[dict] = None,
    root: Optional[Path] = None,
    allow_placeholder: bool = True,
    debug_layers: bool = False,
):
    from PIL import Image

    cat = catalog or load_catalog()
    asset_root = assets_root(cat, root)
    canvas = cat.get('canvas') or {}
    width = int(canvas.get('width') or 512)
    height = int(canvas.get('height') or 512)
    out = Image.new('RGBA', (width, height), (20, 24, 30, 255))
    for layer in spec.layers:
        sprite = load_sprite_rgba(
            layer.sprite_id,
            cat,
            asset_root,
            (width, height),
            allow_placeholder=allow_placeholder,
        )
        if layer.kind == 'background':
            out.alpha_composite(sprite, (0, 0))
        else:
            out.alpha_composite(sprite, (int(layer.xy[0]), int(layer.xy[1])))
    rgb = out.convert('RGB')
    if debug_layers:
        _draw_debug_overlay(rgb, spec)
    return rgb


def compose_facility_scene(
    world: WorldState,
    cache_dir: Path,
    catalog: Optional[dict] = None,
    root: Optional[Path] = None,
    allow_placeholder: bool = True,
    debug_layers: Optional[bool] = None,
) -> tuple[SceneVisualSpec, Path]:
    """Compose and cache a 512×512 PNG for the current facility view."""
    import os

    if debug_layers is None:
        debug_layers = str(os.environ.get('PUCA_SPRITE_DEBUG') or '').strip().lower() in (
            '1', 'true', 'yes', 'on',
        )
    cat = catalog or load_catalog()
    spec = build_visual_spec(world, cat)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = '_dbg' if debug_layers else ''
    destination = cache_dir / f'sprite_{spec.key[:24]}{suffix}.png'
    if destination.is_file() and not debug_layers:
        try:
            from PIL import Image
            with Image.open(destination) as existing:
                if existing.size == (512, 512) and existing.format == 'PNG':
                    return spec, destination
        except OSError:
            destination.unlink(missing_ok=True)
    image = compose_image(
        spec,
        cat,
        root=root or DEFAULT_ASSETS_ROOT,
        allow_placeholder=allow_placeholder,
        debug_layers=bool(debug_layers),
    )
    tmp = destination.with_suffix('.tmp.png')
    image.save(tmp, format='PNG')
    tmp.replace(destination)
    return spec, destination
