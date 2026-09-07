# Deathtrap Dungeon POC notes

## Faithful source material

Derived from the supplied *Deathtrap Dungeon* opening:

- The player enters after other contestants and receives one key.
- After roughly five minutes they reach a stone table with six locked boxes; one bears the player's name.
- Wrong key or lock-picking without disabling the trap fires a poison dart.
- Trap Search DC 25; Disable Device DC 25; Open Lock DC 35 on another box.
- Boxes: Hardness 10, 10 hp.
- The player's key opens only the named box.
- Named box contents: 2 gp and Sukumvit's clue note.
- Encounter 2 junction: white arrow pointing west; closer inspection can reveal tracks (three west, one right).

## Puca POC additions

- **Approaching challenger (anti-stall pressure).** Inspired by the Knight, Elf, two Barbarians and Ninja who entered immediately before the player, but **not** taken from canonical encounter text. Fictional-time progression may bring a Barbarian contestant (`Grimnak`) into Encounter 1 if the player continually waits or performs non-productive actions. This is a POC world-pressure device so Encounter 1 does not freeze forever.
- Typing-first intent interpretation (AI or heuristic) with Python owning authoritative resolution.
- Debug play mode that never calls the visual generator but still builds the would-be image request.
- Deterministic seeded RNG with save/load of RNG state.

## Architecture

1. Player free text
2. **Ollama interpreter** (default) receives raw text + public perception + authored action descriptors → hierarchical classification / intent (no outcomes). HeuristicInterpreter is tests/offline only.
3. Entity grounding (ambiguity → clarification; no silent named-box pick)
4. Python resolution (checks, traps, damage, movement, perception/meta answers)
5. Fictional time + Encounter-1 world pressure (separate from hidden `guidance_level`)
6. Narrator from resolved facts (+ optional humorous re-anchor from guidance)
7. Image decision + prompt (suppressed in debug; auditory-only → REUSE)

## Launch

```bash
./launch_dungeon_debug.sh
# or
python -m puca_dungeon --debug --seed 91
# Windows:
#   Play Deathtrap Dungeon.bat
# offline / tests:
python -m puca_dungeon --heuristic
```

`Play Puca Dungeon Debug.bat` launches the Spirit adventure with `--debug`, not this POC.

Requires local Ollama with `mistral` (or `--model`). Fails clearly if Ollama is down unless `--heuristic` / `--allow-heuristic-fallback`.
