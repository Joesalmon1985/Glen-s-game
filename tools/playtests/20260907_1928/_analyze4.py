# -*- coding: utf-8 -*-
import json, re
from pathlib import Path
ROOT = Path(r"C:\Users\joesa\Documents\Cursor\GlenGame\tools\playtests\20260907_1928")

def load(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

# after_state structure
rec = load(ROOT / "object_chaos_seed109" / "traces.jsonl")[0]
after = rec["trace"]["after_state"]
print("after_state keys:", sorted(after.keys()))
for k, v in after.items():
    if isinstance(v, dict):
        print(" ", k, "keys", sorted(v.keys())[:30])
    elif isinstance(v, list):
        print(" ", k, "list", len(v), v[:3] if v else None)
    else:
        print(" ", k, repr(v)[:100])

# book_diver read book turns
print("\n=== book_diver book-related ===")
for rec in load(ROOT / "book_diver_seed107" / "traces.jsonl"):
    inp = (rec.get("input") or "").lower()
    if "book" in inp or "casket" in inp or "west" in inp or "attack" in inp:
        tr = rec["trace"]
        res = tr.get("resolution") or {}
        types = [f.get("type") for f in (res.get("structured_facts") or []) if isinstance(f, dict)]
        print("t%s %r mode=%s types=%s ach=%s" % (rec["turn"], rec.get("input"), rec.get("mode"), types, res.get("intended_effect_achieved")))
        print("  facts=%s" % (" ".join(res.get("facts") or []))[:260])
        print("  state_diff=%s" % str(tr.get("state_diff"))[:200])

# Scan all short responses for leak-ish and substitution symptoms
print("\n=== short.jsonl response scans ===")
checks = {
    "structured_state": re.compile(r"Structured\s+State", re.I),
    "facility_phase": re.compile(r"facility\s+phase", re.I),
    "sated_quenched": re.compile(r"sated\s*\|\s*quenched|\bsated\b\s*[:=]|\bquenched\b\s*[:=]", re.I),
    "give_door_space": re.compile(r"you give the door space", re.I),
    "you_wash_voluntary": re.compile(r"you wash\.", re.I),
    "sleep_follows": re.compile(r"sleep follows", re.I),
}
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    for rec in load(d / "short.jsonl"):
        resp = rec.get("response") or ""
        inp = rec.get("input") or ""
        for name, pat in checks.items():
            if pat.search(resp):
                # filter voluntary wash when input is wash
                if name == "you_wash_voluntary" and "refuse" not in inp.lower() and "won't" not in inp.lower():
                    continue
                if name == "sleep_follows" and "fight" not in inp.lower() and "refuse" not in inp.lower():
                    continue
                if name == "give_door_space" and "not" in resp.lower()[max(0, pat.search(resp).start()-20):pat.search(resp).start()]:
                    continue
                print("%s t%s [%s] inp=%r snip=%r" % (d.name, rec.get("turn"), name, inp, resp[max(0,pat.search(resp).start()-30):pat.search(resp).end()+40]))

# Confirm object_chaos image reasons and bedding/throw outcomes in short
print("\n=== object_chaos short key turns ===")
for rec in load(ROOT / "object_chaos_seed109" / "short.jsonl"):
    if rec["turn"] in (1, 2, 4, 13, 14):
        print("t%s > %s" % (rec["turn"], rec["input"]))
        print("  ", (rec.get("response") or "")[:180].replace("\n", " "))
        print("  IMG", (rec.get("image_prompt") or "")[:120])

# mixed_resist fight sleep / will not back short
print("\n=== mixed_resist key ===")
for rec in load(ROOT / "mixed_resist_then_book_seed110" / "short.jsonl"):
    if rec["turn"] in (4, 6, 14):
        print("t%s > %s" % (rec["turn"], rec["input"]))
        print("  ", (rec.get("response") or "")[:220].replace("\n", " "))

# obstructive no + refuse wash
print("\n=== obstructive key ===")
for rec in load(ROOT / "obstructive_seed103" / "short.jsonl"):
    if rec["turn"] in (5, 6, 11, 12, 14):
        print("t%s > %s" % (rec["turn"], rec["input"]))
        print("  ", (rec.get("response") or "")[:220].replace("\n", " "))

# language_maximalist him
print("\n=== language_maximalist him ===")
for rec in load(ROOT / "language_maximalist_seed108" / "short.jsonl"):
    if "him" in (rec.get("input") or "").lower():
        print("t%s > %s" % (rec["turn"], rec["input"]))
        print("  ", (rec.get("response") or "")[:220].replace("\n", " "))
