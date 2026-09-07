# -*- coding: utf-8 -*-
"""Verify Level 1 campaign: original 6 exit criteria + additional checks."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\joesa\Documents\Cursor\GlenGame\tools\playtests\20260907_final")
sys.path.insert(0, str(ROOT))

# Run original analyzer first (writes report + prints criteria)
import _analyze_exit_criteria as base  # noqa: E402

base.main()

report_path = ROOT / "_exit_criteria_report.json"
report = json.loads(report_path.read_text(encoding="utf-8"))

PERSONAS = [
    "cooperative_serious_seed101",
    "minimalist_inspector_seed102",
    "obstructive_seed103",
    "hostile_violent_seed104",
    "escape_obsessed_seed105",
    "absurd_surreal_seed106",
    "book_diver_seed107",
    "language_maximalist_seed108",
    "object_chaos_seed109",
    "mixed_resist_then_book_seed110",
]


def load_jsonl(path: Path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def facts_text(res: dict) -> str:
    facts = (res or {}).get("facts") or []
    if isinstance(facts, list):
        return " ".join(str(f) for f in facts)
    return str(facts)


def structured_facts(res: dict) -> list:
    return list((res or {}).get("structured_facts") or [])


def structured_types(res: dict) -> list:
    types = []
    for f in structured_facts(res):
        if isinstance(f, dict) and f.get("type"):
            types.append(str(f.get("type")))
    return types


extra = {}

# --- A: book_diver enters book_dungeon on read ---
bd_dir = ROOT / "book_diver_seed107"
bd_traces = load_jsonl(bd_dir / "traces.jsonl")
bd_enter = []
for rec in bd_traces:
    inp = (rec.get("input") or "").lower()
    mode = rec.get("mode")
    tr = rec.get("trace") or {}
    before_mode = (tr.get("before_state") or {}).get("mode")
    res = tr.get("resolution") or {}
    types = structured_types(res)
    readish = any(w in inp for w in ("read", "open the book", "open book")) and "book" in inp
    if not readish and "read" in inp:
        readish = True
    entered = mode == "book_dungeon" or "book_enter" in types
    if readish and entered:
        bd_enter.append({
            "turn": rec.get("turn"),
            "input": rec.get("input"),
            "before_mode": before_mode,
            "mode": mode,
            "types": types,
            "facts": facts_text(res)[:200],
        })
# also: any mode==book_dungeon after a read at some point
any_book_mode = [r for r in bd_traces if r.get("mode") == "book_dungeon"]
extra["A_book_diver_enters_on_read"] = {
    "status": "PASS" if bd_enter else "FAIL",
    "enter_events": bd_enter[:10],
    "book_dungeon_turns": len(any_book_mode),
    "evidence": bd_enter[0] if bd_enter else {"note": "no read->book_dungeon transition found", "book_dungeon_turns": len(any_book_mode)},
}

# --- B: no book_exit structured fact while mode remains facility ---
book_exit_viols = []
for dname in PERSONAS:
    d = ROOT / dname
    for rec in load_jsonl(d / "traces.jsonl"):
        mode = rec.get("mode")
        tr = rec.get("trace") or {}
        res = tr.get("resolution") or {}
        for f in structured_facts(res):
            if not isinstance(f, dict):
                continue
            t = str(f.get("type") or "").lower()
            if t == "book_exit" and mode == "facility":
                book_exit_viols.append({
                    "persona": dname,
                    "turn": rec.get("turn"),
                    "input": rec.get("input"),
                    "mode": mode,
                    "fact": f,
                    "facts": facts_text(res)[:180],
                })
extra["B_no_book_exit_while_facility"] = {
    "status": "PASS" if not book_exit_viols else "FAIL",
    "violation_count": len(book_exit_viols),
    "violations": book_exit_viols[:20],
}

# --- C: short_transcript.txt and short.jsonl for all 10 ---
missing_short = []
present = {}
for dname in PERSONAS:
    d = ROOT / dname
    st = (d / "short_transcript.txt").exists()
    sj = (d / "short.jsonl").exists()
    present[dname] = {"short_transcript.txt": st, "short.jsonl": sj}
    if not st or not sj:
        missing_short.append({"persona": dname, "short_transcript.txt": st, "short.jsonl": sj})
extra["C_short_artifacts_all_10"] = {
    "status": "PASS" if not missing_short else "FAIL",
    "missing": missing_short,
    "present": present,
}

# --- D: zero Structured State / sated|quenched dumps in short transcripts ---
leak_pat = re.compile(r"Structured\s+State|sated\s*\|\s*quenched|\bsated\b\s*[:=]|\bquenched\b\s*[:=]", re.I)
short_leaks = []
for dname in PERSONAS:
    path = ROOT / dname / "short_transcript.txt"
    if not path.exists():
        continue
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if leak_pat.search(line):
            short_leaks.append({"persona": dname, "line": i, "snip": line[:160]})
extra["D_no_structured_dumps_in_short"] = {
    "status": "PASS" if not short_leaks else "FAIL",
    "violation_count": len(short_leaks),
    "violations": short_leaks[:20],
}

# --- E: throw book never enters book_dungeon ---
throw_enter = []
for dname in PERSONAS:
    for rec in load_jsonl(ROOT / dname / "traces.jsonl"):
        inp = (rec.get("input") or "").lower()
        if "throw" not in inp or "book" not in inp:
            continue
        tr = rec.get("trace") or {}
        before_mode = (tr.get("before_state") or {}).get("mode")
        mode = rec.get("mode")
        res = tr.get("resolution") or {}
        types = structured_types(res)
        entered = (before_mode == "facility" and mode == "book_dungeon") or ("book_enter" in types)
        if entered or mode == "book_dungeon":
            # only count if this throw caused enter / still book after throw from facility
            if entered or (mode == "book_dungeon" and before_mode != "book_dungeon"):
                throw_enter.append({
                    "persona": dname,
                    "turn": rec.get("turn"),
                    "input": rec.get("input"),
                    "before_mode": before_mode,
                    "mode": mode,
                    "types": types,
                    "facts": facts_text(res)[:180],
                })
extra["E_throw_book_never_enters"] = {
    "status": "PASS" if not throw_enter else "FAIL",
    "violation_count": len(throw_enter),
    "violations": throw_enter[:20],
}

# --- F: refuse wash forced cases are compromised not direct+achieved ---
refuse_wash_bad = []
refuse_wash_ok = []
for dname in PERSONAS:
    for rec in load_jsonl(ROOT / dname / "traces.jsonl"):
        inp = (rec.get("input") or "").lower()
        if "wash" not in inp:
            continue
        refuse_like = any(w in inp for w in ("refuse", "won't", "will not", "not wash", "don't wash", "do not wash", "resist"))
        if not refuse_like:
            continue
        tr = rec.get("trace") or {}
        res = tr.get("resolution") or {}
        enactment = rec.get("enactment") or res.get("enactment")
        achieved = res.get("intended_effect_achieved")
        types = structured_types(res)
        facts = facts_text(res).lower()
        washed = "washed" in types or ("you wash" in facts) or ("washing happens" in facts) or ("anyway" in facts)
        # forced wash case: wash still happens despite refuse
        forced = washed and ("refusal fails" in facts or "anyway" in facts or "washed" in types or enactment == "compromised")
        # also treat washed type after refuse as forced
        if "washed" in types or ("washing happens" in facts) or ("you wash" in facts and refuse_like):
            forced = True
        info = {
            "persona": dname,
            "turn": rec.get("turn"),
            "input": rec.get("input"),
            "enactment": enactment,
            "intended_effect_achieved": achieved,
            "types": types,
            "facts": facts_text(res)[:200],
            "enactment_cause": rec.get("enactment_cause") or res.get("enactment_cause"),
        }
        if not forced and not washed:
            continue
        # forced wash must NOT be direct + achieved
        if enactment == "direct" and achieved is True:
            refuse_wash_bad.append(info)
        else:
            refuse_wash_ok.append(info)

extra["F_refuse_wash_compromised_not_direct_achieved"] = {
    "status": "PASS" if not refuse_wash_bad else "FAIL",
    "violation_count": len(refuse_wash_bad),
    "violations": refuse_wash_bad[:20],
    "ok_cases": refuse_wash_ok[:20],
}

# Merge into report
report["extra_criteria"] = extra
report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

print("\n" + "=" * 60)
print("=== EXTRA CRITERIA ===")
for k, v in extra.items():
    print(f"  {k}: {v['status']}", end="")
    if "violation_count" in v:
        print(f" ({v['violation_count']} violations)")
    elif k.startswith("A_"):
        ev = v.get("evidence") or {}
        print(f" | book_dungeon_turns={v.get('book_dungeon_turns')} evidence_turn={ev.get('turn')} input={ev.get('input')!r}")
    elif k.startswith("C_"):
        print(f" | missing={len(v.get('missing') or [])}")
    else:
        print()
    # brief evidence
    if v["status"] == "PASS":
        if k.startswith("A_"):
            ev = v["evidence"]
            print(f"     evidence: turn {ev.get('turn')} input={ev.get('input')!r} mode={ev.get('mode')} types={ev.get('types')}")
        elif k.startswith("C_"):
            print(f"     evidence: all 10 have short_transcript.txt + short.jsonl")
        elif k.startswith("F_"):
            print(f"     evidence: {len(v.get('ok_cases') or [])} refuse-wash forced case(s) correctly not direct+achieved")
            for c in (v.get("ok_cases") or [])[:5]:
                print(f"       [{c['persona']} t{c['turn']}] enact={c['enactment']} ach={c['intended_effect_achieved']} types={c['types']}")
        else:
            print(f"     evidence: zero violations")
    else:
        for viol in (v.get("violations") or v.get("missing") or [v.get("evidence")])[:5]:
            if not viol:
                continue
            print("     FAIL:", {x: viol[x] for x in viol if x in (
                "persona", "turn", "input", "mode", "kind", "snip", "line",
                "enactment", "intended_effect_achieved", "types", "facts", "short_transcript.txt", "short.jsonl", "note"
            )})

print("\n=== ORIGINAL 6 (from report) ===")
for k, v in report["criteria"].items():
    print(f"  {k}: {v['status']} ({v['violation_count']} violations)")
    for viol in v["violations"][:3]:
        print("   -", {x: viol[x] for x in viol if x in (
            "persona", "turn", "kind", "input", "pattern", "decision", "reason", "snip", "facts_snip", "classification"
        )})

print("\nWrote", report_path)
