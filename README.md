# Puca: repaired local adventure

## Play on this machine (Spirit adventure)

Double-click **Puca - Play** on your desktop, or **START PUCA** in this folder. Both use **Play Puca.bat**, which checks the local narrator, starts the project's Ollama runtime if needed, and launches the verified build. No account or paid API is needed.

For the same Spirit adventure with the turn debug panel, use **Play Puca Dungeon Debug.bat** (runs `launch.bat --debug`).

## Deathtrap Dungeon (Fighting Fantasy gamebook)

Typing-first console engine over FF passages 1–400 (`puca_dungeon/content/deathtrap_ff`). Skill / Stamina / Luck sheet; Ollama interpret by default, Python resolution. The d20 PDF is not the playable source.

```bash
# Offline / tests
python -m puca_dungeon --heuristic --seed 91

# Player mode with images (needs GPU stack); pick starting potion via chargen ids
python -m puca_dungeon --no-debug --images --seed 91 --potion potion_skill --name Glen
```

Windows: **Play Deathtrap Dungeon.bat** (CLI) or **Play Deathtrap Dungeon GUI.bat** (Tk window + illustrations, no visible Skill/Stamina/Luck meters).

See [docs/DEATHTRAP_POC.md](docs/DEATHTRAP_POC.md). Tests: `python -m unittest tests.test_deathtrap_ff -v`.

The game opens at **2560 x 1440** with larger story text and up to **768 x 768** displayed pixel artwork. You can resize the window; artwork fits the available space. AI illustrations still generate at **512 x 512**, so the larger window does not request more expensive AI images. Close an older open version and use the shortcut again to pick up the update.

Enter a name and starting place, then choose **Begin**. Use the suggested actions or type your own. **Resume** restores your saved adventure. Turn **Illustrations** off for faster text play; use **Skip image** during painting. **Retry** recovers a failed request, save, or illustration without spending another turn.

Your normal save, image cache and runtime log live in `%LOCALAPPDATA%\Puca`. Verification playthroughs use separate saves under `docs/verification/` and never replace your adventure.

## What changed

- One generation job at a time, including Enter-key submissions.
- Real consequences, preserved final narration, durable facts and save/resume.
- A scene must save successfully before it spends a turn. Failed saves can retry without rerolling the story.
- Missing/corrupt art recovers; failed image cleanup does not prevent text play.
- Suggested actions remain visible. Voice can restart after initialization failure.
- AI context is bounded; internal outcome labels are rejected and retried instead of shown as fiction.
- SD1.5 loads actual FP16 weights with CPU offloading, 20 steps and efficient attention. Images are reused until the location or major visible scene changes.
- The supplied raw PEFT LoRA attaches and merges; missing adapter files never silently substitute base art.

## Verified

- **43 regression tests passed**, each collected and executed once. Native Tk tests use fresh processes to avoid cross-test Tcl teardown contamination.
- **Real Mistral playthrough:** opening plus ten choices, automatic saves, Resume during play, final narration and disabled finished-game controls.
- **Real illustrations:** SD1.5, supplied LoRA, 512 x 512, 20 steps; all checked image components used FP16.
- The measured image pass peaked at **2.32 GiB active / 2.49 GiB reserved PyTorch GPU memory**. This is not total game/system VRAM. About 0.58 GiB remained allocated after the image hand-off; the real subsequent narration turns still succeeded.
- Ollama reported no resident AI model after every completed turn in the playthrough.

**Test hardware was this laptop's RTX 5060 8 GB, not the target RTX 3060 Ti/i3.** No speed or minimum-VRAM guarantee is inferred for the target desktop. The LoRA was made to load correctly; it was not retrained, and image/story quality still varies.

## Build and transfer

`build.bat` builds the updated 1440p executable at `dist-qhd/Puca/Puca.exe`. Keep its entire `Puca` folder together, not only the EXE. AI weights and Ollama are separate dependencies. The root-level original EXE and the earlier `dist/Puca` build are untouched; the original source and installer are in `original/`.

For another PC, follow **SETUP.md**. Do not copy `.venv` between machines. `requirements.txt` holds runtime pins; `docs/verification/environment.txt` records the actual tested environment.

See **docs/AUDIT.md** for the original audit and **docs/verification/** for real test/playthrough/GPU evidence.
