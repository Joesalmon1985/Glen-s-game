# Deathtrap FF fidelity

Summary of the `deathtrap_ff` passage pack after `tools/ff_complete_pack.py`.

## Counts

- **Total passages:** 400
- **stub_bridged:** 0
- **needs_review:** 0
- **judgement_inferred:** see `gold_graph.json` (OCR gaps filled by editorial judgement)
- **Gold verify:** `python -m puca_dungeon.gold_verify` must report `ok: true`

## Source policy

- In-repo NNTP OCR only; no cleaner book dump.
- When OCR is clear: recover turn-tos / combat / tests; paraphrase lightly.
- When unclear: editorial judgement (`judgement_inferred` + `judgement_note`), staying inside 1–400, no softlocks.

## Opening path

- `1 ↔ 270 ↔ 66` and west combat `101 → 37 → 400/399` remain protected hand-authored nodes.

## Red team

LLM-only: `python scripts/deathtrap_redteam.py` (Ollama required; heuristic forbidden).
