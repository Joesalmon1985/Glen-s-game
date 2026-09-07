# Facility sprite kit

Pre-generated room backgrounds, props, and characters for facility-mode scene compositing.

## Generate (offline, GPU)

From the repo root, with the same image deps as the game (`install.bat`):

```bash
python scripts/generate_sprites.py --dump-draft
python scripts/generate_sprites.py --list
python scripts/generate_sprites.py --only room:cell
python scripts/generate_sprites.py
```

Useful flags: `--dry-run`, `--only backgrounds|props|characters|room:cell|<id>`, `--force`, `--no-lora`, `--candidates N`, `--seed-base INT`.

Generation can take hours. The script skips assets that already exist and look valid. Catalog `negative_prompt` is passed through to the diffuser.

## Red-team + closed-loop bakeoff

Hybrid heuristic + Ollama vision QA for every kit sprite and composed room fixture:

```bash
# Stage 1 — audit (heuristics always; vision if `ollama pull llava`)
python -m scripts.sprite_redteam audit
python -m scripts.sprite_redteam audit --skip-vision

# Stage 2 — regenerate failing assets (4 seeds) + layout slot bakeoffs
python -m scripts.sprite_redteam regenerate --from <stamp>

# Stage 3 — promote winners (dry-run by default)
python -m scripts.sprite_redteam promote --from <stamp>
python -m scripts.sprite_redteam promote --from <stamp> --apply --reaudit

# Full closed loop (up to 3 rounds)
python -m scripts.sprite_redteam loop --max-rounds 3
```

Artifacts land in `tools/sprite_redteam/<stamp>/` (`report.json`, `report.md`, `gallery/`, `candidates/`, `bakeoff.md`).

Clean gate fails on any P0/P1/P2 finding. If vision is skipped, the report marks `vision_skipped` and does not certify aesthetics.

## Runtime

Facility play composes a 512×512 PNG from this kit (no per-turn diffusion). Missing sprites fall back to simple placeholder tiles so the UI keeps working before the batch finishes.

Set `PUCA_SPRITE_DEBUG=1` to overlay layer ids while tuning layouts.

Book-dungeon / trial modes still use the old full-scene image path.
