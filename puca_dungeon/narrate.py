"""Narrator: prose downstream of resolved facts only. Optional LLM colour; Python owns facts."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from puca_dungeon.models import WorldState
from puca_dungeon.resolve import Resolution

GUIDANCE_CUES = {
    0: '',
    1: 'Re-anchor lightly; keep it short and diegetic.',
    2: 'Humorous re-anchor plus one salient environmental cue from the passage.',
    3: 'Naturally hint at the obvious authored choices without listing numbers.',
    4: 'Near-direct but still diegetic reminder of the clear options ahead.',
}

NARRATOR_SYSTEM = """You write short second-person Fighting Fantasy narration from AUTHORITATIVE FACTS only.
Do not invent discoveries, damage, passage turns, inventory, or combat outcomes not in the facts.
If facts describe a real attempt, describe it as happening.
Vary wording. Prefer 1-3 sentences.
Return ONLY the prose, no JSON."""


def build_narrator_input(world: WorldState, resolution: Resolution, player_text: str,
                         intent: dict | None = None) -> dict:
    level = world.guidance_level
    sheet = world.sheet
    payload = {
        'player_text': player_text,
        'passage_id': world.passage_id,
        'player_alive': sheet.alive,
        'stamina': sheet.stamina,
        'facts': list(resolution.facts),
        'success': resolution.success,
        'classification': (intent or {}).get('classification'),
        'guidance_level': level,
        'guidance_cue': GUIDANCE_CUES.get(level, ''),
        'needs_clarification': resolution.needs_clarification,
        'combat_active': world.combat.active,
    }
    return payload


def template_narrate(payload: dict, resolution: Resolution) -> str:
    if resolution.needs_clarification and resolution.clarification_prompt:
        base = resolution.clarification_prompt
    elif not resolution.facts:
        base = 'Nothing of note follows from that.'
    else:
        # Skip debug-only enter markers when composing interstitial prose
        usable = [
            f for f in resolution.facts
            if not (isinstance(f, str) and f.startswith('Entered passage '))
        ]
        base = ' '.join(usable) if usable else ' '.join(resolution.facts)

    level = int(payload.get('guidance_level') or 0)
    classification = (payload.get('classification') or '').upper()
    if level <= 0 or resolution.needs_clarification:
        return base
    if classification in ('UNINTERPRETABLE', 'META_REQUEST') or resolution.rejection_reason in (
            'non_diegetic', 'impossible', 'intent_not_understood'):
        extras = {
            1: ' The dungeon waits, unimpressed.',
            2: ' Your Adventure Sheet and the passage ahead remain the real constraints.',
            3: ' Consider the clear choices the passage offers.',
            4: ' Act on one of the clear options before you.',
        }
        extra = extras.get(level, '')
        if extra and extra.strip() not in base:
            return base + extra
    elif level >= 3 and classification == 'SILLY_BUT_VALID':
        return base + ' The passage still demands a real choice.'
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
