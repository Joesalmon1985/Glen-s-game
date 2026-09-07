# -*- coding: utf-8 -*-
"""Analyze Level 1 playtest campaign against exit criteria."""
from __future__ import annotations

import json
import re
from pathlib import Path
from collections import defaultdict

ROOT = Path(r"C:\Users\joesa\Documents\Cursor\GlenGame\tools\playtests\20260907_1928")
CELL_VISIBLE = {"bed", "cup", "door"}
LEAK_PATTERNS = [
    re.compile(r"Structured\s+State", re.I),
    re.compile(r"facility\s+phase", re.I),
    re.compile(r"\bsated\b", re.I),
    re.compile(r"\bquenched\b", re.I),
]

def load_jsonl(path: Path):
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            out.append({"_parse_error": str(e), "_line": i})
    return out

def facts_text(res: dict) -> str:
    facts = (res or {}).get("facts") or []
    if isinstance(facts, list):
        return " ".join(str(f) for f in facts)
    return str(facts)

def structured_types(res: dict) -> list:
    types = []
    for f in (res or {}).get("structured_facts") or []:
        if isinstance(f, dict) and f.get("type"):
            types.append(f.get("type"))
    return types

def get_intent(rec: dict) -> dict:
    tr = rec.get("trace") or {}
    vi = tr.get("validated_intent") or {}
    if isinstance(vi, dict) and "raw" in vi and isinstance(vi.get("raw"), dict):
        # flatten useful fields
        raw = vi["raw"]
        action = raw.get("action") or {}
        return {
            "action_class": vi.get("action_class") or action.get("class"),
            "target": vi.get("target") or action.get("target_ref"),
            "method": vi.get("method") or action.get("method"),
            "classification": raw.get("classification") or vi.get("classification"),
            "intended_effect": vi.get("intended_effect") or action.get("intended_effect"),
            "utterance": vi.get("utterance") or action.get("utterance"),
            "understood": raw.get("understood", vi.get("understood")),
            "raw": raw,
            "full": vi,
        }
    return {
        "action_class": vi.get("action_class"),
        "target": vi.get("target"),
        "method": vi.get("method"),
        "classification": vi.get("classification"),
        "intended_effect": vi.get("intended_effect"),
        "utterance": vi.get("utterance"),
        "full": vi,
    }

def after_facility(rec: dict) -> dict:
    tr = rec.get("trace") or {}
    after = tr.get("after_state") or {}
    return after.get("facility") or after.get("facility_state") or {}

def visible_entities(rec: dict):
    tr = rec.get("trace") or {}
    # prefer after_state / narrator_input
    for src in (
        (tr.get("after_state") or {}).get("visible_entities"),
        (tr.get("narrator_input") or {}).get("visible_entities"),
        (tr.get("before_state") or {}).get("visible_entities"),
    ):
        if src:
            return src
    return []

def normalize_visible(vis) -> set:
    out = set()
    if not vis:
        return out
    if isinstance(vis, dict):
        for k, v in vis.items():
            out.add(str(k).lower())
            if isinstance(v, str):
                out.add(v.lower())
            elif isinstance(v, dict):
                out.add(str(v.get("id") or v.get("name") or "").lower())
    elif isinstance(vis, list):
        for v in vis:
            if isinstance(v, str):
                out.add(v.lower())
            elif isinstance(v, dict):
                out.add(str(v.get("id") or v.get("name") or v.get("entity") or "").lower())
            else:
                out.add(str(v).lower())
    return {x for x in out if x}

