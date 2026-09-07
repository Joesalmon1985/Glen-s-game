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

IMAGE_PROMPT_SYSTEM = """You write a short image-generation prompt for a Fighting Fantasy dungeon scene.
Use ONLY the visible facts and image_seed provided. Do not invent enemies, loot, or locations.
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
        parts.append(f'dark dungeon passage {world.passage_id}')

    if world.combat.active:
        parts.append(f'fighting {world.combat.enemy_name}')
    if not sheet.alive or world.ending == 'death':
        parts.append('fallen adventurer')
    elif world.victory or world.ending == 'victory':
        parts.append('triumphant adventurer emerging from dungeon')

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
        'negative_prompt': 'photorealistic, blurry, text, watermark, explicit, gore',
        'suppressed': True,
        'note': 'IMAGE GENERATION SUPPRESSED',
    }
