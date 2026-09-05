"""Puca's rules. No GUI, network or AI dependencies."""
from dataclasses import dataclass, field, asdict
import json
import os
import re
import tempfile
from pathlib import Path

MAX_TURNS = 10
SPIRIT_DELTAS = {'positive': 10, 'negative': -12, 'neutral': 0}

@dataclass(frozen=True)
class Scene:
    narration: str
    event: str
    spirit: str
    image_prompt: str
    location: str
    choices: tuple = ()
    facts: tuple = ()
    visual_changed: bool = False

@dataclass
class StoryState:
    name: str = ''
    origin: str = ''
    spirit: int = 100
    turn: int = 0
    arrived: bool = False
    history: list = field(default_factory=list)
    facts: list = field(default_factory=list)
    image_key: str = ''
    location: str = ''

    @property
    def finished(self):
        return self.arrived and (self.spirit <= 0 or self.turn >= MAX_TURNS)

    def apply(self, action, scene, opening=False):
        if self.finished:
            raise ValueError('This adventure has ended. Start a new adventure.')
        if scene.spirit not in SPIRIT_DELTAS:
            raise ValueError('Invalid spirit outcome')
        if opening != (not self.arrived):
            raise ValueError('Invalid opening/turn sequence')
        before = self.spirit
        self.spirit = max(0, min(100, before + (0 if opening else SPIRIT_DELTAS[scene.spirit])))
        self.arrived = True
        if not opening:
            self.turn += 1
        self.location = scene.location
        for fact in scene.facts:
            if fact not in self.facts:
                self.facts.append(fact)
        self.history.append({'action': action, 'narration': scene.narration,
                             'event': scene.event, 'spirit_delta': self.spirit - before,
                             'location': scene.location, 'choices': list(scene.choices),
                             'image_prompt': scene.image_prompt})
        return self.spirit - before


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps({'version': 1, 'state': asdict(state)}, ensure_ascii=False, indent=2)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as temp:
            name = temp.name
            temp.write(encoded)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def load_state(path):
    path = Path(path)
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError('Save is too large')
        payload = json.loads(path.read_text(encoding='utf-8'))
        if payload.get('version') != 1 or not isinstance(payload.get('state'), dict):
            raise ValueError('Unsupported save format')
        raw = payload['state']
        if set(raw) != set(StoryState.__dataclass_fields__):
            raise ValueError('Incomplete save')
        if type(raw['turn']) is not int or not 0 <= raw['turn'] <= MAX_TURNS:
            raise ValueError('Invalid turn')
        if type(raw['spirit']) is not int or not 0 <= raw['spirit'] <= 100:
            raise ValueError('Invalid spirit')
        if type(raw['arrived']) is not bool:
            raise ValueError('Invalid arrival state')
        for key, limit in [('name', 80), ('origin', 240), ('location', 100), ('image_key', 64)]:
            if not isinstance(raw[key], str) or len(raw[key]) > limit:
                raise ValueError(f'Invalid {key}')
        if raw['image_key'] and not re.fullmatch('[a-f0-9]{64}', raw['image_key']):
            raise ValueError('Invalid image reference')
        if not isinstance(raw['facts'], list) or len(raw['facts']) > 44 or any(not isinstance(x, str) or len(x) > 240 for x in raw['facts']):
            raise ValueError('Invalid facts')
        records = raw['history']
        if not isinstance(records, list) or len(records) != raw['turn'] + int(raw['arrived']):
            raise ValueError('Inconsistent history')
        if not raw['arrived'] and raw['turn']:
            raise ValueError('Turns before arrival')
        for record in records:
            if not isinstance(record, dict):
                raise ValueError('Invalid history')
            for key, limit in [('action', 800), ('narration', 2400), ('event', 80), ('location', 100), ('image_prompt', 400)]:
                if not isinstance(record.get(key), str) or len(record[key]) > limit:
                    raise ValueError('Invalid history text')
            delta = record.get('spirit_delta')
            if type(delta) is not int or not -12 <= delta <= 10:
                raise ValueError('Invalid score history')
            choices = record.get('choices')
            if not isinstance(choices, list) or len(choices) > 3 or any(not isinstance(x, str) or len(x) > 180 for x in choices):
                raise ValueError('Invalid choices')
        if records:
            if records[0]['spirit_delta'] != 0:
                raise ValueError('Opening cannot change spirit')
            score = 100
            for record in records:
                score += record['spirit_delta']
                if not 0 <= score <= 100:
                    raise ValueError('Invalid score progression')
            if score != raw['spirit'] or records[-1]['location'] != raw['location']:
                raise ValueError('Saved score/location contradict the history')
        elif raw['spirit'] != 100 or raw['location'] or raw['facts'] or raw['image_key']:
            raise ValueError('Unstarted adventure has inconsistent state')
        return StoryState(**raw)
    except (OSError, TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError('Cannot read this save. The existing file has not been changed.') from exc
