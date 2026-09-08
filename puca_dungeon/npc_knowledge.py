"""Player knowledge of NPCs: recognition, believed names, claims — not objective truth."""
from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

NAME_SOURCES = frozenset({
    'self_introduction', 'named_by_other', 'asked_and_understood', 'read_document',
})

_ROLE_NOUNS = frozenset({
    'orderly', 'researcher', 'attendant', 'staff', 'subject', 'doctor', 'nurse',
})


@dataclass
class IdentityClaim:
    claim: str
    kind: str = 'name'  # name | role
    source: str = 'self_introduction'
    speaker_id: str = ''
    believed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'IdentityClaim':
        data = data or {}
        return cls(
            claim=str(data.get('claim') or ''),
            kind=str(data.get('kind') or 'name'),
            source=str(data.get('source') or 'self_introduction'),
            speaker_id=str(data.get('speaker_id') or ''),
            believed=bool(data.get('believed', False)),
        )


@dataclass
class NpcKnowledge:
    encountered: bool = False
    recognised: bool = False
    name_known: bool = False
    known_name: Optional[str] = None
    role_known: bool = False
    known_role: Optional[str] = None
    descriptors: list = field(default_factory=list)
    short_label: str = ''
    identity_claims: list = field(default_factory=list)
    intro_done: bool = False

    def to_dict(self) -> dict:
        claims = []
        for c in self.identity_claims:
            if isinstance(c, IdentityClaim):
                claims.append(c.to_dict())
            elif isinstance(c, dict):
                claims.append(dict(c))
        return {
            'encountered': self.encountered,
            'recognised': self.recognised,
            'name_known': self.name_known,
            'known_name': self.known_name,
            'role_known': self.role_known,
            'known_role': self.known_role,
            'descriptors': list(self.descriptors),
            'short_label': self.short_label,
            'identity_claims': claims,
            'intro_done': self.intro_done,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'NpcKnowledge':
        data = data or {}
        claims = [
            IdentityClaim.from_dict(c) if isinstance(c, dict) else c
            for c in (data.get('identity_claims') or [])
        ]
        return cls(
            encountered=bool(data.get('encountered', False)),
            recognised=bool(data.get('recognised', False)),
            name_known=bool(data.get('name_known', False)),
            known_name=(str(data['known_name']) if data.get('known_name') else None),
            role_known=bool(data.get('role_known', False)),
            known_role=(str(data['known_role']) if data.get('known_role') else None),
            descriptors=list(data.get('descriptors') or []),
            short_label=str(data.get('short_label') or ''),
            identity_claims=claims,
            intro_done=bool(data.get('intro_done', False)),
        )


@dataclass
class NarrativeCharacter:
    npc_id: str
    narrator_reference: str
    name_known: bool = False
    role_known: bool = False

    def to_narrator_dict(self) -> dict:
        """Player-facing projection — no engine id required for prose."""
        return {
            'narrator_reference': self.narrator_reference,
            'name_known': self.name_known,
            'role_known': self.role_known,
        }


def _arc(facility):
    return getattr(facility, 'arc', None)


def _store(facility) -> dict:
    arc = _arc(facility)
    if arc is None:
        return {}
    raw = getattr(arc, 'npc_knowledge', None) or {}
    return dict(raw)


def _write_store(facility, store: dict) -> None:
    arc = _arc(facility)
    if arc is None:
        return
    arc.npc_knowledge = store


def get_knowledge(facility, cid: str) -> NpcKnowledge:
    store = _store(facility)
    return NpcKnowledge.from_dict(store.get(cid) if isinstance(store.get(cid), dict) else store.get(cid))


def set_knowledge(facility, cid: str, knowledge: NpcKnowledge) -> None:
    store = _store(facility)
    store[cid] = knowledge.to_dict()
    _write_store(facility, store)


def appearance_of(facility, cid: str) -> dict:
    raw = (getattr(facility, 'cast', None) or {}).get(cid) or {}
    app = raw.get('appearance') if isinstance(raw, dict) else None
    if isinstance(app, dict) and app:
        return dict(app)
    return {
        'short_label': 'someone present',
        'distinctive': '',
        'role_cue': '',
        'first_seen': 'Someone is here.',
    }


def true_name(facility, cid: str) -> str:
    raw = (getattr(facility, 'cast', None) or {}).get(cid) or {}
    return str(raw.get('name') or '')


def narrator_reference(facility, cid: str) -> str:
    if not cid or cid in ('sarel', 'player', 'staff'):
        if cid == 'staff':
            return 'someone nearby'
        return 'you'
    k = get_knowledge(facility, cid)
    if k.name_known and k.known_name:
        return k.known_name
    if k.short_label:
        if k.recognised and k.intro_done:
            label = k.short_label
            if not label.lower().startswith(('the ', 'a ', 'an ')):
                return f'the {label}'
            return label
        return k.short_label
    app = appearance_of(facility, cid)
    label = str(app.get('short_label') or 'someone present')
    return label


def project_narrative_character(facility, cid: str) -> NarrativeCharacter:
    k = get_knowledge(facility, cid)
    return NarrativeCharacter(
        npc_id=cid,
        narrator_reference=narrator_reference(facility, cid),
        name_known=bool(k.name_known),
        role_known=bool(k.role_known),
    )


def characters_present_packet(facility) -> list[dict]:
    present = list(getattr(_arc(facility), 'present_ids', None) or [])
    out = []
    for cid in present:
        if cid in ('sarel',):
            continue
        nc = project_narrative_character(facility, cid)
        out.append(nc.to_narrator_dict())
    return out


def people_present_phrases(facility) -> list[str]:
    return [c['narrator_reference'] for c in characters_present_packet(facility)]


def _pending(facility) -> list:
    arc = _arc(facility)
    if arc is None:
        return []
    raw = getattr(arc, 'pending_intros', None) or []
    return list(raw)


def _set_pending(facility, items: list) -> None:
    arc = _arc(facility)
    if arc is None:
        return
    arc.pending_intros = list(items)


def note_encounter(facility, cid: str, *, returning: bool = False) -> str:
    """Mark presence. Does not learn names. Returns intro kind: first|return|''."""
    if not cid or cid == 'sarel':
        return ''
    k = get_knowledge(facility, cid)
    app = appearance_of(facility, cid)
    if not k.short_label:
        k.short_label = str(app.get('short_label') or 'someone present')
    distinctive = str(app.get('distinctive') or '').strip()
    if distinctive and distinctive not in k.descriptors:
        k.descriptors.append(distinctive)
    if k.short_label and k.short_label not in k.descriptors:
        k.descriptors.append(k.short_label)
    already = k.intro_done
    k.encountered = True
    k.recognised = True
    kind = ''
    if not already:
        text = str(app.get('first_seen') or f'{k.short_label.capitalize()} is here.')
        pending = _pending(facility)
        pending.append({'cid': cid, 'kind': 'first', 'text': text})
        _set_pending(facility, pending)
        k.intro_done = True
        kind = 'first'
    elif returning:
        if k.name_known and k.known_name:
            text = f'{k.known_name} is here.'
        else:
            label = k.short_label.replace('the ', '', 1)
            text = f'The same {label} is here.'
        pending = _pending(facility)
        if not any(p.get('cid') == cid and p.get('kind') == 'return' for p in pending):
            pending.append({'cid': cid, 'kind': 'return', 'text': text})
            _set_pending(facility, pending)
        kind = 'return'
    set_knowledge(facility, cid, k)
    ensure_distinct_labels(facility)
    return kind


def ensure_present_encountered(facility) -> None:
    present = list(getattr(_arc(facility), 'present_ids', None) or [])
    for cid in present:
        k = get_knowledge(facility, cid)
        if not k.encountered:
            note_encounter(facility, cid, returning=False)


def flush_pending_intros(facility) -> list[dict]:
    items = _pending(facility)
    _set_pending(facility, [])
    facts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get('text') or '').strip()
        if not text:
            continue
        facts.append({
            'type': 'character_intro',
            'npc_id': item.get('cid'),
            'kind': item.get('kind') or 'first',
            'text': text,
        })
    return facts


