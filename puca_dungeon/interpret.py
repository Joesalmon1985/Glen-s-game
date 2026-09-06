"""Intent interpretation: LLM-first semantic matching. Never decides world outcomes.

HeuristicInterpreter exists only for deterministic unit tests and explicit offline fallback.
Do not expand its regex table to cover free-form player English — that is the Ollama path's job.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from puca_dungeon.authored_actions import apply_authored_match
from puca_dungeon.models import CLASSIFICATIONS, Intent


INTERPRETER_SYSTEM = """You interpret player text for a dungeon game into structured intent JSON.
You do NOT decide success, failure, damage, discoveries, movement outcomes, traps, NPC reactions, or any world state change.

You receive three inputs:
1) exact raw player text
2) public/perceptual world state (no hidden secrets)
3) currently available AUTHORED ACTION DESCRIPTORS — internal semantic targets Python can resolve. These are NOT an exhaustive list of what the player may attempt, and NOT a menu for the player.

Procedure:
A) First ask: does the player's intended action substantially correspond to one authored action?
   If YES → classification = MATCH_AUTHORED_ACTION, set matched_action_id to that id, fill action fields.
B) If NO → preserve the player's actual meaning. Do NOT force shake/lick/cartwheel/sing/etc. into search, break, open, or use-key.

Classifications (pick exactly one):
- MATCH_AUTHORED_ACTION — genuine match to an authored descriptor
- GENERAL_WORLD_ACTION — understandable embodied/world action that is not an authored match
- PERCEPTION_QUERY — question about visible/known state (how many boxes, what do I carry, what can I see/hear)
- META_REQUEST — out-of-world / UI / inventory-menu / "press X" style requests
- SILLY_BUT_VALID — physically legible but non-progressing silliness (cartwheel, dance) the character can attempt
- UNINTERPRETABLE — nonsense / empty / no recoverable meaning
- NEEDS_CLARIFICATION — meaning partly clear but required entity is ambiguous

Rules:
- Never invent a tool the player did not imply.
- If multiple boxes exist and the player says "the box" / "a box" / "one of the boxes" without naming which, set needs_clarification=true and ambiguities including which box; do NOT pick the named box silently.
- CRITICAL: shake, rattle, lick, cartwheel, sing, hug are NEVER matches for box.damage, box.unlock.*, box.search, or box.lock.pick. Preserve them as GENERAL_WORLD_ACTION / SILLY_BUT_VALID.
- Example: "shake one of the boxes" → GENERAL_WORLD_ACTION or NEEDS_CLARIFICATION with method=shake. NOT box.damage.
- Example: "lick the box" → GENERAL_WORLD_ACTION method=lick. NOT search/open/use.
- Example: "do a cartwheel" → SILLY_BUT_VALID. NOT move.
- For inspect/search, intended_effect should be "inspect" or "discover_information" unless the player explicitly mentions traps.
- Do not claim interpreter failure for impossible requests (helicopter): use GENERAL_WORLD_ACTION or IMPOSSIBLE class with the intended attempt; Python rejects feasibility.
- Return ONLY JSON.

