#!/usr/bin/env python3
"""Re-parse Fighting Fantasy passage choices/combat/endings from OCR text.

For each passage except protected hand-authored ids:
  - Find turn/tum to N patterns (OCR digit normalize)
  - If choices empty but turn-tos found, synthesize choices
  - If combat missing, parse SKILL/STAMINA enemy lines
  - Detect death/victory endings
  - Flag needs_review for OCR garbage or synthesized choices
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
PASSAGES_DIR = ROOT / "puca_dungeon" / "content" / "deathtrap_ff" / "passages"

PROTECTED_IDS = {1, 37, 66, 101, 142, 198, 270, 399, 400}

sys.path.insert(0, str(ROOT / "tools"))
try:
    from ff_ocr_extract import (  # type: ignore
        COMBAT_RE,
        TURN_RE as BASE_TURN_RE,
        normalize_ocr,
        ocr_digit_token as base_ocr_digit_token,
    )
except ImportError:  # pragma: no cover
    COMBAT_RE = re.compile(
        r"(?i)(?P<name>[A-Z][A-Z0-9 \-']{2,40}?)\s+"
        r"(?:SKILL|s[Kk][IiIl1]{2,4})\s*(?P<skill>\d{1,2})\s+"
        r"(?:STAMINA|s[Tt][Aa][MmNn]{1,3}[IiIl1]?[NnAa])\s*(?P<stam>\d{1,2})"
    )
    BASE_TURN_RE = re.compile(
        r"(?i)\b(?:turn|tum|rurn|tumn|turm)\s+to\s+([0-9OoIl|rRaA]{1,4})\b"
    )

    def normalize_ocr(text: str) -> str:
        return text

    def base_ocr_digit_token(token: str) -> Optional[int]:
        return None


TURN_FIND_RE = re.compile(
    r"(?i)\b(?:turn|tum|turrr|turm|rurn|tumn|tuln|tuin|turt|furn|turr)\s*[.,]?\s*"
    r"(?:to|ro|te|t0|fu|tl|tL|\[o|lo)\s*[,.]?\s*"
    r"([0-9A-Za-zOoIl|?]{1,4})(?=\b|_|$|[.!,;])"
)
TURN_BROKEN_RE = re.compile(
    r"(?i)\btu[rnm]{1,3}\.?n?\s*[.,]?\s*to\s*[,.]?\s*([0-9A-Za-zOoIl]{1,4})\b"
)

COMBAT_LOOSE_RE = re.compile(
    r"(?i)(?P<name>[A-Z][A-Z0-9 \-']{2,40}?)\s+"
    r"(?:SKILL|s[Kk(][IiIl1]{1,4}L?|s\(ILL|sx[IiIl1r]{0,3}L{0,2}|sKrLL|srrl-?I-?)\s*"
    r"(?P<skill>\d{1,2})\s+"
    r"(?:STAMINA|s[Tt][Aa][MmNn]{1,3}[IiIl1]?[NnAa]|STA\.?)\s*"
    r"(?P<stam>\d{1,2})"
)

COMBAT_SPLIT_RE = re.compile(
    r"(?i)(?P<name>[A-Z][A-Z][A-Z0-9 \-']{1,36})\s+"
    r"(?:SKILL|s[Kk(][IiIl1]{1,4}L?|s\(ILL|sKrLL)\s*(?P<skill>\d{1,2})"
    r".{0,120}?"
    r"(?:STAMINA|s[Tt][Aa][MmNn]{1,3}[IiIl1]?[NnAa]|STA\.?)\s*(?P<stam>\d{1,2})",
    re.DOTALL,
)

IF_YOU_RE = re.compile(r"(?i)\bif\s+you\b")

DEATH_PHRASES = (
    "you are dead",
    "your adventure ends",
    "adventure ends here",
    "youradventure ends",
    "from which you can never return",
    "you have failed",
    "slump to the ground",
    "turn to stone",
)
VICTORY_PHRASES = (
    "you have succeeded",
    "champion of fang",
    "champions of fang",
    "you emerge from deathtrap",
    "you are the champion",
)

BAD_OCR_TOKENS = (
    "tum to",
    "turrr",
    "tuln",
    "turn ro",
    "turn [o",
    "turn fu",
    "turt to",
    "furn to",
    "sxrl",
    "s(ill",
    "srrl",
    "stamtna",
    "vou ",
    ",vou",
    "yotr",
    "w1n",
    "{atal",
    "1n the",
    "eflect",
    "pirters",
    "ceature",
    "intenals",
)


def ocr_digit_token(token: str) -> Optional[int]:
    if not token:
        return None

    t = token.strip().rstrip("_-,.")
    if t.lower() in {"the", "a", "an", "your", "you", "it", "stone", "page"}:
        return None

    t = t.replace("?", "")
    # Extended OCR letter->digit map before base helper (base drops unmapped letters)
    trans = str.maketrans(
        {
            "O": "0",
            "o": "0",
            "I": "1",
            "l": "1",
            "|": "1",
            "S": "5",
            "s": "5",
            "B": "8",
            "Z": "2",
            "z": "2",
            "j": "1",
            "J": "1",
            "E": "6",
            "e": "6",
            "D": "0",
            "q": "9",
            "Q": "9",
            "t": "1",
            "T": "1",
            "A": "4",
            "a": "4",
            "G": "6",
            "g": "6",
            "b": "6",
            "r": "1",
            "R": "1",
        }
    )
    t2 = t.translate(trans)
    digits = "".join(ch for ch in t2 if ch.isdigit())
    if digits and len(digits) <= 3:
        n = int(digits)
        if 1 <= n <= 400:
            return n

    base = base_ocr_digit_token(token)
    if base is not None:
        return base
    return None


def passage_corpus(data: dict) -> str:
    parts = [data.get("text") or ""]
    raw = data.get("raw_text")
    if raw:
        parts.append(str(raw))
    return "\n".join(parts)


def find_turn_tos(text: str) -> list[tuple[int, int, int]]:
    found: list[tuple[int, int, int]] = []
    sources = [text]
    try:
        sources.append(normalize_ocr(text))
    except Exception:
        pass

    for src_i, src in enumerate(sources):
        for rx in (TURN_FIND_RE, TURN_BROKEN_RE, BASE_TURN_RE):
            for m in rx.finditer(src):
                dest = ocr_digit_token(m.group(1))
                if dest is None:
                    continue
                start, end = m.start(), m.end()
                if src_i != 0:
                    needle = m.group(0)
                    idx = text.lower().find(needle.lower())
                    if idx < 0:
                        idx = text.lower().find(f"turn to {dest}")
                    if idx >= 0:
                        start, end = idx, idx + max(len(needle), 1)
                    else:
                        start, end = 10**9, 10**9
                if any(abs(s - start) < 3 and d == dest for s, _, d in found):
                    continue
                found.append((start, end, dest))

    found.sort(key=lambda x: (x[0], x[2]))
    out: list[tuple[int, int, int]] = []
    seen_dest: set[int] = set()
    for start, end, dest in found:
        if dest in seen_dest:
            continue
        seen_dest.add(dest)
        out.append((start, end, dest))
    return out


def label_for_turn(text: str, match_start: int, index: int) -> str:
    if match_start <= 0 or match_start >= 10**9:
        return f"Turn to option {index}"
    window_start = max(0, match_start - 160)
    prefix = text[window_start:match_start]
    if_matches = list(IF_YOU_RE.finditer(prefix))
    if if_matches:
        label = prefix[if_matches[-1].start() :].strip(" .,:;-\"'")
    else:
        parts = re.split(r"(?<=[.!?])\s+|\n+", prefix)
        label = (parts[-1] if parts else prefix).strip(" .,:;-\"'")
    label = re.sub(r"\s+", " ", label).strip()
    if len(label) > 80:
        label = label[:77].rstrip() + "..."
    if len(label) < 4:
        return f"Turn to option {index}"
    return label


def synthesize_choices(text: str, turns: list[tuple[int, int, int]]) -> list[dict]:
    choices: list[dict] = []
    for i, (start, _end, dest) in enumerate(turns, start=1):
        choices.append(
            {
                "id": f"choice_{i}",
                "label": label_for_turn(text, start, i),
                "aliases": [],
                "to": dest,
            }
        )
    return choices


def parse_combat(text: str, turns: list[tuple[int, int, int]]) -> Optional[dict]:
    m = (
        COMBAT_RE.search(text)
        or COMBAT_LOOSE_RE.search(text)
        or COMBAT_SPLIT_RE.search(text)
    )
    if not m:
        return None
    name = re.sub(r"\s+", " ", m.group("name")).strip(" -")
    name = re.sub(r"^(?:THE|A|AN)\s+", "", name, flags=re.I)
    if len(name) < 3:
        return None
    if len(name.split()) > 4:
        return None
    if name.isupper():
        name = name.title()
    skill = int(m.group("skill"))
    stam = int(m.group("stam"))
    if not (1 <= skill <= 24 and 1 <= stam <= 50):
        return None

    win_to: Optional[int] = None
    win_m = re.search(
        r"(?i)(?:if\s+)?(?:you\s+)?win[,.]?\s*"
        r"(?:turn|tum|turrr|turm|rurn|turt|furn)\s*"
        r"(?:to|ro|te|fu|\[o)\s*[,.]?\s*"
        r"([0-9A-Za-zOoIl|?]{1,4})",
        text[max(0, m.start()) :],
    )
    if win_m:
        win_to = ocr_digit_token(win_m.group(1))
    if win_to is None:
        for start, _end, dest in turns:
            if start >= m.start():
                win_to = dest
                break
    if win_to is None and turns:
        win_to = turns[0][2]

    return {
        "enemy_name": name or "Enemy",
        "enemy_skill": skill,
        "enemy_stamina": stam,
        "win_to": win_to,
        "enemies": [{"name": name or "Enemy", "skill": skill, "stamina": stam}],
    }


def detect_ending(text: str) -> Optional[str]:
    low = text.lower()
    for phrase in VICTORY_PHRASES:
        if phrase in low:
            return "victory"
    for phrase in DEATH_PHRASES:
        if phrase in low:
            if phrase in (
                "your adventure ends",
                "adventure ends here",
                "youradventure ends",
                "you are dead",
                "you have failed",
                "from which you can never return",
            ):
                return "death"
            if not TURN_FIND_RE.search(text) and not BASE_TURN_RE.search(text):
                return "death"
    return None


def ocr_garbage_score(text: str) -> tuple[float, bool]:
    if not text:
        return 0.0, False
    non_ascii = sum(1 for c in text if ord(c) > 127)
    ratio = non_ascii / max(len(text), 1)
    low = text.lower()
    bad = any(tok in low for tok in BAD_OCR_TOKENS)
    weird = len(re.findall(r"[^\w\s.,;:'\"!?()\-]", text)) / max(len(text), 1)
    if weird > 0.04:
        bad = True
    if len(re.findall(r"(?i)\b\w*\d\w*\b", text)) > 8:
        bad = True
    return ratio, bad


def needs_review_flag(text: str, synthesized: bool) -> bool:
    if synthesized:
        return True
    ratio, bad = ocr_garbage_score(text)
    return ratio > 0.02 or bad


def count_metrics(passages_dir: Path) -> dict[str, int]:
    with_choices = with_combat = with_ending = needs_review = total = 0
    for path in sorted(passages_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        total += 1
        if data.get("choices"):
            with_choices += 1
        if data.get("combat"):
            with_combat += 1
        if data.get("ending"):
            with_ending += 1
        if data.get("needs_review"):
            needs_review += 1
    return {
        "total": total,
        "with_choices": with_choices,
        "with_combat": with_combat,
        "with_ending": with_ending,
        "needs_review": needs_review,
    }


def process_passage(data: dict) -> tuple[dict, dict[str, bool]]:
    flags = {
        "synthesized_choices": False,
        "added_combat": False,
        "set_ending": False,
        "touched": False,
    }
    pid = int(data.get("id") or 0)
    if pid in PROTECTED_IDS:
        return data, flags

    corpus = passage_corpus(data)
    text = data.get("text") or ""
    turns = find_turn_tos(corpus)

    choices = data.get("choices") or []
    synthesized_ids = bool(choices) and all(
        isinstance(c, dict) and str(c.get("id", "")).startswith("choice_")
        for c in choices
    )
    if turns and ((not choices) or synthesized_ids):
        data["choices"] = synthesize_choices(corpus, turns)
        flags["synthesized_choices"] = True
        flags["touched"] = True

    combat = parse_combat(corpus, turns)
    if combat and combat.get("enemy_skill") and combat.get("enemy_stamina"):
        existing = data.get("combat")
        if not existing:
            data["combat"] = combat
            flags["added_combat"] = True
            flags["touched"] = True
        elif synthesized_ids or flags["synthesized_choices"]:
            if existing.get("win_to") != combat.get("win_to") and combat.get("win_to"):
                existing = dict(existing)
                existing["win_to"] = combat["win_to"]
                data["combat"] = existing
                flags["added_combat"] = True
                flags["touched"] = True

    if not data.get("ending"):
        ending = detect_ending(corpus)
        if ending:
            data["ending"] = ending
            flags["set_ending"] = True
            flags["touched"] = True

    review = needs_review_flag(text, flags["synthesized_choices"])
    if flags["added_combat"]:
        review = True
    if review:
        if not data.get("needs_review"):
            flags["touched"] = True
        data["needs_review"] = True

    return data, flags


def project_after(passages_dir: Path) -> dict[str, int]:
    with_choices = with_combat = with_ending = needs_review = total = 0
    for path in sorted(passages_dir.glob("*.json")):
        original = json.loads(path.read_text(encoding="utf-8"))
        pid = int(original.get("id") or 0)
        data = original if pid in PROTECTED_IDS else process_passage(dict(original))[0]
        total += 1
        if data.get("choices"):
            with_choices += 1
        if data.get("combat"):
            with_combat += 1
        if data.get("ending"):
            with_ending += 1
        if data.get("needs_review"):
            needs_review += 1
    return {
        "total": total,
        "with_choices": with_choices,
        "with_combat": with_combat,
        "with_ending": with_ending,
        "needs_review": needs_review,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--passages-dir", type=Path, default=PASSAGES_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    passages_dir: Path = args.passages_dir

    before = count_metrics(passages_dir)
    stats = {
        "updated": 0,
        "skipped_protected": 0,
        "synthesized_choices": 0,
        "added_combat": 0,
        "set_ending": 0,
    }

    if args.dry_run:
        after = project_after(passages_dir)
        for path in sorted(passages_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            pid = int(data.get("id") or 0)
            if pid in PROTECTED_IDS:
                stats["skipped_protected"] += 1
                continue
            _, flags = process_passage(dict(data))
            if flags["synthesized_choices"]:
                stats["synthesized_choices"] += 1
            if flags["added_combat"]:
                stats["added_combat"] += 1
            if flags["set_ending"]:
                stats["set_ending"] += 1
            if flags["touched"]:
                stats["updated"] += 1
    else:
        for path in sorted(passages_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            pid = int(data.get("id") or 0)
            if pid in PROTECTED_IDS:
                stats["skipped_protected"] += 1
                continue
            updated, flags = process_passage(data)
            if flags["synthesized_choices"]:
                stats["synthesized_choices"] += 1
            if flags["added_combat"]:
                stats["added_combat"] += 1
            if flags["set_ending"]:
                stats["set_ending"] += 1
            if flags["touched"]:
                stats["updated"] += 1
                path.write_text(
                    json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
        after = count_metrics(passages_dir)

    print(json.dumps({"before": before, "after": after, "stats": stats}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())