"""Guidance pressure only (no pursuer / Grimnak stall clock).

Does not escalate toward choice menus. Narrator must not receive choice-hint cues.
"""
from __future__ import annotations

from puca_dungeon.models import WorldState
from puca_dungeon.resolve import Resolution


def apply_guidance(world: WorldState, resolution: Resolution) -> dict:
    """Keep guidance_level at 0 — track wasted turns optionally without narrator hints."""
    before = world.guidance_level
    # Productive actions clear any residual pressure.
    if resolution.productive_for_guidance or int(resolution.guidance_delta or 0) == -999:
        world.guidance_level = 0
    else:
        # Never escalate into choice-menu coaching; stay at 0.
        world.guidance_level = 0

    return {
        'guidance_before': before,
        'guidance_after': world.guidance_level,
        'guidance_delta_applied': world.guidance_level - before,
        'choice_hints_suppressed': True,
    }
