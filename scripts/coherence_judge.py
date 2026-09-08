"""Judge player-facing short transcripts for narrative coherence defects.

Usage:
  python scripts/coherence_judge.py tools/playtests/<stamp>
  python scripts/coherence_judge.py tools/playtests/<stamp>/long_serious_seed201

Exit 0 = zero actionable defects; exit 1 = defects found.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Rubric ids matching the plan
RUBRIC = {
    'location': 'Can I always tell where Sarel is?',
    'presence': 'Can I tell who is physically present?',
    'causality': 'Can I understand what just caused the current situation?',
    'npc_motive': 'Do NPC actions follow understandable immediate motives?',
    'weight': 'Do important changes receive enough narrative weight?',
    'memory': 'Does earlier discovered information affect later narration when relevant?',
    'scene_boundary': 'Does prose distinguish scene continuation vs new scene?',
    'summarisable': 'Could I summarise the last five minutes without debug state?',
    # Social meaning (9–14)
    'motive_continuity': 'Do NPC motives stay continuous across related turns?',
    'earned_callback': 'Do callbacks to earlier social facts feel earned?',
    'dialogue_purpose': 'Does dialogue serve a readable purpose (test/verify/withhold/reassure)?',
    'no_game_theory_leak': 'No PD/trust-meter/strategy labels in player-facing prose?',
    'divergent_npc_reads': 'Do different NPCs interpret the same events differently when relevant?',
    'betrayal_reciprocity': 'Are betrayal and reciprocation narrated consistently with prior behaviour?',
}

META_PATTERNS = [
    (re.compile(r'\bwanted_action\b', re.I), 'causality', 'Engine field leaked into prose'),
    (re.compile(r'\benactment\b', re.I), 'causality', 'Engine enactment leaked into prose'),
    (re.compile(r'\bfacility[_\s-]?phase\b', re.I), 'causality', 'facility_phase leaked'),
    (re.compile(r'despite your intention', re.I), 'causality', 'Intention meta commentary'),
    (re.compile(r'\byou mean(?:t)? to\b', re.I), 'causality', 'Intention meta (“you mean/meant to”)'),
    (re.compile(r'words you meant to', re.I), 'causality', 'Intention meta commentary'),
    (re.compile(r'unvoiced desire', re.I), 'causality', 'Desire meta commentary'),
    (re.compile(r'\bdespite your (?:desire|want)\b', re.I), 'causality', 'Desire meta commentary'),
    (re.compile(r'contrast to your desires', re.I), 'causality', 'Desire meta commentary'),
    (re.compile(r'\bdirect action\b', re.I), 'causality', 'Direct-action meta'),
    (
        re.compile(
            r'(?=.*\b(?:casket|torchlight|alcove)\b)'
            r'(?=.*\b(?:observation slit|step away from the door)\b)'
            r'(?!.*\b(?:knock|page is still|printed corridor breaks|real room)\b)',
            re.I | re.S,
        ),
        'scene_boundary',
        'Book-dungeon and cell facility details mixed in one beat',
    ),
    (re.compile(r'the room remains the room', re.I), 'summarisable', 'Stock meta non-event'),
    (re.compile(r'the room does not hurry', re.I), 'summarisable', 'Stock meta wait line'),
    (re.compile(r'nothing in the world shifts for it', re.I), 'summarisable', 'Stock meta null result'),
    (re.compile(r'\bsated\b|\bquenched\b|hygiene aware', re.I), 'summarisable', 'Pressure label leak'),
    # Social / PD leaks
    (re.compile(r'\btrust\s*(=|:|\d)|trust meter|trust score', re.I), 'no_game_theory_leak', 'Trust meter leak'),
    (re.compile(r'\b(tit[-\s]?for[-\s]?tat|GENEROUS_TIT|defection|payoff matrix|nash)\b', re.I), 'no_game_theory_leak', 'Game-theory label leak'),
    (re.compile(r'\b(COOPERATE|DEFECT)\b'), 'no_game_theory_leak', 'COOPERATE/DEFECT label leak'),
    (re.compile(r'\b(strategy_label|relationship_scores|disclose_depth)\b', re.I), 'no_game_theory_leak', 'Strategy internals leak'),
    (re.compile(r'\b(TEST|VERIFY|WITHHOLD|RECIPROCATE|TERMINATE)\s+move\b', re.I), 'dialogue_purpose', 'Conversational move enum leaked'),
    (re.compile(r'\bdelta\s+of\s+\d+\b', re.I), 'no_game_theory_leak', 'Language-practice delta meter leak'),
    (re.compile(r'\blanguage practice\b', re.I), 'no_game_theory_leak', 'Language practice meter leak'),
]

ROOM_WORDS = {
    'cell': re.compile(r'\b(cell|small (locked )?room|bed beneath|observation slit)\b', re.I),
    'corridor': re.compile(r'\bcorridor\b', re.I),
    'washroom': re.compile(r'\b(washroom|wash(?:ing)?|basin|soap)\b', re.I),
    'mess': re.compile(r'\b(mess|bowl|food|meal)\b', re.I),
    'interview': re.compile(
        r'\b(interview|question|brighter room|sits opposite|across (?:from )?you|table)\b',
        re.I,
    ),
    'heaven': re.compile(r'\bheaven\b', re.I),
    'hell': re.compile(r'\bhell\b', re.I),
    'research_quarters': re.compile(r'\b(research|subject quarters|registered)\b', re.I),
    'prep': re.compile(r'\b(preparation|machine)\b', re.I),
}

SCENE_CHANGE_TYPES = {
    'slit_opens', 'door_procedure', 'forced_removal', 'arrive_wash',
    'washed', 'fed', 'retrieval', 'arrive_interview', 'day2_wake',
    'contract_offer', 'heaven_expires', 'scene_change',
}


def _parse_short_transcript(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding='utf-8', errors='replace')
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    buf: list[str] = []

    def _flush() -> None:
        nonlocal current, buf
        if current is not None:
            current['prose'] = '\n'.join(buf).strip()
            turns.append(current)
        current = None
        buf = []

    for line in text.splitlines():
        if line.startswith('## OPENING'):
            _flush()
            current = {'turn': 0, 'input': '(opening)', 'prose_lines': []}
            buf = []
            continue
        if line.startswith('## Turn '):
            _flush()
            m = re.match(r'## Turn (\d+)', line)
            current = {'turn': int(m.group(1)) if m else len(turns) + 1, 'input': '', 'prose_lines': []}
            buf = []
            continue
        # Social redteam format: "T0 (opening)" / "T12 > command"
        m_social = re.match(
            r'^T(\d+)\s*(?:>\s*(.*)| \(\s*opening\s*\))?\s*$',
            line,
            re.I,
        )
        if m_social:
            _flush()
            turn_n = int(m_social.group(1))
            cmd = (m_social.group(2) or '').strip()
            if turn_n == 0 or (not cmd and 'opening' in line.lower()):
                current = {'turn': 0, 'input': '(opening)', 'prose_lines': []}
            else:
                current = {'turn': turn_n, 'input': cmd, 'prose_lines': []}
            buf = []
            continue
        if current is None:
            continue
        if line.startswith('> ') and not current.get('input'):
            current['input'] = line[2:].strip()
            continue
        if line.startswith('IMAGE:'):
            continue
        if line.startswith('#'):
            continue
        buf.append(line)
    _flush()
    return turns


def _load_trace_rooms(traces_path: Path) -> dict[int, dict[str, Any]]:
    """Ground truth from traces (judge-only, not player-facing)."""
    out: dict[int, dict[str, Any]] = {}
    if not traces_path.is_file():
        return out
    for line in traces_path.read_text(encoding='utf-8', errors='replace').splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        turn = int(rec.get('turn') or 0)
        trace = rec.get('trace') or {}
        res = trace.get('resolution') or {}
        nin = trace.get('narrator_input') or {}
        sc = nin.get('scene_context') if isinstance(nin, dict) else {}
        sc = sc if isinstance(sc, dict) else {}
        room = (
            rec.get('room_id')
            or sc.get('where')
            or ''
        )
        phase = rec.get('phase') or ''
        mode = rec.get('mode') or (nin.get('mode') if isinstance(nin, dict) else '') or ''
        present = list(rec.get('present_ids') or [])
        # Prefer diegetic people from scene_context when available
        if sc.get('people_present'):
            present = list(sc.get('people_present') or [])
        events = list(res.get('world_events') or []) + list(res.get('structured_facts') or [])
        types = {str(e.get('type')) for e in events if isinstance(e, dict)}
        # Also treat must_lead scene_change texts
        for e in events:
            if isinstance(e, dict) and e.get('must_lead'):
                types.add('scene_change')
        out[turn] = {
            'room': room,
            'phase': phase,
            'mode': mode,
            'present': present,
            'event_types': types,
            'staff_present': bool(present) and mode != 'book_dungeon',
        }
    return out


def _defect(turn: int, rubric: str, detail: str, quote: str = '') -> dict:
    return {
        'turn': turn,
        'rubric': rubric,
        'question': RUBRIC.get(rubric, rubric),
        'detail': detail,
        'quote': (quote or '')[:240],
        'actionable': True,
    }


def judge_run(run_dir: Path) -> dict[str, Any]:
    short_path = run_dir / 'short_transcript.txt'
    traces_path = run_dir / 'traces.jsonl'
    if not short_path.is_file():
        return {
            'run': str(run_dir),
            'ok': False,
            'defects': [_defect(0, 'summarisable', 'Missing short_transcript.txt')],
            'soft_notes': [],
        }

    turns = _parse_short_transcript(short_path)
    truth = _load_trace_rooms(traces_path)
    defects: list[dict] = []
    soft_notes: list[dict] = []

    # Opening must locate the cell
    if turns:
        opening = turns[0].get('prose') or ''
        if turns[0].get('turn') == 0 and opening:
            if not ROOM_WORDS['cell'].search(opening):
                defects.append(_defect(
                    0, 'location', 'Opening does not establish that Sarel is in a cell/locked room', opening,
                ))

    prev_room = 'cell'
    rooms_announced: set[str] = {'cell'}
    saw_staff_ask = False
    saw_staff_motive_hint = False

    for t in turns:
        turn_n = int(t.get('turn') or 0)
        if turn_n == 0:
            continue
        prose = t.get('prose') or ''
        low = prose.lower()
        gt = truth.get(turn_n) or {}
        room = str(gt.get('room') or prev_room)
        event_types = set(gt.get('event_types') or [])
        mode = str(gt.get('mode') or '')

        # Meta / stock defects
        for pat, rubric, detail in META_PATTERNS:
            if pat.search(prose):
                defects.append(_defect(turn_n, rubric, detail, prose))

        # Location continuity when room changed this turn (facility only)
        if mode != 'book_dungeon' and room and room != prev_room:
            pattern = ROOM_WORDS.get(room)
            # Require announcement within this turn or the scene_change lead
            if pattern and not pattern.search(prose):
                # Corridor may be brief; still require the word or "leave the cell"
                if room == 'corridor' and re.search(r'\bleave\b|\bhands\b|\bescort', prose, re.I):
                    pass
                else:
                    defects.append(_defect(
                        turn_n, 'location',
                        f'Room changed to {room} but player prose does not establish location',
                        prose,
                    ))
            else:
                rooms_announced.add(room)
            # Scene boundary weight
            if not any(et in SCENE_CHANGE_TYPES or et.endswith('_change') for et in event_types):
                # Still a room change — weight check
                if len(prose.split()) < 12:
                    defects.append(_defect(
                        turn_n, 'weight',
                        f'Room change to {room} received too little narrative weight',
                        prose,
                    ))
            elif len(prose.split()) < 8:
                defects.append(_defect(
                    turn_n, 'scene_boundary',
                    f'Scene/room change to {room} not clearly announced',
                    prose,
                ))

        # Presence: if staff/subjects present in GT, require a human cue in prose
        present = list(gt.get('present') or [])
        staff_ids = {
            p for p in present
            if isinstance(p, str) and (
                'orderly' in p or 'senior' in p or 'attendant' in p
                or p in ('iven', 'nessa', 'ruan')
            )
        }
        # people_present may already be diegetic phrases
        diegetic_people = [p for p in present if isinstance(p, str) and ' ' in p]
        staff_present = (
            mode != 'book_dungeon'
            and (bool(staff_ids) or bool(diegetic_people) or bool(gt.get('staff_present')))
        )
        if staff_present and turn_n > 0:
            human_cue = re.search(
                r'\b(they|she|he|someone|staff|orderly|person|figure|hands|gesture|voice|'
                r'iven|nessa|ruan|attendant|professional|researcher)\b',
                prose, re.I,
            )
            # Named people from diegetic list
            named = False
            for phrase in diegetic_people:
                token = phrase.split(',')[0].strip().split()[0]
                if token and re.search(rf'\b{re.escape(token)}\b', prose, re.I):
                    named = True
                    break
            # Active staff beats only — not leftover fed/washed tags on a quiet return
            institutional = any(
                et in (
                    'slit_opens', 'door_escalate', 'forced_removal', 'arrive_wash',
                    'npc_speech', 'arrive_interview', 'retrieval',
                )
                for et in event_types
            )
            # return_cell with other subjects still needs a presence cue
            if 'return_cell' in event_types and (staff_ids or diegetic_people):
                institutional = True
            if institutional and not human_cue and not named:
                defects.append(_defect(
                    turn_n, 'presence',
                    'Staff are present per state but prose has no human presence cue',
                    prose,
                ))

        # Causality / motive around door escalation and forced procedures
        if mode != 'book_dungeon' and 'door_escalate' in event_types and 'forced_removal' not in event_types:
            if not re.search(
                r'\b(call|footstep|arrive|arrives|enter|enters|another|second|'
                r'help|gesture|abandon|repeat|staff|figure|coax)\b',
                prose, re.I,
            ):
                defects.append(_defect(
                    turn_n, 'npc_motive',
                    'Door escalation lacks readable motive/causal sequence',
                    prose,
                ))
            else:
                saw_staff_motive_hint = True
        if 'forced_removal' in event_types:
            if re.search(r'\b(hands|arms|corridor|door|leave|grasp|hold|escort)\b', prose, re.I):
                saw_staff_motive_hint = True
            elif len(prose.split()) < 10:
                defects.append(_defect(
                    turn_n, 'weight',
                    'Major forced transition under-narrated',
                    prose,
                ))
        if 'arrive_wash' in event_types and len(prose.split()) < 10:
            defects.append(_defect(
                turn_n, 'weight',
                'Major forced transition under-narrated',
                prose,
            ))
        if re.search(r'step away|stay away|back\.|away', prose, re.I):
            saw_staff_ask = True
        if re.search(r'\b(want|expect|intend|gesture|waiting|routine)\b', prose, re.I):
            saw_staff_motive_hint = True

        # Empty or near-empty player prose
        if not prose.strip() or prose.strip() in ('.', '…'):
            defects.append(_defect(turn_n, 'summarisable', 'Empty narration', prose))

        prev_room = room or prev_room

    # Social rubric soft/hard checks across the full run
    full = '\n'.join(t.get('prose') or '' for t in turns)
    full_low = full.lower()
    if re.search(r'\btrust\s*(=|:)|tit[-\s]?for[-\s]?tat|\bdefection\b|\bCOOPERATE\b|\bDEFECT\b', full):
        defects.append(_defect(0, 'no_game_theory_leak', 'Game-theory / trust meter leak in run prose', full[:200]))
    # Dialogue purpose: when subjects/staff speech is heavy, look for purposeful verbs (soft)
    if re.search(r'“|\"|says|asks|replies|tells', full_low) and len(full) > 400:
        purposeful = re.search(
            r'\b(wait|watch|test|repeat|refuse|gesture|ask|warn|offer|mark|note|listen)\b',
            full_low,
        )
        if not purposeful and ('social' in run_dir.name or 'nessa' in run_dir.name or 'reciproc' in run_dir.name):
            soft_notes.append({
                'rubric': 'dialogue_purpose',
                'detail': 'Speech-heavy social run lacks clear purposeful dialogue cues (soft)',
                'actionable': False,
            })
    if 'nessa' in full_low and re.search(r'tell (?:the )?staff|report', full_low):
        if not re.search(r'\b(trust|quiet|cold|withdraw|less|guarded|silence)\b', full_low):
            soft_notes.append({
                'rubric': 'betrayal_reciprocity',
                'detail': 'Possible betrayal of Nessa without later social consequence cue (soft)',
                'actionable': False,
            })

    # Run-level checks for serious personas
    persona = run_dir.name
    if 'serious' in persona or 'cooperative' in persona or 'long_' in persona:
        full = '\n'.join(t.get('prose') or '' for t in turns)
        if 'slit' in full.lower() or 'door' in full.lower():
            if not saw_staff_ask and 'step away' not in full.lower() and 'back' not in full.lower():
                soft_notes.append({
                    'rubric': 'npc_motive',
                    'detail': 'Staff ask never clearly restated in serious run (soft)',
                    'actionable': False,
                })
        # Memory: if cup/book examined early, later cell returns should not invent windows etc. — covered by prosecutor
        if re.search(r'\bmark\b|\bbruise\b', full, re.I):
            # soft: later self-examine could echo — not required
            pass

    # Deduplicate identical defects
    seen = set()
    uniq = []
    for d in defects:
        key = (d['turn'], d['rubric'], d['detail'])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(d)

    return {
        'run': run_dir.name,
        'path': str(run_dir),
        'turns_judged': max(0, len(turns) - 1),
        'ok': len(uniq) == 0,
        'defect_count': len(uniq),
        'defects': uniq,
        'soft_notes': soft_notes,
    }


def judge_campaign(root: Path) -> dict[str, Any]:
    runs = sorted(
        p for p in root.iterdir()
        if p.is_dir() and (p / 'short_transcript.txt').is_file()
    )
    if not runs and (root / 'short_transcript.txt').is_file():
        runs = [root]
    reports = [judge_run(r) for r in runs]
    actionable = [d for r in reports for d in r.get('defects') or []]
    summary = {
        'campaign': str(root),
        'runs': len(reports),
        'ok': all(r.get('ok') for r in reports) if reports else False,
        'total_actionable_defects': len(actionable),
        'reports': reports,
    }
    return summary


def _write_reports(summary: dict, root: Path) -> None:
    (root / 'coherence_report.json').write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8',
    )
    lines = [
        f'# Coherence report: {root.name}',
        '',
        f"OK: {summary.get('ok')}  |  actionable defects: {summary.get('total_actionable_defects', 0)}",
        '',
    ]
    for r in summary.get('reports') or []:
        lines.append(f"## {r.get('run')} — {'PASS' if r.get('ok') else 'FAIL'} ({r.get('defect_count', 0)})")
        for d in r.get('defects') or []:
            lines.append(
                f"- turn {d.get('turn')}: **{d.get('rubric')}** — {d.get('detail')}"
            )
            if d.get('quote'):
                lines.append(f"  > {d['quote'][:160]}")
        for n in r.get('soft_notes') or []:
            lines.append(f"- soft: {n.get('detail')}")
        lines.append('')
    (root / 'coherence_report.md').write_text('\n'.join(lines), encoding='utf-8')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Narrative coherence judge for short transcripts')
    ap.add_argument('path', type=Path, help='Campaign dir or single run dir')
    args = ap.parse_args(argv)
    root = args.path
    if not root.exists():
        print(f'Not found: {root}', file=sys.stderr)
        return 2
    summary = judge_campaign(root)
    out_root = root if root.is_dir() else root.parent
    _write_reports(summary, out_root if (out_root / 'short_transcript.txt').is_file() is False or list(out_root.glob('*_seed*')) else root)
    # Always write beside the judged path
    if any(root.glob('*_seed*')) or (root / 'campaign_summary.json').is_file():
        _write_reports(summary, root)
    elif (root / 'short_transcript.txt').is_file():
        _write_reports(summary, root)
    else:
        _write_reports(summary, root)

    print(json.dumps({
        'ok': summary['ok'],
        'runs': summary['runs'],
        'total_actionable_defects': summary['total_actionable_defects'],
        'report': str(root / 'coherence_report.md'),
    }, indent=2))
    return 0 if summary['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
