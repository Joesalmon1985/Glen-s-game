"""Persistent opening-arc history. Never displayed as labels."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ArcState:
    day: int = 1
    scene_id: str = 'wake'
    language_attempts: int = 0
    interview_index: int = 0
    interview_answers: list = field(default_factory=list)
    initial_contract_response: str = ''
    final_contract_response: str = ''
    player_final_intent: str = ''
    actual_contract_response: str = ''
    contract_cause: str = ''
    heaven_experienced: bool = False
    hell_experienced: bool = False
    fear_of_hell: int = 0
    discoveries: list = field(default_factory=list)
    tendencies: dict = field(default_factory=dict)
    behavior_flags: dict = field(default_factory=dict)
    classification: str = ''
    encounter_schedule: dict = field(default_factory=dict)
    present_ids: list = field(default_factory=list)
    met_ids: list = field(default_factory=list)
    body_marks: list = field(default_factory=list)
    concealed_items: list = field(default_factory=list)
    situation_line: str = 'You wake in a small room. Nothing is happening yet.'
    last_ask: str = ''
    heaven_turns: int = 0
    hell_turns: int = 0
    wash_style: str = ''
    claimed_name: str = ''
    narrative_context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'day': self.day,
            'scene_id': self.scene_id,
            'language_attempts': self.language_attempts,
            'interview_index': self.interview_index,
            'interview_answers': list(self.interview_answers),
            'initial_contract_response': self.initial_contract_response,
            'final_contract_response': self.final_contract_response,
            'player_final_intent': self.player_final_intent,
            'actual_contract_response': self.actual_contract_response,
            'contract_cause': self.contract_cause,
            'heaven_experienced': self.heaven_experienced,
            'hell_experienced': self.hell_experienced,
            'fear_of_hell': self.fear_of_hell,
            'discoveries': list(self.discoveries),
            'tendencies': dict(self.tendencies),
            'behavior_flags': dict(self.behavior_flags),
            'classification': self.classification,
            'encounter_schedule': dict(self.encounter_schedule),
            'present_ids': list(self.present_ids),
            'met_ids': list(self.met_ids),
            'body_marks': list(self.body_marks),
            'concealed_items': list(self.concealed_items),
            'situation_line': self.situation_line,
            'last_ask': self.last_ask,
            'heaven_turns': self.heaven_turns,
            'hell_turns': self.hell_turns,
            'wash_style': self.wash_style,
            'claimed_name': self.claimed_name,
            'narrative_context': dict(self.narrative_context or {}),
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'ArcState':
        data = data or {}
        return cls(
            day=int(data.get('day', 1) or 1),
            scene_id=str(data.get('scene_id') or 'wake'),
            language_attempts=int(data.get('language_attempts', 0) or 0),
            interview_index=int(data.get('interview_index', 0) or 0),
            interview_answers=list(data.get('interview_answers') or []),
            initial_contract_response=str(data.get('initial_contract_response') or ''),
            final_contract_response=str(data.get('final_contract_response') or ''),
            player_final_intent=str(data.get('player_final_intent') or ''),
            actual_contract_response=str(data.get('actual_contract_response') or ''),
            contract_cause=str(data.get('contract_cause') or ''),
            heaven_experienced=bool(data.get('heaven_experienced', False)),
            hell_experienced=bool(data.get('hell_experienced', False)),
            fear_of_hell=int(data.get('fear_of_hell', 0) or 0),
            discoveries=list(data.get('discoveries') or []),
            tendencies=dict(data.get('tendencies') or {}),
            behavior_flags=dict(data.get('behavior_flags') or {}),
            classification=str(data.get('classification') or ''),
            encounter_schedule=dict(data.get('encounter_schedule') or {}),
            present_ids=list(data.get('present_ids') or []),
            met_ids=list(data.get('met_ids') or []),
            body_marks=list(data.get('body_marks') or []),
            concealed_items=list(data.get('concealed_items') or []),
            situation_line=str(data.get('situation_line') or 'You wake in a small room.'),
            last_ask=str(data.get('last_ask') or ''),
            heaven_turns=int(data.get('heaven_turns', 0) or 0),
            hell_turns=int(data.get('hell_turns', 0) or 0),
            wash_style=str(data.get('wash_style') or ''),
            claimed_name=str(data.get('claimed_name') or ''),
            narrative_context=dict(data.get('narrative_context') or {}),
        )

    def flag(self, key: str, value: Any = True) -> None:
        self.behavior_flags[key] = value

    def discover(self, key: str) -> None:
        if key and key not in self.discoveries:
            self.discoveries.append(key)

    def mark_met(self, cid: str) -> None:
        if cid and cid not in self.met_ids:
            self.met_ids.append(cid)


def situation_for_phase(phase: str, room_id: str, ask: str = '') -> str:
    rooms = {
        'cell': 'You are in the small locked cell.',
        'corridor': 'You are in a plain corridor.',
        'washroom': 'You are in the washroom.',
        'mess': 'You are in a narrow mess room.',
        'interview': 'You are in an interview room.',
        'prep': 'You are in a preparation room with machines.',
        'heaven': 'You are in the place they call Heaven.',
        'hell': 'You are in the place they call Hell.',
        'research_quarters': 'You are in subject quarters in the research wing.',
    }
    base = rooms.get(room_id, 'You are somewhere in the facility.')
    asks = {
        'slit': 'The observation slit is open. They want you to step away from the door.',
        'door_procedure': 'They want you away from the door before they enter.',
        'wash': 'They intend to wash you.',
        'food': 'A bowl of food is in front of you.',
        'sleep': 'Sleep is becoming hard to resist.',
        'interview': 'They are asking you questions.',
        'contract': 'They are offering a five-year research agreement.',
        'second_offer': 'They are offering the five-year agreement again.',
        'heaven': 'This place is warm and well supplied. Your time here is limited.',
        'hell': 'This place is made to be endured.',
        'research': 'You are registered as a research subject.',
    }
    extra = ask or asks.get(phase, '')
    if extra:
        return f'{base} {extra}'
    return base
