"""Validate content-pack passage graph integrity."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from puca_dungeon.content_loader import PACK_DIR, load_all_passages, load_manifest


def _choice_targets(choice: dict) -> list[int]:
    targets = []
    if choice.get('to') is not None:
        try:
            targets.append(int(choice['to']))
        except (TypeError, ValueError):
            pass
    for key in ('to_success', 'to_fail', 'to_lucky', 'to_unlucky',
                'success_to', 'failure_to', 'lucky_to', 'unlucky_to'):
        if choice.get(key) is not None:
            try:
                targets.append(int(choice[key]))
            except (TypeError, ValueError):
                pass
    return targets


def _combat_targets(combat: Optional[dict]) -> list[int]:
    if not combat or not isinstance(combat, dict):
        return []
    targets = []
    for key in ('win_to', 'lose_to', 'flee_to'):
        if combat.get(key) is not None:
            try:
                targets.append(int(combat[key]))
            except (TypeError, ValueError):
                pass
    return targets


def _test_targets(test: dict) -> list[int]:
    targets = []
    for key in ('to', 'to_success', 'to_fail', 'to_lucky', 'to_unlucky',
                'success_to', 'failure_to', 'lucky_to', 'unlucky_to'):
        if test.get(key) is not None:
            try:
                targets.append(int(test[key]))
            except (TypeError, ValueError):
                pass
    outcomes = test.get('outcomes') or {}
    if isinstance(outcomes, dict):
        for val in outcomes.values():
            try:
                targets.append(int(val))
            except (TypeError, ValueError):
                pass
    return targets


def _as_dict(passage: Any) -> dict:
    if hasattr(passage, 'to_dict'):
        return passage.to_dict()
    if isinstance(passage, dict):
        return passage
    return {
        'id': getattr(passage, 'id', None),
        'choices': getattr(passage, 'choices', []) or [],
        'combat': getattr(passage, 'combat', None),
        'tests': getattr(passage, 'tests', []) or [],
        'ending': getattr(passage, 'ending', None),
    }


def _collect_outgoing(data: dict) -> list[int]:
    outs: list[int] = []
    for choice in data.get('choices') or []:
        if isinstance(choice, dict):
            outs.extend(_choice_targets(choice))
            for cond in choice.get('conditions') or []:
                if isinstance(cond, dict):
                    for key in ('success_to', 'fail_to', 'to'):
                        if cond.get(key) is not None:
                            try:
                                outs.append(int(cond[key]))
                            except (TypeError, ValueError):
                                pass
    outs.extend(_combat_targets(data.get('combat')))
    for test in data.get('tests') or []:
        if isinstance(test, dict):
            outs.extend(_test_targets(test))
    return outs


def validate_pack(pack_dir: Path = PACK_DIR) -> dict:
    """Validate passage graph.

    Returns:
      missing_ids — referenced targets with no passage file
      bad_links — out-of-range or non-integer links
      empty_choice_non_endings — non-ending passages with no choices/combat/tests
      coverage — counts vs declared passage_range
    """
    manifest = load_manifest(pack_dir)
    passages = load_all_passages(pack_dir)
    prange = manifest.get('passage_range') or [1, 400]
    lo, hi = int(prange[0]), int(prange[1])
    start_id = int(
        manifest.get('start_id')
        or manifest.get('start_passage')
        or 1
    )
    expected_ids = set(range(lo, hi + 1))
    present_ids = set(passages.keys())

    missing_ids: list[int] = []
    bad_links: list[dict] = []
    empty_choice_non_endings: list[int] = []
    referenced: set[int] = set()

    for pid, passage in sorted(passages.items()):
        data = _as_dict(passage)
        ending = data.get('ending')
        choices = data.get('choices') or []
        combat = data.get('combat')
        tests = data.get('tests') or []

        if not ending and not choices and not combat and not tests:
            empty_choice_non_endings.append(pid)

        for choice in choices:
            if not isinstance(choice, dict):
                bad_links.append({'from': pid, 'reason': 'choice_not_object', 'choice': choice})
                continue
            raw_to = choice.get('to')
            if raw_to is not None:
                try:
                    int(raw_to)
                except (TypeError, ValueError):
                    bad_links.append({
                        'from': pid,
                        'to': raw_to,
                        'reason': 'non_integer_to',
                        'choice_id': choice.get('id'),
                    })

        if combat and isinstance(combat, dict):
            for key in ('win_to', 'lose_to', 'flee_to'):
                raw = combat.get(key)
                if raw is None:
                    continue
                try:
                    int(raw)
                except (TypeError, ValueError):
                    bad_links.append({
                        'from': pid, 'to': raw, 'reason': f'non_integer_{key}',
                    })

        for target in _collect_outgoing(data):
            referenced.add(target)
            if target < lo or target > hi:
                bad_links.append({'from': pid, 'to': target, 'reason': 'out_of_range'})
            elif target not in present_ids:
                missing_ids.append(target)

    missing_ids = sorted(set(missing_ids))
    empty_choice_non_endings = sorted(empty_choice_non_endings)

    coverage = {
        'range': [lo, hi],
        'expected': len(expected_ids),
        'present': len(present_ids),
        'missing_in_range': sorted(expected_ids - present_ids),
        'extra_outside_range': sorted(present_ids - expected_ids),
        'referenced': len(referenced),
        'unreferenced_present': sorted(
            pid for pid in present_ids
            if pid not in referenced and pid != start_id
        ),
        'pct': round(100.0 * len(present_ids) / max(1, len(expected_ids)), 2),
    }

    return {
        'missing_ids': missing_ids,
        'bad_links': bad_links,
        'empty_choice_non_endings': empty_choice_non_endings,
        'coverage': coverage,
        'ok': not missing_ids and not bad_links and not empty_choice_non_endings,
    }


# Alias used by CLI / OCR tooling
validate_graph = validate_pack


def validate_and_print(pack_dir: Path = PACK_DIR) -> dict:
    report = validate_pack(pack_dir)
    cov = report['coverage']
    print(
        f"Passages {cov['present']}/{cov['expected']} ({cov['pct']}%) | "
        f"missing targets: {len(report['missing_ids'])} | "
        f"bad links: {len(report['bad_links'])} | "
        f"empty non-endings: {len(report['empty_choice_non_endings'])}"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack-dir', type=Path, default=PACK_DIR)
    parser.add_argument('--json-out', type=Path, default=None)
    args = parser.parse_args()
    report = validate_pack(args.pack_dir)
    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
