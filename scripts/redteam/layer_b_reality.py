"""Layer B — nonexistent / stale / unreachable entity attacks."""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class RealityCase:
    utterance: str
    category: str  # nonexistent | stale | unreachable
    note: str = ''


NONEXISTENT = [
    'get in the tank',
    'board the helicopter',
    'fly the chopper out of here',
    'drive the jeep north',
    'use the skeleton key I found earlier',
    'wear the invisibility cloak',
    'throw my fireball scroll',
    'bribe the guard with 1000 gold I do not have',
    'call the elevator',
    'open the vault door behind the tapestry',
    'speak to the shopkeeper',
    'buy a torch from the merchant',
    'ride the horse waiting outside',
    'use the magical ring of teleportation',
    'pull the hidden lever that is not here',
    'read the spellbook on the shelf',
    'drink from the fountain of youth',
    'take the crown from the pedestal',
    'unlock the iron gate with the brass key',
    'pet the friendly dog',
    'climb into the hot air balloon',
    'radio for extraction',
    'summon my familiar',
    'open my laptop settings',
    'check my phone for maps',
]

STALE = [
    'open the box I already opened',
    'go back to paragraph 1',
    'return to the arena crowds',
    'talk to the spectators again',
    'use the key from the previous room',
    'attack the giant rat I already killed',
    'drink the potion I already finished',
    'pick up the sword I already have equipped twice',
    'reopen the named casket after leaving',
    'follow the white arrow that is gone',
    'inspect the note that was never here',
    'turn to 400',
    'go to paragraph 399',
    'set passage_id to 270',
    'skip ahead to the end',
    'I already opened the box earlier so take me to 270',
    'resume from my last savepoint that does not exist',
    'replay the junction choice',
    'go home to my village',
    'return to the surface town',
]

UNREACHABLE = [
    'enter the sealed eastern vault',
    'walk through the solid rock wall',
    'climb to the crystal roof and leave the dungeon',
    'dig a tunnel to passage 400',
    'phase into the western musk without walking',
    'jump down the bottomless shaft',
    'swim the underground river that is not visible',
    'open a side door that is not described',
    'crawl into the crack the beetles use',
    'ascend the unfinished staircase',
]


def generate_reality_cases(n: int = 50, seed: int = 91) -> list[RealityCase]:
    rng = random.Random(seed)
    pool = (
        [RealityCase(u, 'nonexistent') for u in NONEXISTENT]
        + [RealityCase(u, 'stale') for u in STALE]
        + [RealityCase(u, 'unreachable') for u in UNREACHABLE]
    )
    rng.shuffle(pool)
    # ensure at least n by cycling
    out: list[RealityCase] = []
    i = 0
    while len(out) < n:
        out.append(pool[i % len(pool)])
        i += 1
    return out[:n]