def ensure_distinct_labels(facility) -> None:
    present = list(getattr(_arc(facility), 'present_ids', None) or [])
    unknown = []
    for cid in present:
        k = get_knowledge(facility, cid)
        if k.name_known:
            continue
        unknown.append(cid)
    if len(unknown) < 2:
        return
    labels: dict[str, list[str]] = {}
    for cid in unknown:
        k = get_knowledge(facility, cid)
        key = (k.short_label or '').lower()
        labels.setdefault(key, []).append(cid)
    for key, ids in labels.items():
        if len(ids) < 2:
            continue
        for cid in ids:
            k = get_knowledge(facility, cid)
            app = appearance_of(facility, cid)
            distinctive = str(app.get('distinctive') or '').strip()
            base = k.short_label or 'the person'
            if distinctive and distinctive.lower() not in base.lower():
                k.short_label = f'{base} with {distinctive}'
                set_knowledge(facility, cid, k)


def record_identity_claim(
    facility,
    npc_id: str,
    claim: str,
    *,
    kind: str = 'name',
    source: str = 'self_introduction',
    speaker_id: str = '',
    believed: bool = False,
) -> IdentityClaim:
    k = get_knowledge(facility, npc_id)
    ic = IdentityClaim(
        claim=claim,
        kind=kind,
        source=source if source in NAME_SOURCES else source,
        speaker_id=speaker_id or npc_id,
        believed=believed,
    )
    k.identity_claims.append(ic)
    if believed and kind == 'name' and claim:
        k.name_known = True
        k.known_name = claim
    if believed and kind == 'role' and claim:
        k.role_known = True
        k.known_role = claim
        # Role may become a descriptor, but do not replace appearance label unless empty
        if claim and claim not in k.descriptors:
            k.descriptors.append(claim)
    set_knowledge(facility, npc_id, k)
    return ic


