"""Canonical NarrativeEvent / TurnSpec — assembled after resolve+react, before narrate."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class NarrativeEvent:
    """Immutable-from-narration authoritative turn ledger."""
    turn_id: str = ''
    reality: str = 'facility'  # facility | book_dungeon
    location_before: str = ''
    location_after: str = ''

    player_attempt: dict = field(default_factory=dict)
    actual_outcome: dict = field(default_factory=dict)
    contrast: dict = field(default_factory=dict)  # diegetic: kind + cause phrasing

    events: list = field(default_factory=list)  # ordered typed event dicts
    current_scene: dict = field(default_factory=dict)
    discourse: dict = field(default_factory=dict)
    sensations: list = field(default_factory=list)

    social_meaning: list = field(default_factory=list)
    conversational_moves: list = field(default_factory=list)
    salience: dict = field(default_factory=dict)  # must / should / may / omit
    ordered_beats: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'turn_id': self.turn_id,
            'reality': self.reality,
            'location_before': self.location_before,
            'location_after': self.location_after,
            'player_attempt': dict(self.player_attempt or {}),
            'actual_outcome': dict(self.actual_outcome or {}),
            'contrast': dict(self.contrast or {}),
            'events': list(self.events or []),
            'current_scene': dict(self.current_scene or {}),
            'discourse': dict(self.discourse or {}),
            'sensations': list(self.sensations or []),
            'social_meaning': list(self.social_meaning or []),
            'conversational_moves': list(self.conversational_moves or []),
            'salience': dict(self.salience or {}),
            'ordered_beats': list(self.ordered_beats or []),
        }

    def narrator_projection(self) -> dict:
        """Diegetic-only packet for the LLM — no engine labels."""
        must = list((self.salience or {}).get('must_render') or [])
        should = list((self.salience or {}).get('should_render') or [])
        from puca_dungeon.social_meaning import social_projection_for_narrator
        social = social_projection_for_narrator(self.social_meaning)
        if not social and self.social_meaning:
            # Already sanitised lines
            social = [
                e for e in self.social_meaning
                if isinstance(e, dict) and e.get('what_matters')
            ]
        moves = []
        for m in self.conversational_moves or []:
            if not isinstance(m, dict):
                continue
            surface = {
                k: m[k] for k in ('who', 'appears_to_want', 'manner')
                if m.get(k)
            }
            if surface:
                moves.append(surface)
        ordered = []
        for e in self.events or []:
            if not isinstance(e, dict) or e.get('type') in ('enactment', 'conversational_move'):
                continue
            clean = {
                k: v for k, v in e.items()
                if k not in (
                    'conversational_move', 'form', 'enactment', 'wanted', 'actual',
                    'cause',
                )
            }
            ordered.append(clean)
        return {
            'where_you_are': self.location_after or self.location_before,
            'where_you_were': self.location_before,
            'location_changed': bool(
                self.location_before
                and self.location_after
                and self.location_before != self.location_after
            ),
            'attempt': dict(self.player_attempt or {}),
            'actual': dict(self.actual_outcome or {}),
            'physical_contrast': (
                {
                    'note': (self.contrast or {}).get('note') or '',
                    'cause': (self.contrast or {}).get('cause') or '',
                }
                if self.contrast else {}
            ),
            'ordered_events': ordered,
            'people_present': list((self.current_scene or {}).get('people') or []),
            'visible_objects': list((self.current_scene or {}).get('visible_objects') or []),
            'discourse': dict(self.discourse or {}),
            'must_narrate': must,
            'should_narrate': should,
            'social_context': social,
            'npc_manner': moves,
            'sensations': list(self.sensations or []),
            'ordered_beats': list(self.ordered_beats or []),
        }


_CONTRAST_KIND = {
    'direct': '',
    'compromised': 'resistance or constraint limited what you could finish',
    'aborted': 'the attempt did not complete',
    'inverted': 'something else happened instead of what you reached for',
}


def _diegetic_action(action: dict | None) -> dict:
    action = dict(action or {})
    ac = str(action.get('action_class') or action.get('action') or '').strip()
    out = {}
    if ac:
        out['action'] = ac.replace('_', ' ')
    for key in ('target', 'modifier', 'performed'):
        if key in action and action[key] not in (None, ''):
            out[key] = action[key]
    return out


def _sync_enactment_fact(resolution) -> None:
    """Ensure structured enactment fact matches final resolution fields."""
    sf = list(getattr(resolution, 'structured_facts', None) or [])
    enactment = getattr(resolution, 'enactment', 'direct') or 'direct'
    cause = getattr(resolution, 'enactment_cause', '') or ''
    wanted = dict(getattr(resolution, 'wanted_action', None) or {})
    actual = dict(getattr(resolution, 'actual_action', None) or {})
    found = False
    for i, fact in enumerate(sf):
        if isinstance(fact, dict) and fact.get('type') == 'enactment':
            sf[i] = {
                'type': 'enactment',
                'enactment': enactment,
                'cause': cause or None,
                'wanted': wanted,
                'actual': actual,
            }
            found = True
            break
    if not found:
        sf.append({
            'type': 'enactment',
            'enactment': enactment,
            'cause': cause or None,
            'wanted': wanted,
            'actual': actual,
        })
    resolution.structured_facts = sf


def finalize_resolution(
    world,
    resolution,
    *,
    location_before: str = '',
    social_events: Optional[list] = None,
    conversational_moves: Optional[list] = None,
) -> NarrativeEvent:
    """Build canonical turn ledger after resolve+react. Does not mutate world."""
    _sync_enactment_fact(resolution)

    mode = str(getattr(world, 'mode', 'facility') or 'facility')
    fac = getattr(world, 'facility', None)
    loc_after = location_before
    people: list[str] = []
    objects: list[str] = []
    discourse: dict = {}

    if mode == 'facility' and fac is not None:
        loc_after = str(getattr(fac, 'room_id', '') or location_before or 'cell')
        present = list(getattr(getattr(fac, 'arc', None), 'present_ids', None) or [])
        for cid in present:
            try:
                from puca_dungeon.npc_knowledge import narrator_reference
                people.append(narrator_reference(fac, cid))
            except Exception:
                people.append(str(cid).replace('_', ' '))
        objects = [e.id for e in fac.entities_in_room()]
        arc = getattr(fac, 'arc', None)
        nc = getattr(arc, 'narrative_context', None) or {}
        if isinstance(nc, dict):
            discourse = {
                'active_speaker': nc.get('active_speaker') or '',
                'active_addressee': nc.get('active_addressee') or '',
                'current_request': nc.get('current_request') or nc.get('open_ask') or '',
                'current_topic': nc.get('current_topic') or '',
                'recent_referents': dict(nc.get('recent_referents') or {}),
            }
            if nc.get('principal_actors'):
                people = list(nc.get('principal_actors') or people)
    elif mode == 'book_dungeon':
        loc_after = f'passage:{getattr(world, "passage_id", "")}'
        objects = list(getattr(world, 'visible_entities', None) or [])

    enactment = str(getattr(resolution, 'enactment', 'direct') or 'direct')
    cause = str(getattr(resolution, 'enactment_cause', '') or '')
    wanted = _diegetic_action(getattr(resolution, 'wanted_action', None))
    actual = _diegetic_action(getattr(resolution, 'actual_action', None))
    contrast = {}
    if enactment != 'direct':
        contrast = {
            'kind': enactment,
            'note': _CONTRAST_KIND.get(enactment, ''),
            'cause': cause.replace('_', ' ') if cause else '',
        }

    events: list[dict] = []
    order = 1
    for raw in list(getattr(resolution, 'world_events', None) or []) + list(
        getattr(resolution, 'structured_facts', None) or []
    ):
        if not isinstance(raw, dict):
            continue
        et = str(raw.get('type') or '')
        if et in ('enactment',):
            continue
        ev = dict(raw)
        ev.setdefault('order', order)
        if et in ('scene_change',) or raw.get('must_lead'):
            ev['must_narrate'] = True
        if et in ('interview_prompt', 'memory_cue', 'recollection', 'interview_answer'):
            ev.setdefault('physical_location_change', False)
        events.append(ev)
        order += 1

    # Salience
    must: list[str] = []
    should: list[str] = []
    may: list[str] = []
    omit = ['facility_phase', 'stamina', 'skill', 'luck', 'sated', 'quenched', 'hygiene aware']
    if location_before and loc_after and location_before != loc_after:
        must.append(f'Location changed from {location_before} to {loc_after}.')
    for ev in events:
        if ev.get('must_narrate') or ev.get('type') in (
            'scene_change', 'forced_removal', 'arrive_wash', 'slit_opens', 'washed', 'fed',
        ):
            text = str(ev.get('text') or ev.get('type') or '')
            if text:
                must.append(text[:200])
        elif ev.get('type') in ('interview_prompt', 'npc_speech', 'door_escalate'):
            text = str(ev.get('text') or ev.get('understood') or ev.get('type') or '')
            if text:
                should.append(text[:200])

    for se in social_events or []:
        if isinstance(se, dict) and se.get('narrative_line'):
            should.append(str(se['narrative_line'])[:200])

    sensations: list[str] = []
    if mode == 'facility' and fac is not None and (must or should or enactment != 'direct'):
        try:
            from puca_dungeon.enactment import salient_sensations
            sensations = list(salient_sensations(fac.pressures)[:2])
        except Exception:
            pass

    beats = []
    for f in list(getattr(resolution, 'facts', None) or [])[:4]:
        if isinstance(f, str) and f.strip() and not f.startswith('They are still waiting:'):
            beats.append(f.strip()[:200])

    from puca_dungeon.social_meaning import social_projection_for_narrator
    sanitised_social = social_projection_for_narrator(social_events or [])
    sanitised_moves = []
    for m in conversational_moves or []:
        if isinstance(m, dict):
            surface = {k: m[k] for k in ('who', 'appears_to_want', 'manner') if m.get(k)}
            if surface:
                sanitised_moves.append(surface)

    turn_id = str(getattr(world, 'turn_index', '') or '')
    nev = NarrativeEvent(
        turn_id=turn_id,
        reality=mode,
        location_before=location_before or loc_after,
        location_after=loc_after,
        player_attempt=wanted,
        actual_outcome=actual,
        contrast=contrast,
        events=events,
        current_scene={
            'location': loc_after,
            'people': people,
            'visible_objects': objects,
        },
        discourse=discourse,
        sensations=sensations,
        social_meaning=sanitised_social,
        conversational_moves=sanitised_moves,
        salience={
            'must_render': must[:6],
            'should_render': should[:6],
            'may_render': may,
            'omit': omit,
        },
        ordered_beats=beats[:5],
    )
    # Stash on resolution for narrator/session
    try:
        resolution.narrative_event = nev.to_dict()
    except Exception:
        pass
    return nev