def cup_bowl_spill_state_changed(rec: dict) -> bool:
    """Heuristic: cup/bowl related throw/spill with position/fullness change."""
    tr = rec.get("trace") or {}
    res = tr.get("resolution") or {}
    inp = (rec.get("input") or "").lower()
    types = structured_types(res)
    facts = facts_text(res).lower()
    spill_types = {"cup_spilled", "bowl_spilled", "cup_thrown", "bowl_thrown", "liquid_spilled", "spill"}
    if spill_types & set(types):
        return True
    # state_transitions mentioning cup/bowl spill/floor
    for st in res.get("state_transitions") or []:
        s = str(st).lower()
        if any(x in s for x in ("cup", "bowl", "spill")) and any(
            y in s for y in ("floor", "spill", "empty", "broken", "position", "full")
        ):
            return True
    # input-based with state_changed
    if res.get("state_changed") and any(w in inp for w in ("cup", "bowl", "throw", "spill", "pour")):
        if "cup" in inp or "bowl" in inp or "spill" in facts:
            # check entity state diffs
            before = (tr.get("before_state") or {})
            after = (tr.get("after_state") or {})
            bf = before.get("facility") or {}
            af = after.get("facility") or {}
            # entities may be list or dict
            def ent_map(fac):
                ents = fac.get("entities") or fac.get("entity_map") or {}
                if isinstance(ents, list):
                    return {str(e.get("id") or e.get("name")).lower(): e for e in ents if isinstance(e, dict)}
                if isinstance(ents, dict):
                    return {str(k).lower(): v for k, v in ents.items()}
                return {}
            bm, am = ent_map(bf), ent_map(af)
            for key in ("cup", "bowl", "water", "food"):
                b, a = bm.get(key), am.get(key)
                if b and a and b != a:
                    return True
            if "spill" in facts or "floor" in facts and ("cup" in facts or "bowl" in facts):
                return True
    return False

def is_forced_opposite(rec: dict) -> bool:
    """Detect forced opposite outcomes wrongly marked direct+achieved."""
    tr = rec.get("trace") or {}
    res = tr.get("resolution") or {}
    enactment = rec.get("enactment") or res.get("enactment")
    achieved = res.get("intended_effect_achieved")
    if not (enactment == "direct" and achieved is True):
        return False
    facts = facts_text(res).lower()
    inp = (rec.get("input") or "").lower()
    intent = get_intent(rec)
    ac = (intent.get("action_class") or "").lower()
    # refuse/resist but voluntary compliance without refusal-fails framing
    refuse_like = any(w in inp for w in ("refuse", "won't", "will not", "resist", "fight sleep", "not wash", "not eat", "hide the food", "i won't"))
    opposite_markers = [
        "you wash.",
        "you wash ",
        "sleep follows",
        "you sleep",
        "you eat",
        "you give the door space",
        "you step back",
        "anyway",  # sometimes forced
    ]
    # if refuse and voluntary wash without refusal fails / compromised language
    if refuse_like:
        if "you wash." in facts and "anyway" not in facts and "refusal fails" not in facts and "forced" not in facts:
            return True
        if "sleep follows" in facts or ("you sleep" in facts and "fight" in inp):
            return True
        if "you give the door space" in facts and ("not back" in inp or "will not" in inp or "won't" in inp):
            return True
    # enactment_cause suggesting force/invert but marked direct
    cause = (rec.get("enactment_cause") or res.get("enactment_cause") or "").lower()
    if any(c in cause for c in ("forced", "invert", "opposite", "override", "staff_force")):
        return True
    # structured fact type inverted/forced with direct
    for f in res.get("structured_facts") or []:
        if not isinstance(f, dict):
            continue
        t = str(f.get("type") or "").lower()
        e = str(f.get("enactment") or "").lower()
        if e in ("inverted", "forced", "compromised") and enactment == "direct":
            return True
        if "forced" in t or "invert" in t:
            return True
    return False

