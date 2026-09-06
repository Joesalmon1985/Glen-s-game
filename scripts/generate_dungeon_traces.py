"""Generate human-readable debug playthrough traces for the POC."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from puca_dungeon.interpret import HeuristicInterpreter, OllamaInterpreter, ollama_reachable
from puca_dungeon.session import GameSession
from tests.test_llm_semantic_interpret import FIXTURES, FixtureInterpreter

OUT = ROOT / 'tests' / 'traces'


HUMAN_DEBUG_ACTIONS = [
    'grab one of the boxes and shake it',
    'hit the box',
    'how many boxes are there?',
    'grab the box with my name on it and open it',
    'do nothing',
    'turn back around',
    'do a cartwheel',
    'look at the boxes closely',
    'run',
    'run away from the footsteps',
]


def run_trace(name: str, actions: list[str], seed: int = 91, interpreter=None, **world_tweaks) -> Path:
    session = GameSession(
        player_name='Glen', seed=seed, debug=True,
        interpreter=interpreter or HeuristicInterpreter(),
    )
    if 'search_bonus' in world_tweaks:
        session.world.player.search_bonus = world_tweaks['search_bonus']
    lines = [
        f'# Trace: {name}',
        f'seed={seed}',
        f'interpreter={type(session.interpreter).__name__}',
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


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--ollama', action='store_true', help='Use live Ollama for human debug trace')
    parser.add_argument('--model', default='mistral')
    args = parser.parse_args(argv)

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
        interpreter=HeuristicInterpreter(),
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
        interpreter=HeuristicInterpreter(),
    )

    # Offline semantic replay of the human debug script (fixture LLM outputs)
    c = run_trace(
        'trace_c_llm_first_human_debug',
        HUMAN_DEBUG_ACTIONS,
        seed=91,
        interpreter=FixtureInterpreter(FIXTURES),
    )

    print('Wrote', a)
    print('Wrote', b)
    print('Wrote', c)

    if args.ollama:
        if not ollama_reachable():
            raise SystemExit('Ollama not reachable; cannot run live human debug trace')
        d = run_trace(
            'trace_d_ollama_human_debug',
            HUMAN_DEBUG_ACTIONS,
            seed=91,
            interpreter=OllamaInterpreter(model=args.model),
        )
        print('Wrote', d)


if __name__ == '__main__':
    main()
