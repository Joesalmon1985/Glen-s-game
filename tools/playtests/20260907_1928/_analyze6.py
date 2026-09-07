# -*- coding: utf-8 -*-
import json, re
from pathlib import Path
ROOT = Path(r"C:\Users\joesa\Documents\Cursor\GlenGame\tools\playtests\20260907_1928")

def load(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

print("=== forced framing with enactment/achieved ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    for rec in load(d / "traces.jsonl"):
        tr = rec["trace"]
        res = tr.get("resolution") or {}
        facts = " ".join(res.get("facts") or []).lower()
        if any(x in facts for x in ("anyway", "refusal fails", "forced", "happens anyway", "despite your")):
            print("%s t%s enact=%s ach=%s input=%r" % (
                d.name, rec["turn"], rec.get("enactment"), res.get("intended_effect_achieved"), rec.get("input")))
            print("  ", facts[:200])

# mixed_resist book attempts
print("\n=== mixed_resist book attempts ===")
for rec in load(ROOT / "mixed_resist_then_book_seed110" / "traces.jsonl"):
    inp = (rec.get("input") or "").lower()
    if "book" in inp or "read" in inp:
        res = rec["trace"].get("resolution") or {}
        types = [f.get("type") for f in (res.get("structured_facts") or []) if isinstance(f, dict)]
        print("t%s %r mode=%s types=%s facts=%s" % (rec["turn"], rec.get("input"), rec.get("mode"), types, " ".join(res.get("facts") or [])[:160]))
