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
# Bump when chroma / overlay rules change so compose caches invalidate.
CHROMA_VERSION = 2

# Props already painted into the room background. Overlay only when the live
# sprite differs from that baked default (open slit, empty cup, bedding down).
_BAKED_PROP_DEFAULTS = {
    'cell': {'bed', 'door_closed', 'door_slit_open', 'cup_full', 'book_face_down'},
    'washroom': {'basin'},
    'heaven': {'heaven_bed'},
}

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
    'body_001': (118, 132, 120),
    'body_002': (62, 58, 72),
    'body_003': (168, 154, 132),
    'body_attendant': (210, 204, 190),
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


def sprite_presentation_active(world: WorldState) -> bool:
    """Facility rooms and the printed book-dungeon both use sprite composition."""
    mode = str(getattr(world, 'mode', '') or '')
    if getattr(world, 'facility', None) is None:
        return False
    return mode in ('facility', 'book_dungeon')


def _baked_into_background(room_id: str, sprite_id: str, slot: str) -> bool:
    if slot in ('cup_floor',):
        return False
    return sprite_id in _BAKED_PROP_DEFAULTS.get(room_id, ())


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


_LIVE_BODY_SPRITES = frozenset({
    'staff_orderly', 'staff_anxious', 'staff_senior',
})
_MAX_NPC_SLOTS = 4
_PLAYER_CAST_ID = 'sarel'


def _present_character_ids(fac) -> list[str]:
    present = [
        str(pid) for pid in (getattr(getattr(fac, 'arc', None), 'present_ids', None) or [])
        if pid and str(pid) != _PLAYER_CAST_ID
    ]
    if present:
        return present
    count = int(getattr(fac, 'staff_count', 0) or 0)
    if count or getattr(fac, 'staff_present', False):
        from puca_dungeon.characters import present_staff_ids
        return list(present_staff_ids(max(1, count or 1)))
    return []


def _body_sprite_for_character(character_id: str) -> str:
    try:
        from puca_dungeon.portrait.assignments import body_sprite_id
        sprite = body_sprite_id(character_id)
        if sprite in _LIVE_BODY_SPRITES:
            return sprite
    except Exception:
        pass
    if character_id == 'senior_researcher':
        return 'staff_senior'
    if character_id == 'orderly_anxious':
        return 'staff_anxious'
    if character_id in ('orderly_quiet', 'attendant_a', 'attendant_b'):
        return 'staff_orderly'
    return ''


def _present_body_sprite_ids(fac) -> list[str]:
    out: list[str] = []
    for cid in _present_character_ids(fac):
        sprite = _body_sprite_for_character(cid)
        if sprite:
            out.append(sprite)
        if len(out) >= _MAX_NPC_SLOTS:
            break
    return out


def _staff_sprite_ids(fac) -> list[str]:
    """Back-compat alias: body sprites for whoever is present."""
    return _present_body_sprite_ids(fac)


def _sprite_file_stamp(catalog: dict, sprite_id: str, root: Path) -> str:
    """Stamp kit PNG identity so compose/fingerprint caches invalidate on art swaps."""
    _kind, entry = _entry_for_sprite(catalog, sprite_id)
    rel = str(entry.get('file') or '')
    if not rel:
        return 'nofile'
    path = root / rel
    try:
        st = path.stat()
    except OSError:
        return 'missing'
    return f'{st.st_mtime_ns}:{st.st_size}'


