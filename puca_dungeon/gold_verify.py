"""Verify pack passages against gold_graph.json."""
from __future__ import annotations

import json
from pathlib import Path

from puca_dungeon.content_loader import PACK_DIR, load_all_passages
from puca_dungeon.graph_validate import _collect_outgoing, _as_dict


def load_gold(pack_dir: Path = PACK_DIR) -> dict:
    path = pack_dir / 'gold_graph.json'
    with path.open(encoding='utf-8') as f:
        return json.load(f)


def verify_gold(pack_dir: Path = PACK_DIR) -> dict:
    """Verify pack passages against gold_graph.json.

    Sparse packs (e.g. ``puca_trial``) only list spine nodes in gold_graph;
    those entries are checked, not a forced 1..400 range.
    """
    gold = load_gold(pack_dir)
    passages = load_all_passages(pack_dir)
    gold_passages = gold.get('passages') or {}
    mismatches = []
    missing_gold = []
    stub_bridged = []
    needs_review = []

    # Gold-listed ids that lack a passage file
    for key, g in sorted(gold_passages.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0):
        try:
            pid = int(key)
        except (TypeError, ValueError):
            mismatches.append({'id': key, 'reason': 'non_integer_gold_id'})
            continue
        p = passages.get(pid)
        if p is None:
            missing_gold.append(pid)
            mismatches.append({'id': pid, 'reason': 'missing_passage'})
            continue
        data = _as_dict(p)
        raw_path = pack_dir / 'passages' / f'{pid:03d}.json'
        raw = json.loads(raw_path.read_text(encoding='utf-8'))
        if raw.get('stub_bridged'):
            stub_bridged.append(pid)
        if raw.get('needs_review'):
            needs_review.append(pid)

        gold_tos = sorted({int(e['to']) for e in (g.get('edges') or []) if 'to' in e})
        pack_tos = sorted(set(_collect_outgoing(data)))
        if gold_tos != pack_tos:
            mismatches.append({
                'id': pid,
                'reason': 'edge_mismatch',
                'gold': gold_tos,
                'pack': pack_tos,
            })
        if (g.get('ending') or None) != (data.get('ending') or None):
            mismatches.append({
                'id': pid,
                'reason': 'ending_mismatch',
                'gold': g.get('ending'),
                'pack': data.get('ending'),
            })

    return {
        'ok': not mismatches and not missing_gold and not stub_bridged and not needs_review,
        'mismatches': mismatches[:50],
        'mismatch_count': len(mismatches),
        'missing_gold': missing_gold,
        'stub_bridged': stub_bridged,
        'needs_review': needs_review,
        'judgement_inferred_count': sum(
            1 for g in gold_passages.values()
            if g.get('judgement_inferred')
        ),
    }


if __name__ == '__main__':
    print(json.dumps(verify_gold(), indent=2))