def take_up_name(facility, npc_id: str, name: str, *, source: str) -> dict:
    """Player understands and uses a claimed name. Still a belief, not verified identity."""
    name = (name or '').strip()
    event = {
        'type': 'learn_npc_name',
        'npc': npc_id,
        'name': name,
        'source': source,
    }
    record_identity_claim(
        facility, npc_id, name, kind='name', source=source,
        speaker_id=npc_id, believed=True,
    )
    return event


def take_up_role(facility, npc_id: str, role: str, *, source: str) -> dict:
    role = (role or '').strip()
    record_identity_claim(
        facility, npc_id, role, kind='role', source=source,
        speaker_id=npc_id, believed=True,
    )
    return {'type': 'learn_npc_role', 'npc': npc_id, 'role': role, 'source': source}


def unknown_true_names(facility) -> list[str]:
    names = []
    cast = getattr(facility, 'cast', None) or {}
    for cid, raw in cast.items():
        if cid == 'sarel':
            continue
        nm = str((raw or {}).get('name') or '').strip()
        if not nm:
            continue
        k = get_knowledge(facility, cid)
        if k.name_known and (k.known_name or '').lower() == nm.lower():
            continue
        names.append(nm)
    return names


def _name_in_text(name: str, text: str) -> bool:
    if not name or not text:
        return False
    if len(name) <= 2:
        return False
    return bool(re.search(rf'(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])', text))


