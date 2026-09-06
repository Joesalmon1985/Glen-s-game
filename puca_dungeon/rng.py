"""Seeded RNG with serializable state for deterministic debug play."""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class GameRNG:
    seed: int
    _rng: random.Random

    @classmethod
    def from_seed(cls, seed: int) -> 'GameRNG':
        return cls(seed=seed, _rng=random.Random(seed))

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)

    def roll_d20(self) -> int:
        return self._rng.randint(1, 20)

    def choice(self, seq):
        return self._rng.choice(seq)

    def getstate(self):
        return self._rng.getstate()

    def setstate(self, state) -> None:
        self._rng.setstate(state)

    def snapshot(self) -> dict:
        return {'seed': self.seed, 'state': self._rng.getstate()}

    @classmethod
    def restore(cls, payload: dict) -> 'GameRNG':
        rng = cls.from_seed(int(payload['seed']))
        rng.setstate(_tupleize(payload['state']))
        return rng


def _tupleize(value):
    if isinstance(value, list):
        return tuple(_tupleize(v) for v in value)
    return value
