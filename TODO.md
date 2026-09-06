# Puca TODO

## Deathtrap Dungeon POC (`wip/typing-first-dungeon`)
- [x] Encounter 1 boxes/traps/key/clue with typing-first intent → Python resolution.
- [x] Encounter 2 junction stub after leaving the boxes.
- [x] Fictional-time pursuer pressure (POC addition; see docs/DEATHTRAP_POC.md).
- [x] Debug play mode with full pipeline dump; image generation suppressed.
- [x] Deterministic tests + human-readable traces under tests/traces/.

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
- Expand dungeon beyond Encounter 2 stub.

Details: [audit](docs/AUDIT.md), [Deathtrap POC](docs/DEATHTRAP_POC.md).
