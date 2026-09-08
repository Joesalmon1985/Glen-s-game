# Puca setup and diagnostics

This folder runs the Python game from a dedicated Windows virtual environment.
The original `my_version_of_kawa.exe` is not replaced by this setup. Use the
Python path below for the reproducible source launch.

## Supported hardware and Python

- Target GPU: NVIDIA RTX 3060 Ti (8 GB) with an i3-class desktop CPU.
- Verified here: NVIDIA RTX 5060 Laptop GPU (8 GB), Python 3.13.15, actual Mistral narration and SD1.5/LoRA generation. The 3060 Ti/i3 target still needs its own speed and memory measurements.
- Supported interpreter: **64-bit Python 3.11, 3.12, or 3.13** through the
  Windows `py` launcher.
- Python 3.14 is deliberately rejected. Do not use a bare `python` or `pip`
  command to install this application.

The installer selects the highest installed supported interpreter in this
order: 3.13, 3.12, then 3.11. It creates `.venv` beside this file and uses
`.venv\Scripts\python.exe -m pip` for every package operation.

## Install

1. Install a supported 64-bit Python from [python.org](https://www.python.org/downloads/windows/)
   with the **Python Launcher** enabled. Confirm one is available, for example:

   ```bat
   py -3.13 --version
   ```

2. Double-click `install.bat`, or run it from a Command Prompt in this folder.
   The script:

   - creates or reuses only the local `.venv`;
   - installs `torch==2.7.1` from the official CUDA 12.8 PyTorch index;
   - installs the pinned non-Torch packages in `requirements.txt` from PyPI;
   - runs a read-only package check and a tiny CUDA tensor check;
   - stops after every failed step instead of claiming setup completed.

3. The installer does **not** install Ollama, download an Ollama executable, or
   pull the Mistral model. That avoids an unrequested executable change and an
   approximately multi-gigabyte model download.

A pre-existing `.venv` is reused only if its interpreter is Python 3.11-3.13.
If it was created with Python 3.14 or is damaged, remove that `.venv` manually
and run `install.bat` again.

## Pinned environment

`requirements.txt` intentionally does not contain Torch. This prevents a later
normal-PyPI install from replacing the CUDA wheel with CPU-only Torch.

| Package | Pin | Install source |
|---|---:|---|
| PyTorch | `2.7.1+cu128` | official `download.pytorch.org/whl/cu128` index |
| diffusers | `0.35.2` | PyPI |
| transformers | `4.57.3` | PyPI |
| peft | `0.18.0` | PyPI |
| accelerate | `1.12.0` | PyPI |
| requests | `2.32.3` | PyPI |
| Pillow | `11.3.0` | PyPI |
| pywin32 | `311` | PyPI |

Package metadata was checked before writing these pins: every listed PyPI
release exists, and the official cu128 index lists Windows `win_amd64` Torch
2.7.1 wheels for CPython 3.11, 3.12, and 3.13. These are **direct dependency
pins**, not a complete transitive lock file; pip still resolves Torch's
transitive dependencies from the official index. The installer was not run
here, so no large Torch/model download or CUDA installation is claimed as
completed, and CUDA runtime behavior was not verified on either target GPU.

## Ollama narration (required for story play)

Ollama is optional only to setup and diagnostics; it is **required for actual
story generation, including `--text-only`**, because the game narrator uses its
local API. For story play, install Ollama yourself from
[ollama.com](https://ollama.com/download), start its local service, then run
this command explicitly in a separate Command Prompt:

```bat
ollama pull mistral
```

`diagnostics.py` only performs a read-only request to Ollama's local
`/api/tags` endpoint. It reports separately whether the executable is on PATH,
whether the service is reachable, and whether a `mistral` model tag is present.
It never calls `ollama pull`.

## Launch

Run `Play Puca.bat` after installation. It uses only:

```text
.venv\Scripts\python.exe -m puca_dungeon.gui
```

That starts Level 1 (facility) with Ollama for story text and local image generation when illustrations are on. A soft Ollama check runs first; if it fails, the GUI may still open with offline fallback text.

```bat
Play Puca.bat
Play Puca.bat --text-only
```

The launch script writes preflight output and any game traceback to
`logs\puca-launch.log`. It does not use a global Python installation. If the
window closes or the game exits, inspect that log before retrying.

## Diagnostics

The diagnostic command is safe to run repeatedly and has no repair side effects:

```bat
.venv\Scripts\python.exe diagnostics.py
```

For a check that does not contact the local Ollama service:

```bat
.venv\Scripts\python.exe diagnostics.py --skip-ollama
```

Output is one JSON document with stable top-level keys:

- `python`: `supported` or `unsupported` (3.11-3.13 only);
- `torch`: `cpu_only`, `cuda_unavailable`, `cuda_ready`, `missing`, or an
  import error, including CUDA build and tiny tensor-test details;
- `packages`: required runtime packages plus optional GPU/image packages and
  their installed versions, including `version_status` drift checks;
- `ollama`: executable, service, and `mistral` model state;
- `overall_status`: `ok`, `warning`, or `error`.

Important distinctions:

- **`cpu_only`**: Torch is installed but is a CPU-only build. More VRAM cannot
  fix it; reinstall the cu128 wheel inside `.venv`.
- **`cuda_unavailable`**: Torch has CUDA support, but the NVIDIA driver/device
  cannot be used by this process. Check the driver, GPU visibility, and the
  active `.venv` interpreter.
- **Missing optional GPU/image packages**: the graphics stack is absent; this
  can be intentional for the text-only mode, but full mode needs it.
- **Ollama not installed/not running/model missing**: story play cannot start;
  install/start/pull it explicitly as described above. Diagnostics itself can
  still run without Ollama.

The diagnostics module imports only Python standard-library modules, so it can
report a missing Torch stack instead of crashing with `ModuleNotFoundError`.

## Linux text-only (no GPU)

On Linux without an NVIDIA GPU, use the text-only path:

1. Run `./install_linux.sh` from this folder. It creates `.venv`, installs
   `requests` and `Pillow` (skips Windows-only `pywin32` and the CUDA Torch
   stack), downloads a user-local Ollama into `.runtime/ollama`, and pulls
   `mistral` into `.runtime/models`.
2. Launch with illustrations off and the turn debug panel on:

   ```bash
   ./launch_linux.sh
   ```

   Or manually:

   ```bash
   source .venv/bin/activate
   export OLLAMA_HOST=127.0.0.1:11434
   export OLLAMA_MODELS="$PWD/.runtime/models"
   python my_version_of_kawa.py --text-only --debug
   ```

On CPU-only machines, the first Mistral reply can take several minutes; later turns
are still slow. Narrator requests wait up to 10 minutes before failing.

After each command, the Debug panel (and `debug-last-turn.json` under the Puca
data directory) shows the narrator request, interpreted scene, options that were
available, engine apply results, and the image-generation payload that would be
sent when illustrations are enabled.
