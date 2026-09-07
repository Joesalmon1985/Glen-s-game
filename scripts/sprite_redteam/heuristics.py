"""Deterministic pixel / geometry checks for sprites and composed scenes."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from scripts.redteam.findings import Finding


@dataclass
class HeuristicResult:
    target: str
    kind: str  # asset | composition
    ok: bool
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'target': self.target,
            'kind': self.kind,
            'ok': self.ok,
            'findings': [f.to_dict() for f in self.findings],
            'metrics': self.metrics,
        }


def _is_near_magenta(r: int, g: int, b: int) -> bool:
    if r >= 230 and b >= 230 and g <= 40:
        return True
    if abs(r - 255) <= 40 and abs(b - 255) <= 40 and g <= 60:
        return True
    return False


def _bbox_area_ratio(img) -> tuple[Optional[tuple[int, int, int, int]], float, float]:
    """Return (bbox, opaque_fraction, bbox_fill_of_canvas)."""
    bbox = img.getbbox()
    w, h = img.size
    canvas = max(1, w * h)
    if not bbox:
        return None, 0.0, 0.0
    pixels = img.load()
    opaque = 0
    for y in range(h):
        for x in range(w):
            if pixels[x, y][3] > 16:
                opaque += 1
    bw = bbox[2] - bbox[0]
    bh = bbox[3] - bbox[1]
    return bbox, opaque / canvas, (bw * bh) / canvas


def _text_blob_suspect(img) -> bool:
    """Cheap OCR-lite: dense high-contrast runs that look like lettering strips."""
    rgba = img.convert('RGBA')
    gray = rgba.convert('L')
    w, h = gray.size
    if w < 8 or h < 8:
        return False
    pixels = gray.load()
    alpha = rgba.load()
    # Horizontal edge density in mid band
    edges = 0
    samples = 0
    y0, y1 = h // 4, (3 * h) // 4
    for y in range(y0, y1, max(1, h // 32)):
        prev = None
        for x in range(0, w, max(1, w // 64)):
            if alpha[x, y][3] < 32:
                prev = None
                continue
            val = pixels[x, y]
            if prev is not None and abs(val - prev) > 48:
                edges += 1
            samples += 1
            prev = val
    if samples < 20:
        return False
    return (edges / samples) > 0.45


def judge_asset(
    path: Path,
    *,
    sprite_id: str,
    kind: str,
    expect_size: tuple[int, int],
) -> HeuristicResult:
    findings: list[Finding] = []
    metrics: dict[str, Any] = {'path': str(path), 'expect_size': list(expect_size)}

    if not path.is_file():
        findings.append(Finding(
            severity='P0',
            layer='sprite_heuristic',
            persona='kit_audit',
            passage_id=0,
            utterance=sprite_id,
            detail=f'Missing sprite file: {path}',
            invariant='asset_exists',
            extra={'sprite_id': sprite_id, 'kind': kind},
        ))
        return HeuristicResult(sprite_id, 'asset', False, findings, metrics)

    try:
        from PIL import Image
        img = Image.open(path).convert('RGBA')
    except Exception as exc:  # noqa: BLE001
        findings.append(Finding(
            severity='P0',
            layer='sprite_heuristic',
            persona='kit_audit',
            passage_id=0,
            utterance=sprite_id,
            detail=f'Corrupt/unreadable PNG: {exc}',
            invariant='asset_valid_png',
            extra={'sprite_id': sprite_id, 'kind': kind},
        ))
        return HeuristicResult(sprite_id, 'asset', False, findings, metrics)

    metrics['size'] = list(img.size)
    if img.size != expect_size:
        findings.append(Finding(
            severity='P0',
            layer='sprite_heuristic',
            persona='kit_audit',
            passage_id=0,
            utterance=sprite_id,
            detail=f'Size {img.size} != expected {expect_size}',
            invariant='asset_size',
            extra={'sprite_id': sprite_id, 'kind': kind},
        ))

    pixels = img.load()
    w, h = img.size
    magenta = 0
    total = w * h
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a > 16 and _is_near_magenta(r, g, b):
                magenta += 1
    magenta_frac = magenta / max(1, total)
    metrics['magenta_frac'] = round(magenta_frac, 5)

    if kind == 'background':
        if magenta_frac > 0.02:
            findings.append(Finding(
                severity='P1',
                layer='sprite_heuristic',
                persona='kit_audit',
                passage_id=0,
                utterance=sprite_id,
                detail=f'Background has magenta bleed ({magenta_frac:.2%})',
                invariant='bg_no_magenta',
                extra={'sprite_id': sprite_id, 'kind': kind},
            ))
        # Flatness: unique colours among opaque pixels (sampled)
        colours = set()
        step = max(1, min(w, h) // 32)
        for y in range(0, h, step):
            for x in range(0, w, step):
                colours.add(pixels[x, y][:3])
        metrics['unique_colours_sample'] = len(colours)
        if len(colours) < 8:
            findings.append(Finding(
                severity='P1',
                layer='sprite_heuristic',
                persona='kit_audit',
                passage_id=0,
                utterance=sprite_id,
                detail=f'Background looks nearly flat ({len(colours)} sampled colours)',
                invariant='bg_not_flat',
                extra={'sprite_id': sprite_id, 'kind': kind},
            ))
    else:
        if magenta_frac > 0.01:
            sev = 'P0' if magenta_frac > 0.15 else 'P1'
            findings.append(Finding(
                severity=sev,
                layer='sprite_heuristic',
                persona='kit_audit',
                passage_id=0,
                utterance=sprite_id,
                detail=f'Residual magenta after key ({magenta_frac:.2%})',
                invariant='chroma_clean',
                extra={'sprite_id': sprite_id, 'kind': kind},
            ))
        bbox, opaque_frac, bbox_frac = _bbox_area_ratio(img)
        metrics['opaque_frac'] = round(opaque_frac, 5)
        metrics['bbox_frac'] = round(bbox_frac, 5)
        metrics['bbox'] = list(bbox) if bbox else None
        # Unique opaque colours (silhouettes / failed style)
        opaque_colours: set[tuple[int, int, int]] = set()
        step = max(1, min(w, h) // 16)
        for y in range(0, h, step):
            for x in range(0, w, step):
                r, g, b, a = pixels[x, y]
                if a > 16:
                    opaque_colours.add((r, g, b))
        metrics['unique_opaque_colours'] = len(opaque_colours)

        if opaque_frac < 0.02 or bbox is None:
            findings.append(Finding(
                severity='P0',
                layer='sprite_heuristic',
                persona='kit_audit',
                passage_id=0,
                utterance=sprite_id,
                detail='Sprite is empty / near-empty after alpha',
                invariant='content_present',
                extra={'sprite_id': sprite_id, 'kind': kind},
            ))
        elif opaque_frac > 0.88:
            # Chroma key failed: solid non-magenta backdrop still fills the canvas
            findings.append(Finding(
                severity='P1',
                layer='sprite_heuristic',
                persona='kit_audit',
                passage_id=0,
                utterance=sprite_id,
                detail=(
                    f'Not isolated for overlay (opaque_frac={opaque_frac:.0%}); '
                    'likely wrong background colour instead of magenta/transparent'
                ),
                invariant='isolation',
                extra={'sprite_id': sprite_id, 'kind': kind},
            ))
        elif bbox_frac < 0.08:
            findings.append(Finding(
                severity='P1',
                layer='sprite_heuristic',
                persona='kit_audit',
                passage_id=0,
                utterance=sprite_id,
                detail=f'Content bbox tiny vs canvas ({bbox_frac:.2%})',
                invariant='bbox_size',
                extra={'sprite_id': sprite_id, 'kind': kind},
            ))
        if len(opaque_colours) <= 3 and opaque_frac >= 0.02:
            findings.append(Finding(
                severity='P1' if kind == 'character' else 'P2',
                layer='sprite_heuristic',
                persona='kit_audit',
                passage_id=0,
                utterance=sprite_id,
                detail=(
                    f'Too few colours ({len(opaque_colours)}) — silhouette/flat '
                    'blob rather than readable pixel art'
                ),
                invariant='detail_palette',
                extra={'sprite_id': sprite_id, 'kind': kind},
            ))
        # Salt-and-pepper / static noise: high neighbour disagreement among opaque pixels
        if opaque_frac >= 0.02:
            disagree = 0
            samples = 0
            step_n = max(1, min(w, h) // 24)
            for y in range(1, h - 1, step_n):
                for x in range(1, w - 1, step_n):
                    r, g, b, a = pixels[x, y]
                    if a <= 16:
                        continue
                    samples += 1
                    for dx, dy in ((1, 0), (0, 1)):
                        r2, g2, b2, a2 = pixels[x + dx, y + dy]
                        if a2 <= 16:
                            continue
                        if abs(r - r2) + abs(g - g2) + abs(b - b2) > 90:
                            disagree += 1
            noise_ratio = disagree / max(1, samples * 2)
            metrics['noise_ratio'] = round(noise_ratio, 4)
            if noise_ratio > 0.35:
                findings.append(Finding(
                    severity='P1',
                    layer='sprite_heuristic',
                    persona='kit_audit',
                    passage_id=0,
                    utterance=sprite_id,
                    detail=f'Heavy pixel noise/static (noise_ratio={noise_ratio:.2f})',
                    invariant='noise',
                    extra={'sprite_id': sprite_id, 'kind': kind},
                ))
        # Note: edge-crush is not flagged — chroma crop + NEAREST fit intentionally
        # fills the catalog size, so content routinely touches the PNG edges.

    if _text_blob_suspect(img):
        findings.append(Finding(
            severity='P2',
            layer='sprite_heuristic',
            persona='kit_audit',
            passage_id=0,
            utterance=sprite_id,
            detail='High edge density — possible baked-in text/lettering',
            invariant='no_text_blob',
            extra={'sprite_id': sprite_id, 'kind': kind},
        ))

    return HeuristicResult(sprite_id, 'asset', len(findings) == 0, findings, metrics)


def _layer_bbox(xy: tuple[int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    x, y = xy
    w, h = size
    return x, y, x + w, y + h


def _clip_fraction(bbox: tuple[int, int, int, int], canvas: tuple[int, int]) -> float:
    x0, y0, x1, y1 = bbox
    cw, ch = canvas
    iw = max(0, min(x1, cw) - max(x0, 0))
    ih = max(0, min(y1, ch) - max(y0, 0))
    area = max(1, (x1 - x0) * (y1 - y0))
    visible = iw * ih
    return 1.0 - (visible / area)


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(1, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1, (bx1 - bx0) * (by1 - by0))
    return inter / float(area_a + area_b - inter)


def _sprite_size(catalog: dict, sprite_id: str, canvas: tuple[int, int]) -> tuple[int, int]:
    if sprite_id in (catalog.get('backgrounds') or {}):
        return canvas
    for section in ('props', 'characters'):
        entry = (catalog.get(section) or {}).get(sprite_id)
        if entry:
            raw = entry.get('size') or [96, 96]
            return int(raw[0]), int(raw[1])
    return 96, 96


def judge_composition(
    *,
    fixture_id: str,
    room_id: str,
    layers: list[Any],
    catalog: dict,
    expected_sprite_ids: Optional[set[str]] = None,
    canvas: tuple[int, int] = (512, 512),
) -> HeuristicResult:
    findings: list[Finding] = []
    metrics: dict[str, Any] = {'room_id': room_id, 'layer_count': len(layers)}
    present = {getattr(layer, 'sprite_id', '') for layer in layers}

    if expected_sprite_ids:
        missing = sorted(expected_sprite_ids - present)
        unexpected_core = []  # only flag missing expected, not extras
        metrics['expected'] = sorted(expected_sprite_ids)
        metrics['missing'] = missing
        if missing:
            findings.append(Finding(
                severity='P0',
                layer='sprite_heuristic',
                persona='layout_audit',
                passage_id=0,
                utterance=fixture_id,
                detail=f'Missing expected sprites: {", ".join(missing)}',
                invariant='expected_sprites',
                extra={'room_id': room_id, 'missing': missing},
            ))

    sized: list[tuple[Any, tuple[int, int, int, int]]] = []
    for layer in layers:
        kind = getattr(layer, 'kind', '')
        if kind == 'background':
            continue
        size = _sprite_size(catalog, layer.sprite_id, canvas)
        bbox = _layer_bbox(tuple(layer.xy), size)
        sized.append((layer, bbox))
        clip = _clip_fraction(bbox, canvas)
        if clip > 0.25:
            sev = 'P0' if clip > 0.5 else 'P1'
            findings.append(Finding(
                severity=sev,
                layer='sprite_heuristic',
                persona='layout_audit',
                passage_id=0,
                utterance=fixture_id,
                detail=f'{layer.sprite_id} clipped {clip:.0%} at {list(layer.xy)}',
                invariant='on_canvas',
                extra={'room_id': room_id, 'sprite_id': layer.sprite_id, 'clip': clip},
            ))
        x0, y0, x1, y1 = bbox
        if x1 <= 0 or y1 <= 0 or x0 >= canvas[0] or y0 >= canvas[1]:
            findings.append(Finding(
                severity='P0',
                layer='sprite_heuristic',
                persona='layout_audit',
                passage_id=0,
                utterance=fixture_id,
                detail=f'{layer.sprite_id} fully off-canvas at {list(layer.xy)}',
                invariant='on_canvas',
                extra={'room_id': room_id, 'sprite_id': layer.sprite_id},
            ))

    characters = [(layer, bbox) for layer, bbox in sized if getattr(layer, 'kind', '') == 'character']
    props = [(layer, bbox) for layer, bbox in sized if getattr(layer, 'kind', '') == 'prop']
    for char_layer, char_bbox in characters:
        # Upper 40% of character bbox ≈ face/torso for overlap check
        x0, y0, x1, y1 = char_bbox
        face = (x0, y0, x1, y0 + int((y1 - y0) * 0.4))
        for prop_layer, prop_bbox in props:
            # Only flag if prop is drawn above character (higher z = later = on top)
            if getattr(prop_layer, 'z', 0) <= getattr(char_layer, 'z', 0):
                continue
            iou = _iou(face, prop_bbox)
            if iou > 0.2:
                findings.append(Finding(
                    severity='P1',
                    layer='sprite_heuristic',
                    persona='layout_audit',
                    passage_id=0,
                    utterance=fixture_id,
                    detail=(
                        f'{prop_layer.sprite_id} overlaps {char_layer.sprite_id} '
                        f'face/torso (IoU={iou:.2f})'
                    ),
                    invariant='character_visible',
                    extra={
                        'room_id': room_id,
                        'prop': prop_layer.sprite_id,
                        'character': char_layer.sprite_id,
                        'iou': iou,
                    },
                ))
        for other_layer, other_bbox in characters:
            if other_layer is char_layer:
                continue
            if getattr(other_layer, 'z', 0) <= getattr(char_layer, 'z', 0):
                continue
            iou = _iou(char_bbox, other_bbox)
            if iou > 0.35:
                findings.append(Finding(
                    severity='P2',
                    layer='sprite_heuristic',
                    persona='layout_audit',
                    passage_id=0,
                    utterance=fixture_id,
                    detail=f'{other_layer.sprite_id} heavily overlaps {char_layer.sprite_id} (IoU={iou:.2f})',
                    invariant='character_stack',
                    extra={'room_id': room_id, 'iou': iou},
                ))

    return HeuristicResult(fixture_id, 'composition', len(findings) == 0, findings, metrics)


def catalog_expect_size(catalog: dict, kind: str, entry: dict) -> tuple[int, int]:
    canvas = catalog.get('canvas') or {}
    if kind == 'background':
        return int(canvas.get('width') or 512), int(canvas.get('height') or 512)
    raw = entry.get('size') or [96, 96]
    return int(raw[0]), int(raw[1])
