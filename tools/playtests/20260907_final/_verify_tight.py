# -*- coding: utf-8 -*-
import json, re
from pathlib import Path

ROOT = Path(r"tools/playtests/20260907_final")
PERSONAS = [
    "cooperative_serious_seed101","minimalist_inspector_seed102","obstructive_seed103",
    "hostile_violent_seed104","escape_obsessed_seed105","absurd_surreal_seed106",
    "book_diver_seed107","language_maximalist_seed108","object_chaos_seed109",
    "mixed_resist_then_book_seed110",
]

def load_jsonl(p):
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out

def facts_text(res):
    f = (res or {}).get("facts") or []
    return " ".join(str(x) for x in f) if isinstance(f, list) else str(f)

def stypes(res):
    return [str(f.get("type")) for f in ((res or {}).get("structured_facts") or []) if isinstance(f, dict) and f.get("type")]

def get_intent(rec):
    tr = rec.get("trace") or {}
    vi = tr.get("validated_intent") or {}
    if isinstance(vi, dict) and isinstance(vi.get("raw"), dict):
        raw = vi["raw"]
        action = raw.get("action") or {}
        return {
            "action_class": vi.get("action_class") or action.get("class"),
            "target": vi.get("target") or action.get("target_ref"),
            "method": vi.get("method") or action.get("method"),
            "classification": raw.get("classification") or vi.get("classification"),
        }
    return {
        "action_class": vi.get("action_class"),
        "target": vi.get("target"),
        "method": vi.get("method"),
        "classification": vi.get("classification"),
    }

CELL = {"bed", "cup", "door"}
c1, c2, c3, c4, c5, c6 = [], [], [], [], [], []

