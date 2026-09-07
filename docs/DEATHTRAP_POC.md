# Deathtrap Dungeon — Fighting Fantasy gamebook

Playable source is the **Fighting Fantasy** numbered gamebook (passages 1–400), not the d20 PDF conversion. The d20 PDF may exist in the repo for reference only; it is **not** loaded by the engine.

## Architecture

Content pack: `puca_dungeon/content/deathtrap_ff/`

- `manifest.json` — start id, passage range
- `chargen.json` — Skill / Stamina / Luck rolls, gold, provisions, potions
- `passages/NNN.json` — one file per paragraph (text, choices, combat, tests, enter effects, ending)
- `gold_graph.json` — machine-checkable expected edges (OCR-recovered or `judgement_inferred`)

Runtime is a **passage graph**: player free text → interpreter maps to an authored choice, combat action, item use, perception query, or dismiss → Python owns dice, sheet changes, and `turn to` navigation.

### Three-step LLM interpretation (interactive play)

The Ollama interpreter follows an ordered procedure (one JSON call):

1. **Authored** — match free text to a current passage choice / combat / potion / provision action → `MATCH_AUTHORED_ACTION`.
2. **World** — else map a clear attempt (perception, use item, attack) → `GENERAL_WORLD_ACTION` / `PERCEPTION_QUERY`; Python may no-op.
3. **Dismiss** — else `SILLY_BUT_VALID` / `META_REQUEST` / `UNINTERPRETABLE` / clarification; stay on the same passage.

Then **Python resolve** owns dice, sheet changes, and `turn to` navigation. **Narrate:** pack passage text is authoritative on enter; combat/dismiss use the narrator. Image prompts optional (`--images`; suppressed in `--debug`).

Offline / CI uses `--heuristic` (deterministic `HeuristicInterpreter` + template narrator). Red-team waves require Ollama and **must not** use the heuristic path.

### Adventure Sheet

Classic Fighting Fantasy scores from chargen (Skill / Stamina / Luck, gold, provisions, potion). Player-facing UI and CLI openers **hide** these meters; they influence facts fed to narration when relevant. Debug `/sheet` remains available.

## Puca compliance (Deathtrap FF)

| Principle | How Deathtrap implements it |
|-----------|-----------------------------|
| Free text in; LLM interprets | `OllamaInterpreter` three-step JSON intent |
| Python owns reality | `resolve.py` + `ff_rules.py` own dice, sheet, `turn to` |
| Narration from facts | Pack text on enter; narrator from resolution facts otherwise |
| Images from visible state | `image_prompt.py` from final world + passage seed |
| Optional examples, not menus | GUI example chips fill the entry only |
| Understood but prevented | Dismiss / failure facts — never a fixed INVALID COMMAND |
| Hidden embodied state | No on-screen Skill/Stamina/Luck |
| World autonomy / systemic physics / NPC schedules | **Not** modelled — FF authored graph only |

## Opening path

Hand-authored early nodes remain protected:

- **1** — six boxes; open named box → **270** or continue north → **66**
- **66** — junction (west / east / inspect tracks)
- West combat: **101** → **37** (Giant Rat) → win **400** / lose **399** / flee **66**

Full pack fidelity: see `docs/DEATHTRAP_FF_FIDELITY.md` and `gold_graph.json`. Unclear OCR gaps use editorial judgement (`judgement_inferred`).

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

Windows: **Play Deathtrap Dungeon.bat** (Ollama LLM by default; add `--heuristic` only for offline) or **Play Deathtrap Dungeon GUI.bat**.

If the CLI prints `Interpreter: HeuristicInterpreter`, you are **not** using the LLM — start Ollama (`ollama pull mistral`) and relaunch without `--heuristic`.

```bash
python -m puca_dungeon.gui
Play Deathtrap Dungeon GUI.bat --text-only
```

## Tests

```bash
python -m unittest tests.test_deathtrap_ff tests.test_deathtrap_gold -v
python -m puca_dungeon.graph_validate
```
