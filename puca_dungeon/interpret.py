"""Intent interpretation: AI or heuristic. Never decides world outcomes."""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any, Optional

from puca_dungeon.models import Intent


INTERPRETER_SYSTEM = """You interpret player text for a dungeon POC into structured intent JSON.
You do NOT decide success, failure, damage, discoveries, movement outcomes, or NPC reactions.
Return ONLY JSON with keys:
action_class (string, broad class like USE, SEARCH, MOVE, WAIT, SPEAK, STRIKE, PICK_LOCK, DISABLE, ATTACK, WARN, GIVE, HIDE, FLEE, SIT, LICK, OTHER),
target, tool, method, intended_effect, manner, destination, utterance (optional),
sequence (optional array of similar objects if multiple actions).
Do not rewrite strange embodied actions into more useful options.
Do not invent menu choices. Use the perceptual context only as grounding hints."""


def normalize_intent(raw: dict) -> Intent:
    if not isinstance(raw, dict):
        return Intent(action_class='OTHER', understood=False, notes='non-object interpreter payload', raw={})
    action = raw.get('action_class') or raw.get('action') or 'OTHER'
    if not isinstance(action, str) or not action.strip():
        action = 'OTHER'
    seq = raw.get('sequence') or []
    if not isinstance(seq, list):
        seq = []
    return Intent(
        action_class=action.strip().upper().replace(' ', '_'),
        target=_str_or_none(raw.get('target')),
        tool=_str_or_none(raw.get('tool')),
        method=_str_or_none(raw.get('method')),
        intended_effect=_str_or_none(raw.get('intended_effect')),
        manner=_str_or_none(raw.get('manner')),
        destination=_str_or_none(raw.get('destination')),
        utterance=_str_or_none(raw.get('utterance')),
        sequence=[normalize_intent(x).to_dict() for x in seq if isinstance(x, dict)],
        raw=raw,
        understood=True,
        notes=str(raw.get('notes') or ''),
    )