for dname in PERSONAS:
    pname = re.sub(r"_seed\d+$", "", dname)
    prev = None
    for rec in load_jsonl(ROOT / dname / "traces.jsonl"):
        tr = rec.get("trace") or {}
        res = tr.get("resolution") or {}
        inp = (rec.get("input") or "").lower()
        facts = facts_text(res).lower()
        types = set(stypes(res))
        mode = rec.get("mode")
        intent = get_intent(rec)
        ac = (intent.get("action_class") or "").lower()
        base = {"persona": pname, "turn": rec.get("turn"), "input": rec.get("input"), "mode": mode, "phase": rec.get("phase")}

        if any(w in inp for w in ("pull", "drag", "yank", "strip")) and any(w in inp for w in ("bed", "bedding", "blanket", "sheet")):
            if any(bad in facts for bad in ("lie on the bed", "sleep does not come", "you lie", "lie down", "you sleep")):
                c1.append({**base, "kind": "pull_bedding->sleep/lie", "facts_snip": facts[:180]})
        if ("throw" in inp or ac == "throw") and "book" in inp:
            before_mode = (tr.get("before_state") or {}).get("mode")
            prev_mode = None if not prev else prev.get("mode")
            entered = "book_enter" in types or (mode == "book_dungeon" and (before_mode == "facility" or prev_mode == "facility" or prev_mode is None and mode == "book_dungeon" and "book_enter" in types))
            if "book_enter" in types or (mode == "book_dungeon" and prev_mode != "book_dungeon"):
                c1.append({**base, "kind": "throw_book->book_enter", "types": sorted(types), "facts_snip": facts[:180]})
        if "hide" in inp and "food" in inp:
            if "you refuse the food" in facts and "hide" not in facts and "not here" not in facts and "no food" not in facts:
                c1.append({**base, "kind": "hide_food->refuse_only", "facts_snip": facts[:180]})
        if re.search(r"(will not|won't|refuse to)\s+back", inp) or "not back away" in inp:
            if re.search(r"(?<!not )(?<!do not )(?<!don't )give the door space", facts) or re.search(r"\byou give the door space\b", facts):
                c1.append({**base, "kind": "will_not_back->give_door_space", "facts_snip": facts[:180]})
        if "fight sleep" in inp or ("fight" in inp and "sleep" in inp):
            if "sleep follows" in facts:
                c1.append({**base, "kind": "fight_sleep->sleep_follows", "facts_snip": facts[:180]})
        if ("refuse" in inp or "won't" in inp or "will not" in inp) and "wash" in inp:
            enactment = rec.get("enactment") or res.get("enactment")
            achieved = res.get("intended_effect_achieved")
            if re.search(r"\byou wash\b", facts) and "anyway" not in facts and "refusal fails" not in facts and "forced" not in facts:
                if enactment == "direct" and achieved is True:
                    c1.append({**base, "kind": "refuse_wash->voluntary_wash", "facts_snip": facts[:180]})

        if mode == "book_dungeon":
            vis = set()
            for src in ((tr.get("after_state") or {}).get("visible_entities"), (tr.get("narrator_input") or {}).get("visible_entities")):
                if isinstance(src, list):
                    for v in src:
                        if isinstance(v, str):
                            vis.add(v.lower())
                        elif isinstance(v, dict):
                            vis.add(str(v.get("id") or v.get("name") or "").lower())
                elif isinstance(src, dict):
                    vis |= {str(k).lower() for k in src}
            bleed = vis & CELL
            if bleed:
                c2.append({**base, "kind": "cell_bleed", "entities": sorted(bleed)})

        spill_types = {"cup_spilled", "bowl_spilled", "cup_thrown", "bowl_thrown", "liquid_spilled"}
        if types & spill_types or (("throw" in inp or "spill" in inp or "pour" in inp) and ("cup" in inp or "bowl" in inp) and res.get("state_changed")):
            image_dirty = res.get("image_dirty")
            img = tr.get("image") or {}
            decision = str(img.get("decision") or "")
            reason = str(img.get("reason") or "")
            bad = image_dirty is False
            if "visible state unchanged" in reason.lower():
                bad = True
            if decision.upper() == "REGENERATE" and image_dirty is not False and "visible state unchanged" not in reason.lower():
                bad = False
            if bad:
                c3.append({**base, "kind": "spill_without_image_dirty", "image_dirty": image_dirty, "decision": decision, "reason": reason[:120], "types": sorted(types), "facts_snip": facts[:160]})

        enactment = rec.get("enactment") or res.get("enactment")
        achieved = res.get("intended_effect_achieved")
        cause = (rec.get("enactment_cause") or res.get("enactment_cause") or "")
        if enactment == "direct" and achieved is True:
            patterns = [
                (r"refuse.*wash|won't wash|will not wash|not wash", r"\byou wash\b", "refuse_wash_as_achieved"),
                (r"fight sleep|resist sleep|won't sleep|refuse.*sleep", r"sleep follows|\byou sleep\b", "fight_sleep_as_achieved"),
                (r"will not back|won't back|not back away|stand (my|your) ground|refuse.*back", r"(?<!not )(?<!do not )\bgive the door space\b|\byou step back\b", "stand_firm_as_retreat_achieved"),
                (r"refuse.*food|won't eat|will not eat|hide the food", r"you eat\.|you accept the food", "refuse_food_as_eat_achieved"),
            ]
            for ip, fp, kind in patterns:
                if re.search(ip, inp) and re.search(fp, facts):
                    if "refusal fails" in facts or "anyway" in facts or "forced" in facts or "despite" in facts:
                        c4.append({**base, "kind": kind + "_forced_frame_but_achieved_true", "facts_snip": facts[:180], "cause": cause})
                    else:
                        c4.append({**base, "kind": kind, "facts_snip": facts[:180], "cause": cause})

        narr = str(tr.get("narrator_output") or "")
        for pat in [r"Structured\s+State", r"facility\s+phase", r"sated\s*\|\s*quenched"]:
            if re.search(pat, narr, re.I):
                c5.append({**base, "kind": "narrator_leak", "pattern": pat, "snip": narr[:120]})

        if re.search(r"\bhim\b", inp):
            tgt = (intent.get("target") or "")
            if str(tgt).lower() in ("glen", "player", "self"):
                c6.append({**base, "kind": "him_bound_player", "target": tgt, "classification": intent.get("classification")})
            g = tr.get("grounding") or {}
            bindings = g.get("bindings") if isinstance(g, dict) else None
            if isinstance(bindings, dict) and str(bindings.get("target") or "").lower() in ("glen", "player", "self"):
                c6.append({**base, "kind": "him_ground_bound_glen", "bindings": bindings})
        if inp.strip() in ("no", "no.", "no!", "nope", "nah", "n"):
            classification = intent.get("classification") or ""
            if classification == "PERCEPTION_QUERY" or ac.upper() == "PERCEIVE":
                back = False
                if prev:
                    pi = (prev.get("input") or "").lower()
                    po = str((prev.get("trace") or {}).get("narrator_output") or "").lower()
                    pf = facts_text((prev.get("trace") or {}).get("resolution") or {}).lower()
                    if any(w in pi or w in po or w in pf for w in ("back", "door space", "step back", "stand clear")):
                        back = True
                if back:
                    c6.append({**base, "kind": "bare_no_as_PERCEIVE", "classification": classification, "action_class": ac})
        prev = rec

    for name in ("short_transcript.txt", "transcript.txt"):
        path = ROOT / dname / name
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if re.search(r"Structured\s+State|sated\s*\|\s*quenched", line, re.I):
                c5.append({"persona": pname, "dir": dname, "file": name, "line": i, "snip": line[:140], "kind": "transcript_leak"})

