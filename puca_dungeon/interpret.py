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


INTERPRETER_SYSTEM = """You interpret player text for a Fighting Fantasy gamebook into structured intent JSON.
You do NOT decide success, failure, damage, which paragraph to turn to, inventory changes, or combat outcomes.

You receive three inputs:
1) exact raw player text
2) public/perceptual world state (Adventure Sheet summary + current passage perception; no secret branch numbers beyond authored descriptors)
3) currently available AUTHORED ACTION DESCRIPTORS — internal semantic targets (passage choices, combat actions, potion/provision). These are NOT a player menu.

Follow this EXACT three-step procedure (stop at the first match):

STEP 1 — AUTHORED PATH:
Does the player's intent substantially match one authored action (a passage choice, attack/flee while fighting, drink potion, eat provision)?
If YES → classification = MATCH_AUTHORED_ACTION, set matched_action_id to that id, action.class TURN_TO or ATTACK/FLEE/USE as appropriate.
Do NOT force unrelated verbs into a choice.

STEP 2 — WORLD / COMBAT ACTION:
If no authored match: is there still a clear embodied attempt the rules engine might apply (attack when not offered, use an inventory item by name, ask about Skill/Stamina/Luck/inventory, look around)?
If YES → GENERAL_WORLD_ACTION or PERCEPTION_QUERY. Preserve the player's meaning. Python may no-op.

STEP 3 — DISMISS:
Otherwise classify as SILLY_BUT_VALID, META_REQUEST, UNINTERPRETABLE, or NEEDS_CLARIFICATION.
The narrator will dismiss without changing paragraph.

Also set step_selected to 1, 2, or 3 for debugging.

Rules:
- Never invent tools the player did not imply.
- Never invent a matched_action_id that is not in the authored list.
- "open the box" / "open my box" matches open_named_box when that action is listed.
- "continue north" / "keep walking" matches continue_north when listed.
- Cartwheel/dance/sing while choices exist → SILLY_BUT_VALID (step 3), not a turn_to.
- "what are my stats" / "inventory" → PERCEPTION_QUERY (step 2).
- Return ONLY JSON.

JSON schema:
{
  "classification": "<one of MATCH_AUTHORED_ACTION|GENERAL_WORLD_ACTION|PERCEPTION_QUERY|META_REQUEST|SILLY_BUT_VALID|UNINTERPRETABLE|NEEDS_CLARIFICATION>",
  "matched_action_id": "<authored id or null>",
  "step_selected": <1|2|3>,
  "confidence": <0.0-1.0>,
  "action": {
    "class": "<e.g. TURN_TO, ATTACK, FLEE, USE, PERCEIVE, META, BODILY, ...>",
    "target_ref": "<string or null>",
    "tool_ref": "<string or null>",
    "method": "<string or null>",
    "intended_effect": "<string or null>",
    "manner": "<string or null>",
    "destination": "<string or null>",
    "utterance": "<string or null>",
    "query_focus": "<inventory|sheet|passage|visible|... or null>"
  },
  "ambiguities": ["..."],
  "needs_clarification": <bool>,
  "understood": <bool>
}
"""


class InterpreterUnavailable(RuntimeError):
    """Raised when Ollama is required but unreachable."""


def ollama_reachable(url: str = 'http://127.0.0.1:11434/api/tags', timeout: float = 2.0) -> bool:
    """True when the tags endpoint responds with HTTP success (model list may still be empty)."""
    try:
        request = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def ollama_list_models(url: str = 'http://127.0.0.1:11434/api/tags', timeout: float = 2.0) -> Optional[list[str]]:
    """Return installed model names, or None if the service is unreachable / invalid."""
    try:
        request = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if not (200 <= response.status < 300):
                return None
            payload = json.loads(response.read().decode('utf-8'))
        raw_models = payload.get('models', []) if isinstance(payload, dict) else []
        return [
            str(item.get('name'))
            for item in raw_models
            if isinstance(item, dict) and item.get('name')
        ]
    except Exception:
        return None


def ollama_model_ready(
    model: str = 'mistral',
    url: str = 'http://127.0.0.1:11434/api/tags',
    timeout: float = 2.0,
) -> bool:
    """True when Ollama is reachable and the requested model tag is installed."""
    models = ollama_list_models(url=url, timeout=timeout)
    if models is None:
        return False
    return any(name == model or name.startswith(model + ':') for name in models)


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


def normalize_intent(
    raw: dict,
    player_text: str = '',
    authored_actions: list | None = None,
) -> Intent:
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

    turn_to = action.get('turn_to') if 'turn_to' in action else flat.get('turn_to')
    if turn_to is not None:
        try:
            turn_to = int(turn_to)
        except (TypeError, ValueError):
            turn_to = None

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
        'turn_to': turn_to,
    }
    if classification == 'MATCH_AUTHORED_ACTION' and matched:
        fields = apply_authored_match(fields, matched, authored_actions=authored_actions)

    turn_to = fields.get('turn_to', turn_to)
    if turn_to is not None:
        try:
            turn_to = int(turn_to)
        except (TypeError, ValueError):
            turn_to = None

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
        turn_to=turn_to,
        utterance=fields.get('utterance'),
        sequence=[normalize_intent(x, authored_actions=authored_actions).to_dict() for x in seq if isinstance(x, dict)],
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


