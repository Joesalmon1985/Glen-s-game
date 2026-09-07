"""Helpers to read passage hazards and resolve exposure triggers."""
from __future__ import annotations

from typing import Any, Optional, Union

from puca_dungeon.models import Intent, WorldState

PassageLike = Union[dict, Any]
IntentLike = Union[Intent, dict]


def passage_hazards(passage: PassageLike) -> list[dict]:
    """Return hazard dicts from a passage object or mapping."""
    if passage is None:
        return []
    if isinstance(passage, dict):
        raw = passage.get('hazards')
    else:
        raw = getattr(passage, 'hazards', None)
    if not raw:
        return []
    if isinstance(raw, dict):
        return [raw]
    out: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def _intent_get(intent: IntentLike, key: str, default=None):
    if isinstance(intent, dict):
        return intent.get(key, default)
    return getattr(intent, key, default)


def _intent_blob(intent: IntentLike) -> str:
    parts = [
        _intent_get(intent, 'action_class'),
        _intent_get(intent, 'target'),
        _intent_get(intent, 'tool'),
        _intent_get(intent, 'method'),
        _intent_get(intent, 'intended_effect'),
        _intent_get(intent, 'utterance'),
        _intent_get(intent, 'matched_action_id'),
    ]
    return ' '.join(str(p or '') for p in parts).lower()


def _trigger_matches(trigger: Any, intent: IntentLike, idle: bool) -> bool:
    if trigger is None:
        return False
    if isinstance(trigger, str):
        t = trigger.strip().lower()
        if t in ('idle', 'wait', 'time', 'time_sensitive'):
            return idle
        blob = _intent_blob(intent)
        cls = str(_intent_get(intent, 'action_class') or '').upper()
        if t == cls.lower():
            return True
        return t in blob

    if not isinstance(trigger, dict):
        return False

    if trigger.get('time_sensitive') or str(trigger.get('when') or '').lower() in (
        'idle', 'wait', 'time', 'timeout',
    ):
        if idle:
            return True

    cls_need = trigger.get('action_class') or trigger.get('class')
    if cls_need:
        cls = str(_intent_get(intent, 'action_class') or '').upper()
        need = str(cls_need).upper()
        if isinstance(cls_need, (list, tuple, set)):
            allowed = {str(x).upper() for x in cls_need}
            if cls not in allowed:
                return False
        elif cls != need:
            return False

    matched_need = trigger.get('matched_action_id') or trigger.get('action_id')
    if matched_need:
        got = str(_intent_get(intent, 'matched_action_id') or '')
        if got != str(matched_need):
            return False

    target_need = trigger.get('target')
    if target_need:
        got = str(_intent_get(intent, 'target') or '').lower()
        if str(target_need).lower() not in got and got != str(target_need).lower():
            blob = _intent_blob(intent)
            if str(target_need).lower() not in blob:
                return False

    any_of = trigger.get('any_of') or trigger.get('keywords')
    if any_of:
        blob = _intent_blob(intent)
        tokens = [str(x).lower() for x in any_of]
        if not any(tok in blob for tok in tokens):
            return False

    # Empty trigger dict with only exposure metadata should not auto-fire.
    meaningful = any(
        k in trigger for k in (
            'action_class', 'class', 'matched_action_id', 'action_id',
            'target', 'any_of', 'keywords', 'time_sensitive', 'when',
        )
    )
    return meaningful


def _is_idle_intent(intent: IntentLike) -> bool:
    cls = str(_intent_get(intent, 'action_class') or '').upper()
    if cls in ('WAIT', 'REST', 'IDLE', 'LOOK', 'PERCEIVE', 'QUERY'):
        return True
    blob = _intent_blob(intent)
    return any(tok in blob for tok in ('wait', 'linger', 'do nothing', 'stand still'))


def _consequence_facts(hazard: dict, intent: IntentLike) -> list[dict]:
    facts: list[dict] = []
    hid = str(hazard.get('id') or hazard.get('name') or 'hazard')
    consequence = hazard.get('consequence') or hazard.get('effect') or {}
    exposure = hazard.get('exposure') or {}

    facts.append({
        'kind': 'world_event',
        'type': 'hazard_triggered',
        'hazard_id': hid,
        'trigger': hazard.get('trigger'),
    })

    if isinstance(consequence, dict):
        ctype = str(consequence.get('type') or consequence.get('kind') or 'effect')
        fact = {
            'kind': 'world_event',
            'type': 'hazard_consequence',
            'hazard_id': hid,
            'consequence_type': ctype,
        }
        for key in ('site', 'severity', 'outcome', 'status', 'direction'):
            if consequence.get(key) is not None:
                fact[key] = consequence[key]
        # Never copy score-named fields into player-facing structured facts.
        facts.append(fact)
        if ctype in ('wound', 'injury', 'harm') or consequence.get('site'):
            facts.append({
                'kind': 'body_event',
                'type': 'wound',
                'site': consequence.get('site') or 'torso',
                'severity': consequence.get('severity') or 'moderate',
                'source': hid,
                'pain': consequence.get('pain') or consequence.get('severity') or 'moderate',
                'bleeding': consequence.get('bleeding') or 'light',
            })
    elif consequence:
        facts.append({
            'kind': 'world_event',
            'type': 'hazard_consequence',
            'hazard_id': hid,
            'consequence_type': str(consequence),
        })

    if isinstance(exposure, dict) and exposure:
        facts.append({
            'kind': 'world_event',
            'type': 'exposure_change',
            'hazard_id': hid,
            'level': exposure.get('level') or exposure.get('amount'),
            'pressure': exposure.get('pressure') or exposure.get('kind'),
        })

    return facts


def resolve_hazard_triggers(
    world: WorldState,
    passage: PassageLike,
    intent: IntentLike,
    *,
    time_advanced: bool = True,
) -> list[dict]:
    """If player action matches a hazard trigger (or time-sensitive idle), return facts."""
    hazards = passage_hazards(passage)
    if not hazards:
        return []

    idle = _is_idle_intent(intent) and bool(time_advanced)
    triggered: list[dict] = []
    aftermath = dict(world.aftermath or {})

    for hazard in hazards:
        trigger = hazard.get('trigger')
        time_sensitive = bool(
            hazard.get('time_sensitive')
            or (isinstance(trigger, dict) and trigger.get('time_sensitive'))
        )
        matched = _trigger_matches(trigger, intent, idle=idle and time_sensitive)
        if not matched and time_sensitive and idle:
            matched = True
        if not matched:
            continue

        hid = str(hazard.get('id') or hazard.get('name') or 'hazard')
        already = aftermath.get('triggered_hazards') or []
        if hazard.get('once') and hid in already:
            continue

        facts = _consequence_facts(hazard, intent)
        triggered.extend(facts)

        fired = list(already)
        if hid not in fired:
            fired.append(hid)
        aftermath['triggered_hazards'] = fired
        if hazard.get('aftermath'):
            if isinstance(hazard['aftermath'], dict):
                aftermath.update(hazard['aftermath'])
            else:
                aftermath[hid] = hazard['aftermath']

    if aftermath != (world.aftermath or {}):
        world.aftermath = aftermath

    return triggered


def active_hazard_cues(passage: PassageLike) -> list[str]:
    """Player-perceptible warning cues only (no resolution text)."""
    cues: list[str] = []
    for hazard in passage_hazards(passage):
        raw = hazard.get('cues') or hazard.get('warning_cues') or hazard.get('warnings') or []
        if isinstance(raw, str):
            cues.append(raw)
            continue
        for cue in raw:
            if cue:
                cues.append(str(cue))
    return cues
