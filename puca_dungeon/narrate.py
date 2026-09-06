"""Narrator: prose downstream of resolved facts only."""
from __future__ import annotations

from puca_dungeon.models import WorldState
from puca_dungeon.resolve import Resolution


def build_narrator_input(world: WorldState, resolution: Resolution, player_text: str) -> dict:
    return {
        'player_text': player_text,
        'encounter': world.encounter,
        'player_alive': world.player.alive,
        'player_hp': world.player.hp,
        'facts': list(resolution.facts),
        'success': resolution.success,
        'location': world.player.location,
    }


def narrate(world: WorldState, resolution: Resolution, player_text: str) -> tuple[dict, str]:
    """Template narrator (deterministic). Optional LLM can wrap this later."""
    payload = build_narrator_input(world, resolution, player_text)
    if not resolution.facts:
        prose = 'Nothing of note follows from that.'
    else:
        prose = ' '.join(resolution.facts)
    return payload, prose
