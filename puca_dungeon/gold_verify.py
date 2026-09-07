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
    gold = load_gold(pack_dir)
    passages = load_all_passages(pack_dir)
    mismatches = []
    missing_gold = []
    stub_bridged = []
    needs_review = []

    for pid in range(1, 401):
        g = (gold.get('passages') or {}).get(str(pid))
        if not g:
            missing_gold.append(pid)
            continue
        p = passages.get(pid)
        if p is None:
            mismatches.append({'id': pid, 'reason': 'missing_passage'})
            continue
        data = _as_dict(p)
        # Also load raw flags
        raw_path = pack_dir / 'passages' / f'{pid:03d}.json'
        raw = json.loads(raw_path.read_text(encoding='utf-8'))
        if raw.get('stub_bridged'):
            stub_bridged.append(pid)
        if raw.get('needs_review'):
            needs_review.append(pid)

        gold_tos = sorted({int(e['to']) for e in g.get('edges') or [] if 'to' in e})
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
            1 for g in (gold.get('passages') or {}).values()
            if g.get('judgement_inferred')
        ),
    }


if __name__ == '__main__':
    print(json.dumps(verify_gold(), indent=2))
