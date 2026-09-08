"""Validated portrait pose / cue types. No free-text asset paths."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class EyeState(str, Enum):
    OPEN = 'open'
    SLIGHTLY_NARROW = 'slightly_narrow'
    NARROW = 'narrow'
    WIDE = 'wide'
    CLOSED = 'closed'


class Gaze(str, Enum):
    FORWARD = 'forward'
    LEFT = 'left'
    RIGHT = 'right'
    UP = 'up'
    DOWN = 'down'
    AWAY_LEFT = 'away_left'
    AWAY_RIGHT = 'away_right'


class BrowState(str, Enum):
    NEUTRAL = 'neutral'
    RAISED = 'raised'
    LOWERED = 'lowered'
    KNIT = 'knit'
    CONCERNED = 'concerned'
    ASYMMETRIC_RAISE = 'asymmetric_raise'


class MouthState(str, Enum):
    NEUTRAL = 'neutral'
    PRESSED = 'pressed'
    PARTED = 'parted'
    SMALL_SMILE = 'small_smile'
    SMILE = 'smile'
    FROWN = 'frown'
    GRIMACE = 'grimace'
    UNEASY = 'uneasy'


_ENUMS = {
    'eye_openness': EyeState,
    'gaze': Gaze,
    'left_brow': BrowState,
    'right_brow': BrowState,
    'mouth': MouthState,
}

_DEFAULTS = {
    'eye_openness': EyeState.OPEN,
    'gaze': Gaze.FORWARD,
    'left_brow': BrowState.NEUTRAL,
    'right_brow': BrowState.NEUTRAL,
    'mouth': MouthState.NEUTRAL,
}


def _coerce_enum(enum_cls: type[Enum], value: Any, default: Enum) -> Enum:
    if value is None or value == '':
        return default
    if isinstance(value, enum_cls):
        return value
    text = str(value).strip().lower().replace('-', '_').replace(' ', '_')
    for member in enum_cls:
        if member.value == text or member.name.lower() == text:
            return member
    return default


@dataclass(frozen=True)
class FacePose:
    """Temporary presentation state. Do not persist in saves."""

    eye_openness: EyeState = EyeState.OPEN
    gaze: Gaze = Gaze.FORWARD
    left_brow: BrowState = BrowState.NEUTRAL
    right_brow: BrowState = BrowState.NEUTRAL
    mouth: MouthState = MouthState.NEUTRAL
    # Reserved for later overlays; ignored by the current renderer.
    jaw: str = ''
    teeth: str = ''
    blush: str = ''
    tears: str = ''
    sweat: str = ''
    blood: str = ''
    dirt: str = ''
    bruise: str = ''

    @classmethod
    def coerce(cls, raw: Any = None, **kwargs) -> 'FacePose':
        """Build a pose; unknown enum values fall back to documented neutrals."""
        data: dict[str, Any] = {}
        if isinstance(raw, FacePose):
            return raw
        if isinstance(raw, dict):
            data.update(raw)
        data.update(kwargs)
        parsed = {}
        for field_name, enum_cls in _ENUMS.items():
            parsed[field_name] = _coerce_enum(
                enum_cls, data.get(field_name), _DEFAULTS[field_name],
            )
        extra = {}
        for key in ('jaw', 'teeth', 'blush', 'tears', 'sweat', 'blood', 'dirt', 'bruise'):
            extra[key] = str(data.get(key) or '')
        return cls(**parsed, **extra)

    def fingerprint(self) -> str:
        return '|'.join((
            self.eye_openness.value,
            self.gaze.value,
            self.left_brow.value,
            self.right_brow.value,
            self.mouth.value,
        ))

    def to_dict(self) -> dict:
        return {
            'eye_openness': self.eye_openness.value,
            'gaze': self.gaze.value,
            'left_brow': self.left_brow.value,
            'right_brow': self.right_brow.value,
            'mouth': self.mouth.value,
        }


@dataclass(frozen=True)
class FaceIdentity:
    """Stable anatomy keys from a face package. Expression does not mutate these."""

    head: str = ''
    nose: str = ''
    eyes: str = ''
    iris: str = ''
    mouth_base: str = ''
    hair_back: str = ''
    hair_front: str = ''
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class CharacterVisualProfile:
    visual_profile_id: str


@dataclass(frozen=True)
class PortraitCue:
    """Presentation-only. Downstream of world state; never writes it."""

    character_id: str = ''
    visual_profile_id: str = ''
    visible: bool = False
    pose: FacePose = field(default_factory=FacePose)
    focus_reason: str = ''

    def fingerprint(self) -> str:
        if not self.visible or not self.visual_profile_id:
            return ''
        return f'{self.visual_profile_id}:{self.pose.fingerprint()}'

    def to_dict(self) -> dict:
        return {
            'character_id': self.character_id,
            'visual_profile_id': self.visual_profile_id,
            'visible': self.visible,
            'pose': self.pose.to_dict(),
            'focus_reason': self.focus_reason,
        }