def _str_or_none(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class HeuristicInterpreter:
    """Deterministic NL→intent for tests and offline debug. Not a player-visible menu."""

    def interpret(self, text: str, perception: dict) -> tuple[dict, Intent]:
        raw = heuristic_raw(text, perception)
        return raw, normalize_intent(raw)


class OllamaInterpreter:
    def __init__(self, model: str = 'mistral', url: str = 'http://127.0.0.1:11434/api/generate'):
        self.model = model
        self.url = url

    def interpret(self, text: str, perception: dict) -> tuple[dict, Intent]:
        body = {
            'model': self.model,
            'system': INTERPRETER_SYSTEM,
            'prompt': json.dumps({'player_text': text, 'perception': perception}, ensure_ascii=False),
            'stream': False,
            'format': 'json',
            'keep_alive': 0,
            'options': {'temperature': 0.1, 'num_predict': 400, 'num_ctx': 4096},
        }
        request = urllib.request.Request(
            self.url, data=json.dumps(body).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=600) as response:
            payload = json.loads(response.read().decode('utf-8'))
        raw = json.loads(payload['response'])
        return raw, normalize_intent(raw)


def heuristic_raw(text: str, perception: dict) -> dict:
    t = ' '.join(text.lower().strip().split())
    if not t:
        return {'action_class': 'OTHER', 'notes': 'empty'}

    # Waiting / sitting / resting
    if re.fullmatch(r'(wait|wait again|i wait|just wait)(\.|!)?', t) or t in ('...', '…'):
        return {'action_class': 'WAIT', 'intended_effect': 'pass_time'}
    if re.search(r'\b(sit|sit down|take a seat)\b', t):
        return {'action_class': 'SIT', 'intended_effect': 'rest'}

    # Movement past boxes / onward
    if re.search(r'\b(walk past|keep (going|walking)|leave (these |the )?boxes|move on|continue|go (on|forward|deeper|down)|head (down|west|on)|ignore (them|the boxes))\b', t):
        dest = 'passage_ahead'
        if 'west' in t:
            dest = 'west'
        if 'right' in t:
            dest = 'right'
        if 'back' in t or 'retreat' in t:
            dest = 'passage_behind'
        return {'action_class': 'MOVE', 'destination': dest, 'intended_effect': 'leave_area', 'manner': 'onward'}

    # Flee
    if re.search(r'\b(flee|run away|bolt)\b', t):
        return {'action_class': 'FLEE', 'destination': 'passage_ahead', 'intended_effect': 'escape'}

    # Search / inspect traps
    if re.search(r'\b(search|check|inspect|examine|look).*(trap|lock|box)', t) or re.search(r'\btraps?\b', t) and re.search(r'\b(search|check|inspect|look|carefully)\b', t):
        return {'action_class': 'SEARCH', 'target': 'boxes', 'method': 'careful', 'intended_effect': 'discover_trap'}
    if re.search(r'\b(inspect|examine|look at|study).*(box|table|junction|arrow|track)', t):
        target = 'boxes'
        if 'junction' in t or 'arrow' in t or 'track' in t:
            target = 'junction'
        return {'action_class': 'INSPECT', 'target': target, 'method': 'look', 'intended_effect': 'learn'}

    # Disable trap
    if re.search(r'\b(disable|disarm|defuse|safe.*trap)\b', t):
        return {'action_class': 'DISABLE', 'target': 'trap', 'method': 'disable_device', 'intended_effect': 'safe_lock'}

    # Break / smash / strike box or wall (before open/key so "smash open" is not USE)
    if re.search(r'\b(smash|break|bash|punch|strike|hit|destroy)\b', t):
        if re.search(r'\bwall\b', t):
            return {'action_class': 'STRIKE', 'target': 'stone_wall', 'tool': 'fist' if 'punch' in t or 'fist' in t else 'weapon',
                    'intended_effect': 'break_through', 'method': 'force'}
        target = 'named_box' if re.search(r'\b(my |named)\b', t) else 'box'
        tool = 'sword_pommel' if 'pommel' in t or 'sword' in t else 'weapon'
        return {'action_class': 'BREAK', 'target': target, 'tool': tool, 'method': 'force',
                'intended_effect': 'open_force'}

    # Unlock / use key
    if re.search(r'\b(key|unlock)\b', t) and re.search(r'\bbox\b', t):
        tool = 'supplied_key' if re.search(r'\b(my |the )?key\b', t) or 'key' in t else None
        if re.search(r'\b(my name|named|mine|my box)\b', t):
            target = 'named_box'
        elif re.search(r'\b(another|other|different|beside|next)\b', t):
            target = 'other_box'
        else:
            target = 'named_box' if 'my' in t else 'box'
        method = 'unlock'
        return {'action_class': 'USE', 'target': target, 'tool': tool or 'supplied_key',
                'method': method, 'intended_effect': 'open'}
    if re.search(r'\bopen\b', t) and re.search(r'\bbox\b', t) and re.search(r'\bkey\b', t):
        tool = 'supplied_key'
        target = 'named_box' if re.search(r'\b(my name|named|mine|my box)\b', t) else (
            'other_box' if re.search(r'\b(another|other)\b', t) else 'named_box')
        return {'action_class': 'USE', 'target': target, 'tool': tool, 'method': 'unlock', 'intended_effect': 'open'}

    # Pick lock
    if re.search(r'\b(pick|lockpick|lock-pick|pick the lock)\b', t):
        target = 'other_box' if re.search(r'\b(another|other|different)\b', t) else 'box'
        if re.search(r'\b(my name|named|mine|my box)\b', t):
            target = 'named_box'
        return {'action_class': 'PICK_LOCK', 'target': target, 'tool': 'lockpicks',
                'method': 'pick', 'intended_effect': 'open'}

    # Lick / weird embodied
    if re.search(r'\blick\b', t):
        return {'action_class': 'LICK', 'target': 'box', 'intended_effect': 'taste', 'manner': 'embodied'}

    # Combat / social vs challenger
    if re.search(r'\b(attack|kill|stab|slash|fight)\b', t):
        return {'action_class': 'ATTACK', 'target': 'challenger', 'tool': 'sword', 'intended_effect': 'harm'}
    if re.search(r'\b(hide|conceal|duck)\b', t):
        return {'action_class': 'HIDE', 'intended_effect': 'avoid_notice'}
    if re.search(r'\b(surrender|yield|give up)\b', t):
        return {'action_class': 'SURRENDER', 'target': 'challenger', 'intended_effect': 'submit'}
    if re.search(r'\b(warn).*(trap|box)', t) or re.search(r'\btrapped\b', t) and re.search(r'\b(tell|warn|say)\b', t):
        return {'action_class': 'WARN', 'target': 'challenger', 'utterance': text, 'intended_effect': 'share_danger'}
    if re.search(r'\b(offer|give).*(key)\b', t):
        return {'action_class': 'GIVE', 'target': 'challenger', 'tool': 'supplied_key', 'intended_effect': 'bribe'}
    if re.search(r'\b(ally|alliance|together|join|negotiate|parley|talk to)\b', t):
        return {'action_class': 'NEGOTIATE', 'target': 'challenger', 'intended_effect': 'cooperate'}

    # Draw sword
    if re.search(r'\b(draw|unsheathe).*(sword|weapon)\b', t):
        return {'action_class': 'MANIPULATE', 'target': 'sword', 'method': 'draw', 'intended_effect': 'ready_weapon'}

    # Read note / clue
    if re.search(r'\b(read|look at).*(note|clue|message)\b', t):
        return {'action_class': 'INSPECT', 'target': 'clue_note', 'intended_effect': 'read'}

    # Magic words / shout / speak
    if re.search(r'\b(abracadabra|hocus|spell|incant)\b', t):
        return {'action_class': 'SPEAK', 'utterance': text, 'target': 'boxes', 'intended_effect': 'magical_effect', 'manner': 'incantation'}
    if re.search(r'\b(shout|yell|call)\b', t):
        return {'action_class': 'SHOUT', 'utterance': text, 'destination': 'tunnel', 'intended_effect': 'signal'}
    if re.search(r'\b(say|speak|tell)\b', t):
        return {'action_class': 'SPEAK', 'utterance': text, 'intended_effect': 'communicate'}

    # Look around
    if re.search(r'\b(look|peer|glance)\b', t):
        return {'action_class': 'LOOK', 'intended_effect': 'observe'}

    return {'action_class': 'OTHER', 'utterance': text, 'intended_effect': 'unspecified', 'manner': 'freeform'}
