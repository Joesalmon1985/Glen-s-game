"""Diegetic scene/narrative context for the narrator — Python-owned, no engine labels."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from puca_dungeon.facility_models import (
    PHASE_CELL_IDLE,
    PHASE_CONTRACT,
    PHASE_DAY2_WAKE,
    PHASE_DOOR,
    PHASE_EXPLANATION,
    PHASE_FOOD,
    PHASE_HEAVEN,
    PHASE_HELL,
    PHASE_INTERVIEW,
    PHASE_REMOVAL,
    PHASE_RESEARCH,
    PHASE_RETRIEVAL,
    PHASE_RETURN,
    PHASE_SECOND_OFFER,
    PHASE_SLEEP,
    PHASE_SLIT,
    PHASE_WASH,
)

# Map facility phase → diegetic scene identity (never emit phase ids to prose)
_SCENE_BY_PHASE: dict[str, dict[str, str]] = {
    PHASE_CELL_IDLE: {
        'label': 'cell waking',
        'began': 'You woke alone in a locked cell.',
        'situation': 'Alone in a small locked room with ordinary objects and no staff.',
        'tension': 'Nothing is being asked of you yet.',
    },
    PHASE_SLIT: {
        'label': 'slit confrontation',
        'began': 'The observation slit opened; someone outside wants distance from the door.',
        'situation': 'Someone beyond the slit is gesturing and repeating a meaning: back / away.',
        'tension': 'They want you away from the door before they will do more.',
    },
    PHASE_DOOR: {
        'label': 'cell-door confrontation',
        'began': 'Door procedure started; they will not enter while you block safe entry.',
        'situation': 'Staff are preparing to enter. They expect you clear of the door.',
        'tension': 'Staff intend to enter; you may be blocking safe entry.',
    },
    PHASE_REMOVAL: {
        'label': 'forced escort',
        'began': 'They opened the door under their rules and took hold of you.',
        'situation': 'You are being moved through the corridor under restraint.',
        'tension': 'They are taking you somewhere; resistance changes little.',
    },
    PHASE_WASH: {
        'label': 'washroom procedure',
        'began': 'They brought you into a washroom and mean to wash you.',
        'situation': 'Staff treat washing as routine procedure, not punishment.',
        'tension': 'They intend to wash you whether you cooperate or not.',
    },
    PHASE_FOOD: {
        'label': 'meal',
        'began': 'Food was placed in front of you.',
        'situation': 'A meal is present; staff expect you to eat or at least leave it alone.',
        'tension': 'Hunger and the institution both press toward eating.',
    },
    PHASE_RETURN: {
        'label': 'return to cell',
        'began': 'They returned you to the cell after the procedures.',
        'situation': 'Back in the cell; the day is winding toward sleep.',
        'tension': 'Fatigue is rising; the institution expects rest.',
    },
    PHASE_SLEEP: {
        'label': 'sleep',
        'began': 'Sleep took you, or nearly did.',
        'situation': 'The cell and the bed dominate; waking will bring a new day.',
        'tension': 'Sleep is hard to refuse.',
    },
    PHASE_DAY2_WAKE: {
        'label': 'second-day wake',
        'began': 'You woke again in the same cell on a new day.',
        'situation': 'Same cell, new day; formal collection is coming.',
        'tension': 'The institution will collect you more formally.',
    },
    PHASE_RETRIEVAL: {
        'label': 'formal retrieval',
        'began': 'Staff arrived to collect you for interview.',
        'situation': 'You are being escorted toward questioning.',
        'tension': 'They expect compliance with the escort.',
    },
    PHASE_INTERVIEW: {
        'label': 'interview',
        'began': 'Questions began in an interview room.',
        'situation': 'Staff are asking personal questions and recording answers.',
        'tension': 'They want answers; silence or speech both count as behaviour.',
    },
    PHASE_EXPLANATION: {
        'label': 'explanation',
        'began': 'Someone began explaining the programme in institutional terms.',
        'situation': 'An official explanation is underway.',
        'tension': 'They want you to understand enough to decide.',
    },
    PHASE_CONTRACT: {
        'label': 'contract offer',
        'began': 'They offered a five-year research agreement.',
        'situation': 'A bureaucratic contract is on the table: service now, Heaven later.',
        'tension': 'They are waiting for agreement or refusal.',
    },
    PHASE_HEAVEN: {
        'label': 'Heaven',
        'began': 'You were moved into the place they call Heaven.',
        'situation': 'Warmth, supply, and attendants — on a clock you do not control.',
        'tension': 'Time here is limited.',
    },
    PHASE_HELL: {
        'label': 'Hell',
        'began': 'You were moved into the place they call Hell.',
        'situation': 'A place made to be endured.',
        'tension': 'Endurance is the point.',
    },
    PHASE_SECOND_OFFER: {
        'label': 'second contract offer',
        'began': 'The five-year agreement was offered again after Hell.',
        'situation': 'A clean professional asks whether you will reconsider.',
        'tension': 'They are waiting for agreement or continued refusal.',
    },
    PHASE_RESEARCH: {
        'label': 'research registration',
        'began': 'You were registered as a research subject.',
        'situation': 'Subject quarters; the next work has not begun.',
        'tension': 'You are inside the programme now.',
    },
}

_ROLE_PRESENTATION_FALLBACK = {
    'orderly_quiet': 'a large, silent staff member',
    'orderly_anxious': 'a younger, tense staff member',
    'senior_researcher': 'a controlled professional',
    'attendant_a': 'a quiet attendant',
    'attendant_b': 'a quiet attendant',
    'iven': 'another subject named Iven',
    'nessa': 'another subject named Nessa',
    'ruan': 'another subject named Ruan',
}

_GOALS_BY_PHASE: dict[str, str] = {
    PHASE_SLIT: 'get the subject to move back from the door using gesture and short sounds',
    PHASE_DOOR: 'clear the door so staff can enter safely',
    PHASE_REMOVAL: 'move the subject through the corridor under control',
    PHASE_WASH: 'wash the subject as routine hygiene procedure',
    PHASE_FOOD: 'see that the subject is fed',
    PHASE_RETURN: 'return the subject to the cell and leave them to rest',
    PHASE_RETRIEVAL: 'escort the subject to interview',
    PHASE_INTERVIEW: 'obtain answers to scheduled questions',
    PHASE_CONTRACT: 'obtain agreement to the research service',
    PHASE_SECOND_OFFER: 'obtain agreement after Hell',
    PHASE_EXPLANATION: 'explain enough for a decision',
}


@dataclass
class NarrativeSceneContext:
    scene_label: str = 'cell waking'
    began_when: str = 'You woke alone in a locked cell.'
    immediate_situation: str = 'Alone in a small locked room.'
    principal_actors: list[str] = field(default_factory=list)
    characters: list = field(default_factory=list)
    apparent_goals: dict[str, str] = field(default_factory=dict)
    unresolved_tension: str = 'Nothing is being asked of you yet.'
    beats: list[str] = field(default_factory=list)
    what_just_changed: str = ''
    open_ask: str = ''
    room_name: str = 'cell'
    is_new_scene: bool = True

    def to_dict(self) -> dict:
        return {
            'scene_label': self.scene_label,
            'began_when': self.began_when,
            'immediate_situation': self.immediate_situation,
            'principal_actors': list(self.principal_actors),
            'characters': list(self.characters),
            'apparent_goals': dict(self.apparent_goals),
            'unresolved_tension': self.unresolved_tension,
            'beats': list(self.beats),
            'what_just_changed': self.what_just_changed,
            'open_ask': self.open_ask,
            'room_name': self.room_name,
            'is_new_scene': self.is_new_scene,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'NarrativeSceneContext':
        data = data or {}
        return cls(
            scene_label=str(data.get('scene_label') or 'cell waking'),
            began_when=str(data.get('began_when') or ''),
            immediate_situation=str(data.get('immediate_situation') or ''),
            principal_actors=list(data.get('principal_actors') or []),
            characters=list(data.get('characters') or []),
            apparent_goals=dict(data.get('apparent_goals') or {}),
            unresolved_tension=str(data.get('unresolved_tension') or ''),
            beats=list(data.get('beats') or []),
            what_just_changed=str(data.get('what_just_changed') or ''),
            open_ask=str(data.get('open_ask') or ''),
            room_name=str(data.get('room_name') or 'cell'),
            is_new_scene=bool(data.get('is_new_scene', False)),
        )

    def narrator_packet(self) -> dict:
        """Diegetic-only packet for the narrator — no phase ids, no meters."""
        return {
            'scene': self.scene_label,
            'scene_began_when': self.began_when,
            'immediate_situation': self.immediate_situation,
            'where': self.room_name,
            'people_present': list(self.principal_actors),
            'characters': list(self.characters),
            'what_each_appears_to_want': dict(self.apparent_goals),
            'unresolved_immediate_tension': self.unresolved_tension,
            'recent_beats': list(self.beats[-5:]),
            'what_just_changed': self.what_just_changed,
            'open_ask': self.open_ask,
            'this_is_a_new_scene': bool(self.is_new_scene),
        }


def _actor_phrase(facility, cid: str) -> str:
    from puca_dungeon.npc_knowledge import ensure_present_encountered, narrator_reference
    ensure_present_encountered(facility)
    return narrator_reference(facility, cid)


def _goals_for_present(facility, phase: str) -> dict[str, str]:
    present = list(getattr(getattr(facility, 'arc', None), 'present_ids', None) or [])
    base = _GOALS_BY_PHASE.get(phase, '')
    out: dict[str, str] = {}
    for cid in present:
        phrase = _actor_phrase(facility, cid)
        if base:
            out[phrase] = base
        else:
            raw = (getattr(facility, 'cast', None) or {}).get(cid) or {}
            goals = list(raw.get('goals') or [])
            if goals:
                out[phrase] = str(goals[0]).replace('_', ' ')
    return out


def refresh_scene_for_phase(
    facility,
    *,
    new_scene: bool = False,
    what_changed: str = '',
    ask: str = '',
) -> NarrativeSceneContext:
    """Rebuild or continue scene context from authoritative facility state."""
    phase = str(getattr(facility, 'phase', '') or PHASE_CELL_IDLE)
    room = str(getattr(facility, 'room_id', '') or 'cell')
    meta = dict(_SCENE_BY_PHASE.get(phase) or {
        'label': 'facility moment',
        'began': 'The situation shifted.',
        'situation': 'You are somewhere in the facility.',
        'tension': '',
    })
    prev = _read_prev_context(facility)
    same_scene = (
        not new_scene
        and prev.scene_label == meta['label']
        and prev.room_name == room
    )
    present_ids = list(getattr(getattr(facility, 'arc', None), 'present_ids', None) or [])
    actors = [_actor_phrase(facility, cid) for cid in present_ids]
    from puca_dungeon.npc_knowledge import characters_present_packet
    open_ask = ask or str(getattr(getattr(facility, 'arc', None), 'last_ask', '') or '')
    ctx = NarrativeSceneContext(
        scene_label=meta['label'],
        began_when=prev.began_when if same_scene and prev.began_when else meta['began'],
        immediate_situation=meta['situation'],
        principal_actors=actors,
        characters=characters_present_packet(facility),
        apparent_goals=_goals_for_present(facility, phase),
        unresolved_tension=meta['tension'] if not open_ask else f'They are waiting for: {open_ask}.',
        beats=list(prev.beats) if same_scene else [],
        what_just_changed=what_changed,
        open_ask=open_ask,
        room_name=room,
        is_new_scene=not same_scene,
    )
    set_scene_context(facility, ctx)
    return ctx


def _read_prev_context(facility) -> NarrativeSceneContext:
    """Read stored context without refreshing (avoids recursion)."""
    arc = getattr(facility, 'arc', None)
    raw = getattr(arc, 'narrative_context', None) if arc is not None else None
    if isinstance(raw, NarrativeSceneContext):
        return raw
    if isinstance(raw, dict) and raw:
        return NarrativeSceneContext.from_dict(raw)
    return NarrativeSceneContext()


def append_beat(facility, beat: str) -> None:
    beat = (beat or '').strip()
    if not beat:
        return
    ctx = _read_prev_context(facility)
    if not ctx.scene_label:
        ctx = refresh_scene_for_phase(facility, new_scene=False)
    if beat in ctx.beats:
        return
    ctx.beats.append(beat)
    if len(ctx.beats) > 5:
        ctx.beats = ctx.beats[-5:]
    ctx.is_new_scene = False
    set_scene_context(facility, ctx)


def note_change(facility, text: str) -> None:
    text = (text or '').strip()
    if not text:
        return
    ctx = _read_prev_context(facility)
    if not ctx.scene_label:
        ctx = refresh_scene_for_phase(facility, new_scene=False)
    ctx.what_just_changed = text
    set_scene_context(facility, ctx)


def get_scene_context(facility) -> NarrativeSceneContext:
    arc = getattr(facility, 'arc', None)
    raw = getattr(arc, 'narrative_context', None) if arc is not None else None
    if isinstance(raw, NarrativeSceneContext):
        return raw
    if isinstance(raw, dict) and raw:
        return NarrativeSceneContext.from_dict(raw)
    # Empty / missing: create once (refresh stores it)
    return refresh_scene_for_phase(facility, new_scene=True)


_DISCOURSE_KEYS = (
    'active_speaker', 'active_addressee', 'current_request', 'current_topic',
    'recent_referents',
)


def set_scene_context(facility, ctx: NarrativeSceneContext) -> None:
    arc = getattr(facility, 'arc', None)
    if arc is None:
        return
    prev = dict(getattr(arc, 'narrative_context', None) or {})
    merged = ctx.to_dict()
    for key in _DISCOURSE_KEYS:
        if key in prev and key not in merged:
            merged[key] = prev[key]
        elif key in prev and not merged.get(key):
            merged[key] = prev[key]
    arc.narrative_context = merged
    facility.arc = arc


def update_after_turn(facility, resolution, *, scene_flipped: bool = False) -> NarrativeSceneContext:
    """Call after resolve+react: refresh actors/goals and append a beat from facts."""
    ask = str(getattr(getattr(facility, 'arc', None), 'last_ask', '') or '')
    changed = ''
    for ev in list(getattr(resolution, 'world_events', None) or []):
        if isinstance(ev, dict) and ev.get('type') == 'scene_change' and ev.get('text'):
            changed = str(ev['text'])
            scene_flipped = True
            break
    if not changed:
        for ev in list(getattr(resolution, 'world_events', None) or []):
            if isinstance(ev, dict) and ev.get('text') and ev.get('type') in (
                'door_escalate', 'washed', 'fed', 'slit_opens', 'forced_removal',
                'arrive_wash', 'door_procedure',
            ):
                changed = str(ev['text'])
                break
    ctx = refresh_scene_for_phase(
        facility,
        new_scene=scene_flipped,
        what_changed=changed,
        ask=ask,
    )
    facts = [f for f in (resolution.facts or []) if isinstance(f, str) and f.strip()]
    beat_bits = []
    for f in facts[:3]:
        if f.startswith('They are still waiting:'):
            continue
        if f.startswith('Entered passage'):
            continue
        beat_bits.append(f.strip())
    if beat_bits:
        append_beat(facility, ' '.join(beat_bits)[:280])
        ctx = _read_prev_context(facility)
        ctx.what_just_changed = changed or beat_bits[0]
        set_scene_context(facility, ctx)
    return get_scene_context(facility)


def ensure_initial_context(facility) -> NarrativeSceneContext:
    arc = getattr(facility, 'arc', None)
    raw = getattr(arc, 'narrative_context', None) if arc is not None else None
    if isinstance(raw, dict) and raw:
        return NarrativeSceneContext.from_dict(raw)
    if isinstance(raw, NarrativeSceneContext):
        return raw
    return refresh_scene_for_phase(facility, new_scene=True)
