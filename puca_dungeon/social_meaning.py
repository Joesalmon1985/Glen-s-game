"""Bounded social-meaning / reciprocity layer — internal only, never player-facing labels."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Internal forms — never emit these strings to narrator/prose
FORM_PROTECTION = 'protection'
FORM_ASSISTANCE = 'assistance'
FORM_DECEPTION = 'deception'
FORM_BETRAYAL = 'betrayal'
FORM_RECIPROCATION = 'reciprocation'
FORM_CONFIDENCE_KEPT = 'confidence_kept'
FORM_CONFIDENCE_BROKEN = 'confidence_broken'
FORM_WITHHOLD = 'withhold'
FORM_RETALIATION = 'retaliation'
FORM_FORGIVENESS = 'forgiveness'
FORM_COMPLIANCE = 'compliance'
FORM_REFUSAL = 'refusal'


@dataclass
class SocialEvent:
    actor: str
    affected: str
    form: str
    objective_summary: str = ''
    cost: str = 'low'  # low|medium|high
    risk: str = 'low'
    observed_by: list = field(default_factory=list)
    narrative_line: str = ''  # diegetic projection only

    def to_dict(self) -> dict:
        return {
            'actor': self.actor,
            'affected': self.affected,
            'form': self.form,
            'objective_summary': self.objective_summary,
            'cost': self.cost,
            'risk': self.risk,
            'observed_by': list(self.observed_by),
            'narrative_line': self.narrative_line,
        }


def _rel_key(a: str, b: str) -> str:
    return f'{a}->{b}'


def get_expectation(arc_or_cast, actor: str, other: str, key: str, default: float = 0.5) -> float:
    """Directional expectation A->B for honesty/reciprocity/confidentiality/exploitation."""
    store = _expectation_store(arc_or_cast)
    return float(store.get(_rel_key(actor, other), {}).get(key, default))


def _expectation_store(arc) -> dict:
    if arc is None:
        return {}
    if hasattr(arc, 'relationship_expectations'):
        return dict(getattr(arc, 'relationship_expectations', None) or {})
    if isinstance(arc, dict):
        return dict(arc.get('relationship_expectations') or {})
    return {}


def set_expectation(arc, actor: str, other: str, key: str, value: float) -> None:
    if arc is None:
        return
    store = dict(getattr(arc, 'relationship_expectations', None) or {})
    edge = dict(store.get(_rel_key(actor, other)) or {})
    edge[key] = max(0.0, min(1.0, float(value)))
    store[_rel_key(actor, other)] = edge
    arc.relationship_expectations = store


def update_expectation(
    arc,
    actor: str,
    other: str,
    key: str,
    observed: float,
    *,
    learning_rate: float = 0.12,
    salience: float = 1.0,
) -> float:
    old = get_expectation(arc, actor, other, key)
    rate = learning_rate * max(0.05, min(1.0, salience))
    new = old + rate * (observed - old)
    set_expectation(arc, actor, other, key, new)
    return new


def remember_social(cast: dict, cid: str, text: str, *, about: str = 'sarel') -> None:
    if not cid or not text:
        return
    raw = (cast or {}).get(cid)
    if not isinstance(raw, dict):
        return
    from puca_dungeon.characters import CharacterState
    ch = CharacterState.from_dict(raw)
    ch.remember_event({'what': text, 'about': about})
    rel = ch.rel(about)
    rel.remember(text)
    ch.set_rel(about, rel)
    cast[cid] = ch.to_dict()


def classify_social_events(world, resolution, intent=None, player_text: str = '') -> list[dict]:
    """Emit zero-or-more directional social events after physical resolution."""
    fac = getattr(world, 'facility', None)
    if fac is None or str(getattr(world, 'mode', '')) != 'facility':
        return []
    events: list[SocialEvent] = []
    text = (player_text or '').lower()
    present = list(getattr(getattr(fac, 'arc', None), 'present_ids', None) or [])
    sf_types = {
        str(f.get('type'))
        for f in (getattr(resolution, 'structured_facts', None) or [])
        if isinstance(f, dict)
    }
    phase = str(getattr(fac, 'phase', '') or '')

    # Door cooperate / refuse toward staff
    if 'cooperate_door' in sf_types or 'stand_firm' in sf_types:
        staff = present[0] if present else 'orderly_quiet'
        if 'cooperate_door' in sf_types:
            events.append(SocialEvent(
                actor='sarel', affected=staff, form=FORM_COMPLIANCE,
                objective_summary='Sarel gave the door space when asked.',
                observed_by=list(present),
                narrative_line='Sarel moves back when asked; staff treat that as workable obedience.',
            ))
            update_expectation(fac.arc, staff, 'sarel', 'reciprocity', 0.7, salience=0.6)
        else:
            events.append(SocialEvent(
                actor='sarel', affected=staff, form=FORM_REFUSAL,
                objective_summary='Sarel refused to give the door space.',
                cost='medium', risk='medium',
                observed_by=list(present),
                narrative_line='Sarel will not give the door space; staff grow more cautious.',
            ))
            update_expectation(fac.arc, staff, 'sarel', 'reciprocity', 0.25, salience=0.8)

    # Speech toward present NPCs — confidence / deception heuristics (bounded)
    if 'speech' in sf_types or 'npc_speech' in sf_types:
        target = None
        for f in getattr(resolution, 'structured_facts', None) or []:
            if isinstance(f, dict) and f.get('type') == 'speech' and f.get('target'):
                target = str(f.get('target'))
                break
        if not target and present:
            target = present[0]
        if target and target != 'sarel':
            # Trust-test style: revealing low-risk info vs repeating to staff
            if any(w in text for w in ('secret', 'tell them', 'report', 'staff', 'orderly')):
                # Potential betrayal of another subject
                subjects = [c for c in present if c in ('iven', 'nessa', 'ruan')]
                if subjects and target in ('orderly_quiet', 'orderly_anxious', 'senior_researcher'):
                    victim = subjects[0]
                    events.append(SocialEvent(
                        actor='sarel', affected=victim, form=FORM_BETRAYAL,
                        objective_summary=f'Sarel spoke to staff while {victim} was present.',
                        cost='high', risk='high',
                        observed_by=list(present),
                        narrative_line=(
                            f'{fac.character_name(victim)} hears Sarel speak to staff; '
                            'their trust in privacy drops.'
                        ),
                    ))
                    update_expectation(fac.arc, victim, 'sarel', 'confidentiality', 0.2, salience=1.0)
                    remember_social(fac.cast, victim, 'Sarel spoke to staff in front of me.', about='sarel')
            elif any(w in text for w in ('help', 'protect', 'won\'t tell', 'keep quiet', 'secret safe')):
                if target in ('iven', 'nessa', 'ruan'):
                    events.append(SocialEvent(
                        actor='sarel', affected=target, form=FORM_PROTECTION,
                        objective_summary=f'Sarel offered protective confidence toward {target}.',
                        cost='medium',
                        observed_by=list(present),
                        narrative_line=(
                            f'{fac.character_name(target)} takes Sarel\'s protective words seriously enough to watch for proof.'
                        ),
                    ))
                    update_expectation(fac.arc, target, 'sarel', 'confidentiality', 0.65, salience=0.7)
                    remember_social(
                        fac.cast, target,
                        'Sarel offered to keep confidence.',
                        about='sarel',
                    )

    # Wash refuse / cooperate
    if 'washed' in sf_types:
        forced = any(
            isinstance(f, dict) and f.get('type') == 'washed' and f.get('forced')
            for f in (resolution.structured_facts or [])
        )
        staff = [c for c in present if 'orderly' in c or c == 'senior_researcher']
        if staff:
            form = FORM_REFUSAL if forced else FORM_COMPLIANCE
            events.append(SocialEvent(
                actor='sarel', affected=staff[0], form=form,
                objective_summary='Wash procedure completed.',
                observed_by=list(present),
                narrative_line=(
                    'Staff treat the washing as finished routine.'
                    if not forced else
                    'Staff overpower resistance; washing remains routine to them, not punishment.'
                ),
            ))

    # Persist narrative memories for observers
    for ev in events:
        for oid in ev.observed_by:
            if oid in ('iven', 'nessa', 'ruan', 'orderly_quiet', 'orderly_anxious', 'senior_researcher'):
                remember_social(fac.cast, oid, ev.objective_summary or ev.narrative_line, about='sarel')

    # Update discourse referents on arc narrative_context
    _update_discourse(fac, present, resolution)

    return [e.to_dict() for e in events]


def _update_discourse(facility, present: list, resolution) -> None:
    arc = getattr(facility, 'arc', None)
    if arc is None:
        return
    nc = dict(getattr(arc, 'narrative_context', None) or {})
    ask = str(getattr(arc, 'last_ask', '') or '')
    speaker = present[0] if present else ''
    if speaker:
        try:
            name = facility.character_name(speaker)
        except Exception:
            name = speaker
        nc['active_speaker'] = name
        nc['active_addressee'] = 'Sarel'
        nc['recent_referents'] = {
            'him': name,
            'her': name,
            'they': name,
            'them': name,
            'that': ask or 'the current request',
        }
    if ask:
        nc['current_request'] = ask
        nc['current_topic'] = ask
    arc.narrative_context = nc
    facility.arc = arc


def resolve_conversational_move(
    facility,
    speaker_id: str,
    *,
    player_text: str = '',
) -> dict:
    """Python-owned NPC conversational move before any dialogue wording."""
    from puca_dungeon.npc_strategy import choose_move
    return choose_move(facility, speaker_id, player_text=player_text)


def social_projection_for_narrator(social_events: list) -> list[dict]:
    """Sanitised lines only — strip internal form enums from narrator view."""
    out = []
    for ev in social_events or []:
        if not isinstance(ev, dict):
            continue
        line = str(ev.get('narrative_line') or '').strip()
        if not line:
            continue
        out.append({
            'what_matters': line,
            'observable_only': True,
        })
    return out
