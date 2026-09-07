"""Python-owned cast: identities, cosmetic names, relationships, encounters."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

STAFF_NAME_POOL = ['Cam', 'Ben', 'Laurie', 'Dom', 'Glen']
SENIOR_NAME_POOL = ['Maelin', 'Tirren', 'Sovan', 'Elian', 'Veyra']

SUBJECT_IDS = ('iven', 'nessa', 'ruan')
STAFF_IDS = ('senior_researcher', 'orderly_quiet', 'orderly_anxious')

# Encounter windows in story order. Heaven/Hell are after the first contract.
WINDOWS = (
    'wash_corridor',
    'meal',
    'return_escort',
    'day2_retrieval',
    'interview_waiting',
    'afterlife_break',
    'heaven',
    'hell',
)
PRE_SECOND_OFFER = WINDOWS  # all listed windows are at or before second offer
PRE_CONTRACT = WINDOWS[:6]  # no heaven/hell

_TEMPLATES_PATH = Path(__file__).resolve().parent / 'content' / 'facility' / 'cast_templates.json'


def _load_templates() -> dict:
    if _TEMPLATES_PATH.is_file():
        return json.loads(_TEMPLATES_PATH.read_text(encoding='utf-8'))
    return {}


@dataclass
class RelationshipState:
    familiarity: int = 0
    trust: int = 0
    affection: int = 0
    respect: int = 0
    fear: int = 0
    resentment: int = 0
    suspicion: int = 0
    dependency: int = 0
    remembered_interactions: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'familiarity': self.familiarity,
            'trust': self.trust,
            'affection': self.affection,
            'respect': self.respect,
            'fear': self.fear,
            'resentment': self.resentment,
            'suspicion': self.suspicion,
            'dependency': self.dependency,
            'remembered_interactions': list(self.remembered_interactions),
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'RelationshipState':
        data = data or {}
        return cls(
            familiarity=int(data.get('familiarity', 0) or 0),
            trust=int(data.get('trust', 0) or 0),
            affection=int(data.get('affection', 0) or 0),
            respect=int(data.get('respect', 0) or 0),
            fear=int(data.get('fear', 0) or 0),
            resentment=int(data.get('resentment', 0) or 0),
            suspicion=int(data.get('suspicion', 0) or 0),
            dependency=int(data.get('dependency', 0) or 0),
            remembered_interactions=list(data.get('remembered_interactions') or []),
        )

    def remember(self, event: str) -> None:
        if event and event not in self.remembered_interactions:
            self.remembered_interactions.append(event)
            if len(self.remembered_interactions) > 24:
                self.remembered_interactions = self.remembered_interactions[-24:]


@dataclass
class CharacterState:
    id: str
    name: str
    role: str
    location: str = ''
    presentation: str = ''
    language: int = 80
    emotion: str = 'neutral'
    goals: list = field(default_factory=list)
    beliefs: list = field(default_factory=list)
    knowledge: list = field(default_factory=list)
    secrets: list = field(default_factory=list)
    uncertainties: list = field(default_factory=list)
    may_reveal: list = field(default_factory=list)
    must_conceal: list = field(default_factory=list)
    tendencies: dict = field(default_factory=dict)
    relationships: dict = field(default_factory=dict)  # other_id -> RelationshipState dict
    episodic_memories: list = field(default_factory=list)
    current_activity: str = ''

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'role': self.role,
            'location': self.location,
            'presentation': self.presentation,
            'language': self.language,
            'emotion': self.emotion,
            'goals': list(self.goals),
            'beliefs': list(self.beliefs),
            'knowledge': list(self.knowledge),
            'secrets': list(self.secrets),
            'uncertainties': list(self.uncertainties),
            'may_reveal': list(self.may_reveal),
            'must_conceal': list(self.must_conceal),
            'tendencies': dict(self.tendencies),
            'relationships': dict(self.relationships),
            'episodic_memories': list(self.episodic_memories),
            'current_activity': self.current_activity,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'CharacterState':
        data = data or {}
        return cls(
            id=str(data.get('id') or ''),
            name=str(data.get('name') or ''),
            role=str(data.get('role') or ''),
            location=str(data.get('location') or ''),
            presentation=str(data.get('presentation') or ''),
            language=int(data.get('language', 80) or 80),
            emotion=str(data.get('emotion') or 'neutral'),
            goals=list(data.get('goals') or []),
            beliefs=list(data.get('beliefs') or []),
            knowledge=list(data.get('knowledge') or []),
            secrets=list(data.get('secrets') or []),
            uncertainties=list(data.get('uncertainties') or []),
            may_reveal=list(data.get('may_reveal') or []),
            must_conceal=list(data.get('must_conceal') or []),
            tendencies=dict(data.get('tendencies') or {}),
            relationships=dict(data.get('relationships') or {}),
            episodic_memories=list(data.get('episodic_memories') or []),
            current_activity=str(data.get('current_activity') or ''),
        )

    def rel(self, other_id: str) -> RelationshipState:
        raw = self.relationships.get(other_id)
        if isinstance(raw, RelationshipState):
            return raw
        rel = RelationshipState.from_dict(raw if isinstance(raw, dict) else None)
        self.relationships[other_id] = rel.to_dict()
        return rel

    def set_rel(self, other_id: str, rel: RelationshipState) -> None:
        self.relationships[other_id] = rel.to_dict()

    def remember_event(self, event: dict) -> None:
        self.episodic_memories.append(event)
        if len(self.episodic_memories) > 40:
            self.episodic_memories = self.episodic_memories[-40:]


def _character_from_template(cid: str, name: str, template: dict) -> CharacterState:
    return CharacterState(
        id=cid,
        name=name,
        role=str(template.get('role') or cid),
        presentation=str(template.get('presentation') or ''),
        goals=list(template.get('goals') or []),
        beliefs=list(template.get('beliefs') or []),
        knowledge=list(template.get('knowledge') or []),
        secrets=list(template.get('secrets') or []),
        may_reveal=list(template.get('may_reveal') or []),
        must_conceal=list(template.get('must_conceal') or []),
        relationships={'sarel': RelationshipState().to_dict()},
    )


def generate_cast(rng) -> dict[str, dict]:
    """Assign cosmetic names independently of personality templates."""
    templates = _load_templates()
    staff_names = rng.shuffle(STAFF_NAME_POOL) if hasattr(rng, 'shuffle') else list(STAFF_NAME_POOL)
    if not hasattr(rng, 'shuffle'):
        # Fallback deterministic-ish if a bare Random-like object
        try:
            rng._rng.shuffle(staff_names)  # type: ignore[attr-defined]
        except Exception:
            pass
    senior_name = rng.choice(SENIOR_NAME_POOL)
    leftover = list(staff_names[2:])
    mapping = {
        'senior_researcher': senior_name,
        'orderly_quiet': staff_names[0],
        'orderly_anxious': staff_names[1],
        'iven': 'Iven',
        'nessa': 'Nessa',
        'ruan': 'Ruan',
        'sarel': 'Sarel',
    }
    if leftover:
        mapping['attendant_a'] = leftover[0]
    if len(leftover) > 1:
        mapping['attendant_b'] = leftover[1]

    cast: dict[str, dict] = {}
    for cid, name in mapping.items():
        tmpl = dict(templates.get(cid) or {})
        if cid.startswith('attendant'):
            tmpl.setdefault('role', 'attendant')
            tmpl.setdefault('presentation', 'gentle, quietly institutional')
            tmpl.setdefault('goals', ['keep_the_guest_comfortable'])
            tmpl.setdefault('beliefs', ['this_is_a_continuation_environment'])
            tmpl.setdefault('may_reveal', ['small_comforts'])
            tmpl.setdefault('must_conceal', ['facility_logistics'])
        if cid == 'sarel':
            tmpl.setdefault('role', 'subject')
            tmpl.setdefault('presentation', 'newly woken, language-limited')
        cast[cid] = _character_from_template(cid, name, tmpl).to_dict()
    return cast


def schedule_subject_encounters(rng) -> dict[str, list[str]]:
    """Each other subject gets 1–2 windows. All have ≥1 at or before second offer.

    Heaven/Hell windows are allowed, but each subject also gets a guaranteed
    pre-contract window so the accept-now route can still meet them (or we
    fall back at processing using that pre-contract slot if they skipped it).
    """
    pre = list(PRE_CONTRACT)
    later = ['heaven', 'hell']
    schedule: dict[str, list[str]] = {}
    # Shuffle copies so assignment varies by seed
    pre_pool = rng.shuffle(pre) if hasattr(rng, 'shuffle') else list(pre)
    later_pool = rng.shuffle(later) if hasattr(rng, 'shuffle') else list(later)
    for i, cid in enumerate(SUBJECT_IDS):
        first = pre_pool[i % len(pre_pool)]
        windows = [first]
        extra_choice = later_pool[i % len(later_pool)]
        if extra_choice not in windows:
            windows.append(extra_choice)
        # Unique-ish second pre window if we still need variety
        second_pre = pre_pool[(i + 3) % len(pre_pool)]
        if second_pre not in windows and rng.randint(0, 1):
            windows.append(second_pre)
        schedule[cid] = windows
    return schedule


def subjects_for_window(schedule: dict, window: str) -> list[str]:
    return [cid for cid, wins in (schedule or {}).items() if window in (wins or [])]


def unmet_subjects(schedule: dict, met_ids: list[str]) -> list[str]:
    met = set(met_ids or [])
    return [cid for cid in SUBJECT_IDS if cid not in met]


def name_of(cast: dict, cid: str) -> str:
    raw = (cast or {}).get(cid) or {}
    if isinstance(raw, dict):
        return str(raw.get('name') or cid)
    return cid


def id_for_name(cast: dict, name: str) -> Optional[str]:
    needle = (name or '').strip().lower()
    if not needle:
        return None
    for cid, raw in (cast or {}).items():
        nm = str((raw or {}).get('name') or '').lower()
        if nm == needle or cid == needle:
            return cid
    return None


def present_staff_ids(staff_count: int) -> list[str]:
    if staff_count <= 0:
        return []
    if staff_count == 1:
        return ['orderly_quiet']
    if staff_count == 2:
        return ['orderly_quiet', 'orderly_anxious']
    return ['orderly_quiet', 'orderly_anxious', 'senior_researcher']


def record_memory(cast: dict, cid: str, text: str, *, about: str = 'sarel') -> None:
    raw = (cast or {}).get(cid)
    if not isinstance(raw, dict):
        return
    ch = CharacterState.from_dict(raw)
    ch.remember_event({'what': text, 'about': about})
    rel = ch.rel(about)
    rel.remember(text)
    ch.set_rel(about, rel)
    cast[cid] = ch.to_dict()
