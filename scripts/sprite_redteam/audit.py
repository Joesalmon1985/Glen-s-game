"""Stage 1: audit kit assets + composed fixture scenes."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from puca_dungeon.scene_compose import build_visual_spec, compose_image
from puca_dungeon.visual_catalog import DEFAULT_ASSETS_ROOT, iter_sprite_jobs, load_catalog
from scripts.redteam.findings import Finding
from scripts.sprite_redteam.fixtures import all_fixtures
from scripts.sprite_redteam.heuristics import catalog_expect_size, judge_asset, judge_composition
from scripts.sprite_redteam.report import copy_into_gallery, new_run_dir, write_report
from scripts.sprite_redteam.vision_judge import DEFAULT_VISION_MODEL, VisionJudge


def run_audit(
    *,
    assets_root: Optional[Path] = None,
    catalog_path: Optional[Path] = None,
    out_root: Optional[Path] = None,
    stamp: Optional[str] = None,
    vision_model: str = DEFAULT_VISION_MODEL,
    skip_vision: bool = False,
    fixtures_limit: Optional[int] = None,
) -> dict:
    catalog = load_catalog(str(catalog_path) if catalog_path else None)
    root = Path(assets_root or DEFAULT_ASSETS_ROOT)
    run_dir = new_run_dir(stamp=stamp, out_root=out_root)
    judge = VisionJudge(model=vision_model, enabled=not skip_vision)

    findings: list[Finding] = []
    asset_scores: list[dict] = []
    composition_scores: list[dict] = []
    vision_any_skip = skip_vision or not judge.available()

    jobs = iter_sprite_jobs(catalog)
    for job in jobs:
        sprite_id = job['id']
        kind = job['kind']
        path = root / job['file']
        expect = catalog_expect_size(catalog, kind, {'size': job.get('size')})
        heur = judge_asset(path, sprite_id=sprite_id, kind=kind, expect_size=expect)
        findings.extend(heur.findings)
        gallery_dest = run_dir / 'gallery' / 'assets' / f'{sprite_id}.png'
        if path.is_file():
            copy_into_gallery(path, gallery_dest)
            vision = judge.score_asset(
                gallery_dest,
                sprite_id=sprite_id,
                kind=kind,
                prompt=str(job.get('prompt') or ''),
            )
            if vision.skipped:
                vision_any_skip = True
            findings.extend(vision.findings)
            asset_scores.append({
                **vision.to_dict(),
                'heuristic_ok': heur.ok,
                'heuristic_metrics': heur.metrics,
            })
        else:
            asset_scores.append({
                'target': sprite_id,
                'kind': 'asset',
                'ok': False,
                'skipped': True,
                'error': 'missing_file',
                'heuristic_ok': heur.ok,
                'heuristic_metrics': heur.metrics,
                'scores': {},
                'findings': [f.to_dict() for f in heur.findings],
            })

    fixtures = all_fixtures(catalog)
    if fixtures_limit is not None:
        fixtures = fixtures[: max(0, fixtures_limit)]

    for fx in fixtures:
        spec = build_visual_spec(fx.world, catalog)
        heur = judge_composition(
            fixture_id=fx.fixture_id,
            room_id=fx.room_id,
            layers=spec.layers,
            catalog=catalog,
            expected_sprite_ids=fx.expected_sprite_ids,
        )
        findings.extend(heur.findings)
        image = compose_image(spec, catalog, root=root, allow_placeholder=True)
        dest = run_dir / 'gallery' / 'compositions' / f'{fx.fixture_id}.png'
        dest.parent.mkdir(parents=True, exist_ok=True)
        image.save(dest, format='PNG')
        layer_summary = ', '.join(
            f'{layer.sprite_id}@{layer.xy[0]},{layer.xy[1]}'
            for layer in spec.layers
            if layer.kind != 'background'
        )
        vision = judge.score_composition(
            dest,
            fixture_id=fx.fixture_id,
            room_id=fx.room_id,
            layer_summary=layer_summary,
        )
        if vision.skipped:
            vision_any_skip = True
        findings.extend(vision.findings)
        composition_scores.append({
            **vision.to_dict(),
            'room_id': fx.room_id,
            'heuristic_ok': heur.ok,
            'heuristic_metrics': heur.metrics,
            'layers': [layer.to_dict() for layer in spec.layers],
        })

    report = write_report(
        run_dir,
        findings=findings,
        asset_scores=asset_scores,
        composition_scores=composition_scores,
        vision_skipped=vision_any_skip,
        meta={
            'assets_root': str(root),
            'vision_model': vision_model,
            'fixture_count': len(fixtures),
            'job_count': len(jobs),
        },
    )
    return report
