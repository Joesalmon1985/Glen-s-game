"""Typing-first CLI for Fighting Fantasy Deathtrap Dungeon."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from puca_dungeon.interpret import HeuristicInterpreter, InterpreterUnavailable, OllamaInterpreter
from puca_dungeon.narrate import OllamaNarrator, TemplateNarrator
from puca_dungeon.session import GameSession


def run_cli(session: GameSession) -> int:
    print(session.opening_text)
    print()
    if session.debug:
        print('Debug play mode. Type freely. Developer commands start with / (e.g. /state, /sheet, /help, /quit).')
        print('IMAGE GENERATION IS SUPPRESSED; would-be prompts still appear in the turn debug dump.')
    else:
        print('Type freely to act. Commands: /sheet /save /load /quit')
        if session.generate_images:
            print('Image generation enabled.')
    print(f'Interpreter: {type(session.interpreter).__name__}')
    print(f'Narrator: {type(session.narrator).__name__}')
    if type(session.interpreter).__name__ == 'HeuristicInterpreter':
        print('NOTE: HeuristicInterpreter is offline/regex mode — not the LLM. '
              'For real play, run without --heuristic (Ollama required).')
    print()
    while True:
        try:
            line = input('> ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        try:
            trace = session.submit(line)
        except InterpreterUnavailable as exc:
            print(f'\nERROR: {exc}\n', file=sys.stderr)
            return 2
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
            # Debug-only: passage id and combat meters (engine terms).
            print(f"— Passage {session.world.passage_id} —")
            if session.world.combat.active:
                c = session.world.combat
                print(
                    f"— Fighting {c.enemy_name}: "
                    f"SKILL {c.enemy_skill}  STAMINA {c.enemy_stamina}/{c.enemy_stamina_initial} —"
                )
            print(trace.format_debug())
            print()
        elif session.world.combat.active:
            # Player-facing: enemy presence only — no SKILL/STAMINA banners.
            print(f"— Fighting {session.world.combat.enemy_name} —")
            print()
        else:
            print()
        if session.world.victory or session.world.ending == 'victory':
            print('[Victory! You have conquered Deathtrap Dungeon.]')
            return 0
        if not session.world.sheet.alive or session.world.ending == 'death':
            print('[You have died.]')
            return 0
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Puca Deathtrap Dungeon — Fighting Fantasy gamebook')
    parser.add_argument('--debug', action='store_true', default=True, help='Full pipeline debug (default on)')
    parser.add_argument('--no-debug', action='store_true', help='Player-facing mode (hide mechanics)')
    parser.add_argument('--seed', type=int, default=91, help='RNG seed for determinism')
    parser.add_argument('--name', default='Adventurer', help='Player name')
    parser.add_argument(
        '--potion',
        default='potion_skill',
        choices=['potion_skill', 'potion_strength', 'potion_fortune'],
        help='Starting potion',
    )
    parser.add_argument('--heuristic', action='store_true',
                        help='Use deterministic HeuristicInterpreter (tests/offline only)')
    parser.add_argument('--llm', action='store_true',
                        help='Deprecated: Ollama is already the default. Kept for compatibility.')
    parser.add_argument('--allow-heuristic-fallback', action='store_true',
                        help='If Ollama is down, fall back to HeuristicInterpreter instead of failing')
    parser.add_argument('--model', default='mistral', help='Ollama model for interpreter/narrator')
    parser.add_argument('--template-narrator', action='store_true',
                        help='Use deterministic template narrator instead of Ollama narrator')
    parser.add_argument('--images', action='store_true',
                        help='Generate images when not in --debug (requires GPU stack)')
    parser.add_argument('--trace-out', type=Path, help='Write JSONL turn traces to this path')
    args = parser.parse_args(argv)

    debug = not args.no_debug
    if args.heuristic:
        interpreter = HeuristicInterpreter()
        narrator = TemplateNarrator()
    else:
        interpreter = OllamaInterpreter(model=args.model)
        narrator = TemplateNarrator() if args.template_narrator else OllamaNarrator(model=args.model)

    try:
        session = GameSession(
            player_name=args.name,
            seed=args.seed,
            potion_id=args.potion,
            interpreter=interpreter,
            debug=debug,
            narrator=narrator,
            allow_heuristic_fallback=args.allow_heuristic_fallback,
            ollama_model=args.model,
            generate_images=bool(args.images),
        )
    except InterpreterUnavailable as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2

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
