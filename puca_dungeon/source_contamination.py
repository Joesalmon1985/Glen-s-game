"""Detect source contamination: OCR / PDF / NNTP phrasing leaking into pack prose."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS_CANDIDATES = (
    ROOT / 'tools' / '_ocr_raw.txt',
    ROOT / '_nntp_full_text.txt',
    ROOT / '_pdf_full_text.txt',
)

# Proper nouns / house style strongly associated with the reference gamebook.
_PROPER_NOUN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ('Giant Rat', re.compile(r'\bGiant\s+Rat\b')),
    ('Deathtrap', re.compile(r'\bDeathtrap\b')),
    ('Deathtrap Dungeon', re.compile(r'\bDeathtrap\s+Dungeon\b', re.I)),
    ('Ian Livingstone', re.compile(r'\bIan\s+Livingstone\b')),
    ('Baron Sukumvit', re.compile(r'\bBaron\s+Sukumvit\b', re.I)),
    ('Sukumvit', re.compile(r'\bSukumvit\b', re.I)),
    ('Trial of Champions', re.compile(r'\bTrial\s+of\s+Champions\b', re.I)),
    ('Fang', re.compile(r'\b(?:city\s+of\s+)?Fang\b')),
    ('Fighting Fantasy', re.compile(r'\bFighting\s+Fantasy\b')),
]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def load_reference_corpus(paths: Optional[Iterable[Path]] = None) -> str:
    """Load and concatenate available reference corpus files (missing = skip)."""
    chunks: list[str] = []
    for path in paths or DEFAULT_CORPUS_CANDIDATES:
        path = Path(path)
        if not path.is_file():
            continue
        text = _read_text(path)
        if text.strip():
            chunks.append(text)
    return '\n'.join(chunks)


def _normalize_for_ngram(text: str) -> list[str]:
    # Lowercase alphanumerics; keep word tokens only
    return re.findall(r"[a-z0-9']+", (text or '').lower())


def ngram_overlap(
    text: str,
    corpus: str,
    n: int = 8,
    max_hits: int = 20,
) -> list[dict]:
    """Flag exact n-gram overlaps between text and corpus."""
    if n < 3 or not text or not corpus:
        return []
    src = _normalize_for_ngram(text)
    if len(src) < n:
        return []
    corp = _normalize_for_ngram(corpus)
    if len(corp) < n:
        return []

    corp_set: set[tuple[str, ...]] = set()
    for i in range(len(corp) - n + 1):
        corp_set.add(tuple(corp[i:i + n]))

    hits: list[dict] = []
    seen: set[str] = set()
    for i in range(len(src) - n + 1):
        gram = tuple(src[i:i + n])
        if gram not in corp_set:
            continue
        phrase = ' '.join(gram)
        if phrase in seen:
            continue
        seen.add(phrase)
        hits.append({
            'kind': 'ngram_overlap',
            'n': n,
            'phrase': phrase,
        })
        if len(hits) >= max_hits:
            break
    return hits


def proper_noun_hits(text: str) -> list[dict]:
    """Flag trademark / Ian Livingstone–style proper nouns in trial prose."""
    findings: list[dict] = []
    for label, pat in _PROPER_NOUN_PATTERNS:
        for m in pat.finditer(text or ''):
            findings.append({
                'kind': 'proper_noun',
                'label': label,
                'match': m.group(0),
                'span': [m.start(), m.end()],
            })
    return findings


def scan_text(text: str, corpus: str = '', *, n: int = 8, source: str = '') -> list[dict]:
    findings: list[dict] = []
    for hit in proper_noun_hits(text):
        if source:
            hit = {**hit, 'source': source}
        findings.append(hit)
    if corpus:
        for hit in ngram_overlap(text, corpus, n=n):
            if source:
                hit = {**hit, 'source': source}
            findings.append(hit)
    return findings


def scan_pack(
    pack_dir: Path | str,
    corpus: Optional[str] = None,
    n: int = 8,
) -> list[dict]:
    """Scan all passage JSON under pack_dir/passages for contamination."""
    pack_dir = Path(pack_dir)
    if corpus is None:
        corpus = load_reference_corpus()
    passages_dir = pack_dir / 'passages'
    findings: list[dict] = []
    if not passages_dir.is_dir():
        return findings
    for path in sorted(passages_dir.glob('*.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append({
                'kind': 'read_error',
                'source': str(path),
                'error': str(exc),
            })
            continue
        text = str(data.get('text') or '')
        seed = str(data.get('image_seed') or '')
        blob = f'{text}\n{seed}'.strip()
        if not blob:
            continue
        for hit in scan_text(blob, corpus or '', n=n, source=str(path)):
            findings.append(hit)
    return findings


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--pack-dir',
        type=Path,
        default=Path(__file__).resolve().parent / 'content' / 'puca_trial',
    )
    parser.add_argument('--n', type=int, default=8)
    parser.add_argument('--json', action='store_true', help='Print JSON findings')
    args = parser.parse_args(argv)

    corpus = load_reference_corpus()
    findings = scan_pack(args.pack_dir, corpus=corpus, n=args.n)
    if args.json:
        print(json.dumps(findings, indent=2, ensure_ascii=False))
    else:
        print(f'corpus_chars={len(corpus)} pack={args.pack_dir} findings={len(findings)}')
        for hit in findings[:50]:
            kind = hit.get('kind')
            src = hit.get('source', '')
            detail = hit.get('phrase') or hit.get('match') or hit.get('label') or hit
            print(f'- {kind}: {detail}  ({src})')
        if len(findings) > 50:
            print(f'... {len(findings) - 50} more')
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
