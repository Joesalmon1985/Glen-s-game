"""Layer A — semantic metamorphic pairs and combinatorial fuzz for action families."""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from typing import Iterable, Iterator


MAJOR_FAMILIES = (
    'perceive',
    'move',
    'use',
    'attack',
    'social',
    'open',
    'impossible',
)

QUOTA_PER_FAMILY = 100


@dataclass
class FuzzCase:
    family: str
    utterance: str
    expect_class_any: tuple[str, ...] = ()
    forbid_class: tuple[str, ...] = ()
    forbid_passage_change: bool = False
    note: str = ''
    pair_id: str = ''
    enforce_class: bool = True  # False for typo-mutated strings


# --- template banks ---------------------------------------------------------

PERCEIVE_STEMS = [
    'look around',
    'look around carefully',
    'examine the surroundings',
    'survey the area',
    'scan the room',
    'peer about',
    'observe carefully',
    'what do I see',
    'take a look',
    'glance around',
    'check my surroundings',
    'inspect the alcove',
    'study the scene',
    'look about me',
]

MOVE_STEMS = [
    'go north',
    'walk north',
    'continue north',
    'head north',
    'press on north',
    'go west',
    'go east',
    'leave the alcove',
    'keep walking',
    'move forward',
    'head deeper',
    'retreat back',
    'go back',
    'walk past the table',
]

USE_STEMS = [
    'use the key',
    "use the key I've got",
    'use my key',
    'try the key',
    'drink my potion',
    'use potion',
    'eat a provision',
    'eat food',
    'draw my sword',
    'ready my sword',
    'put away the sword',
]

ATTACK_STEMS = [
    'attack',
    'attack the enemy',
    'strike with my sword',
    'I swing at it',
    'fight',
    'kill it',
    'stab the beast',
    'slash',
    'hit it hard',
    'attack the wall',
    'attack the boxes',
]

SOCIAL_STEMS = [
    'seduce the enemy',
    'sing a song',
    'charm them',
    'negotiate',
    'ask politely',
    'threaten them',
    'beg for mercy',
    'compliment the boxes',
    'tell a joke',
    'persuade it to leave',
]

OPEN_STEMS = [
    'open the box with my name on it',
    'open my box',
    'open the named casket',
    'open the lid with my name',
    'open named box',
    'crack open my casket',
    'open the marked box',
    'lift the lid with my name',
]

IMPOSSIBLE_STEMS = [
    'turn into a dragon',
    'become invisible',
    'summon a dragon',
    'fly to the moon',
    'teleport to victory',
    'cast fireball',
    'wish for immortality',
    'phase through the wall',
    'stop time',
    'become a god',
]

PARAPHRASE_PREFIXES = [
    '',
    'I ',
    'I try to ',
    'I carefully ',
    'lemme ',
    'gonna ',
    'please ',
    'okay I will ',
    'right, ',
]

PARAPHRASE_SUFFIXES = [
    '',
    ' now',
    ' please',
    ' carefully',
    ' real quick',
    '!',
    '.',
    ' then',
]

SLANG_SUBS = [
    ('look', 'peek'),
    ('around', 'about'),
    ('go', 'head'),
    ('walk', 'trek'),
    ('attack', 'whack'),
    ('open', 'crack'),
    ('drink', 'quaff'),
    ('enemy', 'critter'),
]


def _typo_mutations(text: str, rng: random.Random, n: int = 2) -> list[str]:
    """Simple character mutations for offline fuzz."""
    out = []
    if len(text) < 3:
        return out
    for _ in range(n):
        chars = list(text)
        op = rng.choice(['swap', 'drop', 'dup', 'case'])
        i = rng.randint(0, len(chars) - 1)
        if op == 'swap' and i + 1 < len(chars):
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        elif op == 'drop' and len(chars) > 4:
            del chars[i]
        elif op == 'dup':
            chars.insert(i, chars[i])
        elif op == 'case':
            chars[i] = chars[i].swapcase()
        mut = ''.join(chars)
        if mut != text:
            out.append(mut)
    return out


def _expand_stem(stem: str, rng: random.Random) -> list[tuple[str, bool]]:
    """Return (utterance, enforce_class) pairs. Typos are generated but not class-enforced."""
    variants: list[tuple[str, bool]] = []
    for pre, suf in itertools.product(PARAPHRASE_PREFIXES[:6], PARAPHRASE_SUFFIXES[:5]):
        s = f'{pre}{stem}{suf}'.strip()
        variants.append((s, True))
    for a, b in SLANG_SUBS:
        if a in stem:
            variants.append((stem.replace(a, b, 1), True))
    for mut in _typo_mutations(stem, rng, n=3):
        variants.append((mut, False))
    seen = set()
    uniq: list[tuple[str, bool]] = []
    for v, enforce in variants:
        key = v.strip()
        if key and key not in seen:
            seen.add(key)
            uniq.append((key, enforce))
    return uniq