JSON schema:
{
  "classification": "<one of the classifications above>",
  "matched_action_id": "<authored id or null>",
  "confidence": <0.0-1.0>,
  "action": {
    "class": "<e.g. USE, SEARCH, MOVE, WAIT, MANIPULATE, PERCEIVE, META, BODILY, STRIKE, ...>",
    "target_ref": "<string or null>",
    "tool_ref": "<string or null>",
    "method": "<string or null>",
    "intended_effect": "<string or null>",
    "manner": "<string or null>",
    "destination": "<string or null>",
    "utterance": "<string or null>",
    "query_focus": "<for questions: box_count|named_box|inventory|visible|passage|footsteps|... or null>"
  },
  "ambiguities": ["..."],
  "needs_clarification": <bool>,
  "understood": <bool>
}
"""


class InterpreterUnavailable(RuntimeError):
    """Raised when Ollama is required but unreachable."""


def ollama_reachable(url: str = 'http://127.0.0.1:11434/api/tags', timeout: float = 2.0) -> bool:
    try:
        request = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


# Methods that must never be forced into these authored ops
_METHOD_BLOCKLIST = {
    'box.damage': {'shake', 'rattle', 'lick', 'taste', 'sniff', 'smell', 'sing', 'hug', 'kiss'},
    'box.unlock.player': {'shake', 'rattle', 'lick', 'hit', 'smash', 'break', 'punch', 'cartwheel'},
    'box.unlock.other': {'shake', 'rattle', 'lick', 'hit', 'smash', 'break', 'punch', 'cartwheel'},
    'box.search': {'shake', 'rattle', 'lick', 'cartwheel', 'sing'},
    'box.inspect': {'shake', 'rattle', 'lick', 'smash', 'break', 'cartwheel'},
    'box.lock.pick': {'shake', 'rattle', 'lick', 'smash', 'key', 'unlock'},
}


def validate_authored_match(raw: dict, player_text: str = '') -> dict:
    """Demote forced authored matches that do not genuinely fit the player's method/text."""
    out = dict(raw)
    classification = str(out.get('classification') or '').upper()
    matched = out.get('matched_action_id')
    if classification != 'MATCH_AUTHORED_ACTION' or not matched:
        return out

    action = out.get('action') if isinstance(out.get('action'), dict) else {}
    method = str(action.get('method') or out.get('method') or '').lower()
    effect = str(action.get('intended_effect') or out.get('intended_effect') or '').lower()
    utterance = str(action.get('utterance') or out.get('utterance') or '').lower()
    blob = f'{method} {effect} {utterance} {player_text.lower()}'

    blocked = _METHOD_BLOCKLIST.get(str(matched), set())
    if any(b in blob for b in blocked):
        out['classification'] = 'GENERAL_WORLD_ACTION'
        out['matched_action_id'] = None
        out['notes'] = (str(out.get('notes') or '') + ' demoted_forced_authored_match').strip()
        action = dict(action) if action else {}
        if 'shake' in blob or 'rattle' in blob:
            action['class'] = 'MANIPULATE'
            action['method'] = 'shake'
            action['intended_effect'] = action.get('intended_effect') or 'shake/test'
            out['needs_clarification'] = True
            ambs = list(out.get('ambiguities') or [])
            if 'which box' not in [str(a).lower() for a in ambs]:
                ambs.append('which box')
            out['ambiguities'] = ambs
            out['classification'] = 'NEEDS_CLARIFICATION'
        elif 'lick' in blob:
            action['class'] = 'LICK'
            action['method'] = 'lick'
        elif 'cartwheel' in blob:
            out['classification'] = 'SILLY_BUT_VALID'
            action['class'] = 'BODILY'
            action['method'] = 'cartwheel'
        out['action'] = action
        return out
    return out