def criterion1_substitutions(rec: dict) -> list:
    """Return list of violation descriptions."""
    tr = rec.get("trace") or {}
    res = tr.get("resolution") or {}
    facts = facts_text(res).lower()
    inp = (rec.get("input") or "").lower()
    types = structured_types(res)
    intent = get_intent(rec)
    ac = (intent.get("action_class") or "").lower()
    method = (intent.get("method") or "").lower()
    mode = rec.get("mode")
    after = after_facility(rec)
    fac = after if after else {}
    # also try nested world
    if not fac:
        fac = ((tr.get("after_state") or {}).get("world") or {}).get("facility") or {}

    viols = []

    # 1a pull bedding -> sleep/lie
    if any(w in inp for w in ("pull", "drag", "yank", "strip")) and any(w in inp for w in ("bed", "bedding", "blanket", "sheet")):
        if any(bad in facts for bad in ("lie on the bed", "sleep does not come", "you lie", "lie down", "you sleep")):
            # allow if also mentions bedding on floor as primary and no sleep
            if "sleep" in facts or "lie" in facts:
                viols.append({
                    "kind": "pull_bedding->sleep/lie",
                    "facts_snip": facts[:220],
                })
        # also if slept became true from bedding pull without sleep intent
        if fac.get("slept") and "sleep" not in inp and "lie" not in inp and "rest" not in inp:
            viols.append({
                "kind": "pull_bedding->slept_flag",
                "facts_snip": facts[:220],
            })

    # 1b throw book -> book_enter
    if ("throw" in inp or ac == "throw") and "book" in inp:
        if "book_enter" in types or mode == "book_dungeon":
            # throwing book should not enter
            # if mode switched this turn
            before_mode = (tr.get("before_state") or {}).get("mode")
            if before_mode == "facility" and mode == "book_dungeon":
                viols.append({"kind": "throw_book->book_enter", "types": types, "facts_snip": facts[:220]})
            elif "book_enter" in types:
                viols.append({"kind": "throw_book->book_enter_type", "types": types, "facts_snip": facts[:220]})

    # 1c hide food -> refuse only
    if "hide" in inp and any(w in inp for w in ("food", "bowl", "meal", "bread")):
        if "you refuse the food" in facts and not any(w in facts for w in ("hide", "hidden", "under", "conceal")):
            viols.append({"kind": "hide_food->refuse_only", "facts_snip": facts[:220]})

    # 1d "I will not back away" -> give door space
    if re.search(r"(will not|won't|refuse to)\s+back", inp) or "i will not back away" in inp or "not back away" in inp:
        if "you give the door space" in facts or "give the door space" in facts:
            viols.append({"kind": "will_not_back->give_door_space", "facts_snip": facts[:220]})
        if fac.get("cooperated_door") is True:
            # check if this turn set it
            before_fac = (tr.get("before_state") or {}).get("facility") or {}
            if before_fac.get("cooperated_door") is not True:
                viols.append({"kind": "will_not_back->cooperated_door", "facts_snip": facts[:220]})

    # 1e fight sleep -> voluntary sleep
    if "fight sleep" in inp or ("fight" in inp and "sleep" in inp) or (ac in ("resist", "refuse") and "sleep" in inp):
        if fac.get("slept") and (rec.get("enactment") or res.get("enactment")) == "direct":
            if "anyway" not in facts and "despite" not in facts and "forced" not in facts:
                viols.append({"kind": "fight_sleep->voluntary_sleep", "facts_snip": facts[:220], "enactment": rec.get("enactment")})
        if "sleep follows" in facts and "fight" in inp:
            viols.append({"kind": "fight_sleep->sleep_follows", "facts_snip": facts[:220]})

    # 1f refuse to wash -> voluntary You wash with direct+achieved
    if ("refuse" in inp or "won't" in inp or "will not" in inp or "won't wash" in inp) and "wash" in inp:
        enactment = rec.get("enactment") or res.get("enactment")
        achieved = res.get("intended_effect_achieved")
        if "you wash." in facts or re.search(r"\byou wash\b", facts):
            if "anyway" not in facts and "refusal fails" not in facts and "forced" not in facts:
                if enactment == "direct" and achieved is True:
                    viols.append({
                        "kind": "refuse_wash->voluntary_You_wash_direct_achieved",
                        "facts_snip": facts[:220],
                        "enactment": enactment,
                        "achieved": achieved,
                    })
                elif enactment == "direct":
                    viols.append({
                        "kind": "refuse_wash->You_wash_marked_direct",
                        "facts_snip": facts[:220],
                        "enactment": enactment,
                        "achieved": achieved,
                    })

    return viols


def criterion2_book_cell_bleed(rec: dict) -> list:
    viols = []
    if rec.get("mode") != "book_dungeon":
        return viols
    tr = rec.get("trace") or {}
    vis = normalize_visible(visible_entities(rec))
    # also check narrator_input specifically
    ni = tr.get("narrator_input") or {}
    ni_vis = normalize_visible(ni.get("visible_entities"))
    hit = CELL_VISIBLE & (vis | ni_vis)
    if hit:
        viols.append({"kind": "book_dungeon_cell_visible", "entities": sorted(hit), "visible": sorted(vis | ni_vis)})
    if "facility_phase" in ni:
        viols.append({"kind": "facility_phase_in_narrator_input", "value": ni.get("facility_phase")})
    # also scan narrator_input dump for facility_phase key nested
    ni_s = json.dumps(ni)
    if '"facility_phase"' in ni_s:
        if not any(v.get("kind") == "facility_phase_in_narrator_input" for v in viols):
            viols.append({"kind": "facility_phase_in_narrator_input_nested"})
    return viols


