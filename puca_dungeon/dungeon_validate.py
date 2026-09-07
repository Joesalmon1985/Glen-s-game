"""Prove generated dungeons are completable before play."""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Optional

from puca_dungeon.dungeon_gen import GeneratedDungeon, generate_dungeon
from puca_dungeon.encounter_catalog import encounter_produces_items, encounters_by_id, load_catalog


def _neighbors(dungeon: GeneratedDungeon) -> dict[int, list[tuple[int, Optional[dict]]]]:
    """Map from_id -> list of (to_id, choice_or_none)."""
    adj: dict[int, list[tuple[int, Optional[dict]]]] = defaultdict(list)
    for pid, passage in dungeon.passages.items():
        for ch in passage.get('choices') or []:
            dest = ch.get('to')
            if dest is not None:
                adj[pid].append((int(dest), ch))
        combat = passage.get('combat')
        if isinstance(combat, dict):
            for key in ('win_to', 'lose_to', 'flee_to'):
                dest = combat.get(key)
                if dest is not None:
                    adj[pid].append((int(dest), {'id': f'combat_{key}', 'to': int(dest)}))
    return adj


def _items_on_enter(passage: dict) -> set[str]:
    items: set[str] = set()
    for effect in passage.get('effects_on_enter') or []:
        if isinstance(effect, dict) and effect.get('op') == 'add_item':
            items.add(str(effect.get('item')))
    for tag in passage.get('produces') or []:
        s = str(tag)
        if not s.startswith('flag:') and not s.startswith('knowledge:'):
            items.add(s)
    return items


def _choice_requirements(choice: dict) -> list[str]:
    return [str(x) for x in (choice.get('requires_any') or [])]


def reachable_with_items(dungeon: GeneratedDungeon) -> dict[int, set[str]]:
    """BFS collecting best (superset) item sets reachable at each node.

    Approximation: track one accumulated item set along paths; merge by union
    when revisiting with new items.
    """
    adj = _neighbors(dungeon)
    best: dict[int, set[str]] = {}
    start = dungeon.entry_id
    start_items = _items_on_enter(dungeon.passages[start])
    queue: deque[tuple[int, frozenset[str]]] = deque()
    queue.append((start, frozenset(start_items)))
    best[start] = set(start_items)
    seen: set[tuple[int, frozenset[str]]] = {(start, frozenset(start_items))}

    while queue:
        node, items_f = queue.popleft()
        items = set(items_f)
        if node not in dungeon.passages:
            continue
        items |= _items_on_enter(dungeon.passages[node])
        for dest, choice in adj.get(node, []):
            if dest not in dungeon.passages:
                continue
            req = _choice_requirements(choice) if choice else []
            if req and not any(r in items for r in req):
                # Cannot take this edge yet
                continue
            new_items = set(items) | _items_on_enter(dungeon.passages.get(dest) or {})
            key = (dest, frozenset(new_items))
            prev = best.get(dest)
            if prev is not None and new_items <= prev:
                continue
            best[dest] = (prev or set()) | new_items
            if key not in seen:
                seen.add(key)
                queue.append((dest, frozenset(best[dest])))
    return best


