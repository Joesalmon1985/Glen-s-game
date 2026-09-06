"""Typing-first debug UI for the Deathtrap Dungeon POC."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from puca_dungeon.interpret import HeuristicInterpreter, OllamaInterpreter
from puca_dungeon.session import GameSession


def run_cli(session: GameSession) -> int:
    print(session.opening_text)
    print()
    print('Debug play mode. Type freely. Developer commands start with / (e.g. /state, /help, /quit).')
    print('IMAGE GENERATION IS SUPPRESSED; would-be prompts still appear in the turn debug dump.')
    print()
    while True:
        try:
            line = input('> ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        trace = session.submit(line)
        if trace.debug_command == '/quit' or trace.narrator_output == '__QUIT__':
            print('Bye.')
            return 0
        if trace.debug_command:
            print(trace.narrator_output)
            print()
            continue
        print()
        print(trace.narrator_output)
        print()
        if session.debug:
            print(trace.format_debug())
            print()
        if not session.world.player.alive:
            print('[You have died.]')
            return 0
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Puca Deathtrap Dungeon POC — typing-first debug play')
    parser.add_argument('--debug', action='store_true', default=True, help='Full pipeline debug (default on)')
    parser.add_argument('--no-debug', action='store_true', help='Player-facing mode (hide mechanics)')
    parser.add_argument('--seed', type=int, default=91, help='RNG seed for determinism')
    parser.add_argument('--name', default='Adventurer', help='Player name (named box label)')
    parser.add_argument('--llm', action='store_true', help='Use Ollama interpreter instead of heuristic')
    parser.add_argument('--model', default='mistral', help='Ollama model when --llm')
    parser.add_argument('--trace-out', type=Path, help='Write JSONL turn traces to this path')
    args = parser.parse_args(argv)

    debug = not args.no_debug
    if args.llm:
        interpreter = OllamaInterpreter(model=args.model)
    else:
        interpreter = HeuristicInterpreter()

    session = GameSession(player_name=args.name, seed=args.seed, interpreter=interpreter, debug=debug)

    # Wrap submit to optionally record traces
    if args.trace_out:
        original = session.submit

        def submit_and_log(text: str):
            tr = original(text)
            args.trace_out.parent.mkdir(parents=True, exist_ok=True)
            with args.trace_out.open('a', encoding='utf-8') as fh:
                fh.write(json.dumps(tr.to_dict(), ensure_ascii=False, default=str) + '\n')
            return tr

        session.submit = submit_and_log  # type: ignore

    return run_cli(session)


if __name__ == '__main__':
    raise SystemExit(main())