def criterion3_image_dirty(rec: dict) -> list:
    viols = []
    tr = rec.get("trace") or {}
    res = tr.get("resolution") or {}
    img = tr.get("image") or {}
    inp = (rec.get("input") or "").lower()
    facts = facts_text(res).lower()
    types = set(structured_types(res))

    is_spill = bool(
        types & {"cup_spilled", "bowl_spilled", "cup_thrown", "bowl_thrown", "liquid_spilled", "spill", "book_thrown"}
        or ("spill" in facts and ("cup" in facts or "bowl" in facts or "water" in facts))
        or (("throw" in inp or "spill" in inp or "pour" in inp) and ("cup" in inp or "bowl" in inp))
    )
    # refine: cup/bowl spills specifically
    is_cup_bowl = (
        ("cup" in inp or "bowl" in inp or "cup" in facts or "bowl" in facts)
        and (
            res.get("state_changed")
            or res.get("image_dirty")
            or "spill" in facts
            or "floor" in facts
            or "throw" in inp
            or "pour" in inp
            or types & {"cup_spilled", "bowl_spilled", "cup_thrown", "bowl_thrown"}
        )
    )
    if not is_cup_bowl and not (types & {"cup_spilled", "bowl_spilled", "cup_thrown", "bowl_thrown"}):
        return viols

    # state actually changed?
    state_changed = res.get("state_changed")
    # also check entity diffs
    before = (tr.get("before_state") or {}).get("facility") or {}
    after = (tr.get("after_state") or {}).get("facility") or {}

    def ent_states(fac):
        ents = fac.get("entities") or {}
        if isinstance(ents, list):
            return {str(e.get("id")): e.get("state") for e in ents if isinstance(e, dict)}
        if isinstance(ents, dict):
            out = {}
            for k, v in ents.items():
                if isinstance(v, dict):
                    out[str(k)] = v.get("state") if "state" in v else v
            return out
        return {}

    be, ae = ent_states(before), ent_states(after)
    entity_changed = False
    for k in set(be) | set(ae):
        if k.lower() in ("cup", "bowl") and be.get(k) != ae.get(k):
            entity_changed = True

    if not (state_changed or entity_changed or types & {"cup_spilled", "bowl_spilled", "cup_thrown", "bowl_thrown"} or "spill" in facts):
        return viols

    decision = str(img.get("decision") or "")
    reason = str(img.get("reason") or "")
    image_dirty = res.get("image_dirty")

    bad = False
    if image_dirty is False:
        bad = True
    if "visible state unchanged" in reason.lower() or decision.upper() in ("SKIP", "UNCHANGED", "KEEP"):
        if "unchanged" in reason.lower() or decision.upper() in ("SKIP", "UNCHANGED", "KEEP"):
            bad = True
    if decision.upper() == "REGENERATE" and image_dirty is not False:
        bad = False  # ok
        # but if reason says unchanged that's still weird
        if "visible state unchanged" in reason.lower():
            bad = True

    if bad:
        viols.append({
            "kind": "spill_without_image_dirty",
            "image_dirty": image_dirty,
            "decision": decision,
            "reason": reason[:160],
            "state_changed": state_changed,
            "entity_changed": entity_changed,
            "types": sorted(types),
            "facts_snip": facts[:180],
        })
    return viols


