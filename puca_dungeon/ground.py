"""Bind intent to current-passage entities, tools, and authored actions."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from puca_dungeon.models import Intent, WorldState

PassageLike = Union[dict, Any]

_ABSENT_VEHICLES = frozenset({'tank', 'tanks', 'helicopter', 'helicopters', 'chopper', 'choppers'})
_MAGIC_IMPOSSIBLE = frozenset({
    'dragon', 'cthulhu', 'teleport', 'fly', 'moon', 'transform', 'summon',
})


@dataclass
class Grounding:
    bindings: dict = field(default_factory=dict)
    ambiguous: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    notes: str = ''
    grounded: Optional[bool] = None
    clarification_prompt: str = ''

    def to_dict(self) -> dict:
        return {
            'bindings': dict(self.bindings),
            'ambiguous': list(self.ambiguous),
            'failed': list(self.failed),
            'notes': self.notes,
            'grounded': self.grounded,
            'clarification_prompt': self.clarification_prompt,
        }


def _passage_field(passage: PassageLike, key: str, default=None):
    if isinstance(passage, dict):
        return passage.get(key, default)
    return getattr(passage, key, default)


def _find_authored(authored_actions: Optional[list[dict]], action_id: Optional[str]) -> Optional[dict]:
    if not action_id or not authored_actions:
        return None
    for action in authored_actions:
        if str(action.get('id') or '') == str(action_id):
            return action
    return None


def _inventory_blob(world: WorldState) -> str:
    parts: list[str] = []
    for item in world.sheet.inventory or []:
        if isinstance(item, dict):
            parts.append(str(item.get('name') or item.get('id') or item.get('label') or ''))
        else:
            parts.append(str(item))
    if world.sheet.potion and not world.sheet.potion_used:
        parts.append(str(world.sheet.potion))
        parts.append('potion')
    if int(world.sheet.provisions or 0) > 0:
        parts.append('provision')
        parts.append('provisions')
    return ' '.join(parts).lower()


def _passage_entity_blob(passage: PassageLike, world: WorldState) -> str:
    entities = list(_passage_field(passage, 'entities') or [])
    entities.extend(world.visible_entities or [])
    names = [str(e).lower().replace('_', ' ') for e in entities if e]
    # Common diegetic stand-ins for boxes / enemy
    if any('casket' in n or 'box' in n for n in names):
        names.extend(['box', 'boxes', 'casket', 'caskets'])
    if world.combat.active:
        enemy = (world.combat.enemy_name or 'enemy').lower()
        names.extend(['enemy', enemy, 'hound'])
    return ' '.join(names)


def _requested_entity_tokens(intent: Intent) -> list[str]:
    parts = [
        intent.target, intent.tool, intent.destination,
        intent.utterance, intent.method,
    ]
    blob = ' '.join(str(p or '') for p in parts).lower()
    found: list[str] = []
    # Prefer whole-word vehicle matches (avoid 'chopper' substring of 'helicopter')
    for name in ('helicopter', 'tank', 'chopper'):
        if re_word(name, blob) and name not in found:
            found.append('helicopter' if name == 'chopper' else name)
    for tok in ('key', 'potion', 'sword', 'box', 'enemy'):
        if re_word(tok, blob) and tok not in found:
            found.append(tok)
    return found


def re_word(word: str, blob: str) -> bool:
    return bool(re.search(rf'\b{re.escape(word)}\b', blob or ''))


def _entity_present(token: str, world: WorldState, passage: PassageLike) -> bool:
    tok = (token or '').lower().strip()
    if not tok:
        return False
    if tok in _ABSENT_VEHICLES or tok in ('tank', 'helicopter', 'chopper'):
        # Only present if explicitly listed in passage entities / visible
        ent = _passage_entity_blob(passage, world)
        return tok in ent or tok.replace('chopper', 'helicopter') in ent

    inv = _inventory_blob(world)
    ent = _passage_entity_blob(passage, world)

    if tok in ('key', 'keys', 'iron_key'):
        return 'key' in inv
    if tok == 'potion':
        # Keep the potion slot grounded after use so resolve can return
        # potion_already_used instead of inventing entity_absent.
        return 'potion' in inv or bool(world.sheet.potion)
    if tok == 'sword':
        return 'sword' in inv
    if tok in ('box', 'boxes', 'casket', 'caskets'):
        return any(x in ent for x in ('box', 'casket')) or bool(_passage_field(passage, 'entities'))
    if tok in ('enemy', 'hound') or 'enemy' in tok:
        return bool(world.combat.active)
    # Generic: inventory or passage entities
    return tok in inv or tok in ent or tok.replace('_', ' ') in ent


def _genuine_ambiguity_prompt(intent: Intent) -> str:
    """Prompt for real ambiguity only — never a full choice-label menu."""
    ambs = intent.ambiguities or []
    if ambs:
        # Prefer free-text ambiguity notes from the interpreter
        bits = [str(a) for a in ambs if a]
        if bits:
            return 'Which do you mean: ' + '; '.join(bits[:4]) + '?'
    target = (intent.target or intent.tool or '').strip()
    if target:
        return f'Which {target} do you mean?'
    if intent.utterance:
        return 'What exactly do you intend to do?'
    return 'What do you mean?'


def ground_intent(
    world: WorldState,
    intent: Intent,
    passage: PassageLike,
    authored_actions: Optional[list[dict]] = None,
) -> Grounding:
    """Ground free-text intent against entities, inventory, and authored actions."""
    g = Grounding()
    authored_actions = authored_actions or []
    classification = (intent.classification or '').upper()
    cls = (intent.action_class or '').upper()
    matched = intent.matched_action_id

    # --- MATCH_AUTHORED_ACTION: must verify id exists ---
    if classification == 'MATCH_AUTHORED_ACTION':
        authored = _find_authored(authored_actions, matched)
        if authored:
            g.bindings['matched_action_id'] = authored.get('id')
            if authored.get('turn_to') is not None:
                g.bindings['turn_to'] = int(authored['turn_to'])
                if intent.turn_to is None:
                    intent.turn_to = int(authored['turn_to'])
            op = authored.get('operation')
            if op:
                g.bindings['operation'] = op
            g.grounded = True
            g.notes = 'matched_authored_action'
            return g
        g.grounded = False
        g.failed.append('authored_action_absent')
        g.notes = 'matched_id_not_in_authored'
        g.bindings['requested_action_id'] = matched
        return g

    # TURN_TO with verified authored id
    if cls == 'TURN_TO' and matched:
        authored = _find_authored(authored_actions, matched)
        if authored and authored.get('turn_to') is not None:
            g.bindings['matched_action_id'] = matched
            g.bindings['turn_to'] = int(authored['turn_to'])
            intent.turn_to = int(authored['turn_to'])
            if authored.get('operation'):
                g.bindings['operation'] = authored['operation']
            g.grounded = True
            g.notes = 'turn_to_from_authored'
            return g
        if intent.turn_to is not None and authored:
            g.bindings['matched_action_id'] = matched
            g.bindings['turn_to'] = int(intent.turn_to)
            g.grounded = True
            g.notes = 'turn_to_from_intent'
            return g
        g.grounded = False
        g.failed.append('authored_action_absent')
        return g

    # Perception / meta — understood, no entity binding required
    if classification == 'PERCEPTION_QUERY' or cls in ('PERCEIVE', 'QUERY', 'LOOK'):
        g.grounded = True
        g.notes = 'perception'
        return g

    if classification in ('META_INPUT', 'META_REQUEST') or cls == 'META':
        g.grounded = True
        g.notes = 'meta'
        return g

    # Impossible magic: understood but not grounded for magic entities
    if classification == 'IMPOSSIBLE_ATTEMPT' or cls in ('IMPOSSIBLE', 'SUMMON', 'TRANSFORM', 'CAST'):
        blob = ' '.join(filter(None, [intent.utterance, intent.target, intent.method])).lower()
        for magic in _MAGIC_IMPOSSIBLE:
            if magic in blob:
                g.bindings['requested_entity'] = magic
                break
        # Vehicles mentioned in an impossible/summon frame
        for v in ('tank', 'helicopter'):
            if v in blob:
                g.bindings['requested_entity'] = v
                g.failed.append('entity_absent')
                g.grounded = False
                g.notes = 'requested_entity'
                intent.needs_clarification = False
                return g
        g.grounded = False
        g.failed.append('impossible_here')
        g.notes = 'impossible_attempt'
        intent.needs_clarification = False
        return g

    # Ungrounded vehicles / absent entities
    if classification == 'UNGROUNDED_ENTITY':
        tokens = _requested_entity_tokens(intent)
        if not tokens:
            blob = ' '.join(filter(None, [intent.target, intent.tool, intent.utterance])).lower()
            for v in ('tank', 'helicopter'):
                if v in blob:
                    tokens.append(v)
        entity = tokens[0] if tokens else (intent.target or intent.tool or 'unknown')
        g.bindings['requested_entity'] = entity
        g.notes = 'requested_entity'
        g.failed.append('entity_absent')
        g.grounded = False
        intent.needs_clarification = False
        return g

    # Explicit destination "home" — not a local exit
    dest = (intent.destination or '').lower().strip()
    if dest in ('home', 'house', 'outside', 'town') or (
        (intent.intended_effect or '').lower() == 'go_home'
    ):
        g.bindings['requested_destination'] = dest or 'home'
        g.grounded = False
        g.failed.append('destination_absent')
        g.notes = 'destination_absent'
        intent.needs_clarification = False
        return g

    # Combat attack / flee / systemic items with known matched ids
    if matched in ('combat.attack', 'combat.flee'):
        if matched == 'combat.attack' and not world.combat.active:
            g.grounded = False
            g.failed.append('enemy_absent')
            return g
        g.bindings['matched_action_id'] = matched
        g.bindings['target'] = 'enemy' if matched == 'combat.attack' else None
        g.grounded = True
        return g

    if matched in ('item.use_potion', 'item.eat_provision'):
        g.bindings['matched_action_id'] = matched
        if matched == 'item.use_potion' and not _entity_present('potion', world, passage):
            g.grounded = False
            g.failed.append('entity_absent')
            g.bindings['requested_entity'] = 'potion'
            g.notes = 'requested_entity'
            return g
        if matched == 'item.eat_provision' and int(world.sheet.provisions or 0) <= 0:
            g.grounded = False
            g.failed.append('entity_absent')
            g.bindings['requested_entity'] = 'provision'
            g.notes = 'requested_entity'
            return g
        g.grounded = True
        return g

    # Tool / target entity checks for systemic use
    requested = _requested_entity_tokens(intent)
    tool = (intent.tool or '').lower().strip()
    target = (intent.target or '').lower().strip()
    for cand in (tool, target, *requested):
        if not cand:
            continue
        base = cand.replace('iron_', '')
        # Normalize
        if base in _ABSENT_VEHICLES or base in ('tank', 'helicopter', 'chopper'):
            name = 'helicopter' if 'heli' in base or base == 'chopper' else 'tank'
            if not _entity_present(name, world, passage):
                g.bindings['requested_entity'] = name
                g.notes = 'requested_entity'
                g.failed.append('entity_absent')
                g.grounded = False
                intent.needs_clarification = False
                return g
        if base in ('key', 'keys', 'potion', 'sword', 'box', 'boxes', 'enemy'):
            check = 'key' if base.startswith('key') else (
                'box' if base.startswith('box') else base
            )
            if not _entity_present(check, world, passage):
                g.bindings['requested_entity'] = check
                g.notes = 'requested_entity'
                g.failed.append('entity_absent')
                g.grounded = False
                intent.needs_clarification = False
                return g
            g.bindings['tool' if cand == tool else 'target'] = check
            if check == 'key':
                g.bindings['tool'] = 'key'

    # Social / systemic without special entities — grounded as attempt in place
    if classification in ('SOCIAL_ACTION', 'SYSTEMIC_ACTION', 'GENERAL_WORLD_ACTION', 'NO_ACTIONABLE_INTENT'):
        if tool or target:
            # Already checked above; if we got here entities were present or none requested
            g.grounded = True
            g.notes = classification.lower()
            return g
        g.grounded = True
        g.notes = classification.lower()
        return g

    # NEEDS_CLARIFICATION — genuine ambiguity only; never choice-label menus
    if classification == 'NEEDS_CLARIFICATION' or intent.needs_clarification:
        # Impossible / ungrounded-style intents should not clarify
        if classification in ('IMPOSSIBLE_ATTEMPT', 'UNGROUNDED_ENTITY'):
            intent.needs_clarification = False
            g.grounded = False
            return g
        ambs = intent.ambiguities or []
        if not ambs and not intent.target and not intent.tool:
            # Unsupported vague intent — do not invent a menu; resolve handles inability
            intent.needs_clarification = False
            g.grounded = False
            g.notes = 'no_genuine_ambiguity'
            return g
        prompt = _genuine_ambiguity_prompt(intent)
        g.grounded = False
        g.clarification_prompt = prompt
        g.ambiguous.append({
            'ref': intent.target or intent.tool or intent.utterance or 'action',
            'candidates': list(ambs) if ambs else [],
            'prompt': prompt,
        })
        return g

    if world.combat.active and cls in ('ATTACK', 'FLEE', 'FIGHT', 'STRIKE'):
        g.grounded = True
        g.bindings['target'] = 'enemy'
        return g

    # Default: legible systemic attempt in place
    g.grounded = True
    return g
