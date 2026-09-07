# Puca Trial content pack

Default playable pack: `puca_dungeon/content/puca_trial/`.

All passage prose is **original**. The pack reuses only abstract gamebook *grammar*—named containers, a cue-driven junction, a hostile creature, win/lose/flee combat exits, and hazard/exposure flags—not Fighting Fantasy or Deathtrap Dungeon wording.

## Layout

| File | Role |
|------|------|
| `manifest.json` | Pack id, title, start passage, declared range |
| `chargen.json` | FF-style Skill/Stamina/Luck dice, gold, provisions, potions; starting kit includes `iron_key` |
| `gold_graph.json` | Minimal expected edges for the early spine |
| `passages/NNN.json` | Authored situations (spine only) |

## Spine (reachable)

1 → open named casket (**270**) or continue (**66**)  
66 → west (**101**), east dead-end (**20**), or inspect tracks (**80**)  
101 → fight (**37**) or return (**66**)  
37 → win **400** / lose **399** / flee **66**

Unused numbers in `passage_range` [1, 400] are intentionally absent; `get_passage` only loads files that exist. Extend the pack by adding reachable passage JSON, not by stubbing the full range.

## Optional passage fields

Loaded by `content_loader.Passage` (default empty):

- `hazards` — authored hazard tags
- `entities` — visible / interactive entity ids
- `exposure` — e.g. `time_sensitive`, `active_threat`
- `pressures` — future pressure hooks

## Quarantined reference pack

`puca_dungeon/content/deathtrap_ff/` remains on disk for OCR/fidelity reference only. It is **not** the default `PACK_DIR`. Do not copy its prose into new content.
