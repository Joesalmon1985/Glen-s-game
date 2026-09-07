"""Bind intent to current-passage authored actions / turn_to targets."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

from puca_dungeon.models import Intent, WorldState

PassageLike = Union[dict, Any]


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


def _passage_choices(passage: PassageLike) -> list[dict]:
    if isinstance(passage, dict):
        choices = passage.get('choices') or []
    else:
        choices = getattr(passage, 'choices', None) or []
    return [c for c in choices if isinstance(c, dict)]


def _choice_labels(passage: PassageLike) -> list[str]:
    labels = []
    for choice in _passage_choices(passage):
        label = (choice.get('label') or '').strip()
        if label:
            labels.append(label)
    return labels


def _clarification_prompt(passage: PassageLike) -> str:
    labels = _choice_labels(passage)
    if not labels:
        return 'What do you do?'
    if len(labels) == 1:
        return f'Do you mean: {labels[0]}?'
    return 'Which will you do? ' + '; '.join(labels)


def _find_authored(authored_actions: Optional[list[dict]], action_id: Optional[str]) -> Optional[dict]:
    if not action_id or not authored_actions:
        return None
    for action in authored_actions:
        if str(action.get('id') or '') == str(action_id):
            return action
    return None


def ground_intent(
    world: WorldState,
    intent: Intent,
    passage: PassageLike,
    authored_actions: Optional[list[dict]] = None,
) -> Grounding:
    """Ground free-text intent against current passage choices / combat affordances."""
    g = Grounding()
    authored_actions = authored_actions or []
    classification = (intent.classification or '').upper()
    cls = (intent.action_class or '').upper()

    matched = intent.matched_action_id
    authored = _find_authored(authored_actions, matched)

    if classification == 'MATCH_AUTHORED_ACTION' and authored:
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

    # Heuristic: TURN_TO with matched id (even if classification drifted)
    if cls == 'TURN_TO' and matched:
        authored = authored or _find_authored(authored_actions, matched)
        g.bindings['matched_action_id'] = matched
        if authored and authored.get('turn_to') is not None:
            g.bindings['turn_to'] = int(authored['turn_to'])
            intent.turn_to = int(authored['turn_to'])
            g.grounded = True
            g.notes = 'turn_to_from_authored'
            return g
        if intent.turn_to is not None:
            g.bindings['turn_to'] = int(intent.turn_to)
            g.grounded = True
            g.notes = 'turn_to_from_intent'
            return g

    if intent.turn_to is not None:
        g.bindings['turn_to'] = int(intent.turn_to)
        if matched:
            g.bindings['matched_action_id'] = matched
        g.grounded = True
        g.notes = 'explicit_turn_to'
        return g

    # Combat / item ops need little entity binding
    if matched in ('combat.attack', 'combat.flee', 'item.use_potion', 'item.eat_provision'):
        g.bindings['matched_action_id'] = matched
        g.grounded = True
        return g

    if classification in ('PERCEPTION_QUERY', 'META_REQUEST', 'SILLY_BUT_VALID', 'UNINTERPRETABLE'):
        g.grounded = classification != 'UNINTERPRETABLE'
        return g

    if classification == 'NEEDS_CLARIFICATION' or intent.needs_clarification:
        g.grounded = False
        prompt = _clarification_prompt(passage)
        g.clarification_prompt = prompt
        g.ambiguous.append({
            'ref': intent.target or intent.utterance or 'choice',
            'candidates': [c.get('id') for c in _passage_choices(passage)],
            'prompt': prompt,
        })
        return g

    if world.combat.active and cls in ('ATTACK', 'FLEE', 'FIGHT', 'STRIKE'):
        g.grounded = True
        g.bindings['target'] = 'enemy'
        return g

    if cls in ('USE', 'EAT', 'DRINK') or classification == 'GENERAL_WORLD_ACTION':
        # Legible but not necessarily a passage edge — resolve decides dismiss vs item
        g.grounded = True
        if intent.target:
            g.bindings['target_ref'] = intent.target
        return g

    # Default: treat as grounded enough for dismiss/resolve; ambiguity is rare in gamebooks
    g.grounded = True
    return g
