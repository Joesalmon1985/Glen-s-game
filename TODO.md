# Puca TODO

## Current fix pass
- [x] Preserve original source/installer and document the audit.
- [x] Fix spirit rules, narrator request format, endings, and save/resume.
- [x] Prevent overlapping turns; show text before images; recover from generation errors.
- [x] Add scene-image reuse and a lazy FP16/offload/PEFT image path.
- [ ] Finish installer review, integration tests, and native UI checks.
- [ ] Verify actual AI generation and memory on the 3060 Ti desktop; rebuild the EXE only after that gate passes.

## Later
- Evaluate adapter-on/off artwork before retraining the LoRA.
- Compare smaller narrators and image settings using the same scenes.
- Strengthen authored goals, consequences, and endings after a real playthrough.

Details and recommendations: [audit](docs/AUDIT.md). Completed source changes are not proof of GPU performance; the original EXE remains unchanged.
