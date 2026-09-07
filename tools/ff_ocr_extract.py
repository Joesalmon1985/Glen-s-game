#!/usr/bin/env python3
"""Extract Fighting Fantasy Deathtrap Dungeon passages from scanned PDF OCR.

Writes:
  - puca_dungeon/content/deathtrap_ff/passages/NNN.json
  - tools/_ocr_raw.txt
  - tools/_ocr_report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
PASSAGES_DIR = ROOT / "puca_dungeon" / "content" / "deathtrap_ff" / "passages"
DEFAULT_PDF = ROOT / "deathtrap-dungeon-nntp_compress.pdf"
PROTECTED_IDS = {1, 66, 270}

WORD_FIXES = [
    (re.compile(r"\btum\b", re.I), "turn"),
    (re.compile(r"\btumto\b", re.I), "turn to"),
    (re.compile(r"\brurn\b", re.I), "turn"),
    (re.compile(r"\bgadually\b", re.I), "gradually"),
    (re.compile(r"\blnto\b", re.I), "into"),
    (re.compile(r"\bwnsh\b", re.I), "wish"),
    (re.compile(r"\bwrsh\b", re.I), "wish"),
    (re.compile(r"\bLrck\b"), "Luck"),
    (re.compile(r"\bsKrLL\b"), "SKILL"),
    (re.compile(r"\bsxILt\b", re.I), "SKILL"),
    (re.compile(r"\bsrAMrNA\b"), "STAMINA"),
    (re.compile(r"\bSTAMTNA\b"), "STAMINA"),
    (re.compile(r"\bsreurN\.?q?\b", re.I), "STAMINA"),
    (re.compile(r"\bCharnpions\b"), "Champions"),
    (re.compile(r"\bSukumvifs\b"), "Sukumvit's"),
    (re.compile(r"\bManticorc\b"), "Manticore"),
    (re.compile(r"\bceature\b", re.I), "creature"),
    (re.compile(r"\bpirters\b", re.I), "pincers"),
    (re.compile(r"\btarl\b", re.I), "tail"),
    (re.compile(r"\byoLr\b"), "you"),
    (re.compile(r"\b,vou\b"), "you"),
    (re.compile(r"\bvou\b"), "you"),
    (re.compile(r"\bFdu\b"), "you"),
    (re.compile(r"\binteNals\b"), "intervals"),
    (re.compile(r"\bradrating\b"), "radiating"),
    (re.compile(r"\bsolt\b"), "soft"),
    (re.compile(r"\bneardarkness\b"), "near-darkness"),
    (re.compile(r"\bmrce\b"), "mice"),
    (re.compile(r"\barive\b"), "arrive"),
]

TURN_RE = re.compile(r"(?i)\b(?:turn|tum|rurn|tumn|turm)\s+to\s+([0-9OoIl|rRaA]{1,4})\b")
LUCK_RE = re.compile(r"(?i)test\s+your\s+lu(?:ck|rk)|if\s+you\s+are\s+lucky|if\s+you\s+are\s+unlucky")
COMBAT_RE = re.compile(
    r"(?i)(?P<name>[A-Z][A-Z0-9 \-']{2,40}?)\s+"
    r"(?:SKILL|s[Kk][IiIl1]{2,4})\s*(?P<skill>\d{1,2})\s+"
    r"(?:STAMINA|s[Tt][Aa][MmNn]{1,3}[IiIl1]?[NnAa])\s*(?P<stam>\d{1,2})"
)
WIN_RE = re.compile(
    r"(?i)(?:if\s+)?(?:ll)?you\s+win[,.]?\s*(?:turn|tum)\s+to\s+([0-9OoIl|rRaA]{1,4})"
)
PAGE_RANGE_RE = re.compile(r"^(\d{1,3})\s*[-–—]\s*([0-9a-zA-Z]{1,3})$")
HEADER_RE = re.compile(r"^(\d{1,3})[,.]?$")
ADVENTURE_START_RE = re.compile(r"NOW\s+TURN\s+OVER", re.I)


def ocr_digit_token(token: str) -> Optional[int]:
    if not token:
        return None
    t = token.strip()
    trans = str.maketrans({
        "O": "0", "o": "0", "I": "1", "l": "1", "|": "1",
        "S": "5", "s": "5", "B": "8", "Z": "2",
    })
    t2 = t.translate(trans)
    digits = "".join(ch for ch in t2 if ch.isdigit())
    if not digits or len(digits) > 3:
        return None
    # Leading OCR 'r'/'R' often stands for '1' (r85 -> 185)
    if token[:1] in 'rR' and len(digits) == 2:
        n = int('1' + digits)
    else:
        n = int(digits)
    if 1 <= n <= 400:
        return n
    return None



def normalize_ocr(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = text.replace("fi", "fi").replace("fl", "fl")
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    for rx, repl in WORD_FIXES:
        text = rx.sub(repl, text)

    def _fix_turn(m: re.Match) -> str:
        n = ocr_digit_token(m.group(1))
        if n is None:
            return m.group(0)
        return f"turn to {n}"

    text = TURN_RE.sub(_fix_turn, text)
    return text


def extract_pdf_text(pdf_path: Path) -> str:
    chunks: list[str] = []
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        for i, page in enumerate(reader.pages):
            t = page.extract_text() or ""
            chunks.append(f"\n===== PAGE {i + 1} =====\n{t}")
    except Exception as exc:  # noqa: BLE001
        print(f"pypdf extract failed: {exc}", file=sys.stderr)

    if not any(len(c) > 200 for c in chunks):
        try:
            import fitz  # type: ignore

            doc = fitz.open(str(pdf_path))
            chunks = []
            for i, page in enumerate(doc):
                t = page.get_text() or ""
                chunks.append(f"\n===== PAGE {i + 1} =====\n{t}")
        except Exception:
            pass

    return "\n".join(chunks)


def strip_page_banners(text: str) -> str:
    return re.sub(r"\n===== PAGE \d+ =====\n", "\n", text)


def find_adventure_body(text: str) -> str:
    m = ADVENTURE_START_RE.search(text)
    if m:
        return text[m.end() :]
    idx = text.lower().find("the clamour of the excited")
    if idx >= 0:
        return text[idx:]
    return text


def _looks_like_prose(line: str) -> bool:
    s = line.strip()
    if len(s) < 8:
        return False
    letters = sum(c.isalpha() for c in s)
    return letters >= 6


def segment_passages(body: str) -> dict[int, str]:
    lines = body.splitlines()
    passages: dict[int, list[str]] = {}
    current: Optional[int] = None
    pending_from_range: Optional[int] = None

    current = 1
    passages[1] = []

    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()

        prm = PAGE_RANGE_RE.match(s)
        if prm:
            a = int(prm.group(1))
            if 1 <= a <= 400 and a not in passages:
                pending_from_range = a
            i += 1
            continue

        hm = HEADER_RE.match(s)
        if hm:
            n = int(hm.group(1))
            if 1 <= n <= 400:
                if n not in passages:
                    passages[n] = []
                current = n
                pending_from_range = None
                i += 1
                continue

        if pending_from_range is not None and _looks_like_prose(s):
            n = pending_from_range
            if n not in passages:
                passages[n] = []
            current = n
            pending_from_range = None

        if current is not None:
            if re.fullmatch(r"\d{1,2}[-–]\d{1,2}", s):
                i += 1
                continue
            passages[current].append(raw)
        i += 1

    out: dict[int, str] = {}
    for pid, plines in passages.items():
        text = "\n".join(plines).strip()
        text = re.sub(r"(?m)^\d{1,3}\s*-\s*[0-9a-zA-Z]{1,3}\s*$", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            out[pid] = text
    return out


def parse_choices(text: str) -> list[dict]:
    choices: list[dict] = []
    seen: set[int] = set()
    for m in TURN_RE.finditer(text):
        to = ocr_digit_token(m.group(1))
        if to is None or to in seen:
            continue
        start = max(0, m.start() - 160)
        prefix = text[start : m.start()]
        parts = re.split(r"(?<=[.!?])\s+|\n+", prefix)
        label = (parts[-1] if parts else prefix).strip(" .,:;-")
        label = re.sub(r"\s+", " ", label)
        if len(label) > 120:
            label = label[-120:]
        if not label:
            label = f"Turn to {to}"
        choices.append({"id": f"to_{to}", "label": label[:180], "aliases": [], "to": to})
        seen.add(to)
    return choices


def parse_combat(text: str) -> Optional[dict]:
    win_to = None
    mw = WIN_RE.search(text)
    if mw:
        win_to = ocr_digit_token(mw.group(1))

    enemies: list[dict] = []
    for m in COMBAT_RE.finditer(text):
        name = re.sub(r"\s+", " ", m.group("name")).strip(" -")
        enemies.append(
            {
                "name": name.title() if name.isupper() else name,
                "skill": int(m.group("skill")),
                "stamina": int(m.group("stam")),
            }
        )

    if not enemies and win_to is None:
        return None
    if not enemies:
        return {"enemies": [], "win_to": win_to}
    if len(enemies) == 1:
        e = enemies[0]
        return {
            "enemy_name": e["name"],
            "enemy_skill": e["skill"],
            "enemy_stamina": e["stamina"],
            "win_to": win_to,
            "enemies": enemies,
        }
    return {"enemies": enemies, "win_to": win_to}


def parse_luck_tests(text: str) -> list[dict]:
    tests: list[dict] = []
    if not LUCK_RE.search(text):
        return tests
    lucky = None
    unlucky = None
    m_l = re.search(
        r"(?i)if\s+you\s+are\s+lucky[,.]?\s*(?:turn|tum)\s+to\s+([0-9OoIl|rRaA]{1,4})",
        text,
    )
    m_u = re.search(
        r"(?i)if\s+you\s+are\s+unlucky[,.]?\s*(?:turn|tum)\s+to\s+([0-9OoIl|rRaA]{1,4})",
        text,
    )
    if m_l:
        lucky = ocr_digit_token(m_l.group(1))
    if m_u:
        unlucky = ocr_digit_token(m_u.group(1))
    if lucky or unlucky:
        tests.append(
            {
                "type": "luck",
                "success_to": lucky,
                "failure_to": unlucky,
                "lucky_to": lucky,
                "unlucky_to": unlucky,
            }
        )
    else:
        tests.append({"type": "luck", "needs_review": True})
    return tests


def detect_ending(text: str) -> Optional[str]:
    low = text.lower()
    if "your adventure ends here" in low or "adventure ends here" in low:
        return "death"
    if "you have failed" in low and "trial" in low:
        return "death"
    if "from which you can never return" in low:
        return "death"
    if re.search(r"(?i)you\s+are\s+dead|slump to the ground", text):
        if not TURN_RE.search(text):
            return "death"
    return None



def split_merged_sequences(segments: dict[int, str]) -> dict[int, str]:
    """Split trailing paragraphs after choices/endings into missing sequential ids."""
    changed = True
    while changed:
        changed = False
        for pid in list(sorted(segments.keys())):
            nxt = pid + 1
            if nxt > 400 or nxt in segments:
                continue
            raw = segments[pid]
            matches = list(TURN_RE.finditer(raw))
            cut = None
            if matches:
                cut = matches[-1].end()
            else:
                m_end = re.search(
                    r"(?i)adventure ends here|never return|you have failed",
                    raw,
                )
                if m_end:
                    cut = m_end.end()
            if cut is None:
                continue
            tail = raw[cut:].strip()
            if len(tail) < 40:
                continue
            paras = re.split(r"\n\s*\n", raw)
            if len(paras) < 2:
                head = raw[:cut].rstrip()
                if len(tail) >= 40 and sum(c.isalpha() for c in tail) > 30:
                    segments[pid] = head
                    segments[nxt] = tail
                    changed = True
                continue
            head_parts = []
            tail_parts = []
            past = False
            for p in paras:
                if not past:
                    head_parts.append(p)
                    pos_end = (raw.find(p) if raw.find(p) >= 0 else 0) + len(p)
                    # Approximate: once accumulated length past cut
                    if sum(len(x) for x in head_parts) + 2 * len(head_parts) >= cut:
                        past = True
                else:
                    tail_parts.append(p)
            # Safer: split raw at first blank line after cut
            after = raw[cut:]
            mblank = re.search(r"\n\s*\n", after)
            if mblank:
                head = raw[: cut + mblank.end()].rstrip()
                # Actually keep head through cut only; tail after blank
                head = raw[:cut].rstrip()
                tail2 = after[mblank.end() :].strip()
            else:
                head = raw[:cut].rstrip()
                # If no blank, take remaining as next if it starts with capital letter sentence
                tail2 = after.strip()
            if len(tail2) >= 40 and head:
                segments[pid] = head
                segments[nxt] = tail2
                changed = True
    return segments


def clean_best_effort(text: str) -> str:
    t = normalize_ocr(text)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    paras = []
    buf: list[str] = []
    for line in t.splitlines():
        s = line.strip()
        if not s:
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        buf.append(s)
    if buf:
        paras.append(" ".join(buf))
    return "\n\n".join(paras).strip().lstrip(' .,:;-')


def is_hand_authored_better(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if data.get("ocr_source"):
        return False
    text = (data.get("text") or "").strip()
    if data.get("needs_review") and text.startswith("[Passage"):
        return False
    choices = data.get("choices") or []
    return bool(text) and len(text) > 40 and isinstance(choices, list)


def build_passage_obj(pid: int, raw: str) -> dict:
    cleaned = clean_best_effort(raw)
    choices = parse_choices(cleaned)
    combat = parse_combat(cleaned)
    tests = parse_luck_tests(cleaned)
    ending = detect_ending(cleaned)

    letters = sum(c.isalpha() for c in cleaned)
    ratio = letters / max(len(cleaned), 1)
    needs_review = False
    if not cleaned:
        needs_review = True
    elif ratio < 0.5:
        needs_review = True
    elif len(cleaned) < 40 and not ending:
        needs_review = True
    if combat and combat.get("enemies") and not combat.get("win_to") and not ending:
        needs_review = True

    obj: dict[str, Any] = {
        "id": pid,
        "text": cleaned if cleaned else f"[Passage {pid} — needs review]",
        "choices": choices,
        "combat": combat,
        "tests": tests,
        "effects_on_enter": [],
        "ending": ending,
        "image_seed": "",
        "ocr_source": True,
        "needs_review": needs_review,
    }
    if needs_review or not cleaned:
        obj["raw_text"] = raw[:4000]
    return obj


def stub_passage(pid: int, referenced: bool = False) -> dict:
    return {
        "id": pid,
        "text": f"[Passage {pid} — needs review]",
        "choices": [],
        "combat": None,
        "tests": [],
        "effects_on_enter": [],
        "ending": None,
        "image_seed": "",
        "ocr_source": True,
        "needs_review": True,
        "referenced": bool(referenced),
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(pdf_path: Path, passages_dir: Path, skip_extract: bool = False) -> dict:
    raw_path = TOOLS / "_ocr_raw.txt"
    if skip_extract and raw_path.exists():
        raw = raw_path.read_text(encoding="utf-8", errors="replace")
    else:
        if pdf_path.exists():
            raw = extract_pdf_text(pdf_path)
        else:
            alt = ROOT / "_nntp_full_text.txt"
            if not alt.exists():
                raise FileNotFoundError(pdf_path)
            raw = alt.read_text(encoding="utf-8", errors="replace")
        raw_path.write_text(raw, encoding="utf-8", errors="replace")

    body = find_adventure_body(strip_page_banners(raw))
    body_norm = normalize_ocr(body)
    segments = split_merged_sequences(segment_passages(body_norm))

    written = 0
    skipped_protected: list[int] = []
    parsed_ok = 0
    stubs_from_fail = 0
    ocr_passages: dict[int, dict] = {}

    for pid in range(1, 401):
        path = passages_dir / f"{pid:03d}.json"
        if pid in PROTECTED_IDS and is_hand_authored_better(path):
            skipped_protected.append(pid)
            try:
                ocr_passages[pid] = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
            continue

        if pid in segments:
            obj = build_passage_obj(pid, segments[pid])
            if obj.get("needs_review") and not obj.get("choices") and len(obj.get("text", "")) < 60:
                stubs_from_fail += 1
            else:
                parsed_ok += 1
            write_json(path, obj)
            ocr_passages[pid] = obj
            written += 1

    referenced: set[int] = set()
    for obj in ocr_passages.values():
        for ch in obj.get("choices") or []:
            try:
                referenced.add(int(ch["to"]))
            except Exception:
                pass
        combat = obj.get("combat") or {}
        if isinstance(combat, dict):
            for k in ("win_to", "lose_to", "flee_to"):
                if combat.get(k) is not None:
                    try:
                        referenced.add(int(combat[k]))
                    except Exception:
                        pass
        for test in obj.get("tests") or []:
            for k in ("success_to", "failure_to", "lucky_to", "unlucky_to"):
                if test.get(k) is not None:
                    try:
                        referenced.add(int(test[k]))
                    except Exception:
                        pass

    stubs_created = 0
    for pid in range(1, 401):
        path = passages_dir / f"{pid:03d}.json"
        if pid in PROTECTED_IDS and is_hand_authored_better(path):
            continue
        if path.exists() and pid in segments:
            continue
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if (
                    not existing.get("ocr_source")
                    and not existing.get("needs_review")
                    and len(existing.get("text") or "") > 40
                ):
                    continue
            except Exception:
                pass
        if pid in segments:
            continue
        obj = stub_passage(pid, referenced=pid in referenced)
        write_json(path, obj)
        ocr_passages[pid] = obj
        stubs_created += 1
        written += 1

    for pid in referenced:
        if pid < 1 or pid > 400:
            continue
        path = passages_dir / f"{pid:03d}.json"
        if not path.exists():
            continue
        if pid in PROTECTED_IDS and is_hand_authored_better(path):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        text = (data.get("text") or "").strip()
        if text.startswith("[Passage") or data.get("needs_review"):
            data["needs_review"] = True
            if text.startswith("[Passage"):
                data["referenced"] = True
            write_json(path, data)

    real = 0
    with_choices = 0
    with_combat = 0
    with_luck = 0
    bad_links = []
    for pid in range(1, 401):
        path = passages_dir / f"{pid:03d}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        text = (data.get("text") or "").strip()
        if text and not text.startswith("[Passage"):
            real += 1
        if data.get("choices"):
            with_choices += 1
        if data.get("combat"):
            with_combat += 1
        if data.get("tests"):
            with_luck += 1
        for ch in data.get("choices") or []:
            to = ch.get("to")
            try:
                to_i = int(to)
            except Exception:
                bad_links.append({"from": pid, "to": to, "reason": "non_int"})
                continue
            if to_i < 1 or to_i > 400:
                bad_links.append({"from": pid, "to": to_i, "reason": "out_of_range"})

    segmented_ids = sorted(segments.keys())
    report = {
        "pdf": str(pdf_path),
        "raw_chars": len(raw),
        "body_chars": len(body_norm),
        "segmented_count": len(segments),
        "segmented_ids_sample": segmented_ids[:50],
        "missing_segment_ids_count": len([i for i in range(1, 401) if i not in segments]),
        "missing_segment_ids_sample": [i for i in range(1, 401) if i not in segments][:80],
        "written": written,
        "skipped_protected": skipped_protected,
        "parsed_ok_estimate": parsed_ok,
        "stubs_from_fail": stubs_from_fail,
        "stubs_created": stubs_created,
        "coverage_real_text": real,
        "coverage_real_pct": round(100.0 * real / 400, 2),
        "files_present": 400,
        "with_choices": with_choices,
        "with_combat": with_combat,
        "with_luck_tests": with_luck,
        "bad_links": bad_links[:100],
        "bad_links_count": len(bad_links),
        "referenced_count": len(referenced),
        "turn_matches_in_body": len(list(TURN_RE.finditer(body_norm))),
    }
    write_json(TOOLS / "_ocr_report.json", report)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--passages-dir", type=Path, default=PASSAGES_DIR)
    ap.add_argument("--skip-extract", action="store_true")
    args = ap.parse_args()
    report = run(args.pdf, args.passages_dir, skip_extract=args.skip_extract)
    keys = (
        "written",
        "segmented_count",
        "coverage_real_text",
        "coverage_real_pct",
        "stubs_created",
        "skipped_protected",
        "bad_links_count",
        "with_choices",
        "with_combat",
        "with_luck_tests",
    )
    print(json.dumps({k: report[k] for k in keys}, indent=2))
    print(f"Report: {TOOLS / '_ocr_report.json'}")


if __name__ == "__main__":
    main()
