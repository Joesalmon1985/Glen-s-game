# Deathtrap / Puca Trial POC

Default playable pack is **`puca_dungeon/content/puca_trial/`** (original spine prose). The Fighting Fantasy `deathtrap_ff` dump remains on disk for OCR/reference only and is **not** the default `PACK_DIR`. See `docs/PUCA_TRIAL.md`.

## Architecture

- `manifest.json` / `chargen.json` / `passages/NNN.json` / `gold_graph.json` — pack layout
- Runtime: free text → **two-stage interpret** (Stage A neutral intent, Stage B authored match) → ground → resolve → **world autonomy** (`world_react`: time, enemy opportunity, hazards) → narrate → optional image
- Python owns dice, sheet, passage turns, and whether attempts succeed; the narrator must not invent outcomes

### Interpretation (interactive play)

Ollama (or offline `HeuristicInterpreter`) produces intent JSON. Hard validation remaps forced authored matches, ungrounded vehicles, impossible powers, social-vs-combat, and key-vs-potion confusions. Compound actions keep an ordered `sequence[]`.

Then **Python resolve** + **world_react** own reality. Pack passage text is authoritative on enter; combat/dismiss/social use the narrator from structured facts. Image prompts optional (`--images`; suppressed in `--debug`).

Offline / CI: `--heuristic` + template narrator. Red-team waves require Ollama (no heuristic).

### Adventure Sheet

FF-style Skill / Stamina / Luck from chargen. Player-facing UI hides meters; debug `/sheet` remains. Engine-leak scanning rejects SKILL/STAMINA/LUCK jargon in player-facing prose.

## Puca compliance

| Principle | Implementation |
|-----------|----------------|
| Free text in; LLM interprets | Two-stage interpret + hard validation |
| Python owns reality | `resolve.py` + `ff_rules.py` + `world_react.py` |
| Narration from facts | Pack text on enter; narrator from structured facts otherwise |
| Images from visible state | `image_prompt.py` |
| Understood but prevented | Failure / absence facts — never INVALID COMMAND |
| Hidden embodied state | No on-screen Skill/Stamina/Luck |
| World autonomy | Modelled: time advance, enemy opportunity attacks, hazards |

## Opening path (puca_trial spine)

- **1** — six caskets; open named → **270** or continue → **66**
- **66** — junction (west / east / inspect tracks)
- West: **101** → **37** (tunnel-hound) → win **400** / lose **399** / flee **66**

QA helpers: `narrator_prosecutor`, `source_contamination`, `prose_lint`; regressions in `tests/test_adversarial_reality_regressions.py`.

## GUI turn feel

Story advances as soon as interpret → resolve → narrate finishes. Input unlocks before illustration completes. Diffusion uses a determinate progress bar; starting a new action cancels in-flight paint.

## Launch

```bash
# Offline / tests (no Ollama)
python -m puca_dungeon --heuristic --seed 91

# Player-facing with optional images
python -m puca_dungeon --no-debug --images --seed 91 --potion potion_skill --name Glen

# Debug pipeline dump
python -m puca_dungeon --seed 91

# LLM-only red team (Ollama required; no heuristic)
python scripts/deathtrap_redteam.py --seed 91
```

Windows: **Play Puca.bat** (Level 1 facility GUI + illustrations).

If the CLI prints `Interpreter: HeuristicInterpreter`, you are **not** using the LLM — start Ollama (`ollama pull mistral`) and relaunch without `--heuristic`.

```bash
python -m puca_dungeon.gui
Play Puca.bat --text-only
```

## Tests

```bash
python -m unittest tests.test_adversarial_reality_regressions tests.test_engine_leak tests.test_deathtrap_ff tests.test_deathtrap_gold -v
python -m puca_dungeon.graph_validate
python -m puca_dungeon.source_contamination
```
