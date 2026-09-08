"""Standard pose matrix and contact-sheet export for the face bake-off."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from puca_dungeon.portrait.manifest import CANVAS_SIZE, FACE_PROFILE_IDS
from puca_dungeon.portrait.render import portrait_to_display_rgb, render_portrait
from puca_dungeon.portrait.types import BrowState, EyeState, FacePose, Gaze, MouthState

STANDARD_POSES: tuple[tuple[str, FacePose], ...] = (
    ('neutral', FacePose()),
    ('small smile', FacePose(mouth=MouthState.SMALL_SMILE)),
    ('pressed / guarded', FacePose(mouth=MouthState.PRESSED, eye_openness=EyeState.SLIGHTLY_NARROW)),
    ('frown', FacePose(mouth=MouthState.FROWN, left_brow=BrowState.LOWERED, right_brow=BrowState.LOWERED)),
    ('wide-eyed', FacePose(eye_openness=EyeState.WIDE)),
    ('narrow-eyed', FacePose(eye_openness=EyeState.NARROW)),
    ('eyes closed', FacePose(eye_openness=EyeState.CLOSED)),
    ('look left', FacePose(gaze=Gaze.LEFT)),
    ('look right', FacePose(gaze=Gaze.RIGHT)),
    ('brows raised', FacePose(left_brow=BrowState.RAISED, right_brow=BrowState.RAISED)),
    ('brows knit', FacePose(left_brow=BrowState.KNIT, right_brow=BrowState.KNIT)),
)


def gallery_label(visual_profile_id: str) -> str:
    digits = ''.join(ch for ch in visual_profile_id if ch.isdigit())
    if digits:
        return f'FACE {int(digits):03d}'
    return 'FACE'


def default_export_dir() -> Path:
    return Path(__file__).resolve().parents[2] / 'tools' / 'portrait_bakeoff'


def _cell_size(scale: int = 1) -> tuple[int, int]:
    return CANVAS_SIZE[0] // scale, CANVAS_SIZE[1] // scale


def _paste_scaled(sheet, portrait, xy, scale: int) -> None:
    from PIL import Image

    rgb = portrait_to_display_rgb(portrait)
    if scale != 1:
        size = _cell_size(scale)
        rgb = rgb.resize(size, Image.Resampling.NEAREST)
    sheet.paste(rgb, xy)


def export_neutral_sheet(
    dest: Path,
    profile_ids: Iterable[str] = FACE_PROFILE_IDS,
    scale: int = 4,
) -> Path:
    from PIL import Image, ImageDraw

    ids = list(profile_ids)
    cw, ch = _cell_size(scale)
    pad = 16
    label_h = 28
    width = pad + len(ids) * (cw + pad)
    height = pad + label_h + ch + pad
    sheet = Image.new('RGB', (width, height), (18, 20, 24))
    draw = ImageDraw.Draw(sheet)
    pose = FacePose()
    x = pad
    for pid in ids:
        portrait = render_portrait(pid, pose)
        _paste_scaled(sheet, portrait, (x, pad + label_h), scale)
        draw.text((x + 8, pad + 4), gallery_label(pid), fill=(230, 220, 200))
        x += cw + pad
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, format='PNG')
    return dest


def export_expression_sheet(
    visual_profile_id: str,
    dest: Path,
    poses: Iterable[tuple[str, FacePose]] = STANDARD_POSES,
    scale: int = 4,
    columns: int = 4,
) -> Path:
    from PIL import Image, ImageDraw

    items = list(poses)
    cw, ch = _cell_size(scale)
    pad = 12
    label_h = 22
    header = 36
    cols = max(1, columns)
    rows = (len(items) + cols - 1) // cols
    width = pad + cols * (cw + pad)
    height = header + rows * (label_h + ch + pad) + pad
    sheet = Image.new('RGB', (width, height), (18, 20, 24))
    draw = ImageDraw.Draw(sheet)
    draw.text((pad, 10), gallery_label(visual_profile_id), fill=(230, 220, 200))
    for i, (name, pose) in enumerate(items):
        col = i % cols
        row = i // cols
        x = pad + col * (cw + pad)
        y = header + row * (label_h + ch + pad)
        draw.text((x + 4, y), name, fill=(180, 175, 165))
        portrait = render_portrait(visual_profile_id, pose)
        _paste_scaled(sheet, portrait, (x, y + label_h), scale)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, format='PNG')
    return dest


def export_contact_sheets(out_dir: Optional[Path] = None) -> list[Path]:
    target = Path(out_dir) if out_dir is not None else default_export_dir()
    target.mkdir(parents=True, exist_ok=True)
    written = [
        export_neutral_sheet(target / 'face_bakeoff_all_neutral.png'),
    ]
    for pid in FACE_PROFILE_IDS:
        digits = ''.join(ch for ch in pid if ch.isdigit())
        written.append(
            export_expression_sheet(pid, target / f'face_bakeoff_expressions_{digits}.png')
        )
    return written


if __name__ == '__main__':
    for path in export_contact_sheets():
        print(path)