def _family_expectations(family: str) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    if family == 'perceive':
        return (('PERCEPTION_QUERY',), ('MATCH_AUTHORED_ACTION',), True)
    if family == 'impossible':
        return (
            ('IMPOSSIBLE_ATTEMPT', 'META_INPUT', 'META_REQUEST', 'NO_ACTIONABLE_INTENT', 'UNINTERPRETABLE'),
            ('MATCH_AUTHORED_ACTION',),
            True,
        )
    if family == 'social':
        return (
            ('SOCIAL_ACTION', 'SYSTEMIC_ACTION', 'NEEDS_CLARIFICATION', 'NO_ACTIONABLE_INTENT'),
            (),
            False,
        )
    if family == 'use':
        return (
            ('SYSTEMIC_ACTION', 'MATCH_AUTHORED_ACTION', 'UNGROUNDED_ENTITY', 'GENERAL_WORLD_ACTION'),
            (),
            False,
        )
    if family == 'open':
        return (('MATCH_AUTHORED_ACTION', 'SYSTEMIC_ACTION', 'NEEDS_CLARIFICATION'), (), False)
    if family == 'move':
        return (('MATCH_AUTHORED_ACTION', 'SYSTEMIC_ACTION', 'GENERAL_WORLD_ACTION'), (), False)
    if family == 'attack':
        return (
            ('SYSTEMIC_ACTION', 'MATCH_AUTHORED_ACTION', 'GENERAL_WORLD_ACTION', 'SOCIAL_ACTION'),
            (),
            False,
        )
    return ((), (), False)


STEMS = {
    'perceive': PERCEIVE_STEMS,
    'move': MOVE_STEMS,
    'use': USE_STEMS,
    'attack': ATTACK_STEMS,
    'social': SOCIAL_STEMS,
    'open': OPEN_STEMS,
    'impossible': IMPOSSIBLE_STEMS,
}


def generate_family_cases(family: str, quota: int = QUOTA_PER_FAMILY, seed: int = 91) -> list[FuzzCase]:
    rng = random.Random(seed + hash(family) % 10007)
    stems = STEMS[family]
    expect, forbid, no_move = _family_expectations(family)
    pool: list[tuple[str, bool]] = []
    for stem in stems:
        pool.extend(_expand_stem(stem, rng))
    fillers = ['now', 'please', 'slowly', 'again', 'mate', 'boss']
    while len(pool) < quota:
        stem = rng.choice(stems)
        pool.append((
            f'{rng.choice(PARAPHRASE_PREFIXES)}{stem} {rng.choice(fillers)}'.strip(),
            True,
        ))
    cases = []
    for i, (utt, enforce) in enumerate(pool[:quota]):
        cases.append(FuzzCase(
            family=family,
            utterance=utt,
            expect_class_any=expect,
            forbid_class=forbid,
            forbid_passage_change=no_move and family in ('perceive', 'impossible') and enforce,
            note='template_expand',
            pair_id=f'{family}:{i}',
            enforce_class=enforce,
        ))
    return cases


def generate_metamorphic_pairs(family: str, n: int = 20, seed: int = 91) -> list[tuple[FuzzCase, FuzzCase]]:
    """Pairs that should share classification family under paraphrase."""
    rng = random.Random(seed + 17)
    stems = STEMS[family]
    expect, forbid, no_move = _family_expectations(family)
    pairs = []
    for i in range(n):
        stem = stems[i % len(stems)]
        a = FuzzCase(family, stem, expect, forbid, no_move, 'meta_a', f'{family}:pair:{i}:a')
        expanded = [u for u, enf in _expand_stem(stem, rng) if enf]
        b_utt = rng.choice(expanded[1:] or [stem])
        b = FuzzCase(family, b_utt, expect, forbid, no_move, 'meta_b', f'{family}:pair:{i}:b')
        pairs.append((a, b))
    return pairs


def generate_all_layer_a(seed: int = 91, per_family: int = QUOTA_PER_FAMILY) -> dict[str, list[FuzzCase]]:
    return {fam: generate_family_cases(fam, per_family, seed) for fam in MAJOR_FAMILIES}


def generate_compound_cases(n: int = 50, seed: int = 91) -> list[str]:
    rng = random.Random(seed)
    left = [
        'draw my sword',
        'look around',
        'open my box',
        'drink my potion',
        'go north',
        'attack',
        'use the key',
        'sing',
        'wait',
    ]
    right = [
        'go back to the boxes',
        'open the named casket',
        'walk north',
        'attack the enemy',
        'eat a provision',
        'look around carefully',
        'flee',
        'sit down',
        'go west',
    ]
    connectors = [' and ', ' then ', ', then ', ' and also ', ' before I ']
    out = []
    for i in range(n):
        out.append(rng.choice(left) + rng.choice(connectors) + rng.choice(right))
    # force some contradictory compounds
    out[:5] = [
        'open my box but also leave it shut and walk north',
        'attack the boxes without touching them',
        'go west and east at the same time',
        'drink my potion and also save it unused',
        'draw sword and go back to boxes and open',
    ]
    return out[:n]


def generate_ambiguity_cases(n: int = 50, seed: int = 91) -> list[str]:
    base = [
        'do it', 'yes', 'that', 'the other one', 'go there', 'open it',
        'maybe', 'whatever', 'you decide', 'same as before', 'continue',
        'the left one', 'the right one', 'both', 'neither', 'huh?',
    ]
    rng = random.Random(seed)
    out = list(base)
    while len(out) < n:
        out.append(rng.choice(base) + rng.choice(['', '?', '...', ' please']))
    return out[:n]


def generate_discourse_cases(n: int = 50, seed: int = 91) -> list[str]:
    """Anaphora / pronoun discourse attacks (player-facing only)."""
    base = [
        'open it', 'take that', 'follow them', 'go there', 'use it',
        'hit him', 'talk to her', 'pick those up', 'leave it',
        'the one with my name', 'that casket', 'those tracks',
        'the western one', 'the eastern path', 'this place',
        'do the same thing', 'again', 'once more',
    ]
    rng = random.Random(seed + 3)
    out = list(base)
    while len(out) < n:
        out.append(rng.choice(base))
    return out[:n]
