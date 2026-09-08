"""Narrator: prose downstream of resolved facts only. Optional LLM colour; Python owns facts."""
from __future__ import annotations

import json
import re
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

NARRATOR_SYSTEM = """You are a line editor for a text adventure, not an author.

You receive DRAFT prose (authoritative, written by the game) plus scene_context.
Return the same prose with only these edits allowed:
- smooth sentence rhythm and joins; vary sentence length; cut stiff repetition
- keep second person, present tense, plain concrete words
- register: dry, observant, a little wry — like a tired detective noticing things

You MUST preserve, verbatim: every quoted utterance (“…”), every proper name,
every paragraph break, and the final line beginning with an em dash (— …) if present.
You MUST NOT add facts, objects, people, movement, emotions, or explanations that
are not in the draft. Never mention intention, enactment, phases, meters,
scene_context, or that you are editing. Never quote the scene_context back. No headings, no lists, no JSON.
If unsure, return the draft unchanged."""


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

    composed = None
    if mode == 'facility' and getattr(world, 'facility', None) is not None:
        try:
            from puca_dungeon.compose_turn import compose, to_text
            fac = world.facility
            known = set(getattr(getattr(fac, 'arc', None), 'known_names', None) or [])
            room_before = str(getattr(resolution, 'room_before', '') or getattr(world, '_room_before_turn', '') or fac.room_id)
            composed = compose(world, resolution, room_before=room_before, known_names=known)
            composed['text'] = to_text(composed)
        except Exception:
            composed = None
    payload = {
        'player_text_non_authoritative': player_text,
        'draft': (composed or {}).get('text') or '',
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
        try:
            from puca_dungeon.narrative_context import get_scene_context, ensure_initial_context
            ensure_initial_context(world.facility)
            payload['scene_context'] = get_scene_context(world.facility).narrator_packet()
        except Exception:
            pass
    return payload


def template_narrate(payload: dict, resolution: Resolution) -> str:
    if resolution.needs_clarification and resolution.clarification_prompt:
        return resolution.clarification_prompt
    if isinstance(payload, dict) and payload.get('draft') and payload.get('mode') == 'facility':
        return str(payload['draft'])

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
        # Sensory contrast — never "you meant to" meta
        if enactment == 'aborted':
            if cause == 'institutional_force':
                _add('Your body does not finish the motion. Other hands decide the rest.')
            else:
                _add('The motion dies unfinished.')
        elif enactment == 'inverted':
            _add('Something else happens instead of what you reached for.')
        elif enactment == 'compromised':
            if 'force' in cause or cause == 'institutional_force':
                _add('You cannot stop what follows.')
            else:
                _add('You only manage part of it.')

    scene = payload.get('scene_context') if isinstance(payload, dict) else None
    if isinstance(scene, dict) and scene.get('this_is_a_new_scene') and scene.get('immediate_situation'):
        # Soft anchor when no scene_change lead text was emitted
        if not lead and scene.get('where'):
            _add(f'You are in the {scene["where"]}.')

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
        if isinstance(scene, dict) and scene.get('unresolved_immediate_tension'):
            return str(scene['unresolved_immediate_tension'])
        return 'Nothing around you answers that.'
    return 'A moment passes without a clear change.'


_QUOTE_RE = re.compile(r'“([^”]+)”')
_PARA_SPLIT = re.compile(r'(?:\r?\n){2,}')
_NAME_RE = re.compile(r'\b(Iven|Nessa|Ruan|Sarel|Maelin|Tirren|Sovan|Elian|Veyra|Cam|Ben|Laurie|Dom|Glen)\b')
_META_RE = re.compile(
    r'\b(draft|scene_context|enactment|intention|phase|meter|structured|perception confirms|'
    r'visible entities|as an editor|here is|revised|polished)\b', re.I,
)


def polish_is_faithful(draft: str, polished: str) -> bool:
    """Accept the LLM's edit only if it kept every quote, name, paragraph and the voice line."""
    if not polished or len(polished) > len(draft) * 1.6 + 80 or len(polished) < len(draft) * 0.55:
        return False
    if _META_RE.search(polished):
        return False
    for q in _QUOTE_RE.findall(draft):
        if q not in polished:
            return False
    if set(_NAME_RE.findall(draft)) - set(_NAME_RE.findall(polished)):
        return False
    if set(_NAME_RE.findall(polished)) - set(_NAME_RE.findall(draft)):
        return False
    d_paras = [x for x in _PARA_SPLIT.split(draft) if x.strip()]
    p_paras = [x for x in _PARA_SPLIT.split(polished) if x.strip()]
    if len(d_paras) != len(p_paras):
        return False
    if d_paras and d_paras[-1].lstrip().startswith(chr(8212)) and not p_paras[-1].lstrip().startswith(chr(8212)):
        return False
    return True


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
        draft = str(payload.get('draft') or '').strip()
        if payload.get('mode') != 'facility' or not draft:
            return self.fallback.narrate(world, resolution, player_text, intent)
        # The LLM only polishes the authoritative draft. Scene context helps it keep
        # tone; it must never add content.
        sc = payload.get('scene_context') or {}
        llm_payload = {
            'draft': draft,
            'scene_context': {
                'where': sc.get('where'),
                'people_present': sc.get('people_present'),
                'this_is_a_new_scene': sc.get('this_is_a_new_scene'),
            },
        }
        body = {
            'model': self.model,
            'system': NARRATOR_SYSTEM,
            'prompt': json.dumps(llm_payload, ensure_ascii=False),
            'stream': False,
            'keep_alive': 0,
            'options': {'temperature': 0.35, 'num_predict': 320, 'num_ctx': 4096},
        }
        request = urllib.request.Request(
            self.url, data=json.dumps(body).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = json.loads(response.read().decode('utf-8'))
            prose = (raw.get('response') or '').strip()
            if not prose:
                return payload, draft
            if not polish_is_faithful(draft, prose):
                return payload, draft
            # Prosecutor: fall back to draft if prose contradicts facts / leaks engine vocab
            try:
                from puca_dungeon.narrator_prosecutor import prosecute, has_blocking_failure
                hits = prosecute(prose, resolution, world)
                if has_blocking_failure(hits):
                    return payload, draft
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
