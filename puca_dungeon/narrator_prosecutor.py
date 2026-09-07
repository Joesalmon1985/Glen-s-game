"""Deterministic prosecutor: flag narrator claims that invent or contradict state."""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional


SUPPORTED = 'SUPPORTED'
ALLOWED_INFERENCE = 'ALLOWED_INFERENCE'
UNSUPPORTED = 'UNSUPPORTED'
CONTRADICTS_STATE = 'CONTRADICTS_STATE'

_ENTITY_PATTERNS = (
    ('tank', re.compile(r'\b(?:tank|tanks)\b', re.I)),
    ('helicopter', re.compile(r'\b(?:helicopter|chopper|heli)\b', re.I)),
    ('dragon', re.compile(r'\b(?:dragon|dragons)\b', re.I)),
    ('forest', re.compile(r'\b(?:forest|woods|woodland)\b', re.I)),
    ('portal', re.compile(r'\b(?:portal|teleport(?:ation|ed|ing)?|warp)\b', re.I)),
)

_MOVEMENT_CLAIM = re.compile(
    r'\b(?:you\s+(?:leave|press\s+on|walk|head|continue|arrive|enter)|'
    r'passage\s+widens|junction|go\s+(?:north|south|east|west))\b',
    re.I,
)

_STAMINA_NUM = re.compile(
    r'\b(?:stamina|skill|luck)\s*(?:is|=|:)?\s*(\d+)\b'
    r'|\b(\d+)\s+(?:stamina|skill|luck)\b'
    r'|\blose\s+(\d+)\s+stamina\b',
    re.I,
)

_ENGINE_LEAK = re.compile(
    r'\b(?:structured\s+state|facility\s+phase|debug_metrics|'
    r'sated|quenched|hygiene\s+aware|adventure\s+sheet|'
    r'wanted_action|actual_action|enactment|direct\s+action)\b',
    re.I,
)

_INTENTION_META = re.compile(
    r'despite\s+your\s+intention|'
    r'despite\s+your\s+(?:desire|want)|'
    r'\byou\s+mean(?:t)?\s+to\b|'
    r'words\s+you\s+meant\s+to\b|'
    r'unvoiced\s+desire|'
    r'contrast\s+to\s+your\s+desires|'
    r'align(?:s|ed)?\s+with\s+(?:your\s+)?desire',
    re.I,
)

_WASHED_FACT = re.compile(
    r'\b(?:wash(?:ed|ing)?|the\s+washing\s+happens|water\s+leaves)\b',
    re.I,
)
_WASH_NEGATION = re.compile(
    r'\b(?:water\s+remains?\s+untouched|remain(?:s|ed)?\s+untouched|'
    r'resist(?:s|ed)?\s+the\s+basin|do\s+not\s+wash|don\'?t\s+wash|'
    r'water\s+untouched)\b',
    re.I,
)

_PROP_SPLIT = re.compile(r'(?<=[.!?])\s+|\n+')


def extract_propositions_heuristic(prose: str) -> list[str]:
    """Split prose into simple claim-ish strings (sentences + entity mentions)."""
    text = (prose or '').strip()
    if not text:
        return []
    props: list[str] = []
    seen: set[str] = set()

    def _add(p: str) -> None:
        p = re.sub(r'\s+', ' ', (p or '').strip())
        if not p or p.lower() in seen:
            return
        seen.add(p.lower())
        props.append(p)

    for sent in _PROP_SPLIT.split(text):
        _add(sent)

    lower = text.lower()
    for name, pat in _ENTITY_PATTERNS:
        if pat.search(lower):
            _add(f'entity_mention:{name}')

    if _MOVEMENT_CLAIM.search(text):
        _add('movement_claim')

    for m in _STAMINA_NUM.finditer(text):
        _add(f'meter_number:{m.group(0)}')

    return props