def build_visual_spec(world: WorldState, catalog: Optional[dict] = None) -> SceneVisualSpec:
    cat = catalog or load_catalog()
    root = assets_root(cat)
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
        if _baked_into_background(room_id, sprite_id, slot):
            continue
        xy = slots.get(slot) or slots.get(entity.id) or [200, 300]
        layers.append(SpriteLayer(
            sprite_id=sprite_id,
            kind='prop',
            xy=(int(xy[0]), int(xy[1])),
            z=z,
        ))
        z += 1

    for i, body_sprite in enumerate(_present_body_sprite_ids(fac)):
        xy = slots.get(f'npc_{i}') or slots.get(f'staff_{i}') or [320 + i * 30, 250]
        layers.append(SpriteLayer(
            sprite_id=body_sprite,
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
    asset_stamps = {
        layer.sprite_id: _sprite_file_stamp(cat, layer.sprite_id, root)
        for layer in layers
    }
    key_payload = {
        'room': room_id,
        'layers': [layer.to_dict() for layer in layers],
        'assets': asset_stamps,
        'chroma': CHROMA_VERSION,
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


def _is_key_magenta(r: int, g: int, b: int) -> bool:
    if r >= 200 and b >= 190 and g <= 90:
        return True
    if r >= 170 and b >= 130 and g <= 110 and (r - g) >= 60 and (b - g) >= 30:
        return True
    return False


def _neighbour_transparent(pixels, x: int, y: int, w: int, h: int) -> bool:
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < w and 0 <= ny < h and pixels[nx, ny][3] <= 16:
            return True
    return False


def chroma_key_magenta(image):
    """Make near-magenta pixels transparent and strip pink/purple edge fringes."""
    rgba = image.convert('RGBA')
    pixels = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a and _is_key_magenta(r, g, b):
                pixels[x, y] = (r, g, b, 0)
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a <= 16:
                continue
            if not _neighbour_transparent(pixels, x, y, w, h):
                continue
            if (r + b) > (2 * g + 50) and r >= 110 and b >= 70:
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


def book_dungeon_visual_key(world: WorldState) -> str:
    passage = str(getattr(world, 'passage_id', '') or '0')
    player = _player_sprite_id(world)
    return f'{passage}:{player}:v2'


def compose_book_dungeon_image(world: WorldState, catalog: Optional[dict] = None, root: Optional[Path] = None):
    """Printed alcove: damp stone, torchlight, six caskets, the player. Not the live cell."""
    from PIL import Image, ImageDraw

    cat = catalog or load_catalog()
    asset_root = assets_root(cat, root)
    canvas = cat.get('canvas') or {}
    width = int(canvas.get('width') or 512)
    height = int(canvas.get('height') or 512)
    out = Image.new('RGBA', (width, height), (16, 14, 12, 255))
    draw = ImageDraw.Draw(out)

    draw.rectangle([0, 0, width, height], fill=(36, 30, 26, 255))
    for y in range(0, height, 18):
        for x in range(0, width, 28):
            ox = 8 if (y // 18) % 2 else 0
            draw.rectangle([x + ox, y, x + ox + 26, y + 16], outline=(28, 24, 20, 255))
    draw.polygon([(70, 40), (442, 40), (512, 220), (0, 220)], fill=(22, 18, 16, 255))
    draw.polygon([(150, 56), (362, 56), (390, 200), (122, 200)], fill=(10, 8, 8, 255))
    draw.ellipse([236, 70, 276, 108], fill=(48, 28, 12, 255))
    draw.rectangle([0, 218, width, height], fill=(48, 40, 32, 255))
    for y in range(230, height, 22):
        draw.line([(0, y), (width, y)], fill=(38, 32, 26, 255), width=1)
    draw.ellipse([40, 120, 92, 172], fill=(210, 120, 40, 255))
    draw.ellipse([52, 132, 80, 160], fill=(255, 210, 90, 255))
    draw.polygon([(66, 170), (40, 250), (92, 250)], fill=(90, 40, 12, 80))

    draw.rectangle([28, 250, 300, 330], fill=(64, 52, 40, 255))
    draw.rectangle([28, 250, 300, 258], fill=(82, 66, 50, 255))
    draw.rectangle([28, 322, 300, 330], fill=(40, 32, 24, 255))
    lids = (
        (128, 108, 84), (124, 104, 80), (130, 110, 86),
        (122, 102, 78), (126, 106, 82), (108, 86, 60),
    )
    for i, fill in enumerate(lids):
        x0 = 36 + i * 42
        draw.rectangle([x0, 262, x0 + 36, 318], fill=fill + (255,))
        draw.rectangle([x0 + 3, 268, x0 + 33, 276], fill=(48, 38, 28, 255))
        draw.rectangle([x0 + 16, 276, x0 + 20, 314], fill=(40, 32, 24, 255))
        if i == 5:
            draw.rectangle([x0 + 8, 286, x0 + 28, 306], outline=(210, 188, 130, 255))

    draw.rectangle([0, 0, width - 1, height - 1], outline=(92, 72, 48, 255), width=14)
    draw.rectangle([10, 10, width - 11, height - 11], outline=(214, 200, 164, 255), width=2)

    player = load_sprite_rgba(
        _player_sprite_id(world), cat, asset_root, (width, height), allow_placeholder=True,
    )
    px = width - player.size[0] - 48
    py = height - player.size[1] - 36
    out.alpha_composite(player, (px, py))
    return out.convert('RGB')


def compose_book_dungeon_scene(
    world: WorldState,
    cache_dir: Path,
    catalog: Optional[dict] = None,
    root: Optional[Path] = None,
) -> Path:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(book_dungeon_visual_key(world).encode()).hexdigest()[:24]
    destination = cache_dir / f'printed_{key}.png'
    if destination.is_file():
        try:
            from PIL import Image
            with Image.open(destination) as existing:
                if existing.size == (512, 512) and existing.format == 'PNG':
                    return destination
        except OSError:
            destination.unlink(missing_ok=True)
    image = compose_book_dungeon_image(world, catalog=catalog, root=root)
    tmp = destination.with_suffix('.tmp.png')
    image.save(tmp, format='PNG')
    tmp.replace(destination)
    return destination
