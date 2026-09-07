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

NARRATOR_SYSTEM = """You write short second-person narration from authoritative Python facts only.

Two truths (never confuse them):
- wanted_action: what the player intended (desire, not authority).
- actual_action + facts/structured_facts/world_events: what actually happened.

When wanted_action and actual_action diverge (enactment is compromised, aborted, or inverted),
you MAY exploit the contrast — wit, embodiment, embarrassment — but you must narrate ACTUAL
reality. Never invent objects, movement, success, damage, inventory, windows, or exits absent
from the facts merely because the player wanted them.

Hard rules:
- Never negate, replace, or invent physical outcomes that contradict facts.
  If facts say you were washed, do not say the water remained untouched.
- Never quote or paraphrase engine labels: do not write "Structured State", "facility phase",
  "sated", "quenched", "alert", "hygiene aware", "restrained", SKILL, STAMINA, LUCK, or meter numbers.
- Bodily evidence arrives as sensory sentences in body_sensations (if present). Use them sparingly
  and only when salient; do not list status words.
- If world_events or structured_facts contain type scene_change (must_lead), the FIRST paragraph
  MUST announce that change (room left, slit opened, what they are asking). Then narrate the action.
  Scene changes may use 4-8 sentences. Other turns stay economical (1-3 sentences).
- Failure is content. Do not coach. No named inner personalities.
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
    mode = str(getattr(world, 'mode', 'facility') or 'facility')

    payload = {
        'player_text_non_authoritative': player_text,
        'wanted_action': dict(getattr(resolution, 'wanted_action', None) or wanted_action_from_intent(intent)),
        'actual_action': dict(getattr(resolution, 'actual_action', None) or {}),
        'enactment': getattr(resolution, 'enactment', 'direct') or 'direct',
        'enactment_cause': getattr(resolution, 'enactment_cause', '') or '',
        'mode': mode,
        'passage_id': world.passage_id if mode == 'book_dungeon' else None,
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
    }
    # Facility narrative evidence only while actually in the facility
    if mode == 'facility' and getattr(world, 'facility', None) is not None:
        try:
            from puca_dungeon.enactment import salient_sensations
            sensations = salient_sensations(world.facility.pressures)
            if sensations:
                payload['body_sensations'] = sensations
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
    lead: list[str] = []
    for ev in list(getattr(resolution, 'world_events', None) or []) + list(
        getattr(resolution, 'structured_facts', None) or []
    ):
        if isinstance(ev, dict) and ev.get('type') == 'scene_change' and ev.get('text'):
            lead.append(str(ev['text']))

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

    if lead:
        headed = []
        for line in lead:
            if line and line not in headed:
                headed.append(line)
        rest = [p for p in parts if p not in headed]
        return ' '.join(headed + rest)
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
            # Prosecutor: fall back to template if prose contradicts facts / leaks engine vocab
            try:
                from puca_dungeon.narrator_prosecutor import prosecute, has_blocking_failure
                hits = prosecute(prose, resolution, world)
                if has_blocking_failure(hits):
                    return payload, template_narrate(payload, resolution)
            except Exception:
                pass
            return payload, prose
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
            return self.fallback.narrate(world, resolution, player_text, intent)


def narrate(world: WorldState, resolution: Resolution, player_text: str,
            intent: dict | None = None, narrator=None) -> tuple[dict, str]:
    """Default deterministic template narrator (safe for tests)."""
    engine = narrator or TemplateNarrator()
    return engine.narrate(world, resolution, player_text, intent)
