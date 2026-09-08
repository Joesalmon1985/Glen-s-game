#!/usr/bin/env python3
"""Export bake-off contact sheets to tools/portrait_bakeoff/."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from puca_dungeon.portrait.bakeoff import default_export_dir, export_contact_sheets


def main() -> int:
    written = export_contact_sheets(default_export_dir())
    for path in written:
        print(path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
