"""Narrator: prose downstream of resolved facts only. Optional LLM colour; Python owns facts."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from puca_dungeon.models import WorldState
from puca_dungeon.resolve import Resolution

GUIDANCE_CUES = {
    0: '',
    1: 'Re-anchor lightly with dry humour if the action was meta/nonsense; keep it short.',
    2: 'Humorous re-anchor plus mention one salient environmental cue (named box or key).',
    3: 'Naturally hint at obvious interactions: examine boxes, try the key, tamper with locks, damage one, or continue.',
    4: 'Near-direct but still diegetic explanation of the immediate obvious interactions. No menus, buttons, or command tags.',
}

NARRATOR_SYSTEM = """You write short second-person dungeon narration from AUTHORITATIVE FACTS only.
Do not invent discoveries, damage, openings, NPC decisions, or state changes not in the facts.
If facts describe a real bodily attempt (lick, cartwheel, shake), describe it as happening — do not say the character only thought about it.
Vary wording. Prefer 1-3 sentences.
Return ONLY the prose, no JSON."""


def build_narrator_input(world: WorldState, resolution: Resolution, player_text: str,
                         intent: dict | None = None) -> dict:
    level = world.guidance_level
    payload = {
        'player_text': player_text,
        'encounter': world.encounter,
        'player_alive': world.player.alive,
        'player_hp': world.player.hp,
        'facts': list(resolution.facts),
        'success': resolution.success,
        'location': world.player.location,
        'classification': (intent or {}).get('classification'),
        'guidance_level': level,
        'guidance_cue': GUIDANCE_CUES.get(level, ''),
        'needs_clarification': resolution.needs_clarification,
    }
    return payload


def template_narrate(payload: dict, resolution: Resolution) -> str:
    if resolution.needs_clarification and resolution.clarification_prompt:
        base = resolution.clarification_prompt
    elif not resolution.facts:
        base = 'Nothing of note follows from that.'
    else:
        base = ' '.join(resolution.facts)

    level = int(payload.get('guidance_level') or 0)
    classification = (payload.get('classification') or '').upper()
    if level <= 0 or resolution.needs_clarification:
        return base
    if classification in ('UNINTERPRETABLE', 'META_REQUEST') or resolution.rejection_reason in (
            'non_diegetic', 'impossible', 'intent_not_understood'):
        extras = {
            1: ' The boxes remain stubbornly real and unimpressed.',
            2: ' One box bears your name. You are still carrying the key given to you at the entrance.',
            3: ' You could examine the boxes, try the key, tamper with the locks, damage one, or simply continue down the passage.',
            4: ' The immediate work is plain: the named box and your iron key, the locks, force if you must, or the passage onward.',
        }
        extra = extras.get(level, '')
        if extra and extra.strip() not in base:
            return base + extra
    elif level >= 3 and classification == 'SILLY_BUT_VALID':
        return base + ' The table and its six locked boxes still demand a real choice.'
    return base


class TemplateNarrator:
    def narrate(self, world: WorldState, resolution: Resolution, player_text: str,
                intent: dict | None = None) -> tuple[dict, str]:
        payload = build_narrator_input(world, resolution, player_text, intent)
        return payload, template_narrate(payload, resolution)


class OllamaNarrator:
    def __init__(self, model: str = 'mistral', url: str = 'http://127.0.0.1:11434/api/generate'):
        self.model = model
        self.url = url
        self.fallback = TemplateNarrator()

    def narrate(self, world: WorldState, resolution: Resolution, player_text: str,
                intent: dict | None = None) -> tuple[dict, str]:
        payload = build_narrator_input(world, resolution, player_text, intent)
        # Clarification stays crisp and deterministic
        if resolution.needs_clarification:
            return payload, template_narrate(payload, resolution)
        body = {
            'model': self.model,
            'system': NARRATOR_SYSTEM,
            'prompt': json.dumps(payload, ensure_ascii=False),
            'stream': False,
            'keep_alive': 0,
            'options': {'temperature': 0.7, 'num_predict': 220, 'num_ctx': 4096},
        }
        request = urllib.request.Request(
            self.url, data=json.dumps(body).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = json.loads(response.read().decode('utf-8'))
            prose = (raw.get('response') or '').strip()
            if not prose:
                return self.fallback.narrate(world, resolution, player_text, intent)
            return payload, prose
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
            return self.fallback.narrate(world, resolution, player_text, intent)


def narrate(world: WorldState, resolution: Resolution, player_text: str,
            intent: dict | None = None, narrator=None) -> tuple[dict, str]:
    """Default deterministic template narrator (safe for tests)."""
    engine = narrator or TemplateNarrator()
    return engine.narrate(world, resolution, player_text, intent)
