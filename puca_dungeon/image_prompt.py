"""Would-be image prompt from authoritative visible state. Debug never generates."""
from __future__ import annotations

from puca_dungeon.models import EncounterId, WorldState
from puca_dungeon.resolve import Resolution

STYLE = 'pixel art, limited palette, clear silhouette, gentle eerie fantasy, no lettering'


def build_image_prompt(world: WorldState) -> str:
    if world.encounter == EncounterId.WALK_BOXES.value:
        open_boxes = [b.label for b in world.boxes.values() if b.open or b.destroyed]
        parts = [
            'torchlit stone dungeon chamber',
            'stone table with six iron-bound locked boxes',
            f"one box labeled {world.boxes['box_player'].label}",
        ]
        if open_boxes:
            parts.append('open boxes: ' + ', '.join(open_boxes[:3]))
        # Only visible pursuer states affect the prompt
        if world.pursuer.state in ('present', 'hostile', 'allied'):
            parts.append(f'{world.pursuer.kind} challenger {world.pursuer.name} present')
        # approaching/close are auditory — omit from visual prompt
        if world.flags.get('sword_drawn'):
            parts.append('drawn sword')
        detail = ', '.join(parts)
    elif world.encounter == EncounterId.JUNCTION.value:
        if world.junction_inspected:
            detail = 'dungeon junction, white painted arrow pointing west, dusty tracks on stone floor'
        else:
            detail = 'dungeon junction, white painted arrow pointing west, dusty floor'
    elif world.encounter == EncounterId.DEAD.value:
        detail = 'fallen adventurer in a torchlit dungeon, still boxes on a stone table'
    else:
        detail = 'dark dungeon passage'
    return f'{STYLE}, {detail}'


def image_decision(world: WorldState, resolution: Resolution) -> dict:
    prompt = build_image_prompt(world)
    # Only visible authoritative changes should regenerate.
    # Auditory-only and zero-visible-damage strikes should reuse.
    visible_dirty = bool(resolution.image_dirty)
    reuse = bool(world.last_image_prompt) and world.last_image_prompt == prompt and not visible_dirty
    if not world.last_image_prompt:
        decision = 'REGENERATE'
        reason = 'first image'
    elif reuse:
        decision = 'REUSE'
        reason = 'visible state unchanged'
    else:
        decision = 'REGENERATE'
        reason = 'visual state changed' if visible_dirty or world.last_image_prompt != prompt else 'first image'
    world.last_image_prompt = prompt
    return {
        'decision': decision,
        'reason': reason,
        'full_prompt': prompt,
        'negative_prompt': 'photorealistic, blurry, text, watermark, explicit, gore',
        'suppressed': True,
        'note': 'DEBUG MODE — IMAGE GENERATION SUPPRESSED',
    }
