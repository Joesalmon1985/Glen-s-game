"""Run the Social redteam agent for facility dialogue stress tests.

Usage:
  python scripts/social_redteam_runs.py --heuristic --max-turns 20
  python scripts/social_redteam_runs.py --max-turns 45 --seeds 301,302,303
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from puca_dungeon.interpret import HeuristicInterpreter, OllamaInterpreter, ollama_reachable
from puca_dungeon.narrate import OllamaNarrator, TemplateNarrator
from puca_dungeon.session import GameSession
from scripts.redteam.agents import AgentContext, Social, make_agent


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')


def _short_line(turn: int, cmd: str, prose: str) -> str:
    body = (prose or '').strip().replace('\n', ' ')
    if len(body) > 320:
        body = body[:317] + '...'
    return f'T{turn} > {cmd}\n{body}\n'


def run_one(
    *,
    seed: int,
    out_dir: Path,
    heuristic: bool,
    model: str,
    max_turns: int,
) -> dict:
    run_dir = out_dir / f'social_seed{seed}'
    run_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    agent = make_agent('Social', rng)

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

    opening = session.opening_text or ''
    if not opening:
        tr0 = session.submit('look around')
        opening = getattr(tr0, 'narrator_output', '') or ''

    ctx = AgentContext(opening=opening, last_prose=opening)
    agent.observe(ctx, opening)

    transcript: list[str] = [f'# Social redteam seed={seed}\n', opening, '\n']
    short_lines: list[str] = [f'T0 (opening)\n{(opening or "")[:320]}\n']
    traces: list[dict] = []

    for turn in range(1, max_turns + 1):
        cmd = agent.next_command(ctx)
        if not cmd:
            break
        trace = session.submit(cmd)
        prose = getattr(trace, 'narrator_output', '') or ''
        agent.observe(ctx, prose)
        transcript.append(f'\n> {cmd}\n{prose}\n')
        short_lines.append(_short_line(turn, cmd, prose))
        fac = session.world.facility
        traces.append({
            'turn': turn,
            'command': cmd,
            'prose': prose,
            'phase': getattr(fac, 'phase', None) if fac else None,
            'room_id': getattr(fac, 'room_id', None) if fac else None,
            'present_ids': list(getattr(getattr(fac, 'arc', None), 'present_ids', None) or []) if fac else [],
            'mode': getattr(session.world, 'mode', None),
        })
        if not session.world.sheet.alive or session.world.ending in ('death', 'victory'):
            break

    (run_dir / 'transcript.txt').write_text(''.join(transcript), encoding='utf-8')
    (run_dir / 'short_transcript.txt').write_text('\n'.join(short_lines), encoding='utf-8')
    with (run_dir / 'traces.jsonl').open('w', encoding='utf-8') as fh:
        for row in traces:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    summary = {
        'agent': 'Social',
        'seed': seed,
        'turns': len(traces),
        'heuristic': heuristic,
        'final_phase': traces[-1]['phase'] if traces else None,
        'final_room': traces[-1]['room_id'] if traces else None,
        'names_seen': list(getattr(agent, 'seen_names', []) or []),
        'asked_about': sorted(getattr(agent, 'asked_about', set()) or []),
    }
    (run_dir / 'summary.json').write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8',
    )
    return summary


def write_dialogue_notes(out_dir: Path, summaries: list[dict]) -> None:
    lines = [
        '# Social redteam dialogue notes',
        '',
        f'Runs: {len(summaries)}',
        '',
    ]
    for s in summaries:
        lines.append(f"## social_seed{s.get('seed')}")
        lines.append(f"- turns: {s.get('turns')}  phase: {s.get('final_phase')}  room: {s.get('final_room')}")
        lines.append(f"- names seen: {', '.join(s.get('names_seen') or []) or '(none)'}")
        lines.append(f"- asked about: {', '.join(s.get('asked_about') or []) or '(none)'}")
        lines.append('- Review short_transcript.txt for: NPC address/reply, purposeful moves, pronoun binding, no PD leaks.')
        lines.append('')
    lines.extend([
        '## Findings',
        '- (fill after reading transcripts)',
        '- What worked:',
        '- What broke:',
        '- Next fixes:',
        '',
    ])
    (out_dir / 'DIALOGUE_NOTES.md').write_text('\n'.join(lines), encoding='utf-8')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Social facility dialogue redteam runs')
    ap.add_argument('--heuristic', action='store_true')
    ap.add_argument('--model', default='llama3.2')
    ap.add_argument('--max-turns', type=int, default=45)
    ap.add_argument('--seeds', default='301,302,303')
    ap.add_argument('--out', type=Path, default=None)
    args = ap.parse_args(argv)

    if not args.heuristic and not ollama_reachable():
        print('Ollama not reachable; pass --heuristic or start Ollama.', file=sys.stderr)
        return 2

    out = args.out or (ROOT / 'tools' / 'playtests' / f'{_stamp()}_social_redteam')
    out.mkdir(parents=True, exist_ok=True)
    seeds = [int(x.strip()) for x in str(args.seeds).split(',') if x.strip()]
    summaries = []
    for seed in seeds:
        print(f'Running Social seed={seed}…')
        summaries.append(run_one(
            seed=seed,
            out_dir=out,
            heuristic=args.heuristic,
            model=args.model,
            max_turns=args.max_turns,
        ))
    (out / 'campaign_summary.json').write_text(
        json.dumps({'runs': summaries}, indent=2, ensure_ascii=False), encoding='utf-8',
    )
    write_dialogue_notes(out, summaries)
    print(f'Wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
