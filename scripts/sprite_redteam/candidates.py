"""Stage 2: generate asset candidates and layout bakeoff variants."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from puca_dungeon.scene_compose import build_visual_spec, compose_image
from puca_dungeon.visual_catalog import DEFAULT_ASSETS_ROOT, iter_sprite_jobs, load_catalog
from scripts.sprite_redteam.fixtures import (
    apply_layout_override,
    fixture_for_room,
    layout_delta_variants,
)
from scripts.sprite_redteam.heuristics import catalog_expect_size, judge_asset, judge_composition
from scripts.sprite_redteam.report import load_report, resolve_run_dir
from scripts.sprite_redteam.vision_judge import DEFAULT_VISION_MODEL, VisionJudge

ROOT = Path(__file__).resolve().parents[2]

PROMPT_MUTATIONS = (
    ', SOLID bright magenta background #FF00FF only, no other backdrop colours',
    ', clear readable details, coloured clothing, single subject, solid magenta #FF00FF backdrop',
    ', high contrast edges, readable at small size, solid #FF00FF chroma key background',
    ', isolated prop, empty magenta #FF00FF field only, no mauve no teal no gray backdrop',
)


def _chroma_key_and_fit(src: Path, dest: Path, size: tuple[int, int], kind: str) -> None:
    from scripts.generate_sprites import _chroma_key_and_fit as impl
    impl(src, dest, size, kind)


def _job_map(catalog: dict) -> dict[str, dict]:
    return {job['id']: job for job in iter_sprite_jobs(catalog)}


def regenerate_from_report(
    stamp_or_path: str,
    *,
    assets_root: Optional[Path] = None,
    catalog_path: Optional[Path] = None,
    out_root: Optional[Path] = None,
    candidates: int = 4,
    seed_base: int = 1000,
    vision_model: str = DEFAULT_VISION_MODEL,
    skip_vision: bool = False,
    no_lora: bool = False,
    dry_run: bool = False,
) -> dict:
    run_dir = resolve_run_dir(stamp_or_path, out_root=out_root)
    report = load_report(run_dir)
    queue = report.get('regen_queue') or {}
    asset_ids = list(queue.get('assets') or [])
    room_ids = list(queue.get('rooms') or [])
    nudges = dict(queue.get('slot_nudges') or {})

    catalog = load_catalog(str(catalog_path) if catalog_path else None)
    root = Path(assets_root or DEFAULT_ASSETS_ROOT)
    jobs = _job_map(catalog)
    negative = str(catalog.get('negative_prompt') or '')
    judge = VisionJudge(model=vision_model, enabled=not skip_vision)

    result: dict[str, Any] = {
        'run_dir': str(run_dir),
        'assets': {},
        'layouts': {},
        'dry_run': dry_run,
    }

    if asset_ids and not dry_run:
        from puca_images import ImageGenerator

        workdir = root / 'cache' / 'sd_raw'
        workdir.mkdir(parents=True, exist_ok=True)
        lora = ROOT / 'pixel_style_lora_style_only'
        use_lora = (not no_lora) and (lora / 'adapter_model.safetensors').is_file()
        gen = ImageGenerator(cache_dir=workdir, lora_folder=lora, use_lora=use_lora)
    else:
        gen = None

    for sprite_id in asset_ids:
        job = jobs.get(sprite_id)
        if not job:
            result['assets'][sprite_id] = {'error': 'not_in_catalog'}
            continue
        kind = job['kind']
        size = catalog_expect_size(catalog, kind, {'size': job.get('size')})
        cand_dir = run_dir / 'candidates' / sprite_id
        cand_dir.mkdir(parents=True, exist_ok=True)
        scores: list[dict] = []
        n = max(1, int(candidates))
        for i in range(n):
            mutation = PROMPT_MUTATIONS[i % len(PROMPT_MUTATIONS)]
            style = job.get('style') or ''
            prompt = f"{job['prompt']}{mutation}"
            full = prompt if not style else f'{style}, {prompt}'
            seed = int(seed_base) + i * 997 + (hash(sprite_id) % 10000)
            dest = cand_dir / f'c{i}.png'
            entry: dict[str, Any] = {
                'id': f'c{i}',
                'path': str(dest),
                'seed': seed,
                'prompt': full,
            }
            if dry_run:
                entry['status'] = 'dry_run'
                scores.append(entry)
                continue
            assert gen is not None
            loc = f'sprite_bakeoff_{kind}_{sprite_id}_c{i}'
            try:
                from puca_images import BAKEOFF_STEPS
                _key, raw_path = gen.generate(
                    loc,
                    full,
                    negative_prompt=negative or None,
                    seed=seed,
                    steps=BAKEOFF_STEPS,
                )
                _chroma_key_and_fit(
                    Path(raw_path),
                    dest,
                    size if kind != 'background' else (512, 512),
                    kind,
                )
                heur = judge_asset(dest, sprite_id=f'{sprite_id}:c{i}', kind=kind, expect_size=size)
                vision = judge.score_asset(
                    dest,
                    sprite_id=f'{sprite_id}:c{i}',
                    kind=kind,
                    prompt=str(job.get('prompt') or ''),
                )
                overall = float((vision.scores or {}).get('overall') or 0.0)
                if vision.skipped:
                    overall = 5.0 if heur.ok else 0.0
                if not heur.ok:
                    overall = min(overall, 2.0)
                if not vision.ok and not vision.skipped:
                    overall = min(overall, 3.0)
                entry.update({
                    'status': 'ok',
                    'heuristic_ok': heur.ok,
                    'vision': vision.to_dict(),
                    'overall': overall,
                })
            except Exception as exc:  # noqa: BLE001
                entry.update({'status': 'failed', 'error': str(exc), 'overall': -1.0})
            scores.append(entry)
        scores_sorted = sorted(
            scores,
            key=lambda row: (
                1 if row.get('heuristic_ok') else 0,
                float(row.get('overall') or -1),
            ),
            reverse=True,
        )
        winner = None
        for row in scores_sorted:
            if row.get('status') != 'ok' or not row.get('heuristic_ok'):
                continue
            vision = row.get('vision') or {}
            if vision and not vision.get('skipped') and not vision.get('ok', True):
                continue
            if float(row.get('overall') or 0) < 4.0:
                continue
            winner = row['id']
            break
        result['assets'][sprite_id] = {
            'candidates': scores,
            'winner': winner,
            'file': job['file'],
        }

    for room_id in room_ids:
        layout = dict((catalog.get('layouts') or {}).get(room_id) or {})
        base_slots = {k: list(v) for k, v in dict(layout.get('slots') or {}).items()}
        suggested = list(nudges.get(room_id) or [])[:3]
        variants = layout_delta_variants(base_slots, suggested=suggested)
        # Cap variants to keep bakeoffs tractable
        variants = variants[:24]
        layout_scores: list[dict] = []
        fx = fixture_for_room(room_id, staff_count=1, crowded=True)
        for name, slots in variants:
            cat2 = apply_layout_override(catalog, room_id, slots)
            spec = build_visual_spec(fx.world, cat2)
            heur = judge_composition(
                fixture_id=f'{room_id}:{name}',
                room_id=room_id,
                layers=spec.layers,
                catalog=cat2,
                expected_sprite_ids=fx.expected_sprite_ids,
            )
            image = compose_image(spec, cat2, root=root, allow_placeholder=True)
            dest = run_dir / 'candidates' / f'layout_{room_id}' / f'{name}.png'
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                image.save(dest, format='PNG')
            layer_summary = ', '.join(
                f'{layer.sprite_id}@{layer.xy[0]},{layer.xy[1]}'
                for layer in spec.layers
                if layer.kind != 'background'
            )
            if dry_run:
                layout_scores.append({
                    'id': name,
                    'slots': slots,
                    'status': 'dry_run',
                    'overall': 0.0,
                    'heuristic_ok': heur.ok,
                })
                continue
            vision = judge.score_composition(
                dest,
                fixture_id=f'{room_id}:{name}',
                room_id=room_id,
                layer_summary=layer_summary,
            )
            overall = float((vision.scores or {}).get('overall') or 0.0)
            if vision.skipped:
                overall = 5.0 if heur.ok else 0.0
            if not heur.ok:
                overall = min(overall, 2.0)
            layout_scores.append({
                'id': name,
                'slots': slots,
                'path': str(dest),
                'heuristic_ok': heur.ok,
                'vision': vision.to_dict(),
                'overall': overall,
                'status': 'ok',
            })
        ranked = sorted(layout_scores, key=lambda row: float(row.get('overall') or -1), reverse=True)
        result['layouts'][room_id] = {
            'variants': layout_scores,
            'winner': ranked[0]['id'] if ranked else None,
            'winner_slots': ranked[0].get('slots') if ranked else base_slots,
        }

    out_path = run_dir / 'candidates_report.json'
    out_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    (run_dir / 'bakeoff.md').write_text(_bakeoff_markdown(result), encoding='utf-8')
    return result


def _bakeoff_markdown(result: dict) -> str:
    lines = ['# Sprite bakeoff', '', f"Run: `{result.get('run_dir')}`", '']
    lines.append('## Assets')
    lines.append('')
    for sprite_id, payload in (result.get('assets') or {}).items():
        lines.append(f"### `{sprite_id}` → winner `{payload.get('winner')}`")
        for cand in payload.get('candidates') or []:
            lines.append(
                f"- `{cand.get('id')}` overall={cand.get('overall')} "
                f"status={cand.get('status')} seed={cand.get('seed')}"
            )
        lines.append('')
    lines.append('## Layouts')
    lines.append('')
    for room_id, payload in (result.get('layouts') or {}).items():
        lines.append(f"### `{room_id}` → winner `{payload.get('winner')}`")
        for var in (payload.get('variants') or [])[:12]:
            lines.append(
                f"- `{var.get('id')}` overall={var.get('overall')} "
                f"heuristic_ok={var.get('heuristic_ok')}"
            )
        lines.append('')
    return '\n'.join(lines)