def normalize_intent(raw: dict, player_text: str = '') -> Intent:
    if not isinstance(raw, dict):
        return Intent(
            action_class='UNINTERPRETABLE',
            classification='UNINTERPRETABLE',
            understood=False,
            notes='non-object interpreter payload',
            raw={},
        )

    raw = validate_authored_match(raw, player_text=player_text)
    # Nested action object (LLM schema) or flat heuristic fields
    action = raw.get('action') if isinstance(raw.get('action'), dict) else {}
    flat = raw

    action_class = (
        action.get('class')
        or flat.get('action_class')
        or (flat.get('action') if isinstance(flat.get('action'), str) else None)
        or 'GENERAL_WORLD_ACTION'
    )
    if not isinstance(action_class, str) or not action_class.strip():
        action_class = 'GENERAL_WORLD_ACTION'
    action_class = action_class.strip().upper().replace(' ', '_')

    classification = str(raw.get('classification') or '').strip().upper() or None
    if classification not in CLASSIFICATIONS:
        classification = _infer_classification(action_class, raw)

    matched = raw.get('matched_action_id')
    if matched is not None:
        matched = str(matched).strip() or None

    target = _str_or_none(action.get('target_ref') or action.get('target') or flat.get('target'))
    tool = _str_or_none(action.get('tool_ref') or action.get('tool') or flat.get('tool'))
    method = _str_or_none(action.get('method') or flat.get('method'))
    intended = _str_or_none(action.get('intended_effect') or flat.get('intended_effect'))
    manner = _str_or_none(action.get('manner') or flat.get('manner'))
    destination = _str_or_none(action.get('destination') or flat.get('destination'))
    utterance = _str_or_none(action.get('utterance') or flat.get('utterance'))
    query_focus = _str_or_none(action.get('query_focus') or flat.get('query_focus'))

    ambiguities = raw.get('ambiguities') or []
    if not isinstance(ambiguities, list):
        ambiguities = [str(ambiguities)]
    ambiguities = [str(a) for a in ambiguities if a]

    needs_clarification = bool(raw.get('needs_clarification'))
    if classification == 'NEEDS_CLARIFICATION':
        needs_clarification = True

    understood = raw.get('understood')
    if understood is None:
        understood = classification != 'UNINTERPRETABLE'
    understood = bool(understood)
    if classification == 'UNINTERPRETABLE':
        understood = False
        action_class = 'UNINTERPRETABLE'

    # Overlay authored match canonical fields
    fields = {
        'action_class': action_class,
        'target': target,
        'tool': tool,
        'method': method,
        'intended_effect': intended,
        'manner': manner,
        'destination': destination,
        'utterance': utterance,
    }
    if classification == 'MATCH_AUTHORED_ACTION' and matched:
        fields = apply_authored_match(fields, matched)

    confidence = raw.get('confidence')
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None

    seq = raw.get('sequence') or []
    if not isinstance(seq, list):
        seq = []

    return Intent(
        action_class=str(fields['action_class']).upper().replace(' ', '_'),
        target=fields.get('target'),
        tool=fields.get('tool'),
        method=fields.get('method'),
        intended_effect=fields.get('intended_effect'),
        manner=fields.get('manner'),
        destination=fields.get('destination'),
        utterance=fields.get('utterance'),
        sequence=[normalize_intent(x).to_dict() for x in seq if isinstance(x, dict)],
        raw=raw,
        understood=understood,
        notes=str(raw.get('notes') or ''),
        classification=classification,
        matched_action_id=matched,
        confidence=confidence,
        ambiguities=ambiguities,
        needs_clarification=needs_clarification,
        query_focus=query_focus,
    )


def _infer_classification(action_class: str, raw: dict) -> str:
    """Map legacy heuristic action_class onto hierarchical classification."""
    cls = action_class.upper()
    if cls in ('OTHER', 'UNINTERPRETABLE') and raw.get('notes') == 'empty':
        return 'UNINTERPRETABLE'
    if cls == 'OTHER':
        # Heuristic freeform fallback — still "understood" as vague attempt for old tests
        return 'GENERAL_WORLD_ACTION'
    if cls in ('LOOK',):
        return 'GENERAL_WORLD_ACTION'
    if cls in ('LICK',):
        return 'GENERAL_WORLD_ACTION'
    return 'GENERAL_WORLD_ACTION' if cls not in (
        'USE', 'UNLOCK', 'SEARCH', 'INSPECT', 'PICK_LOCK', 'DISABLE', 'BREAK', 'STRIKE',
        'MOVE', 'FLEE', 'ATTACK', 'WARN', 'GIVE', 'NEGOTIATE', 'SURRENDER', 'HIDE',
        'WAIT', 'SIT', 'SPEAK', 'SHOUT', 'MANIPULATE',
    ) else 'MATCH_AUTHORED_ACTION' if cls in (
        'USE', 'UNLOCK', 'SEARCH', 'INSPECT', 'PICK_LOCK', 'DISABLE', 'BREAK',
        'MOVE', 'FLEE', 'ATTACK', 'WARN', 'GIVE', 'NEGOTIATE', 'SURRENDER', 'HIDE',
    ) else 'GENERAL_WORLD_ACTION'