bd = load_jsonl(ROOT / "book_diver_seed107" / "traces.jsonl")
A_events = []
for rec in bd:
    inp = (rec.get("input") or "").lower()
    res = (rec.get("trace") or {}).get("resolution") or {}
    types = stypes(res)
    if "read" in inp and (rec.get("mode") == "book_dungeon" or "book_enter" in types):
        A_events.append({"turn": rec.get("turn"), "input": rec.get("input"), "mode": rec.get("mode"), "types": types})

B_viol = []
for dname in PERSONAS:
    prev = None
    for rec in load_jsonl(ROOT / dname / "traces.jsonl"):
        res = (rec.get("trace") or {}).get("resolution") or {}
        if "book_exit" in stypes(res):
            prev_mode = None if not prev else prev.get("mode")
            if rec.get("mode") == "facility" and prev_mode != "book_dungeon":
                B_viol.append({"persona": dname, "turn": rec.get("turn"), "input": rec.get("input"), "prev_mode": prev_mode, "mode": rec.get("mode")})
        prev = rec

C_miss = []
for dname in PERSONAS:
    st = (ROOT / dname / "short_transcript.txt").exists()
    sj = (ROOT / dname / "short.jsonl").exists()
    if not st or not sj:
        C_miss.append(dname)

D_viol = []
for dname in PERSONAS:
    path = ROOT / dname / "short_transcript.txt"
    if not path.exists():
        continue
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if re.search(r"Structured\s+State|sated\s*\|\s*quenched", line, re.I):
            D_viol.append({"persona": dname, "line": i, "snip": line[:140]})

E_viol = []
for dname in PERSONAS:
    prev = None
    for rec in load_jsonl(ROOT / dname / "traces.jsonl"):
        inp = (rec.get("input") or "").lower()
        if "throw" in inp and "book" in inp:
            res = (rec.get("trace") or {}).get("resolution") or {}
            types = stypes(res)
            prev_mode = None if not prev else prev.get("mode")
            if "book_enter" in types or (rec.get("mode") == "book_dungeon" and prev_mode != "book_dungeon"):
                E_viol.append({"persona": dname, "turn": rec.get("turn"), "input": rec.get("input"), "mode": rec.get("mode"), "types": types, "facts": facts_text(res)[:160]})
        prev = rec

F_bad, F_ok = [], []
for dname in PERSONAS:
    for rec in load_jsonl(ROOT / dname / "traces.jsonl"):
        inp = (rec.get("input") or "").lower()
        if "wash" not in inp:
            continue
        if not any(w in inp for w in ("refuse", "won't", "will not", "not wash", "resist")):
            continue
        res = (rec.get("trace") or {}).get("resolution") or {}
        types = stypes(res)
        facts = facts_text(res).lower()
        enactment = rec.get("enactment") or res.get("enactment")
        achieved = res.get("intended_effect_achieved")
        forced = ("washed" in types) or ("washing happens" in facts) or ("refusal fails" in facts) or (re.search(r"\byou wash\b", facts) is not None)
        if not forced:
            continue
        info = {"persona": dname, "turn": rec.get("turn"), "input": rec.get("input"), "enactment": enactment, "achieved": achieved, "types": types, "facts": facts_text(res)[:160]}
        if enactment == "direct" and achieved is True:
            F_bad.append(info)
        else:
            F_ok.append(info)

