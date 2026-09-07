"""Narrator: prose downstream of resolved facts only. Optional LLM colour; Python owns facts."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from puca_dungeon import body_events
from puca_dungeon.enactment import wanted_action_from_intent
from puca_dungeon.models import WorldState
from puca_dungeon.resolve import Resolution

# Guidance may track wasted turns but must NOT coach toward authored choice menus.
GUIDANCE_CUES = {
    0: '',
    1: 'Stay brief and diegetic.',
    2: 'Stay brief and diegetic.',
    3: 'Stay brief and diegetic.',
    4: 'Stay brief and diegetic.',
}

NARRATOR_SYSTEM = """You write short second-person narration from AUTHORITATIVE STRUCTURED STATE only.

Two truths (never confuse them):
- wanted_action: what the player intended their character to do (desire, not authority).
- actual_action + facts/structured_facts/world_events: what Python says actually happened.

When wanted_action and actual_action diverge (enactment is compromised, aborted, or inverted),
you MAY exploit the contrast — wit, embodiment, embarrassment — but you must narrate ACTUAL
reality. Never invent objects, movement, success, damage, inventory, windows, or exits absent
from structured state merely because the player wanted them.

Tone:
- Second person, intimate, economical (prefer 1-3 sentences; more only when mismatch is rich).
- Embodied: body, fear, fatigue, hunger, hygiene may appear as sensation, not meters.
- Failure is content. Do not coach or tutorial. No named inner personalities (no LOGIC/VOLITION).
- You may briefly personify a body part as a turn of phrase ("Your knees reach their own conclusion")
  without turning it into a character or RPG system.
