#!/usr/bin/env python3
"""Offline authoring: paint layered 768×768 face packages + body sprites.

Runtime never imports this. Re-run to regenerate procedural_prototype assets.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Paint at 384px then nearest-scale ×2 → 768. Never punch holes with
# semi-transparent fills on an already-opaque layer (PIL replaces, it does not blend).
UNIT = 2
WORK = 192 * UNIT
SCALE = 4 // UNIT
CANVAS = WORK * SCALE  # 768
CX = 96 * UNIT

EYE_STATES = ('open', 'slightly_narrow', 'narrow', 'wide', 'closed')
GAZES = {
    'forward': (0, 0),
    'left': (-7, 0),
    'right': (7, 0),
    'up': (0, -5),
    'down': (0, 5),
    'away_left': (-11, 2),
    'away_right': (11, 2),
}
BROW_STATES = ('neutral', 'raised', 'lowered', 'knit', 'concerned', 'asymmetric_raise')
MOUTH_STATES = ('neutral', 'pressed', 'parted', 'small_smile', 'smile', 'frown', 'grimace', 'uneasy')

Z_ORDER = [
    'hair_back',
    'ears',
    'head',
    'eye_whites',
    'irises',
    'eyelids',
    'nose',
    'mouth_base',
    'mouth',
    'facial_hair',
    'wrinkles',
    'freckles',
    'scars',
    'hair_front',
    'left_brow',
    'right_brow',
]


def _blank():
    from PIL import Image
    return Image.new('RGBA', (WORK, WORK), (0, 0, 0, 0))


def _draw(img):
    from PIL import ImageDraw
    return ImageDraw.Draw(img, 'RGBA')


def _save(img, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    big = img.resize((CANVAS, CANVAS), resample=__import__('PIL').Image.Resampling.NEAREST)
    big.save(path, format='PNG')


def _mix(a, b, t: float):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _rgba(rgb, a=255):
    return (int(rgb[0]), int(rgb[1]), int(rgb[2]), int(a))


def u(n: int | float) -> int:
    return int(round(n * UNIT))


@dataclass
class FaceSpec:
    profile_id: str
    skin: tuple
    skin_shadow: tuple
    skin_lit: tuple
    hair: tuple
    hair_dark: tuple
    hair_light: tuple
    brow: tuple
    iris: tuple
    iris_dark: tuple
    lip: tuple
    lip_dark: tuple
    lash: tuple
    hx: int
    hy: int
    cy: int
    jaw: str
    eye_spread: int
    eye_y: int
    eye_w: int
    eye_h: int
    eye_asym: int
    nose_kind: str
    mouth_y: int
    mouth_w: int
    hair_kind: str
    beard: bool
    wrinkles: bool
    freckles: bool
    scar: bool
    body_id: str
    clothes: tuple
    clothes_dark: tuple
    stature: str


SPECS = (
    FaceSpec(
        profile_id='face_001',
        skin=(198, 168, 132), skin_shadow=(168, 132, 98), skin_lit=(222, 198, 168),
        hair=(72, 48, 36), hair_dark=(48, 32, 24), hair_light=(110, 78, 58),
        brow=(64, 42, 32), iris=(86, 122, 92), iris_dark=(40, 62, 48),
        lip=(176, 110, 108), lip_dark=(148, 82, 84), lash=(36, 24, 20),
        hx=44, hy=52, cy=108, jaw='round',
        eye_spread=24, eye_y=84, eye_w=15, eye_h=10, eye_asym=0,
        nose_kind='button', mouth_y=128, mouth_w=16,
        hair_kind='short_curls', beard=False, wrinkles=False, freckles=False, scar=False,
        body_id='body_001', clothes=(118, 132, 120), clothes_dark=(78, 90, 84), stature='short',
    ),
    FaceSpec(
        profile_id='face_002',
        skin=(110, 78, 58), skin_shadow=(78, 52, 38), skin_lit=(148, 110, 84),
        hair=(18, 14, 12), hair_dark=(10, 8, 8), hair_light=(42, 32, 28),
        brow=(14, 10, 8), iris=(48, 78, 92), iris_dark=(20, 36, 48),
        lip=(128, 72, 70), lip_dark=(96, 48, 48), lash=(8, 6, 6),
        hx=34, hy=58, cy=104, jaw='narrow',
        eye_spread=18, eye_y=82, eye_w=13, eye_h=9, eye_asym=0,
        nose_kind='sharp', mouth_y=130, mouth_w=13,
        hair_kind='tight_dark', beard=False, wrinkles=False, freckles=False, scar=False,
        body_id='body_002', clothes=(62, 58, 72), clothes_dark=(40, 38, 50), stature='tall',
    ),
    FaceSpec(
        profile_id='face_003',
        skin=(214, 196, 178), skin_shadow=(176, 154, 136), skin_lit=(236, 222, 208),
        hair=(148, 148, 142), hair_dark=(110, 110, 108), hair_light=(188, 188, 180),
        brow=(96, 90, 84), iris=(92, 86, 70), iris_dark=(48, 44, 34),
        lip=(168, 120, 118), lip_dark=(140, 92, 90), lash=(70, 64, 58),
        hx=46, hy=50, cy=110, jaw='square',
        eye_spread=22, eye_y=86, eye_w=14, eye_h=8, eye_asym=0,
        nose_kind='hooked', mouth_y=126, mouth_w=15,
        hair_kind='grey_streak', beard=True, wrinkles=True, freckles=False, scar=False,
        body_id='body_003', clothes=(168, 154, 132), clothes_dark=(120, 108, 90), stature='broad',
    ),
    FaceSpec(
        profile_id='face_004',
        skin=(186, 142, 102), skin_shadow=(148, 104, 72), skin_lit=(214, 176, 136),
        hair=(42, 32, 28), hair_dark=(24, 18, 16), hair_light=(72, 56, 48),
        brow=(28, 20, 16), iris=(92, 70, 42), iris_dark=(48, 34, 18),
        lip=(154, 96, 86), lip_dark=(124, 70, 62), lash=(24, 16, 14),
        hx=50, hy=46, cy=108, jaw='wide',
        eye_spread=23, eye_y=85, eye_w=14, eye_h=9, eye_asym=0,
        nose_kind='wide', mouth_y=127, mouth_w=18,
        hair_kind='cropped', beard=False, wrinkles=False, freckles=False, scar=False,
        body_id='', clothes=(150, 145, 130), clothes_dark=(100, 96, 86), stature='mid',
    ),
    FaceSpec(
        profile_id='face_005',
        skin=(208, 166, 140), skin_shadow=(172, 126, 102), skin_lit=(232, 198, 174),
        hair=(148, 64, 42), hair_dark=(110, 42, 28), hair_light=(180, 96, 70),
        brow=(120, 52, 36), iris=(70, 108, 128), iris_dark=(28, 52, 68),
        lip=(186, 108, 112), lip_dark=(150, 78, 82), lash=(64, 28, 22),
        hx=41, hy=51, cy=107, jaw='round',
        eye_spread=21, eye_y=83, eye_w=14, eye_h=10, eye_asym=-3,
        nose_kind='uneven', mouth_y=129, mouth_w=15,
        hair_kind='reddish', beard=False, wrinkles=False, freckles=True, scar=True,
        body_id='', clothes=(140, 135, 150), clothes_dark=(90, 86, 100), stature='mid',
    ),
)


def _eye_centres(spec: FaceSpec):
    ly = u(spec.eye_y)
    ry = u(spec.eye_y + spec.eye_asym)
    return (CX - u(spec.eye_spread), ly), (CX + u(spec.eye_spread), ry)


def paint_head(spec: FaceSpec):
    img = _blank()
    d = _draw(img)
    cx, cy, hx, hy = CX, u(spec.cy), u(spec.hx), u(spec.hy)
    neck_w = u(14 if spec.jaw != 'wide' else 18)
    socket = _mix(spec.skin, spec.skin_shadow, 0.35)
    d.rectangle([cx - neck_w, cy + hy - u(10), cx + neck_w, cy + hy + u(30)], fill=_rgba(spec.skin_shadow))
    d.ellipse([cx - neck_w - u(2), cy + hy + u(18), cx + neck_w + u(2), cy + hy + u(36)], fill=_rgba(spec.skin_shadow))
    d.ellipse([cx - hx + u(4), cy - hy + u(8), cx + hx + u(4), cy + hy + u(6)], fill=_rgba(spec.skin_shadow))
    d.ellipse([cx - hx, cy - hy, cx + hx, cy + hy], fill=_rgba(spec.skin))
    if spec.jaw == 'square':
        d.rectangle([cx - hx + u(6), cy + u(4), cx + hx - u(6), cy + hy - u(4)], fill=_rgba(spec.skin))
        d.rectangle([cx - hx + u(2), cy + hy - u(16), cx + hx - u(2), cy + hy - u(2)], fill=_rgba(spec.skin_shadow))
        d.rectangle([cx - hx + u(4), cy + hy - u(18), cx + hx - u(4), cy + hy - u(6)], fill=_rgba(spec.skin))
    elif spec.jaw == 'wide':
        d.ellipse([cx - hx - u(4), cy + u(8), cx + hx + u(4), cy + hy + u(4)], fill=_rgba(spec.skin))
    elif spec.jaw == 'narrow':
        d.polygon(
            [
                (cx - hx + u(10), cy + u(8)),
                (cx + hx - u(10), cy + u(8)),
                (cx + u(8), cy + hy),
                (cx - u(8), cy + hy),
            ],
            fill=_rgba(spec.skin),
        )
    d.ellipse(
        [cx - hx + u(12), cy - hy + u(8), cx - u(8), cy - u(4)],
        fill=_rgba(spec.skin_lit),
    )
    (lx, ly), (rx, ry) = _eye_centres(spec)
    ew, eh = u(spec.eye_w), u(spec.eye_h)
    for x, y in ((lx, ly), (rx, ry)):
        d.ellipse([x - ew - u(2), y - eh, x + ew + u(2), y + eh + u(4)], fill=_rgba(socket))
    # shoulder / uniform crop so the portrait is a bust, not a floating head
    d.polygon(
        [
            (cx - u(72), WORK - 1),
            (cx - u(42), cy + hy + u(18)),
            (cx + u(42), cy + hy + u(18)),
            (cx + u(72), WORK - 1),
        ],
        fill=_rgba(spec.skin_shadow),
    )
    d.polygon(
        [
            (cx - u(74), WORK - 1),
            (cx - u(36), cy + hy + u(26)),
            (cx + u(36), cy + hy + u(26)),
            (cx + u(74), WORK - 1),
        ],
        fill=_rgba(spec.clothes),
    )
    d.polygon(
        [
            (cx - u(12), cy + hy + u(8)),
            (cx, cy + hy + u(22)),
            (cx + u(12), cy + hy + u(8)),
        ],
        fill=_rgba(spec.clothes_dark),
    )
    return img


def paint_ears(spec: FaceSpec):
    img = _blank()
    d = _draw(img)
    cy = u(spec.cy)
    hx = u(spec.hx)
    ear_h = u(16 if spec.jaw != 'narrow' else 14)
    inner_col = _mix(spec.skin, spec.skin_shadow, 0.4)
    for sign in (-1, 1):
        x = CX + sign * (hx - u(2))
        if sign < 0:
            box = [x - u(8), cy - ear_h, x + u(4), cy + ear_h]
        else:
            box = [x - u(4), cy - ear_h, x + u(8), cy + ear_h]
        d.ellipse(box, fill=_rgba(spec.skin))
        inner = [box[0] + u(3), box[1] + u(5), box[2] - u(3), box[3] - u(5)]
        d.ellipse(inner, fill=_rgba(inner_col))
    return img


def paint_nose(spec: FaceSpec):
    img = _blank()
    d = _draw(img)
    x, y = CX, u(spec.eye_y + 22)
    kind = spec.nose_kind
    shadow = spec.skin_shadow
    if kind == 'button':
        d.ellipse([x - u(6), y + u(4), x + u(6), y + u(16)], fill=_rgba(shadow))
        d.ellipse([x - u(5), y + u(5), x + u(4), y + u(14)], fill=_rgba(spec.skin))
        d.ellipse([x - u(7), y + u(10), x - u(2), y + u(15)], fill=_rgba(shadow))
        d.ellipse([x + u(2), y + u(10), x + u(7), y + u(15)], fill=_rgba(shadow))
    elif kind == 'sharp':
        d.polygon([(x, y - u(6)), (x + u(3), y + u(16)), (x - u(3), y + u(16))], fill=_rgba(shadow))
        d.polygon([(x, y - u(4)), (x + u(2), y + u(14)), (x - u(1), y + u(14))], fill=_rgba(spec.skin_lit))
        d.ellipse([x - u(5), y + u(12), x - u(1), y + u(17)], fill=_rgba(shadow))
        d.ellipse([x + u(1), y + u(12), x + u(5), y + u(17)], fill=_rgba(shadow))
    elif kind == 'hooked':
        d.polygon(
            [(x - u(2), y - u(4)), (x + u(5), y + u(10)), (x + u(2), y + u(18)),
             (x - u(4), y + u(16)), (x - u(3), y + u(6))],
            fill=_rgba(shadow),
        )
        d.ellipse([x - u(6), y + u(12), x + u(6), y + u(20)], fill=_rgba(shadow))
        d.ellipse([x - u(4), y + u(13), x + u(3), y + u(18)], fill=_rgba(spec.skin))
    elif kind == 'wide':
        d.ellipse([x - u(10), y + u(6), x + u(10), y + u(18)], fill=_rgba(shadow))
        d.ellipse([x - u(8), y + u(7), x + u(8), y + u(16)], fill=_rgba(spec.skin))
        d.ellipse([x - u(11), y + u(11), x - u(4), y + u(17)], fill=_rgba(shadow))
        d.ellipse([x + u(4), y + u(11), x + u(11), y + u(17)], fill=_rgba(shadow))
    else:
        d.polygon(
            [(x - u(1), y - u(2)), (x + u(6), y + u(14)), (x - u(4), y + u(16)), (x - u(3), y + u(4))],
            fill=_rgba(shadow),
        )
        d.ellipse([x - u(8), y + u(11), x - u(1), y + u(17)], fill=_rgba(shadow))
        d.ellipse([x + u(1), y + u(10), x + u(6), y + u(15)], fill=_rgba(shadow))
    return img


def _eye_opening(spec: FaceSpec, state: str):
    w, h = u(spec.eye_w), u(spec.eye_h)
    if state == 'wide':
        return w + u(1), h + u(3)
    if state == 'slightly_narrow':
        return w, max(u(3), h - u(3))
    if state == 'narrow':
        return w, max(u(2), h - u(5))
    if state == 'closed':
        return w, u(1)
    return w, h


def paint_eye_whites(spec: FaceSpec, state: str):
    img = _blank()
    d = _draw(img)
    if state == 'closed':
        return img
    ow, oh = _eye_opening(spec, state)
    (lx, ly), (rx, ry) = _eye_centres(spec)
    white = (236, 232, 224)
    corner = (220, 186, 186)
    for x, y in ((lx, ly), (rx, ry)):
        d.ellipse([x - ow, y - oh, x + ow, y + oh], fill=_rgba(white))
        d.ellipse([x - ow, y - oh + u(1), x - ow + u(4), y + oh - u(1)], fill=_rgba(corner))
    return img


def paint_eyelids(spec: FaceSpec, state: str):
    img = _blank()
    d = _draw(img)
    (lx, ly), (rx, ry) = _eye_centres(spec)
    ow, oh = _eye_opening(spec, state)
    lid = spec.skin
    lash = spec.lash
    for x, y in ((lx, ly), (rx, ry)):
        if state == 'closed':
            d.ellipse([x - u(spec.eye_w), y - u(3), x + u(spec.eye_w), y + u(4)], fill=_rgba(spec.skin))
            d.arc(
                [x - u(spec.eye_w), y - u(3), x + u(spec.eye_w), y + u(5)],
                10, 170, fill=_rgba(lash), width=max(2, u(1)),
            )
            continue
        d.chord(
            [x - ow - u(1), y - oh - u(5), x + ow + u(1), y - oh + u(6)],
            180, 360, fill=_rgba(lid),
        )
        d.arc([x - ow, y - oh - u(1), x + ow, y + u(2)], 200, 340, fill=_rgba(lash), width=max(1, u(1)))
        if state in ('slightly_narrow', 'narrow'):
            d.chord(
                [x - ow - u(1), y + oh - u(6), x + ow + u(1), y + oh + u(5)],
                0, 180, fill=_rgba(lid),
            )
        if state == 'narrow':
            d.arc([x - ow, y - u(1), x + ow, y + oh], 15, 165, fill=_rgba(lash), width=max(1, u(1)))
    return img


def paint_gaze(spec: FaceSpec, gaze: str):
    img = _blank()
    d = _draw(img)
    dx, dy = u(GAZES[gaze][0]), u(GAZES[gaze][1])
    (lx, ly), (rx, ry) = _eye_centres(spec)
    r = u(5 if spec.eye_w >= 14 else 4)
    for x, y in ((lx, ly), (rx, ry)):
        ix, iy = x + dx, y + dy
        d.ellipse([ix - r, iy - r, ix + r, iy + r], fill=_rgba(spec.iris))
        d.ellipse([ix - r, iy - r, ix + r, iy + r], outline=_rgba(spec.iris_dark), width=max(1, u(1)))
        d.ellipse([ix - u(2), iy - u(2), ix + u(2), iy + u(2)], fill=_rgba((16, 12, 12)))
        d.ellipse([ix - u(3), iy - u(3), ix - u(1), iy - u(1)], fill=_rgba((240, 236, 230)))
    return img


def _brow_offsets(state: str, side: str):
    y = 0
    knit = 0
    if state == 'raised' or state == 'asymmetric_raise':
        y = -5
    if state == 'lowered':
        y = 3
    if state == 'knit':
        y = 2
        knit = 4 if side == 'left' else -4
    if state == 'concerned':
        y = -2
        knit = 3 if side == 'left' else -3
    return u(knit), u(y)


def paint_brow(spec: FaceSpec, side: str, state: str):
    img = _blank()
    d = _draw(img)
    (lx, ly), (rx, ry) = _eye_centres(spec)
    x, y = (lx, ly) if side == 'left' else (rx, ry)
    dx, dy = _brow_offsets(state, side)
    thick = u(4 if spec.profile_id != 'face_004' else 6)
    if spec.profile_id == 'face_001':
        thick = u(3)
    if spec.profile_id == 'face_005' and side == 'right':
        thick = u(3)
        dy += u(2)
    half = u(spec.eye_w + 3)
    y0 = y - u(spec.eye_h) - u(7) + dy
    x0 = x + dx
    d.line([(x0 - half, y0 + u(2)), (x0, y0), (x0 + half, y0 + u(1))], fill=_rgba(spec.brow), width=thick)
    if thick >= u(5):
        d.line([(x0 - half + u(1), y0 + u(3)), (x0 + half - u(1), y0 + u(3))], fill=_rgba(spec.hair_dark), width=u(2))
    return img


def paint_mouth(spec: FaceSpec, state: str):
    img = _blank()
    d = _draw(img)
    x, y, w = CX, u(spec.mouth_y), u(spec.mouth_w)
    lip, dark = spec.lip, spec.lip_dark
    if spec.jaw == 'narrow':
        w = max(u(10), w - u(2))
    if state == 'neutral':
        d.ellipse([x - w, y - u(3), x + w, y + u(4)], fill=_rgba(lip))
        d.line([(x - w + u(2), y), (x + w - u(2), y)], fill=_rgba(dark), width=max(1, u(1)))
    elif state == 'pressed':
        d.ellipse([x - w + u(1), y - u(2), x + w - u(1), y + u(3)], fill=_rgba(dark))
        d.line([(x - w, y), (x + w, y)], fill=_rgba(spec.skin_shadow), width=u(2))
    elif state == 'parted':
        d.ellipse([x - w + u(2), y - u(4), x + w - u(2), y + u(6)], fill=_rgba(lip))
        d.ellipse([x - u(5), y - u(1), x + u(5), y + u(4)], fill=_rgba((40, 24, 28)))
        d.ellipse([x - u(4), y - u(1), x + u(4), y + u(1)], fill=_rgba((230, 220, 210)))
    elif state == 'small_smile':
        d.arc([x - w - u(2), y - u(8), x + w + u(2), y + u(8)], 20, 160, fill=_rgba(lip), width=u(3))
        d.arc([x - w, y - u(6), x + w, y + u(6)], 25, 155, fill=_rgba(dark), width=max(1, u(1)))
    elif state == 'smile':
        d.pieslice([x - w - u(4), y - u(10), x + w + u(4), y + u(10)], 20, 160, fill=_rgba(lip))
        d.pieslice([x - u(7), y - u(2), x + u(7), y + u(8)], 20, 160, fill=_rgba((40, 24, 28)))
        d.arc([x - w - u(2), y - u(8), x + w + u(2), y + u(8)], 20, 160, fill=_rgba(dark), width=max(1, u(1)))
    elif state == 'frown':
        d.arc([x - w - u(2), y - u(2), x + w + u(2), y + u(12)], 200, 340, fill=_rgba(lip), width=u(3))
        d.arc([x - w, y, x + w, y + u(10)], 210, 330, fill=_rgba(dark), width=max(1, u(1)))
    elif state == 'grimace':
        d.rectangle([x - w, y - u(3), x + w, y + u(5)], fill=_rgba(lip))
        d.rectangle([x - w + u(2), y - u(1), x + w - u(2), y + u(3)], fill=_rgba((230, 220, 210)))
        for t in range(x - w + u(4), x + w - u(3), u(4)):
            d.line([(t, y - u(1)), (t, y + u(3))], fill=_rgba((200, 196, 188)), width=max(1, u(1)))
    else:
        d.ellipse([x - w + u(3), y - u(3), x + w - u(1), y + u(4)], fill=_rgba(lip))
        d.arc([x - u(4), y - u(2), x + w, y + u(8)], 10, 140, fill=_rgba(dark), width=max(1, u(1)))
    return img


def paint_mouth_base(spec: FaceSpec):
    img = _blank()
    d = _draw(img)
    x, y = CX, u(spec.mouth_y)
    d.ellipse([x - u(4), y - u(12), x + u(4), y - u(4)], fill=_rgba(_mix(spec.skin, spec.skin_shadow, 0.25)))
    return img


def paint_hair_back(spec: FaceSpec):
    img = _blank()
    d = _draw(img)
    cx, cy, hx, hy = CX, u(spec.cy), u(spec.hx), u(spec.hy)
    kind = spec.hair_kind
    if kind == 'short_curls':
        for i, (ox, oy, r) in enumerate(((-28, -30, 18), (0, -38, 20), (28, -30, 18), (-36, -12, 14), (36, -12, 14), (0, -18, 16))):
            col = spec.hair if i % 2 == 0 else spec.hair_dark
            d.ellipse([cx + u(ox) - u(r), cy + u(oy) - u(r), cx + u(ox) + u(r), cy + u(oy) + u(r)], fill=_rgba(col))
    elif kind == 'tight_dark':
        d.ellipse([cx - hx - u(6), cy - hy - u(18), cx + hx + u(6), cy + u(8)], fill=_rgba(spec.hair))
        d.ellipse([cx - hx - u(10), cy - u(8), cx - hx + u(6), cy + u(28)], fill=_rgba(spec.hair_dark))
        d.ellipse([cx + hx - u(6), cy - u(8), cx + hx + u(10), cy + u(28)], fill=_rgba(spec.hair_dark))
    elif kind == 'grey_streak':
        d.ellipse([cx - hx - u(4), cy - hy - u(14), cx + hx + u(4), cy + u(4)], fill=_rgba(spec.hair_dark))
        d.ellipse([cx - hx + u(8), cy - hy - u(18), cx + u(6), cy - u(10)], fill=_rgba(spec.hair_light))
        d.rectangle([cx - hx - u(2), cy - u(4), cx + hx + u(2), cy + u(18)], fill=_rgba(spec.hair_dark))
    elif kind == 'cropped':
        d.ellipse([cx - hx - u(2), cy - hy - u(10), cx + hx + u(2), cy - u(8)], fill=_rgba(spec.hair))
        d.rectangle([cx - hx, cy - hy, cx + hx, cy - u(6)], fill=_rgba(spec.hair_dark))
    else:
        d.ellipse([cx - hx - u(8), cy - hy - u(16), cx + hx + u(12), cy + u(10)], fill=_rgba(spec.hair))
        d.polygon(
            [(cx + hx - u(4), cy - u(8)), (cx + hx + u(22), cy + u(36)), (cx + hx - u(2), cy + u(20))],
            fill=_rgba(spec.hair_dark),
        )
    return img


def paint_hair_front(spec: FaceSpec):
    img = _blank()
    d = _draw(img)
    cx, cy = CX, u(spec.cy)
    kind = spec.hair_kind
    if kind == 'short_curls':
        for ox, oy, r in ((-18, -42, 10), (-4, -46, 11), (12, -44, 10), (24, -36, 8)):
            d.ellipse(
                [cx + u(ox) - u(r), cy + u(oy) - u(r), cx + u(ox) + u(r), cy + u(oy) + u(r)],
                fill=_rgba(spec.hair_light if ox > 0 else spec.hair),
            )
    elif kind == 'tight_dark':
        d.arc([cx - u(spec.hx), cy - u(spec.hy) - u(8), cx + u(spec.hx), cy - u(10)], 200, 340, fill=_rgba(spec.hair), width=u(6))
        d.polygon(
            [(cx - u(20), cy - u(spec.hy) + u(2)), (cx - u(4), cy - u(spec.hy) + u(12)), (cx + u(8), cy - u(spec.hy) + u(2))],
            fill=_rgba(spec.hair_dark),
        )
    elif kind == 'grey_streak':
        d.polygon(
            [(cx - u(30), cy - u(spec.hy) + u(2)), (cx - u(8), cy - u(spec.hy) + u(12)), (cx + u(4), cy - u(spec.hy) + u(2))],
            fill=_rgba(spec.hair_light),
        )
        d.polygon(
            [(cx + u(6), cy - u(spec.hy)), (cx + u(22), cy - u(spec.hy) + u(10)), (cx + u(30), cy - u(spec.hy) + u(2))],
            fill=_rgba(spec.hair),
        )
    elif kind == 'cropped':
        d.rectangle([cx - u(spec.hx) + u(8), cy - u(spec.hy) - u(4), cx + u(spec.hx) - u(8), cy - u(spec.hy) + u(6)], fill=_rgba(spec.hair))
    else:
        d.polygon(
            [(cx - u(28), cy - u(spec.hy) + u(2)), (cx - u(6), cy - u(spec.hy) + u(14)), (cx + u(10), cy - u(spec.hy)), (cx - u(4), cy - u(spec.hy) - u(6))],
            fill=_rgba(spec.hair_light),
        )
        d.polygon(
            [(cx + u(8), cy - u(spec.hy)), (cx + u(26), cy - u(spec.hy) + u(12)), (cx + u(34), cy - u(spec.hy) - u(2))],
            fill=_rgba(spec.hair),
        )
    return img


def paint_facial_hair(spec: FaceSpec):
    img = _blank()
    if not spec.beard:
        return img
    d = _draw(img)
    cx = CX
    chin = u(spec.cy + spec.hy)
    my = u(spec.mouth_y)
    d.polygon(
        [
            (cx - u(26), my + u(6)),
            (cx - u(22), chin - u(4)),
            (cx, chin + u(4)),
            (cx + u(22), chin - u(4)),
            (cx + u(26), my + u(6)),
            (cx + u(12), my + u(12)),
            (cx, my + u(16)),
            (cx - u(12), my + u(12)),
        ],
        fill=_rgba(spec.hair_dark),
    )
    d.polygon(
        [
            (cx - u(18), my + u(10)),
            (cx - u(14), chin - u(10)),
            (cx, chin - u(2)),
            (cx + u(14), chin - u(10)),
            (cx + u(18), my + u(10)),
        ],
        fill=_rgba(spec.hair),
    )
    d.ellipse([cx - u(16), my - u(10), cx - u(2), my - u(2)], fill=_rgba(spec.hair_dark))
    d.ellipse([cx + u(2), my - u(10), cx + u(16), my - u(2)], fill=_rgba(spec.hair_dark))
    return img


def paint_wrinkles(spec: FaceSpec):
    img = _blank()
    if not spec.wrinkles:
        return img
    d = _draw(img)
    col = _rgba(spec.skin_shadow, 160)
    (lx, ly), (rx, ry) = _eye_centres(spec)
    d.arc([lx - u(12), ly - u(8), lx + u(8), ly + u(6)], 200, 330, fill=col, width=max(1, u(1)))
    d.arc([rx - u(8), ry - u(8), rx + u(12), ry + u(6)], 210, 340, fill=col, width=max(1, u(1)))
    d.line([(CX - u(18), u(spec.eye_y - 16)), (CX + u(18), u(spec.eye_y - 18))], fill=col, width=max(1, u(1)))
    d.line([(CX - u(14), u(spec.eye_y - 12)), (CX + u(16), u(spec.eye_y - 13))], fill=col, width=max(1, u(1)))
    d.line([(CX - u(8), u(spec.mouth_y + 10)), (CX - u(16), u(spec.mouth_y + 18))], fill=col, width=max(1, u(1)))
    d.line([(CX + u(8), u(spec.mouth_y + 10)), (CX + u(16), u(spec.mouth_y + 18))], fill=col, width=max(1, u(1)))
    return img


def paint_freckles(spec: FaceSpec):
    img = _blank()
    if not spec.freckles:
        return img
    d = _draw(img)
    col = _rgba((168, 96, 70), 200)
    (lx, ly), (rx, ry) = _eye_centres(spec)
    spots = [
        (lx - u(6), ly + u(12)), (lx + u(4), ly + u(16)), (lx - u(2), ly + u(20)),
        (rx + u(5), ry + u(12)), (rx - u(3), ry + u(18)), (rx + u(8), ry + u(20)),
        (CX - u(10), u(spec.eye_y + 28)), (CX + u(8), u(spec.eye_y + 26)),
        (CX - u(18), u(spec.mouth_y - 16)), (CX + u(14), u(spec.mouth_y - 14)),
    ]
    for x, y in spots:
        d.ellipse([x, y, x + u(2), y + u(2)], fill=col)
    return img


def paint_scar(spec: FaceSpec):
    img = _blank()
    if not spec.scar:
        return img
    d = _draw(img)
    (lx, ly), _rx = _eye_centres(spec)
    d.line([(lx + u(10), ly + u(8)), (lx + u(18), ly + u(28))], fill=_rgba((176, 120, 108)), width=u(2))
    d.line([(lx + u(9), ly + u(10)), (lx + u(17), ly + u(26))], fill=_rgba((214, 186, 170)), width=max(1, u(1)))
    return img


def write_manifest(folder: Path, spec: FaceSpec, used: dict[str, bool]) -> None:
    identity = {
        'head': 'base/head.png',
        'ears': 'base/ears.png',
        'nose': 'base/nose.png',
        'mouth_base': 'base/mouth_base.png',
        'hair_back': 'hair/back.png',
        'hair_front': 'hair/front.png',
    }
    if used.get('facial_hair'):
        identity['facial_hair'] = 'details/facial_hair.png'
    if used.get('wrinkles'):
        identity['wrinkles'] = 'details/wrinkles.png'
    if used.get('freckles'):
        identity['freckles'] = 'details/freckles.png'
    if used.get('scars'):
        identity['scars'] = 'details/scars.png'
    manifest = {
        'schema_version': 1,
        'visual_profile_id': spec.profile_id,
        'canvas': {'width': CANVAS, 'height': CANVAS},
        'source': 'procedural_prototype',
        'identity': identity,
        'expressions': {
            'eyes': {k: f'eyes/{k}.png' for k in EYE_STATES},
            'eyelids': {k: f'eyelids/{k}.png' for k in EYE_STATES},
            'gaze': {k: f'gaze/{k}.png' for k in GAZES},
            'brows': {
                'left': {k: f'brows/left_{k}.png' for k in BROW_STATES},
                'right': {k: f'brows/right_{k}.png' for k in BROW_STATES},
            },
            'mouths': {k: f'mouths/{k}.png' for k in MOUTH_STATES},
        },
        'z_order': list(Z_ORDER),
    }
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def generate_face(spec: FaceSpec, dest_root: Path) -> Path:
    folder = dest_root / spec.profile_id
    _save(paint_head(spec), folder / 'base' / 'head.png')
    _save(paint_ears(spec), folder / 'base' / 'ears.png')
    _save(paint_nose(spec), folder / 'base' / 'nose.png')
    _save(paint_mouth_base(spec), folder / 'base' / 'mouth_base.png')
    _save(paint_hair_back(spec), folder / 'hair' / 'back.png')
    _save(paint_hair_front(spec), folder / 'hair' / 'front.png')
    used = {
        'facial_hair': spec.beard,
        'wrinkles': spec.wrinkles,
        'freckles': spec.freckles,
        'scars': spec.scar,
    }
    if spec.beard:
        _save(paint_facial_hair(spec), folder / 'details' / 'facial_hair.png')
    if spec.wrinkles:
        _save(paint_wrinkles(spec), folder / 'details' / 'wrinkles.png')
    if spec.freckles:
        _save(paint_freckles(spec), folder / 'details' / 'freckles.png')
    if spec.scar:
        _save(paint_scar(spec), folder / 'details' / 'scars.png')
    for state in EYE_STATES:
        _save(paint_eye_whites(spec, state), folder / 'eyes' / f'{state}.png')
        _save(paint_eyelids(spec, state), folder / 'eyelids' / f'{state}.png')
    for gaze in GAZES:
        _save(paint_gaze(spec, gaze), folder / 'gaze' / f'{gaze}.png')
    for state in BROW_STATES:
        _save(paint_brow(spec, 'left', state), folder / 'brows' / f'left_{state}.png')
        _save(paint_brow(spec, 'right', state), folder / 'brows' / f'right_{state}.png')
    for state in MOUTH_STATES:
        _save(paint_mouth(spec, state), folder / 'mouths' / f'{state}.png')
    write_manifest(folder, spec, used)
    return folder


def paint_body(spec: FaceSpec, attendant: bool = False):
    """72×128 figure in the same pixel register as staff sprites (collar, pockets, face)."""
    from PIL import Image, ImageDraw

    w, h = 72, 128
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, hair = spec.skin, spec.hair
    if attendant:
        clothes, clothes_d, clothes_l = (214, 208, 196), (176, 168, 154), (232, 226, 214)
    else:
        clothes, clothes_d, clothes_l = spec.clothes, spec.clothes_dark, _mix(spec.clothes, (255, 255, 255), 0.22)
    cx = 36
    short = spec.stature == 'short'
    tall = spec.stature == 'tall'
    broad = spec.stature == 'broad'
    top = 8 if tall else (16 if short else 12)
    tw = 18 if broad else (13 if tall else 15)
    head_r = 12 if broad else (10 if tall else 11)
    head_cy = top + head_r
    torso_y0 = head_cy + head_r - 2
    torso_y1 = 94 if not short else 90
    shoe = (32, 28, 28)
    d.rectangle([cx - 11, 116, cx - 1, 124], fill=_rgba(shoe))
    d.rectangle([cx + 1, 116, cx + 11, 124], fill=_rgba(shoe))
    d.rectangle([cx - 9, torso_y1 - 2, cx - 2, 118], fill=_rgba(clothes_d))
    d.rectangle([cx + 2, torso_y1 - 2, cx + 9, 118], fill=_rgba(clothes_d))
    d.rectangle([cx - 8, torso_y1, cx - 3, 110], fill=_rgba(clothes))
    d.rectangle([cx + 3, torso_y1, cx + 8, 110], fill=_rgba(clothes))
    d.rectangle([cx - tw, torso_y0, cx + tw, torso_y1], fill=_rgba(clothes))
    d.rectangle([cx - tw + 2, torso_y0 + 2, cx + tw - 2, torso_y0 + 10], fill=_rgba(clothes_l))
    d.polygon(
        [(cx - 8, torso_y0 - 2), (cx, torso_y0 + 8), (cx + 8, torso_y0 - 2),
         (cx + 10, torso_y0 + 4), (cx - 10, torso_y0 + 4)],
        fill=_rgba(clothes_d),
    )
    d.line([(cx, torso_y0 + 8), (cx, torso_y1 - 8)], fill=_rgba(clothes_d), width=1)
    d.rectangle([cx - tw + 3, torso_y1 - 18, cx - 3, torso_y1 - 8], outline=_rgba(clothes_d))
    d.rectangle([cx + 3, torso_y1 - 18, cx + tw - 3, torso_y1 - 8], outline=_rgba(clothes_d))
    d.rectangle([cx - tw - 8, torso_y0 + 6, cx - tw, torso_y1 - 10], fill=_rgba(clothes))
    d.rectangle([cx + tw, torso_y0 + 6, cx + tw + 8, torso_y1 - 10], fill=_rgba(clothes))
    d.ellipse([cx - tw - 9, torso_y1 - 16, cx - tw + 1, torso_y1 - 6], fill=_rgba(skin))
    d.ellipse([cx + tw - 1, torso_y1 - 16, cx + tw + 9, torso_y1 - 6], fill=_rgba(skin))
    d.rectangle([cx - 4, head_cy + head_r - 4, cx + 4, torso_y0 + 4], fill=_rgba(spec.skin_shadow))
    d.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r], fill=_rgba(skin))
    d.ellipse([cx - head_r + 3, head_cy - head_r + 2, cx - 1, head_cy], fill=_rgba(spec.skin_lit))
    d.ellipse([cx - head_r - 1, head_cy - head_r - 6, cx + head_r + 1, head_cy - 4], fill=_rgba(hair))
    if spec.hair_kind == 'short_curls':
        d.ellipse([cx - head_r - 4, head_cy - 6, cx - 4, head_cy + 4], fill=_rgba(spec.hair_dark))
        d.ellipse([cx + 4, head_cy - 6, cx + head_r + 4, head_cy + 4], fill=_rgba(spec.hair_light))
    elif spec.hair_kind == 'tight_dark':
        d.rectangle([cx - head_r, head_cy - head_r - 2, cx + head_r, head_cy - 4], fill=_rgba(spec.hair_dark))
    elif spec.hair_kind == 'grey_streak':
        d.ellipse([cx - head_r, head_cy - head_r - 4, cx - 2, head_cy], fill=_rgba(spec.hair_light))
    elif spec.hair_kind == 'reddish':
        d.polygon(
            [(cx + 4, head_cy - 2), (cx + head_r + 6, head_cy + 10), (cx + head_r, head_cy)],
            fill=_rgba(spec.hair_dark),
        )
    if spec.beard:
        d.ellipse([cx - 8, head_cy + 2, cx + 8, head_cy + head_r + 4], fill=_rgba(spec.hair_dark))
    eye_y = head_cy - 1
    d.ellipse([cx - 6, eye_y - 2, cx - 2, eye_y + 2], fill=_rgba((236, 232, 224)))
    d.ellipse([cx + 2, eye_y - 2, cx + 6, eye_y + 2], fill=_rgba((236, 232, 224)))
    d.point((cx - 4, eye_y), fill=_rgba(spec.iris_dark))
    d.point((cx + 4, eye_y), fill=_rgba(spec.iris_dark))
    d.line([(cx - 7, eye_y - 3), (cx - 2, eye_y - 4)], fill=_rgba(spec.brow), width=1)
    d.line([(cx + 2, eye_y - 4), (cx + 7, eye_y - 3)], fill=_rgba(spec.brow), width=1)
    d.line([(cx - 3, head_cy + 6), (cx + 3, head_cy + 6)], fill=_rgba(spec.lip), width=1)
    if spec.freckles:
        d.point((cx - 6, head_cy + 3), fill=_rgba((168, 96, 70)))
        d.point((cx + 5, head_cy + 4), fill=_rgba((168, 96, 70)))
    if spec.scar:
        d.line([(cx - 2, head_cy + 2), (cx + 4, head_cy + 8)], fill=_rgba((176, 120, 108)))
    d.rectangle([cx - tw + 1, torso_y1 - 28, cx + tw - 1, torso_y1 - 24], fill=_rgba((48, 40, 36)))
    return _outline_body(img)


def _outline_body(img):
    from PIL import Image

    w, h = img.size
    src = img.load()
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    dst = out.load()
    ink = (28, 24, 22, 255)
    for y in range(h):
        for x in range(w):
            if src[x, y][3] > 16:
                dst[x, y] = src[x, y]
                continue
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and src[nx, ny][3] > 16:
                    dst[x, y] = ink
                    break
    return out


def generate_bodies(dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    by_id = {s.profile_id: s for s in SPECS}
    mapping = [
        ('body_001', by_id['face_001'], False),
        ('body_002', by_id['face_002'], False),
        ('body_003', by_id['face_003'], False),
        ('body_attendant', by_id['face_001'], True),
    ]
    for name, spec, attendant in mapping:
        path = dest / f'{name}.png'
        paint_body(spec, attendant=attendant).save(path, format='PNG')
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Generate procedural portrait layer kits')
    parser.add_argument('--portraits-root', type=Path, default=_ROOT / 'assets' / 'portraits')
    parser.add_argument('--bodies-dir', type=Path, default=_ROOT / 'assets' / 'sprites' / 'characters')
    parser.add_argument('--skip-faces', action='store_true')
    parser.add_argument('--skip-bodies', action='store_true')
    args = parser.parse_args(argv)
    if not args.skip_faces:
        for spec in SPECS:
            folder = generate_face(spec, args.portraits_root)
            print(f'wrote {folder}')
    if not args.skip_bodies:
        for path in generate_bodies(args.bodies_dir):
            print(f'wrote {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