def validate_dungeon(dungeon: GeneratedDungeon, catalog: dict | None = None) -> dict:
    """Return {ok: bool, errors: [...], warnings: [...], stats: {...}}."""
    errors: list[str] = []
    warnings: list[str] = []
    cat = catalog or load_catalog()
    by_id = encounters_by_id(cat)

    if dungeon.entry_id not in dungeon.passages:
        errors.append('entry_id missing from passages')
    if dungeon.victory_id not in dungeon.passages:
        errors.append('victory_id missing from passages')
    if dungeon.death_id not in dungeon.passages:
        errors.append('death_id missing from passages')

    # Structural: no dangling choice targets
    for pid, passage in dungeon.passages.items():
        for ch in passage.get('choices') or []:
            dest = ch.get('to')
            if dest is None or int(dest) not in dungeon.passages:
                errors.append(f'passage {pid} choice {ch.get("id")} -> missing {dest}')
        combat = passage.get('combat')
        if isinstance(combat, dict):
            for key in ('win_to', 'lose_to', 'flee_to'):
                dest = combat.get(key)
                if dest is not None and int(dest) not in dungeon.passages:
                    errors.append(f'passage {pid} combat.{key} -> missing {dest}')

    reach = reachable_with_items(dungeon) if dungeon.passages else {}
    if dungeon.victory_id not in reach:
        errors.append('victory not reachable from entry under item constraints')
    if dungeon.entry_id not in reach:
        errors.append('entry not self-reachable')

    # Required items: at least one alternative in requires_any must have a producer
    for pid, passage in dungeon.passages.items():
        for ch in passage.get('choices') or []:
            req = _choice_requirements(ch)
            if not req:
                continue
            producers: list[tuple[str, int]] = []
            for tag in req:
                for other_pid, other in dungeon.passages.items():
                    if tag in _items_on_enter(other):
                        producers.append((tag, other_pid))
            if not producers:
                errors.append(
                    f'choice {ch.get("id")} at {pid} requires {req} but no producer exists'
                )
                continue
            # Key only behind its own gate destination
            for tag, prod_pid in producers:
                if prod_pid == ch.get('to'):
                    errors.append(
                        f'key {tag} only behind gate choice {ch.get("id")} at {pid}'
                    )

    # Alternate routes: hub should have >=2 distinct non-return destinations
    hub_pids = [
        pid for pid, eid in dungeon.encounter_at.items()
        if (by_id.get(eid) or {}).get('category') == 'hub'
    ]
    for hub in hub_pids:
        dests = {
            int(ch['to'])
            for ch in (dungeon.passages[hub].get('choices') or [])
            if ch.get('to') is not None
        }
        if len(dests) < 2:
            warnings.append(f'hub {hub} has fewer than 2 distinct exits')

    # Difficulty clustering: count hard encounters on shortest path approx
    hard_ids = [
        pid for pid, eid in dungeon.encounter_at.items()
        if (by_id.get(eid) or {}).get('difficulty') == 'hard'
    ]
    if len(hard_ids) > 2:
        warnings.append(f'many hard encounters clustered: {hard_ids}')

    # Reconnecting routes: some non-hub node returns to hub
    returns_to_hub = False
    if hub_pids:
        hub = hub_pids[0]
        for pid, passage in dungeon.passages.items():
            if pid == hub:
                continue
            for ch in passage.get('choices') or []:
                if ch.get('to') == hub:
                    returns_to_hub = True
            combat = passage.get('combat') or {}
            if combat.get('flee_to') == hub:
                returns_to_hub = True
        if not returns_to_hub:
            warnings.append('no alternate route reconnects to hub')

    stats = {
        'passage_count': len(dungeon.passages),
        'edge_count': len(dungeon.edges),
        'reachable_count': len(reach),
        'fingerprint': dungeon.fingerprint,
        'layout_seed': dungeon.layout_seed,
    }
    return {
        'ok': not errors,
        'errors': errors,
        'warnings': warnings,
        'stats': stats,
    }


def generate_and_validate(layout_seed: int, catalog: dict | None = None) -> tuple[GeneratedDungeon, dict]:
    dungeon = generate_dungeon(layout_seed, catalog=catalog)
    report = validate_dungeon(dungeon, catalog=catalog)
    return dungeon, report


def stress_validate_seeds(
    start: int = 0,
    count: int = 1000,
    catalog: dict | None = None,
) -> dict:
    """Generate and validate many seeds; return aggregate report."""
    failures: list[dict] = []
    fingerprints: set[str] = set()
    for i in range(count):
        seed = start + i
        dungeon, report = generate_and_validate(seed, catalog=catalog)
        fingerprints.add(dungeon.fingerprint)
        if not report['ok']:
            failures.append({'seed': seed, 'errors': report['errors']})
    return {
        'ok': len(failures) == 0,
        'tested': count,
        'unique_fingerprints': len(fingerprints),
        'failures': failures[:50],
        'failure_count': len(failures),
    }