- Never use SKILL, STAMINA, LUCK, Attack Strength, Adventure Sheet, passage numbers, or dice jargon.
- Prefer structured_facts and qualitative body/pressure summaries over raw meters.
- Return ONLY the prose, no JSON."""


def _diegetic_from_structured(facts: list) -> list[str]:
    facts = list(facts or [])
    types_present = {
        str(f.get('type'))
        for f in facts
        if isinstance(f, dict) and f.get('type')
    }
    has_opportunity = 'enemy_opportunity_attack' in types_present
    lines: list[str] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        kind = fact.get('kind') or ''
        ftype = fact.get('type') or ''
        # Prefer opportunity summary over raw hit/wound duplicates from same reaction
        if has_opportunity and ftype in ('enemy_hit_player', 'wound'):
            continue
        if ftype == 'social_no_uptake':
            continue
        if ftype == 'entity_absent':
            entity = fact.get('entity') or 'that'
            lines.append(f'There is no {entity} here.')
        elif ftype == 'destination_absent':
            dest = fact.get('destination') or 'there'
            lines.append(f'There is no way {dest} from here.')
        elif ftype == 'combat_begins':
            lines.append(f'{fact.get("enemy") or "An enemy"} bars your way.')
        elif ftype == 'player_hit_enemy':
            lines.append(f'You strike {fact.get("target") or "the enemy"}.')
        elif ftype == 'enemy_hit_player':
            lines.append(f'{fact.get("actor") or "The enemy"} wounds you.')
        elif ftype == 'enemy_opportunity_attack':
            actor = fact.get('actor') or 'The enemy'
            lines.append(f'{actor} takes the opening and strikes.')
        elif ftype == 'enemy_defeated':
            lines.append(f'{fact.get("enemy") or "The enemy"} falls.')
        elif ftype == 'player_died':
            lines.append('Your wounds overcome you.')
        elif ftype == 'impossible_attempt':
            lines.append('Nothing answers that impossible wish.')
        elif ftype == 'key_attempt':
            # Prefer the richer fact string from resolve when present
            continue
        elif kind == 'body_event' and ftype == 'wound':
            site = fact.get('site') or 'body'
            sev = fact.get('severity') or 'light'
            lines.append(f'A {sev} wound marks your {site}.')
        elif kind == 'perception' and ftype == 'visible_entities':
            ents = fact.get('entities') or []
            if ents:
                shown = ', '.join(str(e).replace('_', ' ') for e in ents[:6])
                lines.append(f'You notice: {shown}.')
    return lines

def build_narrator_input(
    world: WorldState,
    resolution: Resolution,
    player_text: str,
    intent: dict | None = None,
) -> dict:
    sheet = world.sheet
    combat_qual = None
    if world.combat.active:
        combat_qual = {
            'enemy_name': world.combat.enemy_name,
            'active': True,
            'can_flee': world.combat.flee_to is not None,
        }

    structured = list(getattr(resolution, 'structured_facts', None) or [])
    world_events = list(getattr(resolution, 'world_events', None) or [])

    payload = {
        'player_text_non_authoritative': player_text,
        'wanted_action': dict(getattr(resolution, 'wanted_action', None) or wanted_action_from_intent(intent)),
        'actual_action': dict(getattr(resolution, 'actual_action', None) or {}),
        'enactment': getattr(resolution, 'enactment', 'direct') or 'direct',
        'enactment_cause': getattr(resolution, 'enactment_cause', '') or '',
        'mode': getattr(world, 'mode', 'facility'),
        'passage_id': world.passage_id,
        'player_alive': sheet.alive,
        'facts': list(resolution.facts),
        'structured_facts': structured,
        'world_events': world_events,
        'body_state': dict(sheet.body_state or {}),
        'body_qualitative': body_events.qualitative_body_summary(sheet),
        'visible_entities': list(world.visible_entities or []),
        'combat': combat_qual,
        'success': resolution.success,
        'attempted': getattr(resolution, 'attempted', False),
        'intended_effect_achieved': getattr(resolution, 'intended_effect_achieved', False),
        'state_changed': getattr(resolution, 'state_changed', False),
        'classification': (intent or {}).get('classification'),
        'guidance_level': 0,
        'guidance_cue': '',
        'needs_clarification': resolution.needs_clarification,
        'combat_active': world.combat.active,
        # Debug-only; templates and LLM system prompt must ignore score numbers.
        'debug_metrics': {
            'stamina': sheet.stamina,
            'stamina_initial': sheet.stamina_initial,
            'skill': sheet.skill,
            'luck': sheet.luck,
        },
    }
    if getattr(world, 'facility', None) is not None:
        try:
            from puca_dungeon.enactment import qualitative_pressures
            payload['pressures_qualitative'] = qualitative_pressures(world.facility.pressures)
            payload['facility_phase'] = world.facility.phase
            payload['facility_room'] = world.facility.room_id
        except Exception:
            pass
    return payload


def template_narrate(payload: dict, resolution: Resolution) -> str:
    if resolution.needs_clarification and resolution.clarification_prompt:
        return resolution.clarification_prompt

    structured_lines = _diegetic_from_structured(
        list(getattr(resolution, 'structured_facts', None) or [])
        + list(getattr(resolution, 'world_events', None) or [])
    )

    usable = [
        f for f in resolution.facts
        if not (isinstance(f, str) and (
            f.startswith('Entered passage ')
            or f.startswith('passage_id=')
        ))
    ]

    parts: list[str] = []
    seen: set[str] = set()

    def _add(line: str) -> None:
        line = (line or '').strip()
        if not line or line in seen:
            return
        # Skip near-duplicates already covered by usable facts
        for existing in parts:
            if line in existing or existing in line:
                return
        seen.add(line)
        parts.append(line)

    enactment = getattr(resolution, 'enactment', 'direct') or 'direct'
    cause = getattr(resolution, 'enactment_cause', '') or ''
    if enactment in ('compromised', 'aborted', 'inverted'):
        wanted = getattr(resolution, 'wanted_action', None) or {}
        wanted_ac = wanted.get('action_class') or payload.get('player_text_non_authoritative') or 'that'
        if enactment == 'aborted':
            _add(f'You mean to {wanted_ac}. Your body does not finish it' + (f' ({cause}).' if cause else '.'))
        elif enactment == 'inverted':
            _add(f'You mean to {wanted_ac}. Something else happens instead' + (f' — {cause}.' if cause else '.'))
        elif enactment == 'compromised':
            _add(f'You attempt {wanted_ac}, diminished' + (f' by {cause}.' if cause else '.'))

    for f in usable:
        if isinstance(f, str):
            _add(f)
    for line in structured_lines:
        _add(line)

    if parts:
        return ' '.join(parts)
    if getattr(resolution, 'attempted', False) and not getattr(resolution, 'state_changed', False):
        return 'You act, but nothing in the world shifts for it.'
    return 'Nothing of note follows from that.'


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
        # Strip debug_metrics from LLM-facing prompt
        llm_payload = {k: v for k, v in payload.items() if k != 'debug_metrics'}
        body = {
            'model': self.model,
            'system': NARRATOR_SYSTEM,
            'prompt': json.dumps(llm_payload, ensure_ascii=False),
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
