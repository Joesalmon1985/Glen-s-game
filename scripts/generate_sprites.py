#!/usr/bin/env python3
"""Offline batch: generate facility sprites via local Stable Diffusion.

Does not touch game / text mechanics. Resume-safe (skips valid existing files).

Examples:
  python scripts/generate_sprites.py --list
  python scripts/generate_sprites.py --dump-draft
  python scripts/generate_sprites.py --dry-run
  python scripts/generate_sprites.py --only backgrounds
  python scripts/generate_sprites.py --only room:cell
  python scripts/generate_sprites.py --force
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from puca_dungeon.visual_catalog import (
    DEFAULT_ASSETS_ROOT,
    dump_facility_draft,
    iter_sprite_jobs,
    jobs_for_room,
    load_catalog,
)


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


def _colour_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _chroma_key_and_fit(src: Path, dest: Path, size: tuple[int, int], kind: str) -> None:
    from PIL import Image

    img = Image.open(src).convert('RGBA')
    if kind != 'background':
        pixels = img.load()
        w, h = img.size
        # Magenta / near-magenta first
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if r >= 230 and b >= 230 and g <= 40:
                    pixels[x, y] = (r, g, b, 0)
                elif abs(r - 255) <= 40 and abs(b - 255) <= 40 and g <= 60:
                    pixels[x, y] = (r, g, b, 0)
        # Corner flood: SD often paints mauve/teal instead of #FF00FF
        corners = [
            pixels[0, 0][:3],
            pixels[w - 1, 0][:3],
            pixels[0, h - 1][:3],
            pixels[w - 1, h - 1][:3],
        ]
        # Pick the most common corner colour (among opaque corners)
        opaque_corners = [c for i, c in enumerate(corners) if pixels[
            (0 if i % 2 == 0 else w - 1), (0 if i < 2 else h - 1)
        ][3] > 16]
        if opaque_corners:
            # Use first corner as seed if ≥2 corners are near it
            seed = opaque_corners[0]
            near = sum(1 for c in opaque_corners if _colour_dist(c, seed) <= 48)
            if near >= 2 and not (seed[0] >= 230 and seed[2] >= 230 and seed[1] <= 40):
                # Flood from edges: mark pixels similar to seed as transparent
                for y in range(h):
                    for x in range(w):
                        r, g, b, a = pixels[x, y]
                        if a <= 16:
                            continue
                        if _colour_dist((r, g, b), seed) <= 55:
                            # Prefer edge-connected regions: cheap approx via
                            # near-edge or already-cleared neighbour
                            on_edge = x < 3 or y < 3 or x >= w - 3 or y >= h - 3
                            if on_edge:
                                pixels[x, y] = (r, g, b, 0)
                # Second pass: expand transparency into similar interior
                changed = True
                passes = 0
                while changed and passes < 8:
                    changed = False
                    passes += 1
                    for y in range(1, h - 1):
                        for x in range(1, w - 1):
                            r, g, b, a = pixels[x, y]
                            if a <= 16:
                                continue
                            if _colour_dist((r, g, b), seed) > 55:
                                continue
                            neigh = (
                                pixels[x - 1, y][3] <= 16
                                or pixels[x + 1, y][3] <= 16
                                or pixels[x, y - 1][3] <= 16
                                or pixels[x, y + 1][3] <= 16
                            )
                            if neigh:
                                pixels[x, y] = (r, g, b, 0)
                                changed = True
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
    img = img.resize(size, Image.Resampling.NEAREST)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix('.tmp.png')
    img.save(tmp, format='PNG')
    tmp.replace(dest)


def _filter_jobs(jobs: list[dict], only: str | None, catalog: dict) -> list[dict]:
    if not only:
        return jobs
    kind_map = {'backgrounds': 'background', 'props': 'prop', 'characters': 'character'}
    token = only.strip()
    if token in kind_map:
        want = kind_map[token]
        return [job for job in jobs if job['kind'] == want]
    if token.startswith('room:'):
        room_id = token.split(':', 1)[1].strip()
        return jobs_for_room(room_id, catalog)
    # Treat as sprite id substring / exact id
    return [job for job in jobs if job['id'] == token or token in job['id']]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Batch-generate facility sprites with local SD')
    parser.add_argument('--assets', type=Path, default=DEFAULT_ASSETS_ROOT, help='Sprite assets root')
    parser.add_argument('--catalog', type=Path, default=None, help='catalog.json path')
    parser.add_argument('--list', action='store_true', help='List sprite jobs and exit')
    parser.add_argument(
        '--dump-draft',
        action='store_true',
        help='Print rooms/entities/cast draft from facility_models for catalog review',
    )
    parser.add_argument('--dry-run', action='store_true', help='Show work without generating')
    parser.add_argument(
        '--only',
        help='Filter: backgrounds|props|characters|room:cell|<sprite_id>',
    )
    parser.add_argument('--force', action='store_true', help='Regenerate even if file exists')
    parser.add_argument('--no-lora', action='store_true', help='Disable pixel LoRA adapter')
    parser.add_argument('--workdir', type=Path, default=None, help='Temp SD output dir (default: assets/cache)')
    parser.add_argument(
        '--candidates',
        type=int,
        default=1,
        help='Generate N candidates per sprite (writes beside dest as .c0.png … when N>1)',
    )
    parser.add_argument(
        '--seed-base',
        type=int,
        default=None,
        help='Base seed for candidate bakeoffs (default: hash of cache key)',
    )
    args = parser.parse_args(argv)

    if args.dump_draft:
        print(json.dumps(dump_facility_draft(), indent=2, ensure_ascii=False))
        return 0

    catalog = load_catalog(str(args.catalog) if args.catalog else None)
    jobs = _filter_jobs(iter_sprite_jobs(catalog), args.only, catalog)

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
    failed = 0
    n_candidates = max(1, int(args.candidates))
    for index, job in enumerate(jobs, start=1):
        dest = args.assets / job['file']
        size = (int(job['size'][0]), int(job['size'][1]))
        if dest.is_file() and not args.force and n_candidates == 1 and _valid_png(dest):
            print(f'[{index}/{len(jobs)}] skip {job["id"]}')
            skipped += 1
            continue
        style = job.get('style') or ''
        prompt = job['prompt']
        full = prompt if not style else f'{style}, {prompt}'
        negative = str(job.get('negative_prompt') or '') or None
        print(f'[{index}/{len(jobs)}] generate {job["id"]} (candidates={n_candidates}) ...')
        job_failed = False
        for cand_i in range(n_candidates):
            raw_path = None
            last_err: Exception | None = None
            seed = None if args.seed_base is None else int(args.seed_base) + cand_i * 997
            for attempt in range(1, 4):
                loc = f'sprite_{job["kind"]}_{job["id"]}'
                if n_candidates > 1:
                    loc = f'{loc}_c{cand_i}'
                if attempt > 1:
                    loc = f'{loc}_retry{attempt}'
                    full_try = f'{full}, safe for work, furniture only, no people, no nudity'
                else:
                    full_try = full
                try:
                    _key, raw_path = gen.generate(
                        loc,
                        full_try,
                        negative_prompt=negative,
                        seed=seed,
                    )
                    last_err = None
                    break
                except RuntimeError as exc:
                    last_err = exc
                    msg = str(exc).lower()
                    if 'filtered' in msg or 'cancelled' in msg:
                        print(f'  attempt {attempt} failed: {exc}')
                        continue
                    raise
            if last_err is not None or raw_path is None:
                print(f'  FAILED {job["id"]} c{cand_i}: {last_err}')
                job_failed = True
                continue
            fit_size = size if job['kind'] != 'background' else (512, 512)
            if n_candidates == 1:
                out_dest = dest
            else:
                out_dest = dest.with_name(f'{dest.stem}.c{cand_i}{dest.suffix}')
            _chroma_key_and_fit(Path(raw_path), out_dest, fit_size, job['kind'])
            if n_candidates > 1 and cand_i == 0:
                _chroma_key_and_fit(Path(raw_path), dest, fit_size, job['kind'])
            print(f'  wrote {out_dest}')
            made += 1
        if job_failed:
            failed += 1

    elapsed = time.time() - started
    print(f'Done. generated={made} skipped={skipped} failed={failed} elapsed_sec={elapsed:.1f}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
