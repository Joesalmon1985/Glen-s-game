"""Level 1 hostile/varied LLM playtest campaign — ≥10 persona runs with full traces.

Usage:
  python scripts/level1_playtest_campaign.py
  python scripts/level1_playtest_campaign.py --heuristic   # offline templates
  python scripts/level1_playtest_campaign.py --max-turns 40
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from puca_dungeon.interpret import HeuristicInterpreter, OllamaInterpreter, ollama_reachable
from puca_dungeon.narrate import OllamaNarrator, TemplateNarrator
from puca_dungeon.narrator_prosecutor import prosecute as prosecute_narration
from puca_dungeon.session import GameSession

PERSONAS: list[dict[str, Any]] = [
    {
        'id': 'cooperative_serious',
        'seed': 101,
        'actions': [
            'look around',
            'examine the cup',
            'drink from the cup',
            'examine the book',
            'lie on the bed',
            'wait',
            'wait',
            'wait',
            'step back from the door',
            'cooperate',
            'wash myself',
            'eat the food',
            'look at the cell',
            'lie down and sleep',
            'wait',
            'wait',
            'wait',
            'Sarel',
            'a fishing village',
            'my brother',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'yes',
            'look around',
            'wait',
            'wait',
        ],
    },
    {
        'id': 'minimalist_inspector',
        'seed': 102,
        'actions': [
            'look at the bed',
            'look at the cup',
            'look at the book',
            'look at the door',
            'look at the slit',
            'examine myself',
            'wait',
            'wait',
            'wait',
            'wait',
            'look through the slit',
            'step back',
            'look around',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'examine the bed',
            'sleep',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'yes',
            'look around',
        ],
    },
    {
        'id': 'obstructive',
        'seed': 103,
        'actions': [
            'wait',
            'wait',
            'wait',
            'wait',
            'refuse',
            'no',
            'I will not move',
            'stand in front of the door',
            'refuse again',
            'struggle',
            'refuse to wash',
            'refuse to wash',
            'refuse the food',
            'push the bowl away',
            'stay awake',
            'stay awake',
            'stay awake',
            'stay awake',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'no',
            'wait',
            'look around',
            'examine the grate',
            'wait',
            'wait',
            'stay here',
            'look around',
        ],
    },
    {
        'id': 'hostile_violent',
        'seed': 104,
        'actions': [
            'punch the door',
            'wait',
            'wait',
            'wait',
            'attack whoever is outside',
            'scream at him',
            'punch her repeatedly',
            'fight the staff',
            'hit them',
            'run',
            'punch again',
            'threaten him',
            'refuse',
            'attack',
            'stay awake all night',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'no',
            'wait',
            'wait',
            'wait',
            'stay here',
        ],
    },
    {
        'id': 'escape_obsessed',
        'seed': 105,
        'actions': [
            'open the door',
            'kick the door',
            'look for a window',
            'climb through the slit',
            'wait',
            'wait',
            'wait',
            'run',
            'escape',
            'flee down the corridor',
            'break free',
            'run',
            'find an exit',
            'wait',
            'wait',
            'sleep',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'no',
            'wait',
            'look around',
            'wait',
            'stay here',
        ],
    },
    {
        'id': 'absurd_surreal',
        'seed': 106,
        'actions': [
            'turn into a dragon',
            'summon a helicopter',
            'ask the cup for life advice',
            'marry the bed',
            'paint the door invisible',
            'wait',
            'recite poetry to the slit',
            'become soup',
            'wait',
            'wait',
            'teach the staff interpretive dance',
            'invent gravity',
            'wait',
            'read the book upside down while whistling',
            'put the book down',
            'sleep on the ceiling',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'yes',
            'look around',
        ],
    },
    {
        'id': 'book_diver',
        'seed': 107,
        'actions': [
            'pick up the book',
            'read the book',
            'look around',
            'open the named casket',
            'continue',
            'go west',
            'look around',
            'continue',
            'attack',
            'attack',
            'attack',
            'put the book down',
            'look at the cup',
            'read the book',
            'look around',
            'put the book down',
            'wait',
            'wait',
            'sleep',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'yes',
            'look around',
        ],
    },
    {
        'id': 'language_maximalist',
        'seed': 108,
        'actions': [
            'wait',
            'wait',
            'wait',
            'Ask him who he is and why I am here and what the rules of this place are',
            'Tell him exactly what I think of him in elaborate detail',
            'Demand a lawyer and a full explanation of my rights',
            'Apologise profusely while asking for water',
            'Threaten him with consequences',
            'step back',
            'Explain that I am a visiting dignitary',
            'wash carefully',
            'politely request the recipe for this food then eat it',
            'thank them for their hospitality',
            'sleep',
            'Ask why they are questioning me',
            'Tell them my name is Sarel and I lived by the water',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'yes',
            'look around',
        ],
    },
    {
        'id': 'object_chaos',
        'seed': 109,
        'actions': [
            'throw the cup at the wall',
            'pull the bedding onto the floor',
            'move the cup',
            'throw the book',
            'pick up the book',
            'put the book on the bed',
            'kick the door',
            'drink from the cup',
            'wait',
            'wait',
            'wait',
            'throw water',
            'hide the food',
            'throw the bowl',
            'look around',
            'sleep',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'yes',
            'look around',
        ],
    },
    {
        'id': 'mixed_resist_then_book',
        'seed': 110,
        'actions': [
            'wait',
            'wait',
            'wait',
            'I will not back away',
            'punch her',
            'refuse to wash',
            'refuse food',
            'read the book',
            'look around',
            'continue',
            'put the book down',
            'stay awake all night',
            'stay awake',
            'fight sleep',
            'read the book',
            'stop reading',
            'lie down',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'wait',
            'no',
            'wait',
            'examine the grate',
            'wait',
            'stay here',
        ],
    },
]


def _run_persona(
    persona: dict,
    *,
    out_dir: Path,
    heuristic: bool,
    model: str,
    max_turns: int,
) -> dict:
    seed = int(persona['seed'])
    pid = str(persona['id'])
    run_dir = out_dir / f'{pid}_seed{seed}'
    run_dir.mkdir(parents=True, exist_ok=True)

    if heuristic:
        interpreter = HeuristicInterpreter()
        narrator = TemplateNarrator()
    else:
        interpreter = OllamaInterpreter(model=model)
        narrator = OllamaNarrator(model=model)

    session = GameSession(
        player_name='Glen',
        seed=seed,
        debug=True,
        interpreter=interpreter,
        narrator=narrator,
        allow_heuristic_fallback=heuristic,
        generate_images=False,
        start_mode='facility',
        layout_seed=seed,
    )

    transcript: list[str] = [
        f'# Playtest: {pid}',
        f'seed={seed}',
        f'interpreter={type(interpreter).__name__}',
        f'narrator={type(narrator).__name__}',
        '',
        '## OPENING',
        session.opening_text,
        '',
    ]
    short_lines: list[str] = [
        f'# Short playtest: {pid}',
        f'seed={seed}',
        '',
        '## OPENING',
        session.opening_text,
        '',
    ]
    short_jsonl_path = run_dir / 'short.jsonl'
    traces_path = run_dir / 'traces.jsonl'
    enactment_counts: Counter = Counter()
    mode_switches: list[str] = []
    prosecutor_hits = 0
    softlocks = 0
    prev_mode = session.world.mode

    actions = list(persona['actions'])[:max_turns]
    with traces_path.open('w', encoding='utf-8') as tf, short_jsonl_path.open('w', encoding='utf-8') as sf:
        for i, action in enumerate(actions, 1):
            t0 = time.time()
            tr = session.submit(action)
            dt = time.time() - t0
            res = tr.resolution or {}
            enactment = res.get('enactment') or 'direct'
            enactment_counts[enactment] += 1
            cause = res.get('enactment_cause') or ''
            if enactment != 'direct' and not cause and enactment != 'direct':
                # Non-direct without cause is a finding unless world_constraint path
                if res.get('none_reason') not in ('entity_absent', 'impossible_here'):
                    softlocks += 0  # counted in invariants below
            if session.world.mode != prev_mode:
                mode_switches.append(f'{prev_mode}->{session.world.mode}@{i}')
                prev_mode = session.world.mode

            # Narrator prosecutor when possible
            try:
                hits = prosecute_narration(
                    tr.narrator_output or '',
                    res,
                    session.world,
                )
                if hits:
                    prosecutor_hits += len(hits) if isinstance(hits, list) else 1
            except Exception:
                pass

            # Rebellion without cause
            if enactment in ('aborted', 'inverted', 'compromised') and not cause:
                softlocks += 1

            image_prompt = ''
            if isinstance(tr.image, dict):
                image_prompt = tr.image.get('full_prompt') or ''

            record = {
                'turn': i,
                'input': action,
                'seconds': round(dt, 2),
                'mode': session.world.mode,
                'phase': getattr(session.world.facility, 'phase', None) if session.world.facility else None,
                'enactment': enactment,
                'enactment_cause': cause,
                'passage_id': session.world.passage_id,
                'trace': tr.to_dict(),
            }
            tf.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
            sf.write(json.dumps({
                'turn': i,
                'input': action,
                'response': tr.narrator_output or '',
                'image_prompt': image_prompt,
            }, ensure_ascii=False) + '\n')

            transcript.append(f'## Turn {i}')
            transcript.append(f'> {action}')
            transcript.append('')
            transcript.append(tr.narrator_output or '')
            transcript.append('')
            transcript.append('### DEBUG')
            transcript.append(tr.format_debug())
            transcript.append('')

            short_lines.append(f'## Turn {i}')
            short_lines.append(f'> {action}')
            short_lines.append('')
            short_lines.append(tr.narrator_output or '')
            short_lines.append('')
            short_lines.append(f'IMAGE: {image_prompt or "(none)"}')
            short_lines.append('')

            fac = session.world.facility
            if fac and getattr(fac, 'phase', '') == 'research' and i > 20:
                # Reached sandbox; allow a few more looks then stop this persona
                if action in ('look around',) and i >= len(actions) - 1:
                    pass
            if session.world.ending in ('death', 'victory') and session.world.mode == 'book_dungeon':
                # Continue outer if possible
                pass

    (run_dir / 'transcript.txt').write_text('\n'.join(transcript), encoding='utf-8')
    (run_dir / 'short_transcript.txt').write_text('\n'.join(short_lines), encoding='utf-8')
    summary = {
        'persona': pid,
        'seed': seed,
        'turns': len(actions),
        'enactment_histogram': dict(enactment_counts),
        'mode_switches': mode_switches,
        'prosecutor_hits': prosecutor_hits,
        'non_direct_without_cause': softlocks,
        'final_mode': session.world.mode,
        'final_phase': getattr(session.world.facility, 'phase', None) if session.world.facility else None,
        'slept': bool(session.world.facility and session.world.facility.slept),
        'washed': bool(session.world.facility and session.world.facility.washed),
        'fed': bool(session.world.facility and session.world.facility.fed),
        'language_ability': int(getattr(getattr(session.world.facility, 'pressures', None), 'language_ability', 0) or 0),
        'language_attempts': int(getattr(getattr(session.world.facility, 'arc', None), 'language_attempts', 0) or 0),
        'contract': str(getattr(getattr(session.world.facility, 'arc', None), 'actual_contract_response', '') or ''),
        'player_final_intent': str(getattr(getattr(session.world.facility, 'arc', None), 'player_final_intent', '') or ''),
        'staff_names': {
            'quiet': (session.world.facility.character_name('orderly_quiet') if session.world.facility else ''),
            'anxious': (session.world.facility.character_name('orderly_anxious') if session.world.facility else ''),
            'senior': (session.world.facility.character_name('senior_researcher') if session.world.facility else ''),
        },
        'layout_seed': session.world.layout_seed,
        'layout_fingerprint': (session.world.dungeon_layout or {}).get('fingerprint'),
    }
    (run_dir / 'summary.json').write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8',
    )
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Level 1 multi-persona playtest campaign')
    ap.add_argument('--heuristic', action='store_true', help='Offline heuristic+template')
    ap.add_argument('--model', default='mistral')
    ap.add_argument('--max-turns', type=int, default=80)
    ap.add_argument('--out', type=Path, default=None)
    ap.add_argument('--only', nargs='*', default=None, help='Run only these persona ids')
    args = ap.parse_args(argv)

    if not args.heuristic and not ollama_reachable():
        print('Ollama not reachable; pass --heuristic for offline.', file=sys.stderr)
        return 2

    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    out_dir = args.out or (ROOT / 'tools' / 'playtests' / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)

    personas = PERSONAS
    if args.only:
        wanted = set(args.only)
        personas = [p for p in PERSONAS if p['id'] in wanted]
        if not personas:
            print('No matching personas for --only', file=sys.stderr)
            return 2

    # Merge with existing summaries if continuing into same out dir
    existing_path = out_dir / 'campaign_summary.json'
    summaries = []
    if existing_path.is_file():
        try:
            summaries = json.loads(existing_path.read_text(encoding='utf-8'))
        except Exception:
            summaries = []

    index_lines = [
        f'# Level 1 playtest campaign {out_dir.name}',
        '',
        f'heuristic={args.heuristic} model={args.model}',
        '',
        '| Persona | Seed | Slept | Washed | Fed | Enactments | Modes |',
        '|---|---|---|---|---|---|---|',
    ]

    for persona in personas:
        print(f'Running {persona["id"]} seed={persona["seed"]} ...', flush=True)
        summary = _run_persona(
            persona,
            out_dir=out_dir,
            heuristic=args.heuristic,
            model=args.model,
            max_turns=args.max_turns,
        )
        summaries = [s for s in summaries if s.get('persona') != summary['persona']]
        summaries.append(summary)
        print(
            f'  done slept={summary["slept"]} phase={summary["final_phase"]} '
            f'enactments={summary["enactment_histogram"]}',
            flush=True,
        )

    for summary in summaries:
        index_lines.append(
            f'| {summary["persona"]} | {summary["seed"]} | {summary["slept"]} | '
            f'{summary["washed"]} | {summary["fed"]} | `{summary["enactment_histogram"]}` | '
            f'{len(summary.get("mode_switches") or [])} |'
        )

    (out_dir / 'campaign_summary.json').write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False), encoding='utf-8',
    )
    (out_dir / 'INDEX.md').write_text('\n'.join(index_lines) + '\n', encoding='utf-8')
    print('Wrote', out_dir)
    print('INDEX:', out_dir / 'INDEX.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
