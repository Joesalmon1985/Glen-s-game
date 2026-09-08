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

You receive a NarrativeTurnSpec projection:
- turn_spec: where you are/were, attempt vs actual, physical_contrast, ordered_events,
  people_present, must_narrate / should_narrate, social_context, discourse.
- scene_context: continuing dramatic situation.
- facts / world_events: supporting authoritative lines.

Hard rules:
- The turn_spec is immutable authoritative reality. Preserve ordered_events causal order.
- MEMORY_CUE / interview_prompt / recollection events are internal or conversational —
  they do NOT change physical location unless an explicit location change / scene_change exists.
- Never invent objects, people, movement, injuries, or dialogue absent from the turn_spec/facts.
- If attempt differs from actual, dramatise physical contrast only — never say intention,
  enactment, wanted_action, "despite your intention", or "you meant to".
- Use social_context lines as observable significance only; do not invent hidden motives
  beyond what is supplied; never print trust meters, strategy names, or cooperation scores.
- Never mention language practice counts, deltas, attempt numbers, or skill meters.
- people_present / characters use narrator_reference only. Never invent a personal name that is not supplied as known. Never dump biographies or "NEW CHARACTER" announcements.
- Prefer short causal prose. Scene changes may use 4-8 sentences; continuations 1-3.
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
        elif ftype in ('character_intro', 'subject_meeting', 'slit_opens'):
            if fact.get('text'):
                lines.append(str(fact['text']))
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
            from puca_dungeon.narrative_context import get_scene_context, ensure_initial_context
            ensure_initial_context(world.facility)
            payload['scene_context'] = get_scene_context(world.facility).narrator_packet()
        except Exception:
            pass
    # Prefer finalized NarrativeEvent projection when present
    nev = getattr(resolution, 'narrative_event', None)
    if isinstance(nev, dict) and nev:
        try:
            from puca_dungeon.narrative_event import NarrativeEvent
            payload['turn_spec'] = NarrativeEvent(
                turn_id=str(nev.get('turn_id') or ''),
                reality=str(nev.get('reality') or mode),
                location_before=str(nev.get('location_before') or ''),
                location_after=str(nev.get('location_after') or ''),
                player_attempt=dict(nev.get('player_attempt') or {}),
                actual_outcome=dict(nev.get('actual_outcome') or {}),
                contrast=dict(nev.get('contrast') or {}),
                events=list(nev.get('events') or []),
                current_scene=dict(nev.get('current_scene') or {}),
                discourse=dict(nev.get('discourse') or {}),
                sensations=list(nev.get('sensations') or []),
                social_meaning=list(nev.get('social_meaning') or []),
                conversational_moves=list(nev.get('conversational_moves') or []),
                salience=dict(nev.get('salience') or {}),
                ordered_beats=list(nev.get('ordered_beats') or []),
            ).narrator_projection()
            if nev.get('sensations'):
                payload['body_sensations'] = list(nev.get('sensations') or [])[:3]
        except Exception:
            payload['turn_spec'] = {
                'attempt': payload.get('wanted_action'),
                'actual': payload.get('actual_action'),
            }
    # Last-resort name hygiene. Tests fail if this had to rewrite an ordinary packet.
    if mode == 'facility' and getattr(world, 'facility', None) is not None:
        try:
            from puca_dungeon.npc_knowledge import find_unknown_name_leaks, scrub_unknown_names
            leaks = find_unknown_name_leaks(world.facility, payload)
            payload['_name_hygiene_leaks'] = leaks
            if leaks:
                payload, altered = scrub_unknown_names(world.facility, payload)
                payload['_name_hygiene_scrubbed'] = bool(altered)
                payload['_name_hygiene_leaks'] = leaks
        except Exception:
            pass
    return payload


def _finish_sentence(line: str) -> str:
    line = (line or '').strip()
    if not line:
        return ''
    if line[-1] not in '.!?…"”\'':
        line += '.'
    return line


def _is_noise_line(line: str, *, scene_changed: bool) -> bool:
    low = line.strip().lower()
    if low.startswith('you notice:'):
        return True
    if low.startswith('they are still waiting:'):
        return True
    if scene_changed and low.startswith(('bed beneath you', 'a plain corridor', 'a narrow table',
                                         'a brighter room', 'water. a basin', 'your mouth tastes')):
        return True
    return False


