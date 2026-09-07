#!/usr/bin/env python3
"""Deathtrap / PUCA red team entrypoint — delegates to scripts.redteam.campaign.

Legacy online path: requires Ollama (no heuristic) unless --offline is passed.
Clean gate: ANY P0/P1/P2 finding fails (P2 is hard-fail).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redteam.campaign import DEFAULT_REPORT, DEFAULT_TRACES, main as campaign_main


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Preserve old default report paths if caller did not override
    if '--report-out' not in argv and '--offline' not in argv:
        # Online legacy defaults (old wave reports)
        argv = [
            '--report-out', str(ROOT / 'tools' / '_redteam_report.json'),
            '--trace-out', str(ROOT / 'tools' / '_redteam_traces.jsonl'),
            *argv,
        ]
    elif '--offline' in argv and '--report-out' not in argv:
        argv = [
            '--report-out', str(DEFAULT_REPORT),
            '--trace-out', str(DEFAULT_TRACES),
            *argv,
        ]
    return campaign_main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
