# Facility sprite kit

Pre-generated room backgrounds, props, and characters for facility-mode scene compositing.

## Generate (offline, GPU)

From the repo root, with the same image deps as the game (`install.bat`):

```bash
python scripts/generate_sprites.py --list
python scripts/generate_sprites.py
```

Useful flags: `--dry-run`, `--only backgrounds`, `--only props`, `--only characters`, `--force`, `--no-lora`.

Generation can take hours. The script skips assets that already exist and look valid.

## Runtime

Facility play composes a 512×512 PNG from this kit (no per-turn diffusion). Missing sprites fall back to simple placeholder tiles so the UI keeps working before the batch finishes.

Book-dungeon / trial modes still use the old full-scene image path.