def criterion4_forced_as_direct(rec: dict) -> list:
    viols = []
    tr = rec.get("trace") or {}
    res = tr.get("resolution") or {}
    enactment = rec.get("enactment") or res.get("enactment")
    achieved = res.get("intended_effect_achieved")
    facts = facts_text(res).lower()
    inp = (rec.get("input") or "").lower()
    cause = (rec.get("enactment_cause") or res.get("enactment_cause") or "")

    # Look for inverted/forced structured facts
    for f in res.get("structured_facts") or []:
        if not isinstance(f, dict):
            continue
        fe = str(f.get("enactment") or "").lower()
        ft = str(f.get("type") or "").lower()
        if fe in ("inverted", "forced") or ft in ("inverted", "forced_outcome", "force"):
            if enactment == "direct" and achieved is True:
                viols.append({"kind": "structured_inverted_as_direct_achieved", "fact": f, "input": inp[:80]})

    # classic refuse -> compliance marked direct+achieved
    if enactment == "direct" and achieved is True:
        patterns = [
            (r"refuse.*wash|won't wash|will not wash|not wash", r"\byou wash\b", "refuse_wash_as_achieved"),
            (r"fight sleep|resist sleep|won't sleep|refuse.*sleep", r"sleep follows|\byou sleep\b", "fight_sleep_as_achieved"),
            (r"will not back|won't back|not back away|stand (my|your) ground|refuse.*back", r"give the door space|you step back", "stand_firm_as_retreat_achieved"),
            (r"refuse.*food|won't eat|will not eat|hide the food", r"you eat\.|you accept the food", "refuse_food_as_eat_achieved"),
        ]
        for ip, fp, kind in patterns:
            if re.search(ip, inp) and re.search(fp, facts):
                # allow if facts frame as forced
                if "refusal fails" in facts or "anyway" in facts or "forced" in facts or "despite" in facts:
                    # still wrong if intended_effect_achieved True for refuse intent
                    viols.append({"kind": kind + "_forced_frame_but_achieved_true", "facts_snip": facts[:220], "cause": cause})
                else:
                    viols.append({"kind": kind, "facts_snip": facts[:220], "cause": cause})

    # enactment_cause indicates force but direct+achieved
    if enactment == "direct" and achieved is True:
        cl = cause.lower()
        if any(x in cl for x in ("forced", "staff_force", "invert", "override", "opposite")):
            viols.append({"kind": "cause_forced_but_direct_achieved", "cause": cause, "facts_snip": facts[:180]})

    return viols


def criterion5_leaks(rec: dict) -> list:
    tr = rec.get("trace") or {}
    out = tr.get("narrator_output") or ""
    if not isinstance(out, str):
        out = str(out)
    viols = []
    for pat in LEAK_PATTERNS:
        m = pat.search(out)
        if m:
            # for sated/quenched, only flag if looks like raw label dump
            snip = out[max(0, m.start() - 40) : m.end() + 40]
            if pat.pattern.lower() in (r"\bsated\b", r"\bquenched\b"):
                # raw dump often like "sated|quenched" or "sated: true" or label lists
                if not re.search(r"sated\s*\|\s*quenched|quenched\s*\|\s*sated|\bsated\b\s*[:=]|\bquenched\b\s*[:=]|pressures.*sated|labels?:", out, re.I):
                    # narrative use of words might be ok — still flag for review if pipe dump nearby
                    if "|" not in snip and ":" not in snip and "phase" not in snip.lower():
                        continue
            viols.append({"kind": "narrator_leak", "pattern": pat.pattern, "snip": snip.replace("\n", " ")})
    # also short_transcript player-facing lines if present in short.jsonl
    return viols


