#!/usr/bin/env python3
"""Local art → sprite candidates via SD img2img (no Cursor cloud gen).

Examples:
  python scripts/art_to_sprite.py door-slit-candidates
  python scripts/art_to_sprite.py restyle --input path.jpg --id door_closed --state closed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from puca_dungeon.visual_catalog import DEFAULT_ASSETS_ROOT, load_catalog
from scripts.generate_sprites import _chroma_key_and_fit

DOOR_REF_DIR = DEFAULT_ASSETS_ROOT / 'references' / 'door'
DOOR_OUT_DIR = DOOR_REF_DIR / 'candidates'

PROMPTS = {
    'closed': (
        'heavy institutional cell door prop, full front view, thick bolted metal door, '
        'observation slit CLOSED with metal shutter plate, no inner handle, single object, '
        'pixel art prop, solid bright magenta background #FF00FF only, centered, no people'
    ),
    'open': (
        'heavy institutional cell door prop, full front view, thick bolted metal door, '
        'narrow horizontal observation slit OPEN showing dark empty interior beyond, '
        'no inner handle, single object, pixel art prop, solid bright magenta background #FF00FF only, '
        'centered, no people, no faces'
    ),
}

NEGATIVE = (
    'photorealistic, blurry, text, watermark, explicit, gore, people, face, eye staring, '
    'noise, static, multiple doors, room scene, flooded cell, skeleton'
)


def _generator(no_lora: bool):
    from puca_images import ImageGenerator

    workdir = DEFAULT_ASSETS_ROOT / 'cache' / 'sd_raw'
    workdir.mkdir(parents=True, exist_ok=True)
    lora = _ROOT / 'pixel_style_lora_style_only'
    use_lora = (not no_lora) and (lora / 'adapter_model.safetensors').is_file()
    return ImageGenerator(cache_dir=workdir, lora_folder=lora, use_lora=use_lora)


def cmd_door_slit_candidates(args: argparse.Namespace) -> int:
    refs = sorted(DOOR_REF_DIR.glob('doorslit*.jpg')) + sorted(DOOR_REF_DIR.glob('doorslit*.png'))
    if not refs:
        print(f'No doorslit*.jpg/png in {DOOR_REF_DIR}', file=sys.stderr)
        return 1
    catalog = load_catalog()
    size = tuple(int(x) for x in (catalog.get('props') or {}).get('door_closed', {}).get('size') or [96, 180])
    DOOR_OUT_DIR.mkdir(parents=True, exist_ok=True)
    gen = _generator(args.no_lora)
    rows = []
    n_seeds = max(1, int(args.seeds))
    strengths = [float(x) for x in args.strengths.split(',') if x.strip()]
    idx = 0
    for state, prompt in PROMPTS.items():
        sprite_id = 'door_closed' if state == 'closed' else 'door_slit_open'
        for ref in refs:
            for si in range(n_seeds):
                for strength in strengths:
                    idx += 1
                    seed = int(args.seed_base) + idx * 997
                    tag = f'{sprite_id}__{ref.stem}__s{strength:.2f}__seed{seed}'
                    raw_name = f'{tag}_raw.png'
                    fit_name = f'{tag}.png'
                    print(f'[{idx}] img2img {tag} ...')
                    try:
                        _key, raw = gen.generate_img2img(
                            f'door_cand_{tag}',
                            prompt,
                            ref,
                            strength=strength,
                            negative_prompt=NEGATIVE,
                            seed=seed,
                            steps=int(args.steps),
                        )
                        raw_dest = DOOR_OUT_DIR / raw_name
                        raw_dest.write_bytes(Path(raw).read_bytes())
                        fit_dest = DOOR_OUT_DIR / fit_name
                        _chroma_key_and_fit(raw_dest, fit_dest, size, 'prop')
                        rows.append({
                            'id': tag,
                            'state': state,
                            'sprite_id': sprite_id,
                            'ref': ref.name,
                            'strength': strength,
                            'seed': seed,
                            'raw': str(raw_dest.relative_to(_ROOT)).replace('\\', '/'),
                            'fitted': str(fit_dest.relative_to(_ROOT)).replace('\\', '/'),
                            'status': 'ok',
                        })
                        print(f'  wrote {fit_dest}')
                    except Exception as exc:  # noqa: BLE001
                        print(f'  FAILED: {exc}')
                        rows.append({
                            'id': tag,
                            'state': state,
                            'sprite_id': sprite_id,
                            'ref': ref.name,
                            'strength': strength,
                            'seed': seed,
                            'status': 'failed',
                            'error': str(exc),
                        })
    report = {
        'out_dir': str(DOOR_OUT_DIR),
        'size': list(size),
        'no_lora': bool(args.no_lora),
        'candidates': rows,
    }
    (DOOR_OUT_DIR / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    lines = [
        '# Door slit candidates (local img2img)',
        '',
        'Pick one **closed** and one **open** tag (same visual family preferred).',
        'Do not overwrite kit until you approve.',
        '',
        f'Size: `{size[0]}×{size[1]}` · no_lora={args.no_lora}',
        '',
    ]
    for state in ('closed', 'open'):
        lines.append(f'## {state}')
        lines.append('')
        for row in rows:
            if row.get('state') != state or row.get('status') != 'ok':
                continue
            rel = Path(row['fitted']).name
            lines.append(
                f"- `{row['id']}` ref={row['ref']} strength={row['strength']} "
                f"seed={row['seed']}"
            )
            lines.append(f'  ![]({rel})')
            lines.append('')
    (DOOR_OUT_DIR / 'CANDIDATES.md').write_text('\n'.join(lines), encoding='utf-8')
    ok = sum(1 for r in rows if r.get('status') == 'ok')
    print(json.dumps({'ok': ok, 'total': len(rows), 'out': str(DOOR_OUT_DIR)}, indent=2))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Local art → sprite helpers')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_door = sub.add_parser('door-slit-candidates', help='Bake door open/closed candidates from references/door')
    p_door.add_argument('--seeds', type=int, default=1, help='Seeds per ref×strength')
    p_door.add_argument('--strengths', default='0.50,0.65', help='Comma img2img strengths')
    p_door.add_argument('--seed-base', type=int, default=51000)
    p_door.add_argument('--steps', type=int, default=28)
    p_door.add_argument('--no-lora', action='store_true', default=True)
    p_door.add_argument('--with-lora', action='store_true', help='Enable pixel LoRA')

    args = parser.parse_args(argv)
    if args.cmd == 'door-slit-candidates':
        if args.with_lora:
            args.no_lora = False
        return cmd_door_slit_candidates(args)
    parser.error(f'unknown command {args.cmd}')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
