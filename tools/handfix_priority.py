#!/usr/bin/env python3
"""Normalize priority Deathtrap FF passage choice metadata and write a fidelity report.

- For OCR-sourced passages whose choices carry turn_to/to targets, ensure each
  choice has a usable id and label.
- Mark passages with empty choices, no ending, and no combat as needs_review.
- Write docs/DEATHTRAP_FF_FIDELITY.md with pack summary stats.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PASSAGES_DIR = ROOT / "puca_dungeon" / "content" / "deathtrap_ff" / "passages"
REPORT_PATH = ROOT / "docs" / "DEATHTRAP_FF_FIDELITY.md"
EXPECTED_TOTAL = 400
OPENING_CHAIN = (1, 270, 66)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _slug(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return slug[:48] or fallback


def _choice_target(choice: dict[str, Any]) -> Any:
    if "turn_to" in choice and choice.get("turn_to") is not None:
        return choice.get("turn_to")
    return choice.get("to")


def _ensure_choice_ids_labels(data: dict[str, Any]) -> bool:
    """Ensure OCR passages with turn_to/to choices have ids and labels. Returns changed."""
    if not data.get("ocr_source"):
        return False
    choices = data.get("choices") or []
    if not isinstance(choices, list) or not choices:
        return False

    changed = False
    used_ids: set[str] = set()
    for i, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        target = _choice_target(choice)
        if target is None:
            continue

        # Prefer canonical `to`; keep turn_to if that was the only key.
        if choice.get("to") is None and choice.get("turn_to") is not None:
            choice["to"] = choice["turn_to"]
            changed = True

        label = (choice.get("label") or "").strip()
        if not label:
            choice["label"] = f"Turn to {target}"
            label = choice["label"]
            changed = True

        cid = (choice.get("id") or "").strip()
        if not cid:
            cid = _slug(label, f"to_{target}")
            if cid in used_ids:
                cid = f"to_{target}_{i}"
            choice["id"] = cid
            changed = True
        used_ids.add(str(choice["id"]))

        if "aliases" not in choice or choice.get("aliases") is None:
            choice["aliases"] = []
            changed = True

    return changed


def _mark_needs_review_empty(data: dict[str, Any]) -> bool:
    choices = data.get("choices") or []
    has_choices = isinstance(choices, list) and len(choices) > 0
    has_ending = bool(data.get("ending"))
    has_combat = bool(data.get("combat"))
    if has_choices or has_ending or has_combat:
        return False
    if data.get("needs_review") is True:
        return False
    data["needs_review"] = True
    return True


def _verify_opening_path(by_id: dict[int, dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    for pid in OPENING_CHAIN:
        if pid not in by_id:
            notes.append(f"missing passage {pid}")
            continue
        p = by_id[pid]
        if not (p.get("choices") or []):
            notes.append(f"passage {pid} has no choices")
    # 1 → 270 and/or 66; 270 → 66
    p1 = by_id.get(1) or {}
    targets1 = {c.get("to") for c in (p1.get("choices") or []) if isinstance(c, dict)}
    if 270 not in targets1 or 66 not in targets1:
        notes.append(f"passage 1 targets {sorted(t for t in targets1 if t is not None)}; expected 270 and 66")
    p270 = by_id.get(270) or {}
    targets270 = {c.get("to") for c in (p270.get("choices") or []) if isinstance(c, dict)}
    if 66 not in targets270:
        notes.append(f"passage 270 targets {sorted(t for t in targets270 if t is not None)}; expected 66")
    p66 = by_id.get(66) or {}
    targets66 = {c.get("to") for c in (p66.get("choices") or []) if isinstance(c, dict)}
    for expected in (101, 142, 198):
        if expected not in targets66:
            notes.append(f"passage 66 missing link to {expected}")
    if not notes:
        notes.append("opening path 1↔270↔66 verified (1→270→66 and 1→66; 66→101/142/198)")
    return notes


def main() -> int:
    PASSAGES_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    by_id: dict[int, dict[str, Any]] = {}
    files_touched = 0

    for path in sorted(PASSAGES_DIR.glob("*.json")):
        data = _read_json(path)
        pid = int(data.get("id") or path.stem)
        data["id"] = pid

        changed = False
        if _ensure_choice_ids_labels(data):
            changed = True
        if _mark_needs_review_empty(data):
            changed = True

        if changed:
            _write_json(path, data)
            files_touched += 1

        by_id[pid] = data

    total = len(by_id)
    with_choices = sum(1 for p in by_id.values() if p.get("choices"))
    with_combat = sum(1 for p in by_id.values() if p.get("combat"))
    needs_review = sum(1 for p in by_id.values() if p.get("needs_review"))
    with_ending = sum(1 for p in by_id.values() if p.get("ending"))
    ocr_source = sum(1 for p in by_id.values() if p.get("ocr_source"))
    opening_notes = _verify_opening_path(by_id)

    lines = [
        "# Deathtrap FF fidelity",
        "",
        "Summary of the `deathtrap_ff` passage pack after `tools/handfix_priority.py`.",
        "",
        "## Counts",
        "",
        f"- **Total passages:** {total} (expected {EXPECTED_TOTAL})",
        f"- **With choices:** {with_choices}",
        f"- **With combat:** {with_combat}",
        f"- **With ending:** {with_ending}",
        f"- **needs_review:** {needs_review}",
        f"- **ocr_source:** {ocr_source}",
        f"- **Files updated this run:** {files_touched}",
        "",
        "## Opening path",
        "",
    ]
    for note in opening_notes:
        lines.append(f"- {note}")
    lines += [
        "",
        "## Notes",
        "",
        "- Hand-authored priority nodes (1, 66, 270) and the early west demo chain",
        "  (101 → 37 combat → 400 / lose → 399) are playable demo content.",
        "- OCR bulk passages still need an editorial pass: many retain garbled text,",
        "  weak labels, or incomplete graphs even when `needs_review` is false.",
        "- Prefer paraphrased Fighting Fantasy tone when rewriting; do not ship raw OCR",
        "  as final player-facing prose.",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Passages: {total}")
    print(f"with_choices={with_choices} with_combat={with_combat} needs_review={needs_review}")
    print(f"Updated {files_touched} files; wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
