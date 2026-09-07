"""Restricted speaker packets — never dump the cast database to the LLM."""
from __future__ import annotations

from typing import Optional

from puca_dungeon.characters import CharacterState, name_of


def build_speaker_packet(
    cast: dict,
    speaker_id: str,
    *,
    objective: str,
    language_ability: int,
    may_add: Optional[list] = None,
) -> dict:
    raw = (cast or {}).get(speaker_id) or {}
    ch = CharacterState.from_dict(raw if isinstance(raw, dict) else None)
    rel = ch.rel('sarel')
    relationship_summary = (
        'knows Sarel only through recent encounters'
        if rel.familiarity < 2
        else 'has a short shared history with Sarel'
    )
    return {
        'speaker_id': speaker_id,
        'name': ch.name or name_of(cast, speaker_id),
        'role': ch.role,
        'presentation': ch.presentation,
        'objective': objective,
        'emotion': ch.emotion,
        'relationship_summary': relationship_summary,
        'may_reveal': list(ch.may_reveal) + list(may_add or []),
        'must_conceal': list(ch.must_conceal) + [
            'relationship_scores', 'strategy_label', 'trust_meter',
        ],
        'language_constraint': (
            'simple_words_only' if language_ability < 35
            else 'short_sentences' if language_ability < 55
            else 'clear_but_plain'
        ),
    }


def packet_to_fact(packet: dict, spoken_raw: str, understood: str) -> dict:
    return {
        'type': 'npc_speech',
        'speaker': packet.get('speaker_id'),
        'speaker_name': packet.get('name'),
        'raw': spoken_raw,
        'understood': understood,
        'objective': packet.get('objective'),
    }
