"""Build a PortraitCue from world state. Read-only; never mutates the world."""
from __future__ import annotations

from typing import Any, Optional

from puca_dungeon.portrait.assignments import visual_profile_id
from puca_dungeon.portrait.types import (
    BrowState,
    EyeState,
    FacePose,
    MouthState,
    PortraitCue,
)

# Small emotion → pose map. Unknown emotions fall back to neutral.
_EMOTION_POSES: dict[str, dict[str, Any]] = {
    'neutral': {},
    'calm': {},
    'anxious': {
        'eye_openness': EyeState.SLIGHTLY_NARROW,
        'left_brow': BrowState.CONCERNED,
        'right_brow': BrowState.CONCERNED,
        'mouth': MouthState.UNEASY,
    },
    'fear': {
        'eye_openness': EyeState.WIDE,
        'left_brow': BrowState.RAISED,
        'right_brow': BrowState.RAISED,
        'mouth': MouthState.PARTED,
    },
    'angry': {
        'eye_openness': EyeState.NARROW,
        'left_brow': BrowState.KNIT,
        'right_brow': BrowState.KNIT,
        'mouth': MouthState.FROWN,
    },
    'happy': {
        'mouth': MouthState.SMALL_SMILE,
    },
    'sad': {
        'left_brow': BrowState.CONCERNED,
        'right_brow': BrowState.CONCERNED,
        'mouth': MouthState.FROWN,
    },
    'guarded': {
        'eye_openness': EyeState.SLIGHTLY_NARROW,
        'mouth': MouthState.PRESSED,
    },
    'uneasy': {
        'mouth': MouthState.UNEASY,
        'left_brow': BrowState.CONCERNED,
        'right_brow': BrowState.NEUTRAL,
    },
}


_FOCUS_PRIORITY = (
    'senior_researcher',
    'iven',
    'nessa',
    'ruan',
    'orderly_anxious',
)


def pose_from_emotion(emotion: str) -> FacePose:
    key = str(emotion or 'neutral').strip().lower()
    spec = _EMOTION_POSES.get(key) or {}
    return FacePose.coerce(spec)


def _interlocutor_id(world) -> str:
    fac = getattr(world, 'facility', None)
    if fac is None:
        return ''
    try:
        from puca_dungeon.conversation import get_conversation
        conv = get_conversation(fac)
    except Exception:
        conv = dict(getattr(getattr(fac, 'arc', None), 'conversation', None) or {})
    return str(conv.get('interlocutor_id') or '').strip()


def _present_ids(world) -> list[str]:
    fac = getattr(world, 'facility', None)
    if fac is None:
        return []
    return [str(cid) for cid in (getattr(getattr(fac, 'arc', None), 'present_ids', None) or [])]


def _character_emotion(world, character_id: str) -> str:
    fac = getattr(world, 'facility', None)
    if fac is None or not character_id:
        return 'neutral'
    cast = getattr(fac, 'cast', None) or {}
    raw = cast.get(character_id) if isinstance(cast, dict) else None
    if isinstance(raw, dict):
        return str(raw.get('emotion') or 'neutral')
    return str(getattr(raw, 'emotion', None) or 'neutral')


def portrait_cue_from_world(world, *, assignments_path: Optional[str] = None) -> PortraitCue:
    """Visible when conversation is active and a present person has a face package.

    Prefer the interlocutor. If they have no profile (e.g. the quiet orderly),
    frame another present character who does — the camera follows the talk,
    not only the exact speaker id.
    """
    present = _present_ids(world)
    cid = _interlocutor_id(world)
    reason = 'dialogue'
    if cid and cid not in present:
        return PortraitCue(character_id=cid, focus_reason='absent')
    profile = visual_profile_id(cid, assignments_path) if cid else ''
    if not profile:
        if not cid:
            return PortraitCue()
        for other in _FOCUS_PRIORITY:
            if other == cid or other not in present:
                continue
            profile = visual_profile_id(other, assignments_path)
            if profile:
                cid = other
                reason = 'dialogue_group'
                break
        if not profile:
            return PortraitCue(character_id=cid, focus_reason='no_profile')
    pose = pose_from_emotion(_character_emotion(world, cid))
    return PortraitCue(
        character_id=cid,
        visual_profile_id=profile,
        visible=True,
        pose=pose,
        focus_reason=reason,
    )
