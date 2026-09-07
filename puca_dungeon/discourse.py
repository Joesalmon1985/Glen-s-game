"""Pending yes/no and exclusive-choice discourse on WorldState."""
from __future__ import annotations

import re
from typing import Any, Optional, Tuple

from puca_dungeon.models import WorldState

Reply = Tuple[str, Any]

_AFFIRM = re.compile(
    r'^\s*(yes|y|yeah|yep|yup|aye|sure|ok|okay|confirm|do\s+it|go\s+ahead)\s*[.!]?\s*$',
    re.IGNORECASE,
)
_REJECT = re.compile(
    r"^\s*(no|n|nope|nah|cancel|never\s*mind|nevermind|don't|dont|do\s+not)\s*[.!]?\s*$",
    re.IGNORECASE,
)


def set_pending_binary(
    world: WorldState,
    prompt: str,
    confirm_intent_dict: dict,
) -> None:
    """Ask a yes/no question whose affirmative resolves to confirm_intent_dict."""
    world.pending_discourse = {
        'shape': 'binary',
        'prompt': str(prompt or '').strip(),
        'options': [
            {'id': 'yes', 'label': 'yes'},
            {'id': 'no', 'label': 'no'},
        ],
        'antecedent': dict(confirm_intent_dict or {}),
    }


def set_pending_exclusive(
    world: WorldState,
    prompt: str,
    options: list,
) -> None:
    """Ask an exclusive choice; answers must name an option, not bare yes."""
    normalized: list[dict] = []
    for opt in options or []:
        if isinstance(opt, dict):
            oid = str(opt.get('id') or opt.get('label') or '').strip()
            label = str(opt.get('label') or oid).strip()
            if not oid:
                continue
            entry = {'id': oid, 'label': label}
            if 'intent' in opt:
                entry['intent'] = opt['intent']
            if 'antecedent' in opt:
                entry['antecedent'] = opt['antecedent']
            normalized.append(entry)
        else:
            s = str(opt).strip()
            if s:
                normalized.append({'id': s, 'label': s})
    world.pending_discourse = {
        'shape': 'exclusive_choice',
        'prompt': str(prompt or '').strip(),
        'options': normalized,
        'antecedent': None,
    }


def clear_pending(world: WorldState) -> None:
    world.pending_discourse = None


def _match_option(text: str, options: list) -> Optional[dict]:
    raw = (text or '').strip().lower()
    if not raw:
        return None
    for opt in options:
        if not isinstance(opt, dict):
            continue
        oid = str(opt.get('id') or '').strip().lower()
        label = str(opt.get('label') or '').strip().lower()
        if oid and (raw == oid or raw == f'option {oid}'):
            return opt
        if label and (raw == label or label in raw or raw in label):
            return opt
    return None


def resolve_affirmative(text: str, world: WorldState) -> Reply:
    """Resolve player reply against pending discourse.

    Returns one of:
      ('confirm', intent_dict)
      ('reject', None)
      ('ambiguous', clarify_prompt)
      ('not_reply', None)
    """
    pending = world.pending_discourse
    if not isinstance(pending, dict):
        return ('not_reply', None)

    shape = str(pending.get('shape') or '').lower()
    prompt = str(pending.get('prompt') or '').strip()
    options = list(pending.get('options') or [])
    stripped = (text or '').strip()

    if shape == 'binary':
        if _AFFIRM.match(stripped):
            antecedent = pending.get('antecedent')
            if not isinstance(antecedent, dict) or not antecedent:
                return (
                    'ambiguous',
                    prompt or 'What exactly are you confirming?',
                )
            clear_pending(world)
            return ('confirm', dict(antecedent))
        if _REJECT.match(stripped):
            clear_pending(world)
            return ('reject', None)
        return ('not_reply', None)

    if shape == 'exclusive_choice':
        # Bare yes/no never selects the first option.
        if _AFFIRM.match(stripped):
            labels = [
                str(o.get('label') or o.get('id') or '')
                for o in options
                if isinstance(o, dict)
            ]
            labels = [l for l in labels if l]
            if labels:
                joined = '; '.join(labels)
                clarify = (
                    f'Which do you mean? {joined}'
                    if not prompt
                    else f'{prompt} Which option: {joined}?'
                )
            else:
                clarify = prompt or 'Which option do you mean?'
            return ('ambiguous', clarify)
        if _REJECT.match(stripped):
            clear_pending(world)
            return ('reject', None)

        matched = _match_option(stripped, options)
        if matched is not None:
            intent = matched.get('intent') or matched.get('antecedent')
            if isinstance(intent, dict):
                clear_pending(world)
                return ('confirm', dict(intent))
            # Option id alone — caller may expand; still a confirm payload.
            clear_pending(world)
            return (
                'confirm',
                {
                    'matched_action_id': matched.get('id'),
                    'utterance': matched.get('label') or matched.get('id'),
                    'from_discourse_option': True,
                },
            )

        if options:
            labels = [
                str(o.get('label') or o.get('id') or '')
                for o in options
                if isinstance(o, dict)
            ]
            labels = [l for l in labels if l]
            joined = '; '.join(labels) if labels else 'one of the options'
            return (
                'ambiguous',
                f'Please choose among: {joined}.',
            )
        return ('ambiguous', prompt or 'Please clarify your choice.')

    return ('not_reply', None)
