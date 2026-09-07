#!/usr/bin/env python3
"""Offline batch: generate facility sprites via local Stable Diffusion.

Does not touch game / text mechanics. Resume-safe (skips valid existing files).

Examples:
  python scripts/generate_sprites.py --list
  python scripts/generate_sprites.py --dry-run
  python scripts/generate_sprites.py --only backgrounds
  python scripts/generate_sprites.py --force
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from puca_dungeon.visual_catalog import DEFAULT_ASSETS_ROOT, iter_sprite_jobs, load_catalog


def _valid_png(path: Path, expect_size: tuple[int, int] | None = None) -> bool:
    try:
        from PIL import Image
        with Image.open(path) as image:
            if image.format != 'PNG':
                return False
            if expect_size and image.size != expect_size:
                return False
            image.verify()
        return True
    except (OSError, ValueError, ImportError):
        return False


def _chroma_key_and_fit(src: Path, dest: Path, size: tuple[int, int], kind: str) -> None:
    from PIL import Image

    img = Image.open(src).convert('RGBA')
    if kind != 'background':
        pixels = img.load()
        w, h = img.size
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if r >= 230 and b >= 230 and g <= 40:
                    pixels[x, y] = (r, g, b, 0)
                elif abs(r - 255) <= 40 and abs(b - 255) <= 40 and g <= 60:
                    pixels[x, y] = (r, g, b, 0)
        # Crop to opaque bounds then fit
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
    img = img.resize(size, Image.Resampling.NEAREST)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix('.tmp.png')
    img.save(tmp, format='PNG')
    tmp.replace(dest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Batch-generate facility sprites with local SD')
    parser.add_argument('--assets', type=Path, default=DEFAULT_ASSETS_ROOT, help='Sprite assets root')
    parser.add_argument('--catalog', type=Path, default=None, help='catalog.json path')
    parser.add_argument('--list', action='store_true', help='List sprite jobs and exit')
    parser.add_argument('--dry-run', action='store_true', help='Show work without generating')
    parser.add_argument('--only', choices=('backgrounds', 'props', 'characters'), help='Filter by kind')
    parser.add_argument('--force', action='store_true', help='Regenerate even if file exists')
    parser.add_argument('--no-lora', action='store_true', help='Disable pixel LoRA adapter')
    parser.add_argument('--workdir', type=Path, default=None, help='Temp SD output dir (default: assets/cache)')
    args = parser.parse_args(argv)

    catalog = load_catalog(str(args.catalog) if args.catalog else None)
    jobs = iter_sprite_jobs(catalog)
    kind_map = {'backgrounds': 'background', 'props': 'prop', 'characters': 'character'}
    if args.only:
        want = kind_map[args.only]
        jobs = [job for job in jobs if job['kind'] == want]

    print(f'{len(jobs)} sprite job(s)')
    for job in jobs:
        dest = args.assets / job['file']
        status = 'exists' if dest.is_file() else 'missing'
        print(f"  [{job['kind']}] {job['id']} -> {job['file']} ({status})")
    if args.list or args.dry_run:
        return 0

    from puca_images import ImageGenerator

    workdir = args.workdir or (args.assets / 'cache' / 'sd_raw')
    workdir.mkdir(parents=True, exist_ok=True)
    lora = _ROOT / 'pixel_style_lora_style_only'
    use_lora = (not args.no_lora) and (lora / 'adapter_model.safetensors').is_file()
    gen = ImageGenerator(cache_dir=workdir, lora_folder=lora, use_lora=use_lora)

    started = time.time()
    made = 0
    skipped = 0
    for index, job in enumerate(jobs, start=1):
        dest = args.assets / job['file']
        size = (int(job['size'][0]), int(job['size'][1]))
        if dest.is_file() and not args.force and _valid_png(dest):
            print(f'[{index}/{len(jobs)}] skip {job["id"]}')
            skipped += 1
            continue
        style = job.get('style') or ''
        prompt = job['prompt']
        # ImageGenerator also prepends STYLE; keep subject prompt focused.
        full = prompt if not style else f'{style}, {prompt}'
        print(f'[{index}/{len(jobs)}] generate {job["id"]} ...')
        _key, raw_path = gen.generate(f'sprite_{job["kind"]}_{job["id"]}', full)
        _chroma_key_and_fit(Path(raw_path), dest, size if job['kind'] != 'background' else (512, 512), job['kind'])
        made += 1
        print(f'  wrote {dest}')

    elapsed = time.time() - started
    print(f'Done. generated={made} skipped={skipped} elapsed_sec={elapsed:.1f}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
