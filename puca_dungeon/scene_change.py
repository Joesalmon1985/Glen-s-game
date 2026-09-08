"""First-class scene transitions the player cannot miss."""
from __future__ import annotations

from typing import Optional

from puca_dungeon.arc_state import situation_for_phase


def emit_scene_change(
    resolution,
    facility,
    *,
    text: str,
    from_room: Optional[str] = None,
    to_room: Optional[str] = None,
    ask: str = '',
    kind: str = 'scene_change',
) -> dict:
    event = {
        'type': 'scene_change',
        'kind': kind,
        'must_lead': True,
        'text': text,
        'from_room': from_room or getattr(facility, 'room_id', ''),
        'to_room': to_room or getattr(facility, 'room_id', ''),
        'ask': ask,
    }
    events = list(getattr(resolution, 'world_events', None) or [])
    events.append(event)
    resolution.world_events = events
    facts = list(resolution.facts or [])
    if text and text not in facts:
        facts.insert(0, text)
    resolution.facts = facts
    sf = list(getattr(resolution, 'structured_facts', None) or [])
    sf.append(event)
    resolution.structured_facts = sf
    resolution.image_dirty = True
    resolution.state_changed = True
    if hasattr(resolution, 'situation_changed'):
        resolution.situation_changed = True
    arc = getattr(facility, 'arc', None)
    if arc is not None:
        if to_room:
            facility.room_id = to_room
        arc.situation_line = situation_for_phase(facility.phase, facility.room_id, ask)
        arc.last_ask = ask
        facility.arc = arc
    try:
        from puca_dungeon.narrative_context import refresh_scene_for_phase
        room_changed = bool(to_room and to_room != (from_room or ''))
        refresh_scene_for_phase(
            facility,
            new_scene=True,
            what_changed=text,
            ask=ask,
        )
        if room_changed:
            pass  # already new_scene
    except Exception:
        pass
    return event


def restated_ask(facility) -> Optional[str]:
    arc = getattr(facility, 'arc', None)
    ask = getattr(arc, 'last_ask', '') if arc is not None else ''
    if ask:
        return f'They are still waiting: {ask}'
    return None