def criterion6_discourse(persona: str, rec: dict, prev_rec: dict | None) -> list:
    """him/no binding for language_maximalist and obstructive."""
    if persona not in ("language_maximalist", "obstructive"):
        return []
    viols = []
    tr = rec.get("trace") or {}
    res = tr.get("resolution") or {}
    intent = get_intent(rec)
    inp = (rec.get("input") or "").strip()
    inp_l = inp.lower()
    facts = facts_text(res).lower()
    target = str(intent.get("target") or "").lower()
    classification = str(intent.get("classification") or "").upper()
    ac = str(intent.get("action_class") or "")

    # him ≠ Glen
    if re.search(r"\bhim\b", inp_l) or re.search(r"\bhe\b", inp_l):
        if target in ("glen", "player", "self", "you"):
            viols.append({
                "kind": "him_bound_to_glen",
                "input": inp,
                "target": target,
                "classification": classification,
                "action_class": ac,
            })
        # grounding bindings
        g = tr.get("grounding") or {}
        bindings = g.get("bindings") if isinstance(g, dict) else None
        if isinstance(bindings, dict):
            bt = str(bindings.get("target") or "").lower()
            if bt in ("glen", "player", "self"):
                viols.append({"kind": "him_ground_bound_glen", "bindings": bindings, "input": inp})

    # bare no ≠ PERCEIVE when after back gesture
    if inp_l in ("no", "no.", "no!", "nope", "nah") or inp_l == "n":
        prev_inp = ((prev_rec or {}).get("input") or "").lower()
        # pending discourse / prior back gesture context
        before = tr.get("before_state") or {}
        pending = before.get("pending_discourse") or (tr.get("interpreter_input") or {}).get("pending_discourse")
        back_context = False
        if pending:
            ps = json.dumps(pending).lower()
            if any(w in ps for w in ("back", "step_back", "retreat", "door", "space")):
                back_context = True
        if any(w in prev_inp for w in ("back", "step away", "give.*door", "door")):
            back_context = True
        # also if staff asked / slit phase pressure
        phase = rec.get("phase") or ""
        if phase in ("slit", "door", "cell_idle") and pending:
            back_context = True
        # Check narrator/facts for give door space request in previous
        if prev_rec:
            prev_out = ((prev_rec.get("trace") or {}).get("narrator_output") or "").lower()
            prev_facts = facts_text((prev_rec.get("trace") or {}).get("resolution") or {}).lower()
            if any(w in prev_out or w in prev_facts for w in ("step back", "back away", "give the door", "door space", "stand clear")):
                back_context = True

        if back_context and classification == "PERCEPTION_QUERY":
            viols.append({
                "kind": "bare_no_as_PERCEIVE_after_back",
                "input": inp,
                "classification": classification,
                "action_class": ac,
                "facts_snip": facts[:180],
            })
        if back_context and ac.upper() == "PERCEIVE":
            viols.append({
                "kind": "bare_no_action_PERCEIVE_after_back",
                "input": inp,
                "classification": classification,
                "action_class": ac,
            })

    return viols


def scan_transcripts_for_leaks(persona_dir: Path) -> list:
    viols = []
    for name in ("short_transcript.txt", "transcript.txt"):
        path = persona_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        # Only player-facing: lines that look like narrator (not DEBUG/JSON)
        for i, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith("{") or "DEBUG" in line or "interpreter" in line.lower():
                continue
            for pat in LEAK_PATTERNS:
                m = pat.search(line)
                if not m:
                    continue
                snip = line[max(0, m.start() - 30) : m.end() + 50]
                if pat.pattern in (r"\bsated\b", r"\bquenched\b"):
                    if not re.search(r"sated\s*\|\s*quenched|\bsated\b\s*[:=]|\bquenched\b\s*[:=]", line, re.I):
                        if "Structured" not in line and "facility phase" not in line.lower():
                            continue
                viols.append({"file": str(path), "line": i, "pattern": pat.pattern, "snip": snip})
    return viols


def persona_name(dirname: str) -> str:
    # absurd_surreal_seed106 -> absurd_surreal
    m = re.match(r"(.+)_seed\d+$", dirname)
    return m.group(1) if m else dirname


