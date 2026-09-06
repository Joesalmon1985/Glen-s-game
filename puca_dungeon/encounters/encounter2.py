"""Encounter 2 stub: junction with white west arrow (source-derived, minimal)."""
from __future__ import annotations

from puca_dungeon.models import EncounterId, WorldState


def enter_junction(world: WorldState) -> list[str]:
    """Transition into Encounter 2. Returns fact lines for the narrator."""
    world.encounter = EncounterId.JUNCTION.value
    world.player.location = EncounterId.JUNCTION.value
    world.visible_entities = [
        'junction', 'white_arrow_west', 'passage_west', 'passage_right', 'floor_tracks',
    ]
    # Pursuer does not auto-follow for this stub unless already present/hostile
    if world.pursuer.state in ('present', 'hostile', 'allied') and world.pursuer.location == EncounterId.WALK_BOXES.value:
        world.pursuer.location = EncounterId.JUNCTION.value
    facts = [
        'You leave the stone table behind and continue down the passage.',
        'You reach a junction. A white arrow painted on the wall points west.',
        'Closer inspection of the dusty floor could reveal tracks.',
    ]
    return facts


def inspect_junction(world: WorldState) -> list[str]:
    world.junction_inspected = True
    if 'tracks_west_three_right_one' not in world.player.knowledge:
        world.player.knowledge.append('tracks_west_three_right_one')
    return [
        'Scratches and boot-prints in the dust show three contestants went west; one went right.',
    ]
