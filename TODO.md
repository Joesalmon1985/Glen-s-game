# Puca TODO

## Deathtrap Dungeon FF (`puca_dungeon` gamebook)
- [x] Passage pack skeleton: manifest, chargen, passages 001–400 JSON.
- [x] FF rules: Skill/Stamina/Luck, combat rounds, luck/skill tests, potion once, provisions.
- [x] Session pipeline: interpret → ground → resolve → guidance → narrate → image decision.
- [x] Opening path + west combat demo (1 ↔ 270 ↔ 66; 101 → 37 → 400/399/flee 66).
- [x] Graph validate + `tests.test_deathtrap_ff` (heuristic).
- [ ] Editorial pass on OCR bulk passages (`needs_review` / fidelity notes).
- [ ] Complete choice/combat/test graphs for remaining paragraphs beyond the demo spine.
- [ ] Live Ollama playthrough of a full book path; optional `--images` polish.

## Current fix pass (legacy Spirit adventure)
- [x] Preserve original source/installer and document the audit.
- [x] Fix spirit rules, narrator request format, endings, and save/resume.
- [x] Prevent overlapping turns; show text before images; recover from generation errors.
- [x] Add scene-image reuse and a lazy FP16/offload/PEFT image path.
- [ ] Finish installer review, integration tests, and native UI checks.
- [ ] Verify actual AI generation and memory on the 3060 Ti desktop; rebuild the EXE only after that gate passes.

## Later
- Evaluate adapter-on/off artwork before retraining the LoRA.
- Compare smaller narrators and image settings using the same scenes.

Details: [audit](docs/AUDIT.md), [Deathtrap FF](docs/DEATHTRAP_POC.md), [fidelity](docs/DEATHTRAP_FF_FIDELITY.md).