def _str_or_none(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class HeuristicInterpreter:
    """Deterministic NL→intent for tests and offline debug. Not the normal play path."""

    def interpret(self, text: str, perception: dict, authored_actions: list | None = None) -> tuple[dict, Intent]:
        raw = heuristic_raw(text, perception)
        return raw, normalize_intent(raw, player_text=text)


class OllamaInterpreter:
    def __init__(self, model: str = 'mistral', url: str = 'http://127.0.0.1:11434/api/generate'):
        self.model = model
        self.url = url

    def ping(self) -> bool:
        base = self.url.rsplit('/api/', 1)[0]
        return ollama_reachable(f'{base}/api/tags')

    def interpret(self, text: str, perception: dict, authored_actions: list | None = None) -> tuple[dict, Intent]:
        authored_actions = authored_actions or []
        body = {
            'model': self.model,
            'system': INTERPRETER_SYSTEM,
            'prompt': json.dumps({
                'player_text': text,
                'perception': perception,
                'authored_actions': authored_actions,
                'reminder': (
                    'Authored actions are not exhaustive. Preserve non-matching player meaning. '
                    'Do not force shake/lick/cartwheel into search/break/open/use-key.'
                ),
            }, ensure_ascii=False),
            'stream': False,
            'format': 'json',
            'keep_alive': '10m',
            'options': {'temperature': 0.1, 'num_predict': 350, 'num_ctx': 4096},
        }
        request = urllib.request.Request(
            self.url, data=json.dumps(body).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except urllib.error.URLError as exc:
            raise InterpreterUnavailable(
                f'Ollama interpreter unavailable at {self.url}. '
                f'Start Ollama with model {self.model!r}, or pass --heuristic for offline tests.'
            ) from exc
        response_text = payload.get('response', '')
        try:
            raw = json.loads(response_text)
        except json.JSONDecodeError:
            raw = {
                'classification': 'UNINTERPRETABLE',
                'matched_action_id': None,
                'understood': False,
                'action': {'class': 'UNINTERPRETABLE', 'utterance': text},
                'ambiguities': ['malformed_llm_json'],
                'needs_clarification': False,
                'notes': 'malformed_llm_json',
                'llm_response_text': response_text[:2000],
            }
        return raw, normalize_intent(raw, player_text=text)


def heuristic_raw(text: str, perception: dict) -> dict:
    """Legacy deterministic parser for unit tests only. Do not extend for POC coverage."""
    t = ' '.join(text.lower().strip().split())
    if not t:
        return {'action_class': 'OTHER', 'notes': 'empty', 'classification': 'UNINTERPRETABLE', 'understood': False}

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
        return {'action_class': 'SEARCH', 'target': 'boxes', 'method': 'careful', 'intended_effect': 'discover_information'}
    if re.search(r'\b(inspect|examine|look at|study).*(box|table|junction|arrow|track)', t):
        target = 'boxes'
        if 'junction' in t or 'arrow' in t or 'track' in t:
            target = 'junction'
        return {'action_class': 'INSPECT', 'target': target, 'method': 'look', 'intended_effect': 'inspect'}

    # Disable trap
    if re.search(r'\b(disable|disarm|defuse|safe.*trap)\b', t):
        return {'action_class': 'DISABLE', 'target': 'trap', 'method': 'disable_device', 'intended_effect': 'safe_lock'}

    # Break / smash / strike box or wall (before open/key so "smash open" is not USE)
    if re.search(r'\b(smash|break|bash|punch|strike|hit|destroy)\b', t):
        if re.search(r'\bwall\b', t):
            return {'action_class': 'STRIKE', 'target': 'stone_wall', 'tool': 'fist' if 'punch' in t or 'fist' in t else None,
                    'intended_effect': 'break_through', 'method': 'force'}
        target = 'named_box' if re.search(r'\b(my |named)\b', t) else 'box'
        tool = 'sword_pommel' if 'pommel' in t or 'sword' in t else None
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