def _join_prose(lines: list[str]) -> str:
    finished = []
    seen: set[str] = set()
    for raw in lines:
        line = _finish_sentence(raw)
        if not line:
            continue
        key = line.lower()
        if key in seen:
            continue
        skip = False
        for existing in finished:
            if line in existing or existing in line:
                skip = True
                break
        if skip:
            continue
        seen.add(key)
        finished.append(line)
    return '\n\n'.join(finished)


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
        for existing in parts:
            if line in existing or existing in line:
                return
        seen.add(line)
        parts.append(line)

    enactment = getattr(resolution, 'enactment', 'direct') or 'direct'
    cause = getattr(resolution, 'enactment_cause', '') or ''
    if enactment in ('compromised', 'aborted', 'inverted'):
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
        if not lead and scene.get('where'):
            _add(f'You are in the {scene["where"]}.')

    scene_changed = bool(lead)
    location_changed = False
    for ev in list(getattr(resolution, 'world_events', None) or []) + list(
        getattr(resolution, 'structured_facts', None) or []
    ):
        if not isinstance(ev, dict) or ev.get('type') != 'scene_change':
            continue
        frm = str(ev.get('from_room') or '')
        to = str(ev.get('to_room') or '')
        if frm and to and frm != to:
            location_changed = True
            break

    keep_event_types = {
        'character_intro', 'subject_meeting', 'washed', 'fed', 'sleep',
        'learn_npc_name',
    }
    event_lines = []
    for ev in list(getattr(resolution, 'world_events', None) or []) + list(
        getattr(resolution, 'structured_facts', None) or []
    ):
        if not isinstance(ev, dict):
            continue
        if ev.get('type') in keep_event_types and ev.get('text'):
            event_lines.append(str(ev['text']))

    for f in usable:
        if isinstance(f, str) and not _is_noise_line(f, scene_changed=scene_changed):
            _add(f)
    for line in structured_lines:
        if not _is_noise_line(line, scene_changed=scene_changed):
            _add(line)

    if lead:
        headed = []
        for line in lead:
            if line and line not in headed:
                headed.append(line)
        extras = []
        if location_changed:
            for line in event_lines:
                if line not in headed:
                    extras.append(line)
            for line in parts:
                if line in headed or line in extras:
                    continue
                if '"' in line or '“' in line or '”' in line:
                    extras.append(line)
        else:
            extras = [p for p in parts if p not in headed and not _is_noise_line(p, scene_changed=True)]
        return _join_prose(headed + extras[:4])
    if parts:
        return _join_prose(parts)
    if getattr(resolution, 'attempted', False) and not getattr(resolution, 'state_changed', False):
        if isinstance(scene, dict) and scene.get('unresolved_immediate_tension'):
            return str(scene['unresolved_immediate_tension'])
        return 'Nothing around you answers that.'
    return 'A moment passes without a clear change.'


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
        # Diegetic attempt/actual/contrast via turn_spec; strip raw engine dual-truth fields.
        llm_payload = {
            k: v for k, v in payload.items()
            if k not in (
                'wanted_action', 'actual_action', 'enactment', 'enactment_cause',
                'intended_effect_achieved', 'success', 'attempted', 'state_changed',
                'classification', 'guidance_level', 'guidance_cue', 'body_qualitative',
                'body_state',
                '_name_hygiene_leaks', '_name_hygiene_scrubbed',
            )
        }
        # Never expose language-practice meters / deltas to the LLM
        sf = []
        for f in list(llm_payload.get('structured_facts') or []):
            if isinstance(f, dict) and f.get('type') == 'language_practice':
                continue
            if isinstance(f, dict):
                clean = {
                    k: v for k, v in f.items()
                    if k not in ('delta', 'attempts', 'learning_rate', 'disclose_depth')
                }
                sf.append(clean)
            else:
                sf.append(f)
        llm_payload['structured_facts'] = sf
        # Scrub turn_spec ordered_events of the same internals
        ts = llm_payload.get('turn_spec')
        if isinstance(ts, dict) and ts.get('ordered_events'):
            cleaned_ev = []
            for e in ts['ordered_events']:
                if not isinstance(e, dict):
                    continue
                if e.get('type') == 'language_practice':
                    continue
                cleaned_ev.append({
                    k: v for k, v in e.items()
                    if k not in ('delta', 'attempts', 'learning_rate', 'disclose_depth')
                })
            ts = dict(ts)
            ts['ordered_events'] = cleaned_ev
            llm_payload['turn_spec'] = ts
        body = {
            'model': self.model,
            'system': NARRATOR_SYSTEM,
            'prompt': json.dumps(llm_payload, ensure_ascii=False),
            'stream': False,
            'keep_alive': '10m',
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
            # Prosecutor: fail closed — never show unvalidated prose on checker crash
            try:
                from puca_dungeon.narrator_prosecutor import prosecute, has_blocking_failure
                hits = prosecute(prose, resolution, world)
                if has_blocking_failure(hits):
                    return payload, template_narrate(payload, resolution)
            except Exception:
                return payload, template_narrate(payload, resolution)
            return payload, prose
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
            return self.fallback.narrate(world, resolution, player_text, intent)


def narrate(world: WorldState, resolution: Resolution, player_text: str,
            intent: dict | None = None, narrator=None) -> tuple[dict, str]:
    """Default deterministic template narrator (safe for tests)."""
    engine = narrator or TemplateNarrator()
    return engine.narrate(world, resolution, player_text, intent)
