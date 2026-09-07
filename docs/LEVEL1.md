# Level 1 facility + nested book dungeon

Default play starts in **facility** mode (the cell), not the trial spine.

## Modes

| `start_mode` | Meaning |
|---|---|
| `facility` (default) | Cell → slit → removal → wash → food → return → sleep |
| `book_dungeon` | Seeded randomised topology over authored encounters |
| `legacy_pack` | Fixed `puca_trial` passage graph (tests / red-team) |

## Pipeline

Player text → interpret intention → Python resolve (facility or passage) → enactment outcome → world/institution react → narrator receives **wanted_action** vs **actual_action**.

Enactment values: `direct` | `compromised` | `aborted` | `inverted` (rare; always with `enactment_cause`).

## Book

Reading the book enters a seeded dungeon (`layout_seed` in save). Natural-language disengage exits and bookmarks. Outer time advances slowly while reading; institution events can interrupt.

## Commands

```bash
python -m puca_dungeon --seed 91
python -m puca_dungeon --heuristic --seed 91
python scripts/level1_playtest_campaign.py
python scripts/level1_playtest_campaign.py --heuristic
```

## Validation

```bash
python -m pytest tests/test_dungeon_gen.py tests/test_level1_facility.py -q
python -c "from puca_dungeon.dungeon_validate import stress_validate_seeds; print(stress_validate_seeds(0,1000))"
```
