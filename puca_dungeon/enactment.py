"""Intention vs enactment: four outcomes grounded in Python causes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

ENACTMENT_DIRECT = 'direct'
ENACTMENT_COMPROMISED = 'compromised'
ENACTMENT_ABORTED = 'aborted'
ENACTMENT_INVERTED = 'inverted'

VALID_ENACTMENTS = frozenset({
    ENACTMENT_DIRECT,
    ENACTMENT_COMPROMISED,
    ENACTMENT_ABORTED,
    ENACTMENT_INVERTED,
})


@dataclass
class BodyPressures:
    """Hidden meters — narrator sees qualitative summaries only."""
    fatigue: int = 20          # 0–100
    hunger: int = 25
    thirst: int = 20
    hygiene_discomfort: int = 35
    fear: int = 15
    pain: int = 0
    language_ability: int = 15  # 0–100; low = broken speech
    physical_restraint: int = 0  # 0–100; staff holding / bound

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'BodyPressures':
        data = data or {}
        return cls(
            fatigue=_clamp(int(data.get('fatigue', 20) or 20)),
            hunger=_clamp(int(data.get('hunger', 25) or 25)),
            thirst=_clamp(int(data.get('thirst', 20) or 20)),
            hygiene_discomfort=_clamp(int(data.get('hygiene_discomfort', 35) or 35)),
            fear=_clamp(int(data.get('fear', 15) or 15)),
            pain=_clamp(int(data.get('pain', 0) or 0)),
            language_ability=_clamp(int(data.get('language_ability', 15) or 15)),
            physical_restraint=_clamp(int(data.get('physical_restraint', 0) or 0)),
        )


def _clamp(n: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, n))


def qualitative_pressures(p: BodyPressures) -> dict:
    def band(v: int, low: str, mid: str, high: str, extreme: str) -> str:
        if v >= 85:
            return extreme
        if v >= 60:
            return high
        if v >= 35:
            return mid
        return low

    return {
        'fatigue': band(p.fatigue, 'alert', 'tired', 'exhausted', 'collapsing'),
        'hunger': band(p.hunger, 'sated', 'peckish', 'hungry', 'ravenous'),
        'thirst': band(p.thirst, 'quenched', 'dry', 'thirsty', 'parched'),
        'hygiene': band(p.hygiene_discomfort, 'clean', 'aware', 'filthy', 'repellent'),
        'fear': band(p.fear, 'calm', 'uneasy', 'afraid', 'terrified'),
        'pain': band(p.pain, 'none', 'aching', 'hurting', 'agony'),
        'speech': (
            'fluent' if p.language_ability >= 70
            else 'limited' if p.language_ability >= 35
            else 'broken' if p.language_ability >= 10
            else 'almost_none'
        ),
        'restrained': p.physical_restraint >= 40,
    }


def salient_sensations(p: BodyPressures) -> list[str]:
    """Narrative-grade bodily evidence — only non-baseline pressures.

    Never emit machine labels like sated/quenched/alert for the narrator to copy.
    """
    out: list[str] = []
    if p.fatigue >= 60:
        out.append('Your limbs feel heavy; staying upright takes work.')
    elif p.fatigue >= 35:
        out.append('A dull tiredness sits behind your eyes.')
    if p.hunger >= 60:
        out.append('Hunger sharpens every smell of food.')
    elif p.hunger >= 35:
        out.append('Your stomach complains quietly.')
    if p.thirst >= 60:
        out.append('Your mouth tastes dry and sticky.')
    elif p.thirst >= 35:
        out.append('Your tongue wants water.')
    if p.hygiene_discomfort >= 55:
        out.append('Your own smell is hard to ignore.')
    elif p.hygiene_discomfort >= 35:
        out.append('Skin feels unclean enough to notice.')
    if p.fear >= 60:
        out.append('Fear keeps your shoulders tight.')
    elif p.fear >= 35:
        out.append('Unease sits under the ribs.')
    if p.pain >= 35:
        out.append('Pain pulls at your attention.')
    if p.physical_restraint >= 40:
        out.append('Hands or bindings limit what you can move.')
    if p.language_ability < 40:
        out.append('Words come out thin and broken.')
    return out


def wanted_action_from_intent(intent: Any) -> dict:
    if intent is None:
        return {}
    if isinstance(intent, dict):
        data = intent
    else:
        data = intent.to_dict() if hasattr(intent, 'to_dict') else {}
    return {
        'action_class': data.get('action_class'),
        'target': data.get('target'),
        'tool': data.get('tool'),
        'method': data.get('method'),
        'intended_effect': data.get('intended_effect'),
        'manner': data.get('manner'),
        'destination': data.get('destination'),
        'utterance': data.get('utterance'),
        'classification': data.get('classification'),
    }


def decide_enactment(
    *,
    pressures: BodyPressures,
    action_class: str,
    manner: Optional[str] = None,
    classification: Optional[str] = None,
    feasible: bool = True,
    world_blocked: bool = False,
    institutional_force: bool = False,
    rng=None,
) -> tuple[str, str, dict]:
    """Return (enactment, cause, actual_action_patch).

    Never uses inverted/aborted merely to hide missing content — caller must
    pass world_blocked=True for absent/impossible affordances (stays honest failure).
    """
    ac = (action_class or '').lower()
    manner_l = (manner or '').lower()
    violent = any(w in ac or w in manner_l for w in (
        'attack', 'hit', 'punch', 'strike', 'kill', 'violence', 'violent', 'fight',
    ))
    flee = any(w in ac or w in manner_l for w in ('run', 'flee', 'escape', 'sprint'))
    shout = any(w in ac or w in manner_l for w in ('shout', 'scream', 'yell', 'threaten'))
    speak = classification == 'SOCIAL_ACTION' or any(
        w in ac for w in ('talk', 'speak', 'ask', 'say', 'tell', 'apologis', 'threat')
    )
    refuse_body = any(w in ac for w in ('refuse', 'resist', 'struggle'))

    actual: dict = {
        'action_class': action_class,
        'performed': True,
        'modifier': None,
    }

    if world_blocked or not feasible:
        actual['performed'] = False
        actual['modifier'] = 'world_blocked'
        return ENACTMENT_DIRECT, 'world_constraint', actual

    # Restraint / institutional control
    if pressures.physical_restraint >= 55 and (violent or flee or refuse_body):
        actual['performed'] = False
        actual['modifier'] = 'physically_held'
        return ENACTMENT_ABORTED, 'physical_restraint', actual

    if institutional_force and (flee or violent):
        actual['performed'] = False
        actual['modifier'] = 'overpowered'
        return ENACTMENT_ABORTED, 'external_threat', actual

    # Extreme fear + violence → rare inversion toward apology/freeze
    if violent and pressures.fear >= 75 and pressures.physical_restraint >= 20:
        roll = rng.randint(1, 100) if rng is not None else 50
        if roll <= 35:  # still rare overall; gated by extreme state
            actual['action_class'] = 'apologise'
            actual['performed'] = True
            actual['modifier'] = 'self_betraying'
            return ENACTMENT_INVERTED, 'fear', actual
        actual['performed'] = False
        actual['modifier'] = 'froze'
        return ENACTMENT_ABORTED, 'fear', actual

    if violent and pressures.fear >= 55:
        actual['performed'] = False
        actual['modifier'] = 'could_not_follow_through'
        return ENACTMENT_ABORTED, 'fear', actual

    if flee and pressures.fatigue >= 80:
        actual['modifier'] = 'stagger'
        return ENACTMENT_COMPROMISED, 'fatigue', actual

    if flee and pressures.physical_restraint >= 30:
        actual['performed'] = False
        actual['modifier'] = 'held_back'
        return ENACTMENT_ABORTED, 'physical_restraint', actual

    if shout and pressures.fatigue >= 60:
        actual['modifier'] = 'weak_voice'
        return ENACTMENT_COMPROMISED, 'fatigue', actual

    if speak and pressures.language_ability < 40:
        actual['modifier'] = 'broken_speech'
        return ENACTMENT_COMPROMISED, 'language', actual

    # Extreme hunger can compromise food refusal
    if refuse_body and 'food' in (manner_l + ac) and pressures.hunger >= 85:
        actual['action_class'] = 'eat'
        actual['modifier'] = 'body_overrode_refusal'
        return ENACTMENT_COMPROMISED, 'hunger', actual

    if pressures.fatigue >= 95 and ac in (
        'wait', 'stay_awake', 'resist_sleep', 'fight_sleep', 'remain_awake', 'keep_awake',
    ):
        actual['action_class'] = 'sleep'
        actual['modifier'] = 'involuntary_sleep'
        return ENACTMENT_INVERTED, 'fatigue', actual

    if pressures.pain >= 70 and violent:
        actual['modifier'] = 'pain_weakened'
        return ENACTMENT_COMPROMISED, 'pain', actual

    return ENACTMENT_DIRECT, '', actual


def truncate_speech(utterance: str, language_ability: int) -> str:
    """Reduce intended speech to what the character can actually say."""
    text = (utterance or '').strip()
    if not text:
        return ''
    if language_ability >= 70:
        return text
    words = text.replace('?', ' ?').replace('!', ' !').split()
    if language_ability >= 35:
        keep = max(1, min(len(words), 4))
        out = ' '.join(words[:keep])
        return out if out.endswith(('?', '!')) else out + ('?' if '?' in text else '')
    if language_ability >= 10:
        # One content word
        for w in words:
            core = w.strip('.,!?').lower()
            if core in {'who', 'why', 'what', 'where', 'no', 'yes', 'help', 'please', 'sorry', 'back', 'away'}:
                return core.capitalize() + ('?' if '?' in text or core in {'who', 'why', 'what', 'where'} else '')
        return (words[0].strip('.,!?').capitalize() + '?') if words else '…'
    return '…'


def advance_pressures_for_time(p: BodyPressures, seconds: int) -> BodyPressures:
    """Slow bodily drift with fictional time."""
    minutes = max(0, seconds) / 60.0
    p.fatigue = _clamp(p.fatigue + int(minutes * 1.5))
    p.hunger = _clamp(p.hunger + int(minutes * 1.2))
    p.thirst = _clamp(p.thirst + int(minutes * 1.0))
    p.hygiene_discomfort = _clamp(p.hygiene_discomfort + int(minutes * 0.4))
    return p
