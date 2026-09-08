"""Image prompts from visible passage state; optional LLM colouring; optional SD generation."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Optional, Union

from puca_dungeon.models import WorldState
from puca_dungeon.resolve import Resolution

STYLE = 'pixel art, limited palette, clear silhouette, gentle eerie fantasy, no lettering'

PassageLike = Union[dict, Any]

IMAGE_PROMPT_SYSTEM = """You write a short image-generation prompt for a dungeon scene.
Use the Python game-state image_seed AND the short narration_visual_cues from the player-facing text.
Treat game state as authoritative for what exists (room, props, people, body pose).
Use narration cues only for mood, lighting, pose, and what is visibly happening right now.
Do NOT invent tanks, helicopters, forests, enemies, loot, or locations not supported by image_seed / state.
Include the style prefix if missing. No lettering, no gore. One line only.
Return ONLY the prompt text."""

_VISUAL_HINT = re.compile(
    r'\b(see|look|watch|stand|sit|lie|kneel|door|slit|cup|bed|bowl|book|floor|wall|'
    r'light|dark|shadow|room|cell|corridor|wash|mess|orderly|researcher|staff|'
    r'water|spill|broken|open|closed|torch|grate|window|face|eyes|hand|blood|'
    r'wounded|fallen|waiting|present|arrive|leave|speak|voice)\b',
    re.I,
)


def sprites_requested(explicit: Optional[bool] = None) -> bool:
    """Sprites are opt-in via PUCA_IMAGE_MODE=sprites or use_sprites=True."""
    if explicit is not None:
        return bool(explicit)
    return str(os.environ.get('PUCA_IMAGE_MODE') or '').strip().lower() == 'sprites'


def extract_visual_cues_from_narration(narration: Optional[str], max_chars: int = 280) -> str:
    """Pull short, drawable phrases from the player-facing turn text."""
    text = re.sub(r'\s+', ' ', (narration or '').strip())
    if not text:
        return ''
    # Drop pure quoted speech blocks; keep surrounding stage direction.
    text = re.sub(r'"[^"]*"', ' ', text)
    text = re.sub(r"'[^']*'", ' ', text)
    text = re.sub(r'\s+', ' ', text).strip(' .;')
    if not text:
        return ''

    sentences = [
        s.strip()
        for s in re.split(r'(?<=[.!?])\s+', text)
        if s.strip()
    ]
    chosen: list[str] = []
    for sentence in sentences:
        if _VISUAL_HINT.search(sentence) or not chosen:
            chosen.append(sentence.rstrip('.'))
        if len(chosen) >= 3:
            break
    if not chosen:
        chosen = sentences[:2]
    cues = '; '.join(chosen)
    if len(cues) > max_chars:
        cues = cues[: max_chars - 1].rsplit(' ', 1)[0] + '…'
    return cues


def facility_image_seed(world: WorldState) -> str:
    """Authoritative Python facility state condensed for diffusion prompts."""
    fac = getattr(world, 'facility', None)
    if fac is None:
        return ''
    room = (fac.rooms or {}).get(fac.room_id) or {}
    parts = ['facility', fac.room_id or 'cell']
    room_desc = str(room.get('description') or '').strip()
    if room_desc:
        gloss = room_desc.split('\n', 1)[0].strip()
        if '.' in gloss:
            gloss = gloss.split('.', 1)[0].strip() + '.'
        if gloss:
            parts.append(gloss)
    try:
        entities = list(fac.entities_in_room())
    except Exception:
        entities = []
    for e in entities:
        bit = e.id
        pos = (e.state or {}).get('position')
        if pos:
            bit += f' {str(pos).replace("_", " ")}'
        if e.id == 'cup' and (e.state or {}).get('water_spilled'):
            bit += ' spilled water on floor'
        if e.id == 'cup' and getattr(e, 'broken', False):
            bit += ' broken'
        if e.id == 'bed' and (e.state or {}).get('bedding') == 'on_floor':
            bit += ' bedding on floor'
        if e.id == 'bowl' and (e.state or {}).get('spilled'):
            bit += ' food spilled'
        if e.id == 'door' and getattr(fac, 'slit_open', False):
            bit += ' slit open'
        parts.append(bit)
    present_ids = list(getattr(getattr(fac, 'arc', None), 'present_ids', None) or [])
    if present_ids:
        names = []
        for cid in present_ids:
            try:
                names.append(fac.character_name(cid))
            except Exception:
                names.append(str(cid).replace('_', ' '))
        parts.append('people present: ' + ', '.join(names))
    elif getattr(fac, 'staff_present', False):
        count = int(getattr(fac, 'staff_count', 0) or 0)
        parts.append(f'{count} orderly staff at the door' if count else 'staff at the door')
    return ', '.join(parts)


def build_image_prompt(
    world: WorldState,
    passage: Optional[PassageLike] = None,
    narration: Optional[str] = None,
) -> str:
    if passage is None:
        try:
            from puca_dungeon.content_loader import get_passage
            passage = get_passage(world.passage_id)
        except Exception:
            passage = None

    if isinstance(passage, dict):
        seed = passage.get('image_seed') or ''
        room_text = passage.get('text') or ''
    else:
        seed = getattr(passage, 'image_seed', '') if passage is not None else ''
        room_text = getattr(passage, 'text', '') if passage is not None else ''

    if getattr(world, 'mode', '') == 'facility':
        seed = facility_image_seed(world) or seed
    elif not seed:
        seed = ''

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

    cues = extract_visual_cues_from_narration(narration)
    if not cues and room_text and not seed:
        cues = extract_visual_cues_from_narration(str(room_text), max_chars=180)
    if cues:
        parts.append(f'from narration: {cues}')

    # Never add tank/helicopter/forest unless already in seed/state
    detail = ', '.join(p for p in parts if p)
    return f'{STYLE}, {detail}'


def llm_colour_image_prompt(
    base_prompt: str,
    world: WorldState,
    model: str = 'mistral',
    url: str = 'http://127.0.0.1:11434/api/generate',
    narration: Optional[str] = None,
) -> str:
    """Optional LLM rewrite of the image prompt from visible facts + narration cues."""
    payload = {
        'image_seed_prompt': base_prompt,
        'passage_id': world.passage_id,
        'combat': world.combat.enemy_name if world.combat.active else None,
        'alive': world.sheet.alive,
        'victory': world.victory,
        'body_state': dict(world.sheet.body_state or {}),
        'narration_visual_cues': extract_visual_cues_from_narration(narration),
        'reminder': 'Game state is authoritative; narration only colours mood and action. '
                    'Do not invent tank, helicopter, or forest.',
    }
    body = {
        'model': model,
        'system': IMAGE_PROMPT_SYSTEM,
        'prompt': json.dumps(payload, ensure_ascii=False),
        'stream': False,
        'keep_alive': 0,
        'options': {'temperature': 0.6, 'num_predict': 100, 'num_ctx': 2048},
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
    narration: Optional[str] = None,
    use_sprites: Optional[bool] = None,
) -> dict:
    # Sprite kit is opt-in (PUCA_IMAGE_MODE=sprites or use_sprites=True).
    if sprites_requested(use_sprites):
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

    prompt = build_image_prompt(world, passage=passage, narration=narration)
    if colour_with_llm:
        prompt = llm_colour_image_prompt(
            prompt, world, model=ollama_model, narration=narration,
        )

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
