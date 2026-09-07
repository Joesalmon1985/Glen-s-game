"""CLI entry: ``python -m scripts.redteam``."""
from __future__ import annotations

from scripts.redteam.campaign import main

if __name__ == '__main__':
    raise SystemExit(main())