def _fact_blob(structured_facts: Iterable) -> str:
    parts: list[str] = []
    for f in structured_facts or []:
        if isinstance(f, dict):
            parts.append(' '.join(str(v) for v in f.values()))
        else:
            parts.append(str(f))
    return ' '.join(parts).lower()


def _world_visible_blob(world_visible: Any) -> str:
    if world_visible is None:
        return ''
    if isinstance(world_visible, dict):
        bits = []
        for key in ('entities', 'visible_entities', 'hazards', 'passage_text', 'text', 'image_seed'):
            val = world_visible.get(key)
            if isinstance(val, (list, tuple)):
                bits.extend(str(x) for x in val)
            elif val:
                bits.append(str(val))
        return ' '.join(bits).lower()
    if hasattr(world_visible, 'entities'):
        ents = getattr(world_visible, 'entities', None) or []
        text = getattr(world_visible, 'text', '') or ''
        seed = getattr(world_visible, 'image_seed', '') or ''
        return f"{' '.join(str(e) for e in ents)} {text} {seed}".lower()
    return str(world_visible).lower()


def _sheet_meters(structured_facts: list, world: Any) -> dict[str, Optional[int]]:
    meters: dict[str, Optional[int]] = {'stamina': None, 'skill': None, 'luck': None}
    sheet = None
    if world is not None and hasattr(world, 'sheet'):
        sheet = world.sheet
    elif isinstance(world, dict):
        sheet = world.get('sheet')
    if sheet is not None:
        for key in meters:
            if isinstance(sheet, dict):
                meters[key] = sheet.get(key)
            else:
                meters[key] = getattr(sheet, key, None)
    for f in structured_facts or []:
        if not isinstance(f, dict):
            continue
        for key in meters:
            if key in f and f[key] is not None:
                try:
                    meters[key] = int(f[key])
                except (TypeError, ValueError):
                    pass
    return meters


def classify_proposition(
    prop: str,
    structured_facts: list | None = None,
    world_visible: Any = None,
) -> str:
    """Classify a single proposition against structured facts / visible world."""
    p = (prop or '').strip()
    if not p:
        return ALLOWED_INFERENCE

    facts = list(structured_facts or [])
    fact_blob = _fact_blob(facts)
    visible = _world_visible_blob(world_visible)
    combined = f'{fact_blob} {visible}'
    pl = p.lower()

    # Entity invention
    for name, _pat in _ENTITY_PATTERNS:
        mention = f'entity_mention:{name}'
        if pl == mention or (name in pl and 'entity_mention' in pl):
            if name in combined or name.replace('_', ' ') in combined:
                return SUPPORTED
            # Allowed if facts explicitly say entity_absent for that name
            if f'entity_absent' in fact_blob and name in fact_blob:
                return SUPPORTED
            if any(
                isinstance(f, dict)
                and f.get('type') == 'entity_absent'
                and name in str(f.get('entity') or '').lower()
                for f in facts
            ):
                return SUPPORTED
            # Bare "there is no X" style absence is handled as supported via facts;
            # invented presence without absence fact is unsupported.
            return UNSUPPORTED
        if re.search(rf'\b{re.escape(name)}\b', pl) and name not in combined:
            # Positive claim in a sentence (not "no tank")
            if re.search(rf'\b(?:no|not|neither|without)\b[^.]*\b{re.escape(name)}\b', pl):
                return ALLOWED_INFERENCE
            if any(
                isinstance(f, dict)
                and f.get('type') == 'entity_absent'
                and name in str(f.get('entity') or '').lower()
                for f in facts
            ):
                # Narrator may restate absence
                if re.search(rf'\b(?:no|not|absent|isn\'t|is not)\b', pl):
                    return SUPPORTED
                return CONTRADICTS_STATE
            return UNSUPPORTED

    if pl == 'movement_claim':
        # Passage change must be in facts
        if 'entered passage' in fact_blob or 'passage_entered' in fact_blob:
            return SUPPORTED
        if any(
            isinstance(f, dict) and f.get('type') in ('passage_change', 'entered_passage')
            for f in facts
        ):
            return SUPPORTED
        return CONTRADICTS_STATE

    if pl.startswith('meter_number:'):
        return CONTRADICTS_STATE  # meters must not appear in player-facing prose

    # Generic: if proposition text largely restates a fact string, supported
    for f in facts:
        if isinstance(f, str) and f.lower() in pl or (isinstance(f, str) and pl in f.lower()):
            return SUPPORTED
        if isinstance(f, dict):
            for v in f.values():
                if isinstance(v, str) and len(v) > 8 and v.lower() in pl:
                    return SUPPORTED

    # Atmospheric restatement of visible passage text
    if visible and len(pl) > 20:
        tokens = [t for t in re.findall(r"[a-z']{4,}", pl) if t not in {
            'that', 'this', 'with', 'from', 'your', 'have', 'were', 'been', 'into', 'over',
        }]
        hits = sum(1 for t in tokens if t in visible)
        if tokens and hits / max(1, len(tokens)) >= 0.45:
            return SUPPORTED

    return ALLOWED_INFERENCE


