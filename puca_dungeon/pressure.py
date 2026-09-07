"""Guidance pressure only (no pursuer / Grimnak stall clock)."""
from __future__ import annotations

from puca_dungeon.models import WorldState
from puca_dungeon.resolve import Resolution


def apply_guidance(world: WorldState, resolution: Resolution) -> dict:
    """Clamp guidance_level from resolution.guidance_delta."""
    before = world.guidance_level
    delta = int(resolution.guidance_delta or 0)

    if resolution.productive_for_guidance or delta == -999:
        world.guidance_level = 0
    elif delta > 0:
        world.guidance_level = min(4, world.guidance_level + delta)
    elif delta < 0:
        world.guidance_level = max(0, world.guidance_level + delta)

    return {
        'guidance_before': before,
        'guidance_after': world.guidance_level,
        'guidance_delta_applied': world.guidance_level - before,
    }
