"""Seeded dungeon topology generator over authored encounters.

Does not invent rooms from nothing: selects and connects authored encounter
templates into a variable graph. Same layout_seed always yields the same graph.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from puca_dungeon.encounter_catalog import (
    encounter_produces_items,
    encounters_by_id,
    encounters_for_role,
    load_catalog,
)
from puca_dungeon.rng import GameRNG


@dataclass
class GeneratedDungeon:
    layout_seed: int
    entry_id: int
    victory_id: int
    death_id: int
    passages: dict[int, dict] = field(default_factory=dict)
    encounter_at: dict[int, str] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)
    fingerprint: str = ''
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'layout_seed': self.layout_seed,
            'entry_id': self.entry_id,
            'victory_id': self.victory_id,
            'death_id': self.death_id,
            'passages': {str(k): v for k, v in self.passages.items()},
            'encounter_at': {str(k): v for k, v in self.encounter_at.items()},
            'edges': list(self.edges),
            'fingerprint': self.fingerprint,
            'meta': dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'GeneratedDungeon':
        passages = {
            int(k): v for k, v in (data.get('passages') or {}).items()
        }
        encounter_at = {
            int(k): str(v) for k, v in (data.get('encounter_at') or {}).items()
        }
        return cls(
            layout_seed=int(data.get('layout_seed', 0) or 0),
            entry_id=int(data.get('entry_id', 1) or 1),
            victory_id=int(data.get('victory_id', 400) or 400),
            death_id=int(data.get('death_id', 399) or 399),
            passages=passages,
            encounter_at=encounter_at,
            edges=list(data.get('edges') or []),
            fingerprint=str(data.get('fingerprint') or ''),
            meta=dict(data.get('meta') or {}),
        )

    def get_passage(self, passage_id: int) -> dict:
        if passage_id not in self.passages:
            raise KeyError(f'Passage {passage_id} missing from generated dungeon')
        return self.passages[passage_id]


def _pick(rng: GameRNG, items: list[Any]) -> Any:
    if not items:
        raise ValueError('Cannot pick from empty list')
    return rng.choice(items)


def _shuffle(rng: GameRNG, items: list[Any]) -> list[Any]:
    out = list(items)
    # Fisher-Yates using GameRNG
    for i in range(len(out) - 1, 0, -1):
        j = rng.randint(0, i)
        out[i], out[j] = out[j], out[i]
    return out


def _passage_from_encounter(
    passage_id: int,
    enc: dict,
    edge_map: dict[str, int],
    *,
    flee_to: Optional[int] = None,
) -> dict:
    choices = []
    for tmpl in enc.get('choice_templates') or []:
        edge = str(tmpl.get('edge') or '')
        dest = edge_map.get(edge)
        if dest is None:
            continue
        choice = {
            'id': tmpl.get('id'),
            'label': tmpl.get('label'),
            'aliases': list(tmpl.get('aliases') or []),
            'to': int(dest),
        }
        if tmpl.get('requires_any'):
            choice['requires_any'] = list(tmpl['requires_any'])
        choices.append(choice)

    combat = None
    raw_combat = enc.get('combat')
    if isinstance(raw_combat, dict):
        combat = {
            'enemy_name': raw_combat.get('enemy_name'),
            'enemy_skill': int(raw_combat.get('enemy_skill', 0) or 0),
            'enemy_stamina': int(raw_combat.get('enemy_stamina', 0) or 0),
            'win_to': edge_map.get(str(raw_combat.get('win_edge') or 'victory')),
            'lose_to': edge_map.get(str(raw_combat.get('lose_edge') or 'death')),
            'flee_to': edge_map.get(str(raw_combat.get('flee_edge') or 'return'), flee_to),
        }

    return {
        'id': passage_id,
        'text': str(enc.get('text') or ''),
        'choices': choices,
        'combat': combat,
        'tests': list(enc.get('tests') or []),
        'effects_on_enter': list(enc.get('effects_on_enter') or []),
        'ending': enc.get('ending'),
        'image_seed': str(enc.get('image_seed') or ''),
        'needs_review': False,
        'hazards': list(enc.get('hazards') or []),
        'entities': list(enc.get('entities') or []),
        'exposure': dict(enc.get('exposure') or {}),
        'pressures': list(enc.get('pressures') or []),
        'encounter_id': str(enc.get('id') or ''),
        'requires': list(enc.get('requires') or []),
        'produces': list(enc.get('produces') or []),
        'category': str(enc.get('category') or ''),
        'difficulty': str(enc.get('difficulty') or 'easy'),
    }


def generate_dungeon(layout_seed: int, catalog: dict | None = None) -> GeneratedDungeon:
    """Build a completable variable topology from authored encounters."""
    cat = catalog or load_catalog()
    by_id = encounters_by_id(cat)
    rng = GameRNG.from_seed(int(layout_seed) ^ 0xD5A11)

    entry_enc = by_id['alcove_caskets']
    loot_enc = by_id['named_casket_loot']
    hub_enc = by_id['junction']
    tracks_enc = by_id['claw_tracks']
    dead_enc = by_id['cold_dead_end']
    approach_enc = by_id['lair_approach']
    boss_enc = by_id['tunnel_hound']
    victory_enc = by_id['victory']
    death_enc = by_id['death']

    # Optionals that grant items (safe as mid or spur)
    reward_opts = [by_id[eid] for eid in ('rope_cache',) if eid in by_id]
    # Gated chambers: spur-only; never the sole path to the boss
    gated_opts = [
        by_id[eid] for eid in ('collapsed_shortcut', 'chasm_bridge')
        if eid in by_id
    ]
    reward_opts = _shuffle(rng, reward_opts)
    gated_opts = _shuffle(rng, gated_opts)

    include_rope = bool(reward_opts) and bool(rng.randint(0, 1))
    # If chasm is included, rope must also be included and placed upstream
    include_chasm = bool(gated_opts) and any(o['id'] == 'chasm_bridge' for o in gated_opts) and bool(rng.randint(0, 1))
    include_shortcut = bool(gated_opts) and any(o['id'] == 'collapsed_shortcut' for o in gated_opts) and bool(rng.randint(0, 1))
    if include_chasm:
        include_rope = True

    chosen_rewards = [by_id['rope_cache']] if include_rope and 'rope_cache' in by_id else []
    chosen_gated = []
    if include_chasm and 'chasm_bridge' in by_id:
        chosen_gated.append(by_id['chasm_bridge'])
    if include_shortcut and 'collapsed_shortcut' in by_id:
        chosen_gated.append(by_id['collapsed_shortcut'])

    warm_is_danger = bool(rng.randint(0, 1))
    loot_inline = bool(rng.randint(0, 1))

    next_id = 1
    ids: dict[str, int] = {}

    def alloc(key: str) -> int:
        nonlocal next_id
        pid = next_id
        next_id += 1
        ids[key] = pid
        return pid

    alloc('entry')
    alloc('loot')
    alloc('hub')
    alloc('tracks')
    alloc('dead')
    if chosen_rewards:
        alloc('rope')
    for i, _ in enumerate(chosen_gated):
        alloc(f'gate_{i}')
    alloc('approach')
    alloc('boss')
    alloc('victory')
    alloc('death')

    entry_edges = {'open_casket': 'loot', 'forward': 'hub'}
    loot_edges = {'forward': 'hub'}

    hub_edges: dict[str, str] = {'inspect': 'tracks'}
    tracks_edges = {'return': 'hub'}
    dead_edges = {'return': 'hub'}

    # Mandatory clear path: hub -> approach (no item gate)
    if warm_is_danger:
        hub_edges['branch_a'] = 'approach'
        hub_edges['branch_b'] = 'dead'
    else:
        hub_edges['branch_a'] = 'dead'
        hub_edges['branch_b'] = 'approach'

    # Rope cache as optional spur from hub (always skippable)
    rope_edges: dict[str, str] = {}
    if chosen_rewards:
        # Attach rope spur by replacing dead-end sometimes, else from loot
        if rng.randint(0, 1) == 0:
            hub_edges['branch_b' if warm_is_danger else 'branch_a'] = 'rope'
            rope_edges = {'forward': 'hub', 'return': 'hub'}
        else:
            loot_edges['forward'] = 'rope'
            rope_edges = {'forward': 'hub', 'return': 'loot'}

    # Gated chambers as optional spurs from hub; shortcut may reconnect toward approach
    gate_edge_maps: list[dict[str, str]] = []
    for i, genc in enumerate(chosen_gated):
        key = f'gate_{i}'
        if genc['id'] == 'collapsed_shortcut':
            # Token shortcut: spur from hub, forward jumps near approach (bonus path)
            gate_edge_maps.append({'forward': 'approach', 'return': 'hub'})
            # Expose via tracks-adjacent: add by swapping inspect? Keep as dead replacement if free
            free_branch = None
            for bk in ('branch_a', 'branch_b'):
                if hub_edges.get(bk) == 'dead':
                    free_branch = bk
                    break
            if free_branch:
                hub_edges[free_branch] = key
            else:
                # Attach from loot path
                if 'rope' in ids and loot_edges.get('forward') == 'rope':
                    rope_edges['forward'] = key
                else:
                    loot_edges['forward'] = key
        else:
            # chasm: optional spur only; forward also to approach if rope held (runtime)
            gate_edge_maps.append({'forward': 'approach', 'return': 'hub'})
            free_branch = None
            for bk in ('branch_a', 'branch_b'):
                if hub_edges.get(bk) == 'dead':
                    free_branch = bk
                    break
            if free_branch:
                hub_edges[free_branch] = key
            elif 'rope' in ids:
                rope_edges['forward'] = key
            else:
                loot_edges['forward'] = key

    approach_edges = {'forward': 'boss', 'return': 'hub'}
    boss_edges = {
        'victory': 'victory',
        'death': 'death',
        'return': 'hub',
    }

    passages: dict[int, dict] = {}
    encounter_at: dict[int, str] = {}
    edges_list: list[dict] = []

    def materialize(key: str, enc: dict, edge_key_map: dict[str, str], flee: Optional[str] = None):
        pid = ids[key]
        edge_map = {ek: ids[vk] for ek, vk in edge_key_map.items() if vk in ids}
        flee_id = ids[flee] if flee and flee in ids else ids.get('hub')
        passage = _passage_from_encounter(pid, enc, edge_map, flee_to=flee_id)
        if passage.get('combat') and passage['combat'].get('flee_to') is None:
            passage['combat']['flee_to'] = flee_id
        passages[pid] = passage
        encounter_at[pid] = str(enc.get('id') or '')
        for ch in passage.get('choices') or []:
            edges_list.append({
                'from': pid,
                'to': ch['to'],
                'choice_id': ch.get('id'),
                'encounter': encounter_at[pid],
            })
        if passage.get('combat'):
            c = passage['combat']
            for label, dest in (
                ('win', c.get('win_to')),
                ('lose', c.get('lose_to')),
                ('flee', c.get('flee_to')),
            ):
                if dest is not None:
                    edges_list.append({
                        'from': pid,
                        'to': int(dest),
                        'choice_id': f'combat_{label}',
                        'encounter': encounter_at[pid],
                    })

    materialize('entry', entry_enc, entry_edges)
    materialize('loot', loot_enc, loot_edges)
    materialize('hub', hub_enc, hub_edges)
    materialize('tracks', tracks_enc, tracks_edges)
    materialize('dead', dead_enc, dead_edges)
    if chosen_rewards:
        materialize('rope', chosen_rewards[0], rope_edges or {'forward': 'hub', 'return': 'hub'})
    for i, genc in enumerate(chosen_gated):
        materialize(f'gate_{i}', genc, gate_edge_maps[i] if i < len(gate_edge_maps) else {'return': 'hub'})
    materialize('approach', approach_enc, approach_edges)
    materialize('boss', boss_enc, boss_edges, flee='hub')
    materialize('victory', victory_enc, {})
    materialize('death', death_enc, {})

    fp_payload = {
        'seed': layout_seed,
        'ids': ids,
        'encounter_at': encounter_at,
        'edges': sorted(
            (e['from'], e['to'], e.get('choice_id')) for e in edges_list
        ),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fp_payload, sort_keys=True, default=str).encode('utf-8')
    ).hexdigest()[:16]

    dungeon = GeneratedDungeon(
        layout_seed=int(layout_seed),
        entry_id=ids['entry'],
        victory_id=ids['victory'],
        death_id=ids['death'],
        passages=passages,
        encounter_at=encounter_at,
        edges=edges_list,
        fingerprint=fingerprint,
        meta={
            'warm_is_danger': warm_is_danger,
            'loot_inline': loot_inline,
            'optional_ids': [o['id'] for o in chosen_rewards + chosen_gated],
            'node_keys': dict(ids),
        },
    )
    return dungeon


# Module-level registry for runtime passage lookup override
_ACTIVE_DUNGEON: Optional[GeneratedDungeon] = None


def set_active_dungeon(dungeon: Optional[GeneratedDungeon]) -> None:
    global _ACTIVE_DUNGEON
    _ACTIVE_DUNGEON = dungeon


def get_active_dungeon() -> Optional[GeneratedDungeon]:
    return _ACTIVE_DUNGEON


def get_generated_passage(passage_id: int) -> Optional[dict]:
    if _ACTIVE_DUNGEON is None:
        return None
    return _ACTIVE_DUNGEON.passages.get(int(passage_id))