def prosecute(prose: str, resolution: Any = None, world: Any = None) -> list[dict]:
    """Return failure records for UNSUPPORTED / CONTRADICTS_STATE claims."""
    structured: list = []
    passage_before = None
    passage_after = None
    if resolution is not None:
        if isinstance(resolution, dict):
            structured = list(resolution.get('structured_facts') or [])
            structured.extend(resolution.get('world_events') or [])
            structured.extend(
                [{'fact': f} for f in (resolution.get('facts') or []) if isinstance(f, str)]
            )
            if resolution.get('passage_entered') is not None:
                structured.append({
                    'type': 'entered_passage',
                    'passage_id': resolution.get('passage_entered'),
                })
            passage_after = resolution.get('passage_entered')
        else:
            structured = list(getattr(resolution, 'structured_facts', None) or [])
            structured.extend(getattr(resolution, 'world_events', None) or [])
            for f in getattr(resolution, 'facts', None) or []:
                if isinstance(f, str):
                    structured.append({'fact': f})
            entered = getattr(resolution, 'passage_entered', None)
            if entered is not None:
                structured.append({'type': 'entered_passage', 'passage_id': entered})
                passage_after = entered

    world_visible = None
    facility_room_before = None
    facility_room_after = None
    if world is not None:
        if hasattr(world, 'passage_id'):
            passage_before = world.passage_id
            try:
                from puca_dungeon.content_loader import get_passage
                world_visible = get_passage(world.passage_id)
            except Exception:
                world_visible = {
                    'entities': list(getattr(world, 'visible_entities', None) or []),
                }
        elif isinstance(world, dict):
            passage_before = world.get('passage_id')
            world_visible = world
        # Facility TurnSpec locations (room awareness beyond passages)
        nev = None
        if resolution is not None and not isinstance(resolution, dict):
            nev = getattr(resolution, 'narrative_event', None)
        elif isinstance(resolution, dict):
            nev = resolution.get('narrative_event')
        if isinstance(nev, dict):
            facility_room_before = nev.get('location_before') or None
            facility_room_after = nev.get('location_after') or None
        fac = getattr(world, 'facility', None) if not isinstance(world, dict) else None
        if fac is not None and world_visible is None:
            try:
                entities = [e.id for e in fac.entities_in_room()]
            except Exception:
                entities = []
            world_visible = {
                'entities': entities,
                'room_id': getattr(fac, 'room_id', None),
            }
            if facility_room_after is None:
                facility_room_after = str(getattr(fac, 'room_id', '') or '')
            if facility_room_before is None:
                facility_room_before = facility_room_after

    # Passage unchanged → movement claims contradict
    passage_unchanged = (
        passage_after is None
        or (passage_before is not None and int(passage_after) == int(passage_before))
    )
    facility_room_unchanged = (
        facility_room_before is not None
        and facility_room_after is not None
        and str(facility_room_before) == str(facility_room_after)
    )

    failures: list[dict] = []
    props = extract_propositions_heuristic(prose or '')
    for prop in props:
        label = classify_proposition(prop, structured, world_visible)
        pl = prop.lower()

        # Extra deterministic checks
        if pl == 'movement_claim' and passage_unchanged and (
            facility_room_unchanged or facility_room_before is None
        ):
            label = CONTRADICTS_STATE
        if pl == 'movement_claim' and facility_room_unchanged and passage_before is None:
            label = CONTRADICTS_STATE

        for name, pat in _ENTITY_PATTERNS:
            if pl == f'entity_mention:{name}':
                visible_blob = _world_visible_blob(world_visible)
                fact_blob = _fact_blob(structured)
                absent_ok = any(
                    isinstance(f, dict)
                    and f.get('type') == 'entity_absent'
                    and name in str(f.get('entity') or '').lower()
                    for f in structured
                )
                # Presence words in prose without entity in state
                body = (prose or '')
                if pat.search(body) and name not in visible_blob and name not in fact_blob:
                    # Allow explicit negation sentences
                    if re.search(
                        rf'\b(?:no|not a|there is no)\s+{re.escape(name)}\b',
                        body,
                        re.I,
                    ) or absent_ok:
                        if absent_ok or re.search(
                            rf'\b(?:no|not a|there is no)\s+{re.escape(name)}\b',
                            body,
                            re.I,
                        ):
                            label = SUPPORTED
                        else:
                            label = UNSUPPORTED
                    else:
                        label = UNSUPPORTED

        # Stamina / skill / luck numbers vs sheet
        if pl.startswith('meter_number:'):
            meters = _sheet_meters(structured, world)
            m = _STAMINA_NUM.search(prop)
            if m:
                num = next(g for g in m.groups() if g is not None)
                # Any explicit meter number in player-facing prose is a failure
                label = CONTRADICTS_STATE
                failures.append({
                    'proposition': prop,
                    'label': label,
                    'reason': 'meter_leak',
                    'number': int(num),
                    'sheet': meters,
                })
                continue

        if label in (UNSUPPORTED, CONTRADICTS_STATE):
            failures.append({
                'proposition': prop,
                'label': label,
            })

    body = prose or ''
    if _ENGINE_LEAK.search(body):
        failures.append({
            'proposition': 'engine_vocab_leak',
            'label': CONTRADICTS_STATE,
            'reason': 'engine_vocab',
        })
    if _INTENTION_META.search(body):
        failures.append({
            'proposition': 'intention_meta',
            'label': CONTRADICTS_STATE,
            'reason': 'intention_meta',
        })

    # Outcome negation: washed in facts but prose claims water untouched / successful resist
    fact_text = ' '.join(
        str(f) for f in (
            (getattr(resolution, 'facts', None) if resolution is not None and not isinstance(resolution, dict)
             else (resolution or {}).get('facts') if isinstance(resolution, dict) else [])
            or []
        )
        if isinstance(f, str)
    )
    struct_types = []
    for f in structured:
        if isinstance(f, dict) and f.get('type'):
            struct_types.append(str(f.get('type')))
    washed = (
        'washed' in struct_types
        or bool(_WASHED_FACT.search(fact_text))
    )
    if washed and _WASH_NEGATION.search(body):
        failures.append({
            'proposition': 'wash_outcome_negation',
            'label': CONTRADICTS_STATE,
            'reason': 'negates_wash_fact',
        })

    return failures


def has_blocking_failure(failures: list | None) -> bool:
    """True when narrator prose must be replaced by template facts."""
    for f in failures or []:
        if not isinstance(f, dict):
            continue
        if f.get('label') in (CONTRADICTS_STATE, UNSUPPORTED):
            return True
        if f.get('reason') in ('engine_vocab', 'negates_wash_fact', 'meter_leak', 'intention_meta'):
            return True
    return False
