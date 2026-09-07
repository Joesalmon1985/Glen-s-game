# -*- coding: utf-8 -*-
import json, re
from pathlib import Path
ROOT = Path(r"C:\Users\joesa\Documents\Cursor\GlenGame\tools\playtests\20260907_1928")

def load(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

# book_dungeon lie on bed / look at door
print("=== book_dungeon cell-referent actions ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    for rec in load(d / "traces.jsonl"):
        if rec.get("mode") != "book_dungeon":
            continue
        inp = (rec.get("input") or "").lower()
        if any(w in inp for w in ("bed", "cup", "door", "slit", "cell", "wash", "sleep")):
            tr = rec["trace"]
            res = tr.get("resolution") or {}
            ni = tr.get("narrator_input") or {}
            print("%s t%s %r" % (d.name, rec["turn"], rec.get("input")))
            print("  visible=%s facts=%s" % (ni.get("visible_entities"), " ".join(res.get("facts") or [])[:220]))
            print("  narrator=%s" % str(tr.get("narrator_output") or "")[:220])

# All washed/slept transitions with refuse/fight framing
print("\n=== wash/sleep outcomes vs intent ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    for rec in load(d / "traces.jsonl"):
        tr = rec["trace"]
        res = tr.get("resolution") or {}
        types = [f.get("type") for f in (res.get("structured_facts") or []) if isinstance(f, dict)]
        facts = " ".join(res.get("facts") or [])
        fl = facts.lower()
        inp = (rec.get("input") or "")
        if "washed" in types or "slept" in types or re.search(r"\byou wash\b|sleep follows|you sleep", fl):
            print("%s t%s %r enact=%s ach=%s types=%s" % (
                d.name, rec["turn"], inp, rec.get("enactment"), res.get("intended_effect_achieved"), types))
            print("  facts=%s" % facts[:240])

# short.jsonl keys + any leak fields
print("\n=== short.jsonl schema + leak scan ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    rows = load(d / "short.jsonl")
    if not rows:
        print("%s EMPTY short.jsonl" % d.name)
        continue
    print("%s turns=%s keys=%s" % (d.name, len(rows), sorted(rows[0].keys())))
    for rec in rows:
        blob = json.dumps(rec)
        if re.search(r"Structured\s+State|facility\s+phase|sated\s*\|\s*quenched", blob, re.I):
            print("  LEAK in short.jsonl t%s" % rec.get("turn"))

# cup/bowl entity state changes any turn
print("\n=== entity cup/bowl state diffs ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    for rec in load(d / "traces.jsonl"):
        tr = rec["trace"]
        before = (tr.get("before_state") or {}).get("facility") or {}
        after = (tr.get("after_state") or {}).get("facility") or {}
        def ents(fac):
            e = fac.get("entities")
            if isinstance(e, dict):
                return e
            if isinstance(e, list):
                return {x.get("id"): x for x in e if isinstance(x, dict)}
            return {}
        be, ae = ents(before), ents(after)
        for key in ("cup", "bowl"):
            b, a = be.get(key), ae.get(key)
            if b is None and a is None:
                continue
            bs = b.get("state") if isinstance(b, dict) else b
            as_ = a.get("state") if isinstance(a, dict) else a
            if bs != as_:
                res = tr.get("resolution") or {}
                img = tr.get("image") or {}
                print("%s t%s %r %s %s -> %s dirty=%s dec=%s reason=%s" % (
                    d.name, rec["turn"], rec.get("input"), key, bs, as_,
                    res.get("image_dirty"), img.get("decision"), img.get("reason")))

# book_diver: did they enter book?
print("\n=== book_diver modes ===")
d = ROOT / "book_diver_seed107"
modes = []
for rec in load(d / "traces.jsonl"):
    modes.append((rec["turn"], rec.get("mode"), rec.get("input"), rec.get("enactment")))
print(modes)

# prosecutor hits absurd
print("\n=== absurd prosecutor / short transcript excerpts for refuse ===")
for name in ("absurd_surreal_seed106", "obstructive_seed103", "mixed_resist_then_book_seed110", "object_chaos_seed109"):
    d = ROOT / name
    st = (d / "short_transcript.txt").read_text(encoding="utf-8", errors="replace")
    print("--- %s short_transcript head ---" % name)
    print("\n".join(st.splitlines()[:40]))
    print("...")
