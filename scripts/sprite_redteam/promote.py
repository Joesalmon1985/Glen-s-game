"""Stage 3: promote bakeoff winners into the live kit / catalog."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Optional

from puca_dungeon.visual_catalog import DEFAULT_ASSETS_ROOT, DEFAULT_CATALOG_PATH, clear_catalog_cache
from scripts.sprite_redteam.audit import run_audit
from scripts.sprite_redteam.report import resolve_run_dir
from scripts.sprite_redteam.vision_judge import DEFAULT_VISION_MODEL

ROOT = Path(__file__).resolve().parents[2]


def promote_from_report(
    stamp_or_path: str,
    *,
    apply: bool = False,
    assets_root: Optional[Path] = None,
    catalog_path: Optional[Path] = None,
    out_root: Optional[Path] = None,
    reaudit: bool = False,
    max_rounds: int = 3,
    vision_model: str = DEFAULT_VISION_MODEL,
    skip_vision: bool = False,
) -> dict:
    run_dir = resolve_run_dir(stamp_or_path, out_root=out_root)
    cand_path = run_dir / 'candidates_report.json'
    if not cand_path.is_file():
        raise FileNotFoundError(
            f'No candidates_report.json in {run_dir}. Run regenerate first.'
        )
    candidates = json.loads(cand_path.read_text(encoding='utf-8'))
    root = Path(assets_root or DEFAULT_ASSETS_ROOT)
    catalog_file = Path(catalog_path or DEFAULT_CATALOG_PATH)
    catalog = json.loads(catalog_file.read_text(encoding='utf-8'))

    actions: list[dict[str, Any]] = []

    for sprite_id, payload in (candidates.get('assets') or {}).items():
        winner = payload.get('winner')
        if not winner:
            continue
        winner_row = None
        for cand in payload.get('candidates') or []:
            if cand.get('id') == winner:
                winner_row = cand
                break
        if not winner_row or winner_row.get('status') not in ('ok',) or not winner_row.get('heuristic_ok', True):
            actions.append({
                'type': 'asset',
                'sprite_id': sprite_id,
                'status': 'skipped',
                'reason': 'no_ok_winner' if not winner_row else 'heuristic_fail_or_bad_status',
            })
            continue
        src = Path(winner_row['path'])
        rel = payload.get('file')
        if not rel:
            actions.append({
                'type': 'asset',
                'sprite_id': sprite_id,
                'status': 'skipped',
                'reason': 'missing_file_field',
            })
            continue
        dest = root / rel
        action = {
            'type': 'asset',
            'sprite_id': sprite_id,
            'src': str(src),
            'dest': str(dest),
            'winner': winner,
            'overall': winner_row.get('overall'),
        }
        if apply:
            if not src.is_file():
                action['status'] = 'failed'
                action['reason'] = 'winner_missing'
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                action['status'] = 'applied'
        else:
            action['status'] = 'dry_run'
        actions.append(action)

    layouts = catalog.setdefault('layouts', {})
    for room_id, payload in (candidates.get('layouts') or {}).items():
        slots = payload.get('winner_slots')
        if not slots:
            continue
        action = {
            'type': 'layout',
            'room_id': room_id,
            'winner': payload.get('winner'),
            'slots': slots,
        }
        if apply:
            layout = dict(layouts.get(room_id) or {})
            layout['slots'] = {k: list(v) for k, v in slots.items()}
            if 'background' not in layout:
                layout['background'] = room_id
            layouts[room_id] = layout
            action['status'] = 'applied'
        else:
            action['status'] = 'dry_run'
        actions.append(action)

    if apply and any(a.get('type') == 'layout' and a.get('status') == 'applied' for a in actions):
        catalog_file.write_text(json.dumps(catalog, indent=2) + '\n', encoding='utf-8')
        clear_catalog_cache()

    promote_report = {
        'run_dir': str(run_dir),
        'apply': apply,
        'actions': actions,
        'applied_count': sum(1 for a in actions if a.get('status') == 'applied'),
        'dry_run_count': sum(1 for a in actions if a.get('status') == 'dry_run'),
    }

    reaudit_reports: list[dict] = []
    if apply and reaudit:
        # Closed loop: re-audit up to max_rounds (caller may invoke regenerate again)
        for round_i in range(max(1, int(max_rounds))):
            stamp = f'{run_dir.name}_reaudit_{round_i + 1}'
            audit_report = run_audit(
                assets_root=root,
                catalog_path=catalog_file,
                out_root=run_dir.parent,
                stamp=stamp,
                vision_model=vision_model,
                skip_vision=skip_vision,
            )
            reaudit_reports.append({
                'stamp': stamp,
                'clean_gate_passed': audit_report.get('clean_gate_passed'),
                'finding_counts': audit_report.get('finding_counts'),
                'regen_queue': audit_report.get('regen_queue'),
            })
            if audit_report.get('clean_gate_passed'):
                break

    promote_report['reaudit'] = reaudit_reports
    out = run_dir / 'promote_report.json'
    out.write_text(json.dumps(promote_report, indent=2), encoding='utf-8')
    return promote_report


def closed_loop(
    *,
    assets_root: Optional[Path] = None,
    catalog_path: Optional[Path] = None,
    out_root: Optional[Path] = None,
    max_rounds: int = 3,
    candidates: int = 4,
    seed_base: int = 1000,
    vision_model: str = DEFAULT_VISION_MODEL,
    skip_vision: bool = False,
    no_lora: bool = False,
    apply: bool = True,
) -> dict:
    """Audit → regenerate → promote for up to max_rounds."""
    from scripts.sprite_redteam.candidates import regenerate_from_report

    history: list[dict] = []
    stamp = None
    for round_i in range(max(1, int(max_rounds))):
        audit_report = run_audit(
            assets_root=assets_root,
            catalog_path=catalog_path,
            out_root=out_root,
            stamp=stamp,
            vision_model=vision_model,
            skip_vision=skip_vision,
        )
        run_dir = Path(audit_report['run_dir'])
        stamp = run_dir.name
        history.append({'round': round_i + 1, 'phase': 'audit', 'report': {
            'clean_gate_passed': audit_report.get('clean_gate_passed'),
            'finding_counts': audit_report.get('finding_counts'),
            'regen_queue': audit_report.get('regen_queue'),
            'run_dir': str(run_dir),
        }})
        if audit_report.get('clean_gate_passed'):
            break
        queue = audit_report.get('regen_queue') or {}
        if not queue.get('assets') and not queue.get('rooms'):
            break
        cand = regenerate_from_report(
            stamp,
            assets_root=assets_root,
            catalog_path=catalog_path,
            out_root=out_root,
            candidates=candidates,
            seed_base=seed_base + round_i * 100,
            vision_model=vision_model,
            skip_vision=skip_vision,
            no_lora=no_lora,
        )
        history.append({'round': round_i + 1, 'phase': 'regenerate', 'winner_assets': list((cand.get('assets') or {}).keys())})
        promo = promote_from_report(
            stamp,
            apply=apply,
            assets_root=assets_root,
            catalog_path=catalog_path,
            out_root=out_root,
            reaudit=False,
            vision_model=vision_model,
            skip_vision=skip_vision,
        )
        history.append({'round': round_i + 1, 'phase': 'promote', 'promote': promo})
        if not apply:
            break
        # Next audit uses a fresh stamp sibling
        stamp = f'{run_dir.name}_r{round_i + 2}'

    summary = {'history': history, 'rounds': len(history)}
    if out_root:
        out = Path(out_root)
    else:
        out = ROOT / 'tools' / 'sprite_redteam'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'closed_loop_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary
