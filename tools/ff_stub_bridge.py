#!/usr/bin/env python3
"""Bridge empty stub passages so pack demos can traverse placeholder IDs.

Only touches passages that already have needs_review=true, empty choices,
no combat, no ending, and stub text starting with "[Passage". Real OCR
narrative with empty choices is left alone for editorial review.

Each bridged stub gets a single press_on choice to (id % 400) + 1.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PASSAGES_DIR = ROOT / "puca_dungeon" / "content" / "deathtrap_ff" / "passages"
PASSAGE_MODULO = 400

PRESS_ON_CHOICE = {
    "id": "press_on",
    "label": "Press on deeper into the dungeon",
    "aliases": ["press on", "continue", "go on", "onward", "deeper"],
}


def _is_stub_bridge_candidate(data: dict[str, Any]) -> bool:
    if not data.get("needs_review"):
        return False
    text = data.get("text") or ""
    if not isinstance(text, str) or not text.startswith("[Passage"):
        return False
    choices = data.get("choices") or []
    if choices:
        return False
    if data.get("combat"):
        return False
    if data.get("ending"):
        return False
    return True


def bridge_target(passage_id: int) -> int:
    return (int(passage_id) % PASSAGE_MODULO) + 1


def process_passage(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if not _is_stub_bridge_candidate(data):
        return data, False
    pid = int(data.get("id") or 0)
    choice = dict(PRESS_ON_CHOICE)
    choice["to"] = bridge_target(pid)
    data = dict(data)
    data["choices"] = [choice]
    data["needs_review"] = True
    data["stub_bridged"] = True
    return data, True


def count_metrics(passages_dir: Path) -> dict[str, int]:
    total = with_choices = with_combat = with_ending = needs_review = 0
    empty_non_ending = stub_empty = stub_bridged = 0
    for path in sorted(passages_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        total += 1
        choices = data.get("choices") or []
        combat = data.get("combat")
        ending = data.get("ending")
        if choices:
            with_choices += 1
        if combat:
            with_combat += 1
        if ending:
            with_ending += 1
        if data.get("needs_review"):
            needs_review += 1
        if data.get("stub_bridged"):
            stub_bridged += 1
        if not choices and not combat and not ending:
            empty_non_ending += 1
            text = data.get("text") or ""
            if (
                data.get("needs_review")
                and isinstance(text, str)
                and text.startswith("[Passage")
            ):
                stub_empty += 1
    return {
        "total": total,
        "with_choices": with_choices,
        "with_combat": with_combat,
        "with_ending": with_ending,
        "needs_review": needs_review,
        "empty_choice_non_endings": empty_non_ending,
        "stub_empty_remaining": stub_empty,
        "stub_bridged": stub_bridged,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--passages-dir", type=Path, default=PASSAGES_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    passages_dir: Path = args.passages_dir

    before = count_metrics(passages_dir)
    updated = 0
    skipped = 0

    for path in sorted(passages_dir.glob("*.json"), key=lambda p: int(p.stem)):
        data = json.loads(path.read_text(encoding="utf-8"))
        new_data, touched = process_passage(data)
        if not touched:
            skipped += 1
            continue
        updated += 1
        if not args.dry_run:
            path.write_text(
                json.dumps(new_data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    if not args.dry_run:
        after = count_metrics(passages_dir)
    else:
        after = {
            **before,
            "with_choices": before["with_choices"] + updated,
            "empty_choice_non_endings": before["empty_choice_non_endings"] - updated,
            "stub_empty_remaining": max(0, before["stub_empty_remaining"] - updated),
            "stub_bridged": before["stub_bridged"] + updated,
        }

    print(
        json.dumps(
            {
                "before": before,
                "after": after,
                "stats": {
                    "updated": updated,
                    "skipped": skipped,
                    "dry_run": args.dry_run,
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