def match_authored_heuristic(text: str, authored_actions: list | None) -> Optional[dict]:
    """Match player text to an authored action by id / label / aliases (tests/offline)."""
    if not authored_actions:
        return None
    t = ' '.join((text or '').lower().strip().split())
    if not t:
        return None

    scored: list[tuple[int, dict]] = []
    for action in authored_actions:
        if not isinstance(action, dict) or not action.get('id'):
            continue
        phrases: list[str] = []
        aid = str(action.get('id') or '')
        phrases.append(aid.replace('_', ' ').replace('.', ' '))
        desc = str(action.get('description') or '')
        label = desc.split(' (also:')[0].strip()
        if label:
            phrases.append(label)
        for alias in action.get('aliases') or []:
            if alias:
                phrases.append(str(alias))
        # Also use label field if present on compact payload
        if action.get('label'):
            phrases.append(str(action['label']))

        best_len = 0
        for phrase in phrases:
            p = ' '.join(phrase.lower().strip().split())
            if not p:
                continue
            if t == p or p in t or t in p:
                best_len = max(best_len, len(p))
                continue
            # Token containment: "continue north" vs alias "go north"
            t_tokens = set(t.split())
            p_tokens = set(p.split())
            if p_tokens and p_tokens <= t_tokens:
                best_len = max(best_len, len(p))
        if best_len:
            scored.append((best_len, action))

    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


class HeuristicInterpreter:
    """Deterministic NL→intent for tests and offline debug. Not the normal play path."""

    def interpret(self, text: str, perception: dict, authored_actions: list | None = None) -> tuple[dict, Intent]:
        matched = match_authored_heuristic(text, authored_actions)
        if matched:
            op = matched.get('operation') or ''
            action_class = 'TURN_TO'
            if op == 'combat_attack':
                action_class = 'ATTACK'
            elif op == 'combat_flee':
                action_class = 'FLEE'
            elif op in ('use_potion', 'eat_provision'):
                action_class = 'USE'
            raw = {
                'classification': 'MATCH_AUTHORED_ACTION',
                'matched_action_id': matched.get('id'),
                'understood': True,
                'confidence': 0.95,
                'action': {
                    'class': action_class,
                    'turn_to': matched.get('turn_to'),
                    'utterance': text,
                },
                'needs_clarification': False,
                'notes': 'heuristic_authored_match',
            }
            return raw, normalize_intent(raw, player_text=text, authored_actions=authored_actions)

        raw = heuristic_raw(text, perception)
        return raw, normalize_intent(raw, player_text=text, authored_actions=authored_actions)


class OllamaInterpreter:
    def __init__(self, model: str = 'mistral', url: str = 'http://127.0.0.1:11434/api/generate'):
        self.model = model
        self.url = url

    def ping(self) -> bool:
        base = self.url.rsplit('/api/', 1)[0]
        return ollama_model_ready(self.model, f'{base}/api/tags')

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
        return raw, normalize_intent(raw, player_text=text, authored_actions=authored_actions)


def heuristic_raw(text: str, perception: dict) -> dict:
    """Legacy deterministic parser for unit tests only. Do not extend for POC coverage."""
    t = ' '.join(text.lower().strip().split())
    if not t:
        return {'action_class': 'OTHER', 'notes': 'empty', 'classification': 'UNINTERPRETABLE', 'understood': False}

    # Sheet / inventory perception (FF Adventure Sheet)
    if re.search(
        r'\b(inventory|possessions|what am i carrying|what am i holding|'
        r'what is my inventory|what\'?s in my (pack|bag|backpack)|'
        r'my (stats|scores|sheet)|adventure sheet|'
        r'what (is|are) my (skill|stamina|luck|stats|scores))\b',
        t,
    ):
        focus = 'inventory'
        if re.search(r'\b(skill|stamina|luck|stats|scores|sheet)\b', t) and 'inventory' not in t:
            focus = 'sheet'
        return {
            'action_class': 'QUERY',
            'classification': 'PERCEPTION_QUERY',
            'query_focus': focus,
            'intended_effect': 'observe',
            'utterance': text,
            'understood': True,
        }

    # Silly embodied dismissals
    if re.search(r'\b(cartwheel|somersault|pirouette|backflip)\b', t):
        return {
            'action_class': 'BODILY',
            'classification': 'SILLY_BUT_VALID',
            'method': 'cartwheel',
            'utterance': text,
            'intended_effect': 'flourish',
            'understood': True,
        }

    # Potion / provisions (even if authored list omitted them after use)
    if re.search(r'\b(drink|quaff|use)\b.*\bpotion\b|\bpotion\b.*\b(drink|quaff)\b', t):
        return {
            'action_class': 'USE',
            'classification': 'GENERAL_WORLD_ACTION',
            'matched_action_id': 'item.use_potion',
            'target': 'potion',
            'tool': 'potion',
            'intended_effect': 'restore',
            'utterance': text,
            'understood': True,
        }
    if re.search(r'\b(eat|consume)\b.*\bprovisions?\b|\beat\b.*\bfood\b', t):
        return {
            'action_class': 'USE',
            'classification': 'GENERAL_WORLD_ACTION',
            'matched_action_id': 'item.eat_provision',
            'target': 'provision',
            'intended_effect': 'restore_stamina',
            'utterance': text,
            'understood': True,
        }

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
