# -*- coding: utf-8 -*-
import json, re
from pathlib import Path
ROOT = Path(r"C:\Users\joesa\Documents\Cursor\GlenGame\tools\playtests\20260907_1928")

def load(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

print("=== C2 book_dungeon turns ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    for rec in load(d / "traces.jsonl"):
        if rec.get("mode") != "book_dungeon":
            continue
        tr = rec["trace"]
        ni = tr.get("narrator_input") or {}
        vis = ni.get("visible_entities")
        after = tr.get("after_state") or {}
        s = json.dumps(after).lower()
        cell = [e for e in ("bed", "cup", "door") if re.search(r"\b" + e + r"\b", s)]
        phase_keys = [k for k in ni.keys() if "phase" in k or "facility" in k or "debug" in k]
        print("%s t%s input=%r" % (d.name, rec["turn"], rec.get("input")))
        print("  ni.visible=%r facility_phase=%s phase_keys=%s" % (vis, "facility_phase" in ni, phase_keys))
        print("  after cell hits=%s" % cell)

print("\n=== C3 cup/bowl throw/spill ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    for rec in load(d / "traces.jsonl"):
        inp = (rec.get("input") or "").lower()
        tr = rec["trace"]
        res = tr.get("resolution") or {}
        img = tr.get("image") or {}
        types = [f.get("type") for f in (res.get("structured_facts") or []) if isinstance(f, dict)]
        hit = any(t in types for t in ("cup_thrown", "bowl_spilled", "cup_spilled", "bowl_thrown"))
        hit = hit or (("cup" in inp or "bowl" in inp) and any(w in inp for w in ("throw", "spill", "pour", "smash", "drop")))
        if not hit:
            continue
        facts = " ".join(res.get("facts") or [])
        print("%s t%s %r dirty=%s state_changed=%s dec=%s reason=%s types=%s" % (
            d.name, rec["turn"], rec.get("input"), res.get("image_dirty"), res.get("state_changed"),
            img.get("decision"), img.get("reason"), types))
        print("  facts=%s" % facts[:220])

print("\n=== C1 candidates ===")
pats = [r"pull.*bed", r"throw.*book", r"hide.*food", r"will not back", r"won't back", r"fight sleep", r"refuse.*wash", r"won't wash"]
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    for rec in load(d / "traces.jsonl"):
        inp = rec.get("input") or ""
        if not any(re.search(p, inp, re.I) for p in pats):
            continue
        tr = rec["trace"]
        res = tr.get("resolution") or {}
        types = [f.get("type") for f in (res.get("structured_facts") or []) if isinstance(f, dict)]
        facts = " ".join(res.get("facts") or [])
        print("%s t%s %r mode=%s enact=%s ach=%s types=%s" % (
            d.name, rec["turn"], inp, rec.get("mode"), rec.get("enactment"),
            res.get("intended_effect_achieved"), types))
        print("  facts=%s" % facts[:260])

print("\n=== C4 forced/compromised with direct+achieved ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    for rec in load(d / "traces.jsonl"):
        tr = rec["trace"]
        res = tr.get("resolution") or {}
        enactment = rec.get("enactment") or res.get("enactment")
        achieved = res.get("intended_effect_achieved")
        facts = " ".join(res.get("facts") or []).lower()
        inp = (rec.get("input") or "").lower()
        cause = (rec.get("enactment_cause") or res.get("enactment_cause") or "")
        # compromised/inverted marked wrong
        if enactment == "direct" and achieved is True:
            if "refusal fails" in facts or "happens anyway" in facts or "forced" in facts:
                print("SUSPECT %s t%s %r enact=%s ach=%s cause=%r" % (d.name, rec["turn"], rec.get("input"), enactment, achieved, cause))
                print("  facts=%s" % facts[:240])
        if enactment == "compromised" and achieved is True:
            # may be ok for speech compromise; flag refuse/force cases
            if any(w in inp for w in ("refuse", "fight", "won't", "will not", "hide")):
                print("COMP+ACH %s t%s %r cause=%r" % (d.name, rec["turn"], rec.get("input"), cause))
                print("  facts=%s" % facts[:240])

print("\n=== C5 leak scan narrator_output + short_transcript ===")
pats = [re.compile(r"Structured\s+State", re.I), re.compile(r"facility\s+phase", re.I),
        re.compile(r"sated\s*\|\s*quenched", re.I), re.compile(r"\bsated\b\s*[:=]", re.I),
        re.compile(r"\bquenched\b\s*[:=]", re.I)]
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    for rec in load(d / "traces.jsonl"):
        out = (rec["trace"].get("narrator_output") or "")
        for pat in pats:
            if pat.search(out):
                print("LEAK narrator %s t%s %s" % (d.name, rec["turn"], pat.pattern))
    for fname in ("short_transcript.txt", "transcript.txt"):
        text = (d / fname).read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            for pat in pats:
                if pat.search(line):
                    print("LEAK %s:%s:%s %r" % (d.name, fname, i, line[:120]))

print("\n=== C6 him/no for language_maximalist + obstructive ===")
for name in ("language_maximalist_seed108", "obstructive_seed103"):
    d = ROOT / name
    prev = None
    for rec in load(d / "traces.jsonl"):
        inp = rec.get("input") or ""
        tr = rec["trace"]
        vi = tr.get("validated_intent") or {}
        raw = vi.get("raw") or {}
        action = raw.get("action") or {}
        target = vi.get("target") or action.get("target_ref")
        cls = raw.get("classification") or vi.get("classification")
        ac = vi.get("action_class") or action.get("class")
        g = tr.get("grounding") or {}
        bindings = g.get("bindings") if isinstance(g, dict) else None
        if re.search(r"\bhim\b|\bhe\b", inp, re.I) or inp.strip().lower() in ("no", "no.", "nope"):
            print("%s t%s %r ac=%s tgt=%r cls=%s bindings=%s" % (name, rec["turn"], inp, ac, target, cls, bindings))
            print("  facts=%s" % (" ".join((tr.get("resolution") or {}).get("facts") or []))[:200])
            if prev:
                print("  prev_input=%r" % prev.get("input"))
        prev = rec

print("\n=== hide food when food present ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    for rec in load(d / "traces.jsonl"):
        inp = (rec.get("input") or "").lower()
        if "hide" in inp and "food" in inp:
            tr = rec["trace"]
            res = tr.get("resolution") or {}
            before = tr.get("before_state") or {}
            print("%s t%s phase=%s room=%s" % (d.name, rec["turn"], rec.get("phase"), (before.get("facility") or {}).get("room_id")))
            print("  facts=%s" % (" ".join(res.get("facts") or []))[:240])
            print("  types=%s enact=%s ach=%s" % (
                [f.get("type") for f in (res.get("structured_facts") or []) if isinstance(f, dict)],
                rec.get("enactment"), res.get("intended_effect_achieved")))