def main():
    report = {
        "campaign": str(ROOT),
        "personas_files": {},
        "criteria": {},
        "bugs": [],
    }
    dirs = sorted([d for d in ROOT.iterdir() if d.is_dir()])
    all_c1, all_c2, all_c3, all_c4, all_c5, all_c6 = [], [], [], [], [], []

    for d in dirs:
        pname = persona_name(d.name)
        files = {
            "short_transcript.txt": (d / "short_transcript.txt").exists(),
            "short.jsonl": (d / "short.jsonl").exists(),
            "transcript.txt": (d / "transcript.txt").exists(),
            "traces.jsonl": (d / "traces.jsonl").exists(),
        }
        report["personas_files"][d.name] = files

        traces = load_jsonl(d / "traces.jsonl")
        prev = None
        for rec in traces:
            if "_parse_error" in rec:
                continue
            turn = rec.get("turn")
            base = {"persona": pname, "dir": d.name, "turn": turn, "input": rec.get("input"), "mode": rec.get("mode"), "phase": rec.get("phase")}
            for v in criterion1_substitutions(rec):
                all_c1.append({**base, **v})
            for v in criterion2_book_cell_bleed(rec):
                all_c2.append({**base, **v})
            for v in criterion3_image_dirty(rec):
                all_c3.append({**base, **v})
            for v in criterion4_forced_as_direct(rec):
                all_c4.append({**base, **v})
            for v in criterion5_leaks(rec):
                all_c5.append({**base, **v, "source": "narrator_output"})
            for v in criterion6_discourse(pname, rec, prev):
                all_c6.append({**base, **v})
            prev = rec

        for v in scan_transcripts_for_leaks(d):
            all_c5.append({"persona": pname, "dir": d.name, **v, "source": "transcript_file"})

    def summarize(name, viols, pass_if_zero=True):
        status = "PASS" if (len(viols) == 0) == pass_if_zero else "FAIL"
        # always PASS if zero viols
        status = "PASS" if len(viols) == 0 else "FAIL"
        return {
            "status": status,
            "violation_count": len(viols),
            "violations": viols[:40],  # cap
            "truncated": len(viols) > 40,
        }

    report["criteria"]["1_zero_substitutions"] = summarize("1", all_c1)
    report["criteria"]["2_book_dungeon_no_cell"] = summarize("2", all_c2)
    report["criteria"]["3_cup_bowl_image_dirty"] = summarize("3", all_c3)
    report["criteria"]["4_forced_not_direct_achieved"] = summarize("4", all_c4)
    report["criteria"]["5_no_structured_state_leaks"] = summarize("5", all_c5)
    report["criteria"]["6_him_no_discourse"] = summarize("6", all_c6)

    # Also dump interesting candidate turns for manual review: all refuse/throw/hide/fight sleep etc
    interesting = []
    for d in dirs:
        pname = persona_name(d.name)
        for rec in load_jsonl(d / "traces.jsonl"):
            if "_parse_error" in rec:
                continue
            inp = (rec.get("input") or "").lower()
            keys = ("pull", "bedding", "throw the book", "hide", "back away", "fight sleep", "refuse to wash", "throw the cup", "spill", "bowl")
            if any(k in inp for k in keys) or inp.strip() in ("no", "no.", "him") or re.search(r"\bhim\b", inp):
                tr = rec.get("trace") or {}
                res = tr.get("resolution") or {}
                intent = get_intent(rec)
                img = tr.get("image") or {}
                interesting.append({
                    "persona": pname,
                    "turn": rec.get("turn"),
                    "input": rec.get("input"),
                    "mode": rec.get("mode"),
                    "phase": rec.get("phase"),
                    "enactment": rec.get("enactment"),
                    "enactment_cause": rec.get("enactment_cause"),
                    "action_class": intent.get("action_class"),
                    "target": intent.get("target"),
                    "classification": intent.get("classification"),
                    "method": intent.get("method"),
                    "intended_effect_achieved": res.get("intended_effect_achieved"),
                    "image_dirty": res.get("image_dirty"),
                    "state_changed": res.get("state_changed"),
                    "image_decision": img.get("decision"),
                    "image_reason": img.get("reason"),
                    "types": structured_types(res),
                    "facts": facts_text(res)[:300],
                    "narrator_snip": str(tr.get("narrator_output") or "")[:200],
                    "facility_phase_in_ni": "facility_phase" in (tr.get("narrator_input") or {}),
                    "visible": sorted(normalize_visible(visible_entities(rec)))[:20],
                })
    report["interesting_turns"] = interesting

    out_path = ROOT / "_exit_criteria_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Wrote", out_path)

    # Console summary
    print("\n=== FILE PRESENCE ===")
    for name, files in report["personas_files"].items():
        missing = [k for k, v in files.items() if not v]
        st = "OK" if not missing else ("MISSING: " + ",".join(missing))
        print(f"  {name}: short_transcript={files['short_transcript.txt']} short.jsonl={files['short.jsonl']} ({st})")

    print("\n=== CRITERIA ===")
    for k, v in report["criteria"].items():
        print(f"  {k}: {v['status']} ({v['violation_count']} violations)")
        for viol in v["violations"][:8]:
            print("   -", {x: viol[x] for x in viol if x in ("persona","turn","kind","input","pattern","entities","decision","reason","snip","facts_snip","classification","target","action_class")})

    print("\n=== INTERESTING TURN COUNT ===", len(interesting))
    # print key interesting
    for it in interesting:
        print(f"  [{it['persona']} t{it['turn']}] {it['input']!r} mode={it['mode']} enact={it['enactment']} ac={it['action_class']} tgt={it['target']} cls={it['classification']} ach={it['intended_effect_achieved']} dirty={it['image_dirty']} dec={it['image_decision']} types={it['types']}")
        print(f"     facts: {it['facts'][:160]}")

if __name__ == "__main__":
    main()
