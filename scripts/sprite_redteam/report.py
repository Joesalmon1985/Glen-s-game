"""Report / gallery writers for sprite red-team runs."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.redteam.findings import Finding, clean_gate, severity_counts

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_ROOT = ROOT / 'tools' / 'sprite_redteam'


def new_run_dir(stamp: Optional[str] = None, out_root: Optional[Path] = None) -> Path:
    out_root = Path(out_root or DEFAULT_OUT_ROOT)
    if not stamp:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    path = out_root / stamp
    path.mkdir(parents=True, exist_ok=True)
    (path / 'gallery' / 'assets').mkdir(parents=True, exist_ok=True)
    (path / 'gallery' / 'compositions').mkdir(parents=True, exist_ok=True)
    (path / 'candidates').mkdir(parents=True, exist_ok=True)
    return path


def resolve_run_dir(stamp_or_path: str, out_root: Optional[Path] = None) -> Path:
    candidate = Path(stamp_or_path)
    if candidate.is_dir():
        return candidate
    out_root = Path(out_root or DEFAULT_OUT_ROOT)
    path = out_root / stamp_or_path
    if not path.is_dir():
        raise FileNotFoundError(f'Red-team run not found: {stamp_or_path}')
    return path


def copy_into_gallery(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.copy2(src, dest)
    return dest


def write_report(
    run_dir: Path,
    *,
    findings: list[Finding],
    asset_scores: list[dict],
    composition_scores: list[dict],
    vision_skipped: bool,
    meta: Optional[dict] = None,
) -> dict:
    counts = severity_counts(findings)
    passed, rationale = clean_gate(findings)
    # Aesthetic clean gate requires vision when any scores were requested but skipped
    aesthetic_note = ''
    if vision_skipped:
        aesthetic_note = (
            ' Vision judge skipped (Ollama/model unavailable); '
            'clean gate reflects heuristics only and does not certify aesthetics.'
        )
        # Do not claim aesthetic pass
        if passed:
            passed = False
            rationale = (
                'Clean gate FAILED: vision_skipped — heuristics may be clean, '
                'but aesthetics were not judged.'
            )

    report = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'run_dir': str(run_dir),
        'finding_counts': counts,
        'clean_gate_passed': passed,
        'clean_gate_rationale': rationale + aesthetic_note,
        'vision_skipped': vision_skipped,
        'findings': [f.to_dict() for f in findings],
        'asset_scores': asset_scores,
        'composition_scores': composition_scores,
        'meta': meta or {},
        'regen_queue': _regen_queue(findings, asset_scores, composition_scores),
    }
    (run_dir / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (run_dir / 'report.md').write_text(_markdown_report(report), encoding='utf-8')
    (run_dir / 'INDEX.md').write_text(_index_markdown(run_dir, report), encoding='utf-8')
    return report


def _regen_queue(
    findings: list[Finding],
    asset_scores: list[dict],
    composition_scores: list[dict],
) -> dict[str, Any]:
    assets: set[str] = set()
    rooms: set[str] = set()
    nudges: dict[str, list[dict[str, list[int]]]] = {}
    for finding in findings:
        extra = finding.extra or {}
        if finding.invariant in (
            'asset_exists', 'asset_valid_png', 'asset_size', 'chroma_clean',
            'content_present', 'bbox_size', 'no_text_blob', 'isolation',
            'detail_palette', 'noise',
            'bg_no_magenta', 'bg_not_flat', 'subject_correctness',
            'no_text_watermark', 'vision_overall', 'style_match',
        ):
            # Strip candidate suffixes like cup_full:c0
            asset_id = str(finding.utterance or '').split(':', 1)[0]
            if asset_id:
                assets.add(asset_id)
        if finding.invariant in (
            'on_canvas', 'expected_sprites', 'character_visible',
            'character_stack', 'composition_overall', 'occlusion',
        ):
            rid = str(extra.get('room_id') or '')
            if rid:
                rooms.add(rid)
        if 'room_id' in extra and finding.layer.startswith('sprite'):
            rooms.add(str(extra['room_id']))
        if 'slot_nudges' in extra and extra['slot_nudges']:
            rid = str(extra.get('room_id') or 'unknown')
            nudges.setdefault(rid, []).append(dict(extra['slot_nudges']))

    for row in asset_scores:
        if not row.get('ok') and not row.get('skipped'):
            asset_id = str(row.get('target') or '').split(':', 1)[0]
            if asset_id:
                assets.add(asset_id)
    for row in composition_scores:
        room = str(row.get('room_id') or '')
        if not room:
            for finding in findings:
                if finding.utterance == row.get('target') and finding.extra.get('room_id'):
                    room = str(finding.extra['room_id'])
                    break
        if not row.get('ok') and not row.get('skipped') and room:
            rooms.add(room)
        if row.get('slot_nudges') and room:
            nudges.setdefault(room, []).append(dict(row['slot_nudges']))

    assets.discard('')
    return {
        'assets': sorted(assets),
        'rooms': sorted(rooms),
        'slot_nudges': nudges,
    }


def _markdown_report(report: dict) -> str:
    lines = [
        '# Sprite red-team report',
        '',
        f"- Clean gate: **{'PASS' if report['clean_gate_passed'] else 'FAIL'}**",
        f"- Rationale: {report['clean_gate_rationale']}",
        f"- Findings: P0={report['finding_counts'].get('P0', 0)} "
        f"P1={report['finding_counts'].get('P1', 0)} "
        f"P2={report['finding_counts'].get('P2', 0)}",
        f"- Vision skipped: {report.get('vision_skipped')}",
        '',
        '## Regen queue',
        '',
        f"- Assets: {', '.join(report['regen_queue'].get('assets') or []) or '(none)'}",
        f"- Rooms: {', '.join(report['regen_queue'].get('rooms') or []) or '(none)'}",
        '',
        '## Findings',
        '',
    ]
    if not report['findings']:
        lines.append('_No findings._')
    for finding in report['findings']:
        lines.append(
            f"- **{finding['severity']}** `{finding['invariant']}` "
            f"{finding['utterance']}: {finding['detail']}"
        )
    lines.extend(['', '## Asset scores', ''])
    for row in report.get('asset_scores') or []:
        overall = (row.get('scores') or {}).get('overall', '—')
        status = 'skip' if row.get('skipped') else ('ok' if row.get('ok') else 'FAIL')
        lines.append(f"- `{row.get('target')}` [{status}] overall={overall} {row.get('why') or row.get('error') or ''}")
    lines.extend(['', '## Composition scores', ''])
    for row in report.get('composition_scores') or []:
        overall = (row.get('scores') or {}).get('overall', '—')
        status = 'skip' if row.get('skipped') else ('ok' if row.get('ok') else 'FAIL')
        lines.append(f"- `{row.get('target')}` [{status}] overall={overall} {row.get('why') or row.get('error') or ''}")
    lines.append('')
    return '\n'.join(lines)


def _index_markdown(run_dir: Path, report: dict) -> str:
    lines = [
        f"# Sprite red-team {run_dir.name}",
        '',
        f"[Full report](report.md) · [JSON](report.json)",
        '',
        '## Asset gallery',
        '',
    ]
    assets_dir = run_dir / 'gallery' / 'assets'
    if assets_dir.is_dir():
        for path in sorted(assets_dir.glob('*.png')):
            lines.append(f'- `{path.stem}` ![](gallery/assets/{path.name})')
    lines.extend(['', '## Composition gallery', ''])
    comps = run_dir / 'gallery' / 'compositions'
    if comps.is_dir():
        for path in sorted(comps.glob('*.png')):
            lines.append(f'- `{path.stem}` ![](gallery/compositions/{path.name})')
    lines.append('')
    return '\n'.join(lines)


def load_report(run_dir: Path) -> dict:
    path = run_dir / 'report.json'
    if not path.is_file():
        raise FileNotFoundError(f'No report.json in {run_dir}')
    return json.loads(path.read_text(encoding='utf-8'))
