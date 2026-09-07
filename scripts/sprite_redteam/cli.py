"""CLI: ``python -m scripts.sprite_redteam <audit|regenerate|promote|loop>``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from puca_dungeon.visual_catalog import DEFAULT_ASSETS_ROOT, DEFAULT_CATALOG_PATH
from scripts.sprite_redteam.vision_judge import DEFAULT_VISION_MODEL


def _add_shared(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--assets', type=Path, default=DEFAULT_ASSETS_ROOT)
    parser.add_argument('--catalog', type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument('--out', type=Path, default=ROOT / 'tools' / 'sprite_redteam')
    parser.add_argument('--vision-model', default=DEFAULT_VISION_MODEL)
    parser.add_argument('--skip-vision', action='store_true', help='Heuristics only')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Hybrid heuristic + vision sprite red-team and bakeoff loop',
    )
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_audit = sub.add_parser('audit', help='Score kit + fixture compositions')
    _add_shared(p_audit)
    p_audit.add_argument('--stamp', default=None)
    p_audit.add_argument('--fixtures-limit', type=int, default=None)

    p_regen = sub.add_parser('regenerate', help='Generate candidates for failed assets/layouts')
    _add_shared(p_regen)
    p_regen.add_argument('--from', dest='from_stamp', required=True, help='Audit stamp or path')
    p_regen.add_argument('--candidates', type=int, default=4)
    p_regen.add_argument('--seed-base', type=int, default=1000)
    p_regen.add_argument('--no-lora', action='store_true')
    p_regen.add_argument('--dry-run', action='store_true')

    p_promo = sub.add_parser('promote', help='Promote bakeoff winners into kit/catalog')
    _add_shared(p_promo)
    p_promo.add_argument('--from', dest='from_stamp', required=True)
    p_promo.add_argument('--apply', action='store_true', help='Write winners (default dry-run)')
    p_promo.add_argument('--reaudit', action='store_true', help='Re-audit after apply')
    p_promo.add_argument('--max-rounds', type=int, default=3)

    p_loop = sub.add_parser('loop', help='Closed loop: audit → regenerate → promote')
    _add_shared(p_loop)
    p_loop.add_argument('--max-rounds', type=int, default=3)
    p_loop.add_argument('--candidates', type=int, default=4)
    p_loop.add_argument('--seed-base', type=int, default=1000)
    p_loop.add_argument('--no-lora', action='store_true')
    p_loop.add_argument('--dry-run', action='store_true', help='Do not apply promotions')

    args = parser.parse_args(argv)

    if args.cmd == 'audit':
        from scripts.sprite_redteam.audit import run_audit

        report = run_audit(
            assets_root=args.assets,
            catalog_path=args.catalog,
            out_root=args.out,
            stamp=args.stamp,
            vision_model=args.vision_model,
            skip_vision=args.skip_vision,
            fixtures_limit=args.fixtures_limit,
        )
        print(json.dumps({
            'run_dir': report.get('run_dir'),
            'clean_gate_passed': report.get('clean_gate_passed'),
            'finding_counts': report.get('finding_counts'),
            'regen_queue': report.get('regen_queue'),
            'vision_skipped': report.get('vision_skipped'),
        }, indent=2))
        return 0 if report.get('clean_gate_passed') else 1

    if args.cmd == 'regenerate':
        from scripts.sprite_redteam.candidates import regenerate_from_report

        result = regenerate_from_report(
            args.from_stamp,
            assets_root=args.assets,
            catalog_path=args.catalog,
            out_root=args.out,
            candidates=args.candidates,
            seed_base=args.seed_base,
            vision_model=args.vision_model,
            skip_vision=args.skip_vision,
            no_lora=args.no_lora,
            dry_run=args.dry_run,
        )
        print(json.dumps({
            'run_dir': result.get('run_dir'),
            'assets': list((result.get('assets') or {}).keys()),
            'layouts': list((result.get('layouts') or {}).keys()),
            'dry_run': result.get('dry_run'),
        }, indent=2))
        return 0

    if args.cmd == 'promote':
        from scripts.sprite_redteam.promote import promote_from_report

        result = promote_from_report(
            args.from_stamp,
            apply=args.apply,
            assets_root=args.assets,
            catalog_path=args.catalog,
            out_root=args.out,
            reaudit=args.reaudit,
            max_rounds=args.max_rounds,
            vision_model=args.vision_model,
            skip_vision=args.skip_vision,
        )
        print(json.dumps({
            'run_dir': result.get('run_dir'),
            'apply': result.get('apply'),
            'applied_count': result.get('applied_count'),
            'dry_run_count': result.get('dry_run_count'),
            'reaudit': result.get('reaudit'),
        }, indent=2))
        return 0

    if args.cmd == 'loop':
        from scripts.sprite_redteam.promote import closed_loop

        summary = closed_loop(
            assets_root=args.assets,
            catalog_path=args.catalog,
            out_root=args.out,
            max_rounds=args.max_rounds,
            candidates=args.candidates,
            seed_base=args.seed_base,
            vision_model=args.vision_model,
            skip_vision=args.skip_vision,
            no_lora=args.no_lora,
            apply=not args.dry_run,
        )
        print(json.dumps(summary, indent=2))
        return 0

    parser.error(f'unknown command {args.cmd}')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
