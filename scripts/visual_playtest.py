#!/usr/bin/env python3
"""Play Level 1 with sprite/portrait capture for visual red-team loops.

    python scripts/visual_playtest.py --heuristic --max-turns 28
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from puca_dungeon.conversation import set_interlocutor
from puca_dungeon.interpret import HeuristicInterpreter, OllamaInterpreter
from puca_dungeon.narrate import OllamaNarrator, TemplateNarrator
from puca_dungeon.portrait.bakeoff import export_contact_sheets, gallery_label
from puca_dungeon.portrait.cues import portrait_cue_from_world
from puca_dungeon.portrait.manifest import FACE_PROFILE_IDS
from puca_dungeon.portrait.present import compose_facility_presentation
from puca_dungeon.portrait.render import portrait_to_display_rgb, render_portrait
from puca_dungeon.portrait.types import FacePose
from puca_dungeon.session import GameSession

SCRIPT = [
    'look around',
    'examine the cup',
    'examine the book',
    'look at the door',
    'wait',
    'wait',
    'look through the slit',
    'who are you',
    'hello',
    'cooperate',
    'walk with them',
    'look around',
    'who is with me',
    'wash myself',
    'look at the people here',
    'hello',
    'what is this place',
    'eat the food',
    'talk to the nearest person',
    'who are you',
    'why are you here',
    'look around',
    'wait',
    'go back to the cell',
    'look around',
    'wait',
    'wait',
    'sleep',
]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')


def _snapshot(session: GameSession, dest: Path, allow_placeholder: bool = True) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    kind, path = compose_facility_presentation(
        session.world, dest.parent, allow_placeholder=allow_placeholder,
    )
    shutil.copy2(path, dest)
    cue = portrait_cue_from_world(session.world)
    fac = session.world.facility
    return {
        'kind': kind,
        'file': dest.name,
        'room': getattr(fac, 'room_id', None) if fac else None,
        'phase': getattr(fac, 'phase', None) if fac else None,
        'mode': getattr(session.world, 'mode', None),
        'present_ids': list(getattr(getattr(fac, 'arc', None), 'present_ids', None) or []) if fac else [],
        'portrait': cue.to_dict(),
    }


def _dump_fixtures(out_dir: Path, session: GameSession) -> list[dict]:
    """Force key presence / portrait states so the bake-off is not luck-dependent."""
    from copy import deepcopy

    fac = session.world.facility
    assert fac is not None
    saved = deepcopy(fac.to_dict())
    saved_mode = session.world.mode
    session.world.mode = 'facility'
    rows = []
    fixtures = [
        ('cell_empty', 'cell', [], ''),
        ('cell_staff', 'cell', ['orderly_quiet', 'orderly_anxious'], ''),
        ('wash_subjects', 'washroom', ['orderly_quiet', 'iven', 'nessa'], ''),
        ('mess_subjects', 'mess', ['iven', 'nessa', 'ruan'], ''),
        ('interview_senior', 'interview', ['senior_researcher', 'orderly_quiet'], ''),
        ('heaven_attendant', 'heaven', ['attendant_a', 'iven'], ''),
        ('talk_iven', 'mess', ['iven', 'nessa'], 'iven'),
        ('talk_nessa', 'mess', ['iven', 'nessa'], 'nessa'),
        ('talk_ruan', 'cell', ['ruan'], 'ruan'),
        ('talk_senior', 'interview', ['senior_researcher'], 'senior_researcher'),
        ('talk_anxious', 'corridor', ['orderly_anxious', 'orderly_quiet'], 'orderly_anxious'),
    ]
    img_dir = out_dir / 'fixtures'
    img_dir.mkdir(parents=True, exist_ok=True)
    for name, room, present, speaker in fixtures:
        fac.room_id = room
        fac.arc.present_ids = list(present)
        fac.staff_present = any(
            cid in present for cid in (
                'orderly_quiet', 'orderly_anxious', 'senior_researcher',
                'attendant_a', 'attendant_b',
            )
        )
        fac.staff_count = sum(
            1 for cid in present
            if cid in ('orderly_quiet', 'orderly_anxious', 'senior_researcher')
        )
        set_interlocutor(fac, speaker)
        dest = img_dir / f'{name}.png'
        meta = _snapshot(session, dest)
        meta['fixture'] = name
        rows.append(meta)
    fac_restored = type(fac).from_dict(saved)
    session.world.facility = fac_restored
    session.world.mode = saved_mode
    return rows


def run(*, heuristic: bool, seed: int, max_turns: int, model: str, out_root: Path) -> Path:
    run_dir = out_root / f'visual_{_stamp()}_seed{seed}'
    img_dir = run_dir / 'images'
    img_dir.mkdir(parents=True, exist_ok=True)

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
        allow_heuristic_fallback=True,
        generate_images=False,
        start_mode='facility',
        layout_seed=seed,
        image_cache_dir=img_dir / '_cache',
    )

    transcript = [f'# Visual playtest seed={seed}\n', session.opening_text, '\n']
    short = [f'T0 (opening)\n{(session.opening_text or "")[:400]}\n']
    snaps = [_snapshot(session, img_dir / 'T00_opening.png')]
    snaps[-1]['turn'] = 0
    snaps[-1]['command'] = '(opening)'

    turns = SCRIPT[:max_turns]
    for i, action in enumerate(turns, start=1):
        fac = session.world.facility
        present = list(getattr(getattr(fac, 'arc', None), 'present_ids', None) or []) if fac else []
        cmd = action
        if present and action in ('wait',) and i in (8, 9, 16, 20):
            cmd = 'who are you'
        trace = session.submit(cmd)
        prose = getattr(trace, 'narrator_output', '') or ''
        transcript.append(f'\n## Turn {i}\n> {cmd}\n\n{prose}\n')
        short.append(f'T{i} > {cmd}\n{(prose or "")[:400]}\n')
        snap = _snapshot(session, img_dir / f'T{i:02d}.png')
        snap['turn'] = i
        snap['command'] = cmd
        snap['prose'] = prose
        snaps.append(snap)
        if not session.world.sheet.alive or session.world.ending in ('death', 'victory'):
            break

    fixture_rows = _dump_fixtures(run_dir, session)
    bakeoff_dir = run_dir / 'bakeoff'
    export_contact_sheets(bakeoff_dir)

    (run_dir / 'transcript.txt').write_text(''.join(transcript), encoding='utf-8')
    (run_dir / 'short_transcript.txt').write_text('\n'.join(short), encoding='utf-8')
    (run_dir / 'images.json').write_text(json.dumps(snaps, indent=2), encoding='utf-8')
    (run_dir / 'fixtures.json').write_text(json.dumps(fixture_rows, indent=2), encoding='utf-8')
    summary = {
        'seed': seed,
        'heuristic': heuristic,
        'turns': len(snaps) - 1,
        'images': [s['file'] for s in snaps],
        'fixture_files': [r['file'] for r in fixture_rows],
        'portrait_turns': [s['turn'] for s in snaps if s.get('kind') == 'portrait'],
        'printed_turns': [s['turn'] for s in snaps if s.get('kind') == 'printed'],
        'present_events': [
            {'turn': s['turn'], 'present_ids': s['present_ids'], 'room': s['room']}
            for s in snaps if s.get('present_ids')
        ],
        'gallery_labels': {pid: gallery_label(pid) for pid in FACE_PROFILE_IDS},
    }
    (run_dir / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    (run_dir / 'NOTES.md').write_text(
        '# Visual playtest\n\n'
        'Inspect `images/`, `fixtures/`, and `bakeoff/` then iterate portrait/body art.\n',
        encoding='utf-8',
    )
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Visual playtest with image capture')
    parser.add_argument('--heuristic', action='store_true')
    parser.add_argument('--seed', type=int, default=101)
    parser.add_argument('--max-turns', type=int, default=24)
    parser.add_argument('--model', default='mistral')
    parser.add_argument('--out', type=Path, default=ROOT / 'tools' / 'playtests')
    args = parser.parse_args(argv)
    run_dir = run(
        heuristic=args.heuristic,
        seed=args.seed,
        max_turns=args.max_turns,
        model=args.model,
        out_root=args.out,
    )
    print(run_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
