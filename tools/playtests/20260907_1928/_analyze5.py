# -*- coding: utf-8 -*-
import json, re
from pathlib import Path
ROOT = Path(r"C:\Users\joesa\Documents\Cursor\GlenGame\tools\playtests\20260907_1928")

def load(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

# All image decisions where structured fact is cup/bowl throw/spill OR facts mention spill
print("=== spill-related image decisions ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    for rec in load(d / "traces.jsonl"):
        tr = rec["trace"]
        res = tr.get("resolution") or {}
        img = tr.get("image") or {}
        types = [f.get("type") for f in (res.get("structured_facts") or []) if isinstance(f, dict)]
        facts = " ".join(res.get("facts") or []).lower()
        if not (set(types) & {"cup_thrown","bowl_spilled","cup_spilled","bowl_thrown"} or ("spill" in facts and ("cup" in facts or "bowl" in facts or "water" in facts or "food" in facts))):
            continue
        ok = res.get("image_dirty") is True and "unchanged" not in str(img.get("reason") or "").lower()
        print("[%s] %s t%s dirty=%s dec=%s reason=%r types=%s" % (
            "OK" if ok else "FAIL", d.name, rec["turn"], res.get("image_dirty"), img.get("decision"), img.get("reason"), types))

# book_exit without book_dungeon mode ever
print("\n=== book_enter / book_exit anomalies ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    modes = set()
    for rec in load(d / "traces.jsonl"):
        modes.add(rec.get("mode"))
        tr = rec["trace"]
        res = tr.get("resolution") or {}
        types = [f.get("type") for f in (res.get("structured_facts") or []) if isinstance(f, dict)]
        if set(types) & {"book_enter","book_exit","book_thrown"}:
            print("%s t%s mode=%s types=%s input=%r facts=%s" % (
                d.name, rec["turn"], rec.get("mode"), types, rec.get("input"),
                " ".join(res.get("facts") or [])[:160]))
    if "book_dungeon" not in modes and d.name.startswith("book_diver"):
        print("%s NEVER entered book_dungeon; modes=%s" % (d.name, modes))

# Count mode switches from campaign
print("\n=== mode switches per persona (from traces) ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    switches = []
    prev = None
    for rec in load(d / "traces.jsonl"):
        m = rec.get("mode")
        if prev and m != prev:
            switches.append("%s->%s@%s" % (prev, m, rec["turn"]))
        prev = m
    print("%s: %s" % (d.name, switches or "none"))

# Confirm file presence table
print("\n=== short_transcript + short.jsonl ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    st = d / "short_transcript.txt"
    sj = d / "short.jsonl"
    print("%s: short_transcript=%s (%s bytes) short.jsonl=%s (%s bytes)" % (
        d.name, st.exists(), st.stat().st_size if st.exists() else 0,
        sj.exists(), sj.stat().st_size if sj.exists() else 0))
