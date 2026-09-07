"""Image prompts from visible passage state; optional LLM colouring; optional SD generation."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional, Union

from puca_dungeon.models import WorldState
from puca_dungeon.resolve import Resolution

STYLE = 'pixel art, limited palette, clear silhouette, gentle eerie fantasy, no lettering'

PassageLike = Union[dict, Any]

IMAGE_PROMPT_SYSTEM = """You write a short image-generation prompt for a dungeon scene.
Use ONLY the visible facts and image_seed provided.
Do NOT invent tanks, helicopters, forests, enemies, loot, or locations not in image_seed / state.
Include the style prefix if missing. No lettering, no gore. One line only.
Return ONLY the prompt text."""


def build_image_prompt(world: WorldState, passage: Optional[PassageLike] = None) -> str:
    if passage is None:
        try:
            from puca_dungeon.content_loader import get_passage
            passage = get_passage(world.passage_id)
        except Exception:
            passage = None

    if isinstance(passage, dict):
        seed = passage.get('image_seed') or ''
    else:
        seed = getattr(passage, 'image_seed', '') if passage is not None else ''

    sheet = world.sheet
    parts = []
    if seed:
        parts.append(str(seed))
    else:
        parts.append(f'dark stone passage {world.passage_id}')

    if world.combat.active and world.combat.enemy_name:
        parts.append(f'facing {world.combat.enemy_name}')

    body = dict(sheet.body_state or {})
    injuries = list(sheet.injuries or [])
    if not sheet.alive or world.ending == 'death':
        parts.append('fallen adventurer')
    elif world.victory or world.ending == 'victory':
        parts.append('triumphant adventurer emerging')
    else:
        pain = str(body.get('pain') or 'none')
        bleeding = str(body.get('bleeding') or 'none')
        if injuries or pain not in ('', 'none') or bleeding not in ('', 'none'):
            parts.append('wounded adventurer')
            if bleeding not in ('', 'none'):
                parts.append(f'{bleeding} bleeding')
        else:
            parts.append('wary adventurer')

    # Drawn sword only if equipment / flag says so
    flags = sheet.flags or {}
    drawn = bool(flags.get('sword_drawn') or flags.get('weapon_drawn'))
    inv_blob = ' '.join(
        str(i.get('name') if isinstance(i, dict) else i).lower()
        for i in (sheet.inventory or [])
    )
    if drawn and 'sword' in inv_blob:
        parts.append('sword drawn')

    # Never add tank/helicopter/forest unless already in seed/state
    detail = ', '.join(p for p in parts if p)
    return f'{STYLE}, {detail}'


def llm_colour_image_prompt(
    base_prompt: str,
    world: WorldState,
    model: str = 'mistral',
    url: str = 'http://127.0.0.1:11434/api/generate',
) -> str:
    """Optional LLM rewrite of the image prompt from visible facts only."""
    payload = {
        'image_seed_prompt': base_prompt,
        'passage_id': world.passage_id,
        'combat': world.combat.enemy_name if world.combat.active else None,
        'alive': world.sheet.alive,
        'victory': world.victory,
        'body_state': dict(world.sheet.body_state or {}),
        'reminder': 'Do not invent tank, helicopter, or forest.',
    }
    body = {
        'model': model,
        'system': IMAGE_PROMPT_SYSTEM,
        'prompt': json.dumps(payload, ensure_ascii=False),
        'stream': False,
        'keep_alive': 0,
        'options': {'temperature': 0.6, 'num_predict': 80, 'num_ctx': 2048},
    }
    request = urllib.request.Request(
        url, data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = json.loads(response.read().decode('utf-8'))
        prose = (raw.get('response') or '').strip().strip('"')
        if not prose:
            return base_prompt
        if STYLE.split(',')[0] not in prose.lower() and 'pixel' not in prose.lower():
            prose = f'{STYLE}, {prose}'
        return prose
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        return base_prompt


def image_decision(
    world: WorldState,
    resolution: Resolution,
    passage: Optional[PassageLike] = None,
    colour_with_llm: bool = False,
    ollama_model: str = 'mistral',
) -> dict:
    # Facility mode: compose from pre-generated sprites (no per-turn diffusion).
    try:
        from puca_dungeon.scene_compose import build_visual_spec, facility_mode_active
    except Exception:
        facility_mode_active = None  # type: ignore
        build_visual_spec = None  # type: ignore

    if facility_mode_active is not None and facility_mode_active(world) and build_visual_spec is not None:
        spec = build_visual_spec(world)
        fingerprint = f'sprite:{spec.key}'
        visible_dirty = bool(resolution.image_dirty)
        reuse = bool(world.last_image_prompt) and world.last_image_prompt == fingerprint and not visible_dirty
        if not world.last_image_prompt:
            decision = 'REGENERATE'
            reason = 'first sprite scene'
        elif reuse:
            decision = 'REUSE'
            reason = 'visible sprite state unchanged'
        else:
            decision = 'REGENERATE'
            reason = 'sprite visual state changed'
        world.last_image_prompt = fingerprint
        return {
            'decision': decision,
            'reason': reason,
            'full_prompt': fingerprint,
            'renderer': 'sprites',
            'visual_spec': spec.to_dict(),
            'negative_prompt': '',
            'suppressed': True,
            'note': 'SPRITE COMPOSITION PENDING',
        }

    prompt = build_image_prompt(world, passage=passage)
    if colour_with_llm:
        prompt = llm_colour_image_prompt(prompt, world, model=ollama_model)

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
        'renderer': 'diffusion',
        'negative_prompt': 'photorealistic, blurry, text, watermark, explicit, gore, tank, helicopter',
        'suppressed': True,
        'note': 'IMAGE GENERATION SUPPRESSED',
    }