def iter_string_values(obj: Any, path: str = ''):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in ('npc_id', 'speaker', 'target', 'who_id', 'referent'):
                continue
            yield from iter_string_values(v, f'{path}.{k}' if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_string_values(v, f'{path}[{i}]')


def find_unknown_name_leaks(facility, payload: dict) -> list[dict]:
    """Detect unknown true names in narrator-grade strings. Does not rewrite."""
    names = unknown_true_names(facility)
    leaks = []
    if not names or not isinstance(payload, dict):
        return leaks
    skip_keys = {
        'cast', 'engine', 'debug_cast', 'speaker_id', 'npc_id',
    }
    for path, text in iter_string_values(payload):
        root = path.split('.')[0] if path else ''
        if root in skip_keys:
            continue
        if 'engine' in path.lower():
            continue
        for name in names:
            if _name_in_text(name, text):
                leaks.append({'path': path, 'name': name, 'excerpt': text[:160]})
    return leaks


def scrub_unknown_names(facility, payload: dict) -> tuple[dict, bool]:
    """Last-resort rewrite. Tests should fail if this returns altered=True on an ordinary packet."""
    names = unknown_true_names(facility)
    if not names:
        return payload, False

    def replace_in(obj, cid_hint: str = ''):
        altered_local = False
        if isinstance(obj, str):
            out = obj
            for name in names:
                if _name_in_text(name, out):
                    # Prefer matching NPC's narrator_reference
                    ref = 'someone'
                    cast = getattr(facility, 'cast', None) or {}
                    for cid, raw in cast.items():
                        if str((raw or {}).get('name') or '') == name:
                            ref = narrator_reference(facility, cid)
                            break
                    out = re.sub(rf'(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])', ref, out)
                    altered_local = True
            return out, altered_local
        if isinstance(obj, dict):
            new = {}
            any_a = False
            for k, v in obj.items():
                nv, a = replace_in(v)
                new[k] = nv
                any_a = any_a or a
            return new, any_a
        if isinstance(obj, list):
            new_l = []
            any_a = False
            for v in obj:
                nv, a = replace_in(v)
                new_l.append(nv)
                any_a = any_a or a
            return new_l, any_a
        return obj, False

    cleaned, altered = replace_in(copy.deepcopy(payload))
    return cleaned, altered


def id_for_player_reference(facility, text: str) -> Optional[str]:
    """Resolve a player-facing name or descriptor. Unknown true names do not bind."""
    needle = (text or '').strip().lower()
    if not needle:
        return None
    needle = re.sub(r'^(the|a|an)\s+', '', needle)
    cast = getattr(facility, 'cast', None) or {}
    present = list(getattr(_arc(facility), 'present_ids', None) or [])
    # Believed names first
    for cid in list(present) + list(cast.keys()):
        k = get_knowledge(facility, cid)
        if k.name_known and k.known_name and k.known_name.lower() == needle:
            return cid
        if k.known_role and k.role_known and k.known_role.lower() == needle:
            return cid
    # Descriptors / short labels
    for cid in present or list(cast.keys()):
        k = get_knowledge(facility, cid)
        label = (k.short_label or '').lower()
        label = re.sub(r'^(the|a|an)\s+', '', label)
        if label and (needle == label or needle in label or label in needle):
            return cid
        for d in k.descriptors:
            dl = str(d).lower()
            if needle == dl or needle in dl or dl in needle:
                return cid
        app = appearance_of(facility, cid)
        for key in ('short_label', 'distinctive'):
            val = re.sub(r'^(the|a|an)\s+', '', str(app.get(key) or '').lower())
            if val and (needle == val or needle in val):
                return cid
    # Engine id if the player somehow used it — still not a true-name leak
    if needle in cast and needle != 'sarel':
        return needle
    return None


def bind_overheard_name(facility, spoken_name: str, *, speaker_id: str, present_ids: list[str]) -> Optional[dict]:
    """If an NPC names another present person unambiguously, record a claim and take it up."""
    spoken_name = (spoken_name or '').strip()
    if not spoken_name:
        return None
    cast = getattr(facility, 'cast', None) or {}
    matches = []
    for cid in present_ids:
        if cid == speaker_id:
            continue
        if str((cast.get(cid) or {}).get('name') or '') == spoken_name:
            matches.append(cid)
    if len(matches) != 1:
        return None
    target = matches[0]
    k = get_knowledge(facility, target)
    if k.name_known:
        return None
    return take_up_name(facility, target, spoken_name, source='named_by_other')


def label_avoids_unearned_role(label: str, role_known: bool) -> str:
    if role_known:
        return label
    words = set(re.findall(r'[a-z]+', (label or '').lower()))
    if words & _ROLE_NOUNS:
        return re.sub(
            r'\b(orderly|researcher|attendant|staff member|subject|doctor|nurse)\b',
            'person',
            label,
            flags=re.I,
        )
    return label