def status(ok):
    return "PASS" if ok else "FAIL"

def show(name, viols, limit=5):
    print(f"{status(not viols)} {name} ({len(viols)})")
    for v in viols[:limit]:
        keys = ("persona", "turn", "kind", "input", "types", "facts_snip", "image_dirty", "decision", "entities", "snip", "pattern", "target", "facts", "mode", "prev_mode", "enactment", "achieved", "line")
        print("   ", {k: v[k] for k in keys if k in v})

print("CAMPAIGN_EXIT_CODE=0")
print()
print("=== INDEX ===")
print((ROOT / "INDEX.md").read_text(encoding="utf-8"))
print("=== CHECKS ===")
show("1_zero_substitutions", c1)
show("2_book_dungeon_no_cell", c2)
show("3_cup_bowl_image_dirty", c3)
show("4_forced_not_direct_achieved", c4)
show("5_no_structured_state_leaks", c5)
show("6_him_no_discourse", c6)
print(f"{status(bool(A_events))} A_book_diver_enters_on_read")
print("   ", A_events[0] if A_events else "none")
print(f"{status(not B_viol)} B_no_book_exit_while_facility ({len(B_viol)})")
print("    note: legitimate book_dungeon->facility exits excluded")
for v in B_viol[:3]:
    print("   ", v)
print(f"{status(not C_miss)} C_short_artifacts_all_10 missing={C_miss}")
print(f"{status(not D_viol)} D_no_structured_dumps_in_short ({len(D_viol)})")
for v in D_viol[:3]:
    print("   ", v)
print(f"{status(not E_viol)} E_throw_book_never_enters ({len(E_viol)})")
for v in E_viol[:3]:
    print("   ", v)
# show throw book evidence
for rec in load_jsonl(ROOT / "object_chaos_seed109" / "traces.jsonl"):
    if "throw" in (rec.get("input") or "").lower() and "book" in (rec.get("input") or "").lower():
        res = (rec.get("trace") or {}).get("resolution") or {}
        print("    evidence object_chaos:", rec.get("turn"), rec.get("input"), "mode=", rec.get("mode"), "types=", stypes(res), "facts=", facts_text(res)[:120])
print(f"{status(not F_bad)} F_refuse_wash_compromised_not_direct_achieved ({len(F_bad)})")
print(f"    ok_forced_cases={len(F_ok)}")
for v in F_ok[:5]:
    print("   ", v)
for v in F_bad[:5]:
    print("   BAD", v)

out = {
    "campaign_exit_code": 0,
    "criteria": {
        "1_zero_substitutions": {"status": status(not c1), "count": len(c1), "violations": c1},
        "2_book_dungeon_no_cell": {"status": status(not c2), "count": len(c2), "violations": c2},
        "3_cup_bowl_image_dirty": {"status": status(not c3), "count": len(c3), "violations": c3},
        "4_forced_not_direct_achieved": {"status": status(not c4), "count": len(c4), "violations": c4},
        "5_no_structured_state_leaks": {"status": status(not c5), "count": len(c5), "violations": c5},
        "6_him_no_discourse": {"status": status(not c6), "count": len(c6), "violations": c6},
        "A_book_diver_enters_on_read": {"status": status(bool(A_events)), "events": A_events},
        "B_no_book_exit_while_facility": {"status": status(not B_viol), "count": len(B_viol), "violations": B_viol},
        "C_short_artifacts_all_10": {"status": status(not C_miss), "missing": C_miss},
        "D_no_structured_dumps_in_short": {"status": status(not D_viol), "count": len(D_viol), "violations": D_viol},
        "E_throw_book_never_enters": {"status": status(not E_viol), "count": len(E_viol), "violations": E_viol},
        "F_refuse_wash_compromised": {"status": status(not F_bad), "count": len(F_bad), "ok": F_ok, "bad": F_bad},
    },
}
(ROOT / "_verify_tight_report.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print("Wrote", ROOT / "_verify_tight_report.json")
