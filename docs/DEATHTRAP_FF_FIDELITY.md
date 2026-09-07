# Deathtrap FF fidelity

Summary of the `deathtrap_ff` passage pack after `tools/handfix_priority.py`.

## Counts

- **Total passages:** 400 (expected 400)
- **With choices:** 367
- **With combat:** 22
- **With ending:** 14
- **needs_review:** 273
- **ocr_source:** 391
- **Files updated this run:** 0

## Opening path

- opening path 1↔270↔66 verified (1→270→66 and 1→66; 66→101/142/198)

## Notes

- Hand-authored priority nodes (1, 66, 270) and the early west demo chain
  (101 → 37 combat → 400 / lose → 399) are playable demo content.
- OCR bulk passages still need an editorial pass: many retain garbled text,
  weak labels, or incomplete graphs even when `needs_review` is false.
- Prefer paraphrased Fighting Fantasy tone when rewriting; do not ship raw OCR
  as final player-facing prose.
