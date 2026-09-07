# Deathtrap Dungeon — Fighting Fantasy gamebook

Playable source is the **Fighting Fantasy** numbered gamebook (passages 1–400), not the d20 PDF conversion. The d20 PDF may exist in the repo for reference only; it is **not** loaded by the engine.

## Architecture

Content pack: `puca_dungeon/content/deathtrap_ff/`

- `manifest.json` — start id, passage range
- `chargen.json` — Skill / Stamina / Luck rolls, gold, provisions, potions
- `passages/NNN.json` — one file per paragraph (text, choices, combat, tests, enter effects, ending)

Runtime is a **passage graph**: player free text → interpreter maps to an authored choice, combat action, item use, perception query, or dismiss → Python owns dice, sheet changes, and `turn to` navigation.

### Three-step LLM interpretation (interactive play)

The Ollama interpreter follows an ordered procedure (one JSON call):

1. **Authored** — match free text to a current passage choice / combat / potion / provision action → `MATCH_AUTHORED_ACTION`.
2. **World** — else map a clear attempt (perception, use item, attack) → `GENERAL_WORLD_ACTION` / `PERCEPTION_QUERY`; Python may no-op.
3. **Dismiss** — else `SILLY_BUT_VALID` / `META_REQUEST` / `UNINTERPRETABLE` / clarification; stay on the same passage.

Then **Python resolve** owns dice, sheet changes, and `turn to` navigation. **Narrate:** pack passage text is authoritative on enter; combat/dismiss use the narrator. Image prompts optional (`--images`; suppressed in `--debug`).

Offline / CI uses `--heuristic` (deterministic `HeuristicInterpreter` + template narrator).

### Adventure Sheet

Classic Fighting Fantasy scores from chargen:

| Score | Typical formula |
|-------|-----------------|
| Skill | 1d6+6 |
| Stamina | 2d6+12 |
| Luck | 1d6+6 |

Also: gold, provisions, inventory, one starting potion (`potion_skill` / `potion_strength` / `potion_fortune`), knowledge/flags.

## Opening demo path

Hand-authored early nodes:

- **1** — six boxes; open named box → **270** (gold + clue) or continue north → **66**
- **66** — junction (west / east / inspect tracks)
- West demo combat: **101** → **37** (Giant Rat) → win **400** / lose **399** / flee **66**

Bulk OCR passages still need editorial review; see `docs/DEATHTRAP_FF_FIDELITY.md`.

## Launch

```bash
# Offline / tests (no Ollama)
python -m puca_dungeon --heuristic --seed 91

# Player-facing with optional images (Ollama required unless --allow-heuristic-fallback)
python -m puca_dungeon --no-debug --images --seed 91 --potion potion_skill --name Glen

# Debug pipeline dump (default when not --no-debug)
python -m puca_dungeon --seed 91
```

Windows: **Play Deathtrap Dungeon.bat** (CLI, heuristic) or **Play Deathtrap Dungeon GUI.bat** (Tk GUI with illustrations, no on-screen Skill/Stamina/Luck meters).

GUI launch:

```bash
python -m puca_dungeon.gui
# or
Play Deathtrap Dungeon GUI.bat
# text only:
Play Deathtrap Dungeon GUI.bat --text-only
```

Chargen potion ids: `potion_skill`, `potion_strength`, `potion_fortune` (`--potion` on CLI; potion dropdown in the GUI).

## Tests

```bash
python -m unittest tests.test_deathtrap_ff -v
```

Graph check: `python -m puca_dungeon.graph_validate`.
