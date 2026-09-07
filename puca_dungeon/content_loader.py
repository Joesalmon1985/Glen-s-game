"""Load Puca content packs (manifest, chargen, passages).

Default pack is ``content/puca_trial``. The Fighting Fantasy
``deathtrap_ff`` pack remains on disk for reference only.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


PACK_DIR = Path(__file__).resolve().parent / "content" / "puca_trial"
PASSAGES_DIR = PACK_DIR / "passages"


@dataclass
class Passage:
    id: int
    text: str = ""
    choices: list = field(default_factory=list)
    combat: Optional[dict] = None
    tests: list = field(default_factory=list)
    effects_on_enter: list = field(default_factory=list)
    ending: Optional[str] = None
    image_seed: str = ""
    needs_review: bool = False
    ocr_source: bool = False
    raw_text: str = ""
    hazards: list = field(default_factory=list)
    entities: list = field(default_factory=list)
    exposure: dict = field(default_factory=dict)
    pressures: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        # Keep pack JSON lean: omit empty optional extras when unused
        if not d.get("raw_text"):
            d.pop("raw_text", None)
        if not d.get("ocr_source"):
            d.pop("ocr_source", None)
        if not d.get("hazards"):
            d.pop("hazards", None)
        if not d.get("entities"):
            d.pop("entities", None)
        if not d.get("exposure"):
            d.pop("exposure", None)
        if not d.get("pressures"):
            d.pop("pressures", None)
        return d


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_manifest(pack_dir: Path = PACK_DIR) -> dict:
    return _read_json(pack_dir / "manifest.json")


def load_chargen(pack_dir: Path = PACK_DIR) -> dict:
    path = pack_dir / "chargen.json"
    if not path.exists():
        return {}
    return _read_json(path)


def passage_path(passage_id: int, pack_dir: Path = PACK_DIR) -> Path:
    return pack_dir / "passages" / f"{int(passage_id):03d}.json"


def _passage_from_data(data: dict) -> Passage:
    exposure = data.get("exposure")
    if exposure is None:
        exposure = {}
    elif not isinstance(exposure, dict):
        exposure = {}
    return Passage(
        id=int(data["id"]),
        text=str(data.get("text") or ""),
        choices=list(data.get("choices") or []),
        combat=data.get("combat"),
        tests=list(data.get("tests") or []),
        effects_on_enter=list(data.get("effects_on_enter") or []),
        ending=data.get("ending"),
        image_seed=str(data.get("image_seed") or ""),
        needs_review=bool(data.get("needs_review", False)),
        ocr_source=bool(data.get("ocr_source", False)),
        raw_text=str(data.get("raw_text") or ""),
        hazards=list(data.get("hazards") or []),
        entities=list(data.get("entities") or []),
        exposure=dict(exposure),
        pressures=list(data.get("pressures") or []),
    )


def load_passage(passage_id: int, pack_dir: Path = PACK_DIR) -> Passage:
    path = passage_path(passage_id, pack_dir)
    if not path.exists():
        raise FileNotFoundError(f"Passage {passage_id} not found at {path}")
    return _passage_from_data(_read_json(path))


def get_passage(passage_id: int, pack_dir: Path = PACK_DIR) -> Passage:
    """Load a single passage by id (alias for load_passage)."""
    return load_passage(passage_id, pack_dir)


def load_all_passages(pack_dir: Path = PACK_DIR) -> dict[int, Passage]:
    passages: dict[int, Passage] = {}
    passages_dir = pack_dir / "passages"
    if not passages_dir.is_dir():
        return passages
    for path in sorted(passages_dir.glob("*.json")):
        data = _read_json(path)
        passage = _passage_from_data(data)
        passages[passage.id] = passage
    return passages


def get_pack(pack_dir: Path = PACK_DIR) -> dict:
    """Return manifest + chargen + all passages keyed by id (as dicts)."""
    passages = load_all_passages(pack_dir)
    return {
        "dir": str(pack_dir),
        "manifest": load_manifest(pack_dir),
        "chargen": load_chargen(pack_dir),
        "passages": {pid: p.to_dict() for pid, p in passages.items()},
    }
