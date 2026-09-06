"""Fictional time costs for the Encounter 1 POC."""
from __future__ import annotations

from puca_dungeon.models import Intent


# Approximate seconds — not shown in normal play.
DEFAULT_COST = 15

COST_BY_CLASS = {
    'WAIT': 60,
    'REST': 60,
    'SPEAK': 5,
    'SHOUT': 5,
    'LOOK': 10,
    'INSPECT': 20,
    'SEARCH': 45,
    'USE': 15,
    'UNLOCK': 15,
    'MANIPULATE': 20,
    'PICK_LOCK': 50,
    'DISABLE': 40,
    'STRIKE': 20,
    'BREAK': 25,
    'MOVE': 30,
    'FLEE': 20,
    'HIDE': 25,
    'ATTACK': 15,
    'GIVE': 15,
    'WARN': 10,
    'NEGOTIATE': 30,
    'SURRENDER': 10,
    'LICK': 10,
    'TOUCH': 10,
    'SIT': 40,
    'CAST': 10,
    'OTHER': 20,
}


def time_cost(intent: Intent, resolution: dict | None = None) -> int:
    cls = (intent.action_class or 'OTHER').upper()
    cost = COST_BY_CLASS.get(cls, DEFAULT_COST)
    method = (intent.method or '').lower()
    if method in ('careful', 'thorough', 'search'):
        cost = max(cost, 45)
    if method in ('pick', 'lockpick', 'pick_lock'):
        cost = max(cost, 50)
    if resolution and resolution.get('combat_round'):
        cost = max(cost, 12)
    return cost
