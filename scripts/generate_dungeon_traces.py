"""Generate human-readable debug playthrough traces for the POC."""
from __future__ import annotations

from pathlib import Path

from puca_dungeon.session import GameSession

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tests' / 'traces'


def run_trace(name: str, actions: list[str], seed: int = 91, **world_tweaks) -> Path:
    session = GameSession(player_name='Glen', seed=seed, debug=True)
    for key, value in world_tweaks.items():
        setattr(session.world.player, key, value) if hasattr(session.world.player, key) else None
    if 'search_bonus' in world_tweaks:
        session.world.player.search_bonus = world_tweaks['search_bonus']
    lines = [
        f'# Trace: {name}',
        f'seed={seed}',
        '',
        'OPENING',
        session.opening_text,
        '',
    ]
    for action in actions:
        tr = session.submit(action)
        lines.append(f'> {action}')
        lines.append(tr.narrator_output)
        lines.append('')
        lines.append(tr.format_debug())
        lines.append('')
        if not session.world.player.alive:
            lines.append('--- PLAYER DEAD ---')
            break
    lines.append(f'visual_backend_calls_total={session.visual_backend_calls}')
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f'{name}.txt'
    path.write_text('\n'.join(lines), encoding='utf-8')
    return path


def main():
    a = run_trace(
        'trace_a_pursuer',
        [
            'wait',
            'wait',
            'say abracadabra at the boxes',
            'wait',
            'wait',
            'draw my sword',
            'warn the challenger the boxes are trapped',
        ],
        seed=91,
    )
    b = run_trace(
        'trace_b_success',
        [
            'inspect the boxes carefully',
            'use my key on the box with my name',
            'read the note',
            'keep walking down the tunnel',
        ],
        seed=91,
        search_bonus=25,
    )
    print('Wrote', a)
    print('Wrote', b)


if __name__ == '__main__':
    main()
