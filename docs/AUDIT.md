# Puca prototype audit

## Verdict

Fix the installation and game rules before retraining the art AI or replacing the narrator. The most important performance changes are to make half-precision actually work, prevent the two AI systems competing for GPU memory, and stop generating a new image for every action. The most important game-design change is to make outcomes follow choices rather than a random spirit roll.

**The reported desktop crash is diagnosed from the supplied traceback: the script's Python environment contains CPU-only PyTorch. It is not an out-of-VRAM error.** The traceback also confirms an ignored half-precision setting and a missing memory-efficient loading dependency.

No original game files were changed. This is an audit, not a repaired or benchmarked release.

## Evidence and limits

Reviewed the complete supplied Python source, installer, LoRA configuration, safetensors header, model card, and the EXE's embedded archive metadata. Executed 15 focused checks against the actual Python class bodies, using explicitly controlled substitutes for HTTP, images, widgets, thread scheduling, and randomness. These included a complete controlled ten-turn controller run; they were not an AI-generated playthrough. Read the user's desktop traceback and checked upstream Ollama and Diffusers contracts, including the Diffusers commit recorded in the EXE.

The desktop in the reported failure is an **RTX 3060 Ti with an Intel i3**. Its exact CPU generation, RAM, driver, installed package versions, and measured GPU peak were not supplied. The separate laptop available to this audit is not that desktop. Live image generation, subjective art quality, narrative pacing, voice behaviour, and end-to-end VRAM/latency were not measured. The EXE was inspected without launching it. Its functionality on the desktop is user-reported, not independently replayed here. Source findings refer to the supplied `.py`; byte-for-byte equivalence with the code inside the EXE was not established.

## 1. Confirmed desktop crash and installation drift

### Immediate failure: CPU-only PyTorch

The error ends with:

> `AssertionError: Torch not compiled with CUDA enabled`

The program fails at `.to("cuda")`, before LoRA loading and before diffusion inference. The installed Torch package has no CUDA support. More VRAM, a smaller LoRA, or fewer image steps cannot fix this particular exception. Installing a standalone CUDA toolkit does not turn a CPU-only Torch wheel into a CUDA-enabled one.

The supplied EXE's embedded package metadata is materially different from the script environment:

| Component | Supplied EXE | Desktop script evidence |
|---|---|---|
| Python | 3.13 runtime | 3.14 in traceback |
| PyTorch | `2.7.1+cu118`, CUDA 11.8 build | CPU-only; exact version not logged |
| Diffusers | `0.36.0.dev0`, built from Git | Exact version not logged; rejects `dtype` |
| PEFT | `0.18.0` | Not established |
| Transformers | `4.57.3` | Not established |
| Accelerate | Not checked in EXE metadata | Missing, explicitly warned |

Meanwhile, `install.bat:18` requests the **CUDA 12.4** package index. It does not recreate the EXE's CUDA 11.8 environment. It also uses bare `pip`, installs into whichever environment that command resolves to, pins no Python/package versions, and does not stop when a dependency installation or download fails. Its eventual "Setup complete" message is not proof of a complete installation.

**Recommendation:** create one dedicated, reproducible environment, initially matching the working EXE's Python/CUDA/package baseline where possible. Use that environment's `python -m pip` for all installs and its Python executable for launching. Lock the tested packages, including the exact Git revision if retaining the development Diffusers build. Build the EXE from the same lock. Check every installer exit code and run a tiny CUDA tensor operation before launching the game. This is a baseline to verify, not a claim that recreating package metadata alone fixes every subsequent issue.

### Separate confirmed problem: half-precision is ignored

The log explicitly says:

> `Keyword arguments {'dtype': torch.float16} are not expected ... and will be ignored.`

The source intends to use FP16, but that option does not take effect in the desktop's installed Diffusers version. For that API, use the supported `torch_dtype=torch.float16` argument. Verify the loaded UNet, text encoder, and VAE parameter types rather than assuming the argument worked. Ignoring the request means FP16 is not guaranteed; the traceback alone does not inspect the actual loaded types.

FP16 stores floating-point weights using half the bytes of FP32. That does **not** mean the whole application uses half as much VRAM: activations, caches, other processes, and framework allocations also count.

### Separate confirmed problem: Accelerate is absent

The warning says memory-efficient CPU loading was disabled. Install a compatible, pinned `accelerate` version in the same environment. This improves loading behaviour and enables supported offloading features; it does not itself cure CPU-only Torch.

**Source:** `install.bat:7–43`; `my_version_of_kawa.py:82–91`; supplied `error.txt:7–12, 24–63`.

## 2. Priority findings

### P1. Spirit rewards and penalties ignore the player's outcome

Both `[spirit: positive]` and `[spirit: negative]` lead to the same random draw from **-40 to +25**. The controlled checks demonstrated:

- A positive outcome taking spirit from **60 to 20**.
- A negative outcome taking spirit from **60 to 85**.

The raw draw averages **-7.5 per turn**, before clipping at zero and 100. The opening can also remove up to 80 spirit before the player makes a choice. This makes the score feel arbitrary and can contradict the narrator's explanation.

**Change:** define consequences in game rules. Positive, negative, and neutral outcomes should have bounded, appropriate effects. If uncertainty is part of the design, establish the risk before the action and let the narrator describe the resolved result. Avoid letting free-form AI prose be the sole authority over game state. Do not penalise the player for a malformed AI response.

**Source:** `.py:313–315, 354–360`.

### P1. A second action can start while the first is still generating

Disabling Submit does not disable the entry's Return binding. `process_action()` has no busy guard, so another entered action dispatches another worker. Input is also available while the opening sequence is in progress.

Concurrent workers can mutate the same spirit/turn/context, race the image filenames, initialise or use the same diffusion pipeline concurrently, and increase GPU pressure. The checks reproduced two worker dispatches with Submit already disabled. They did not measure an actual GPU race or establish this as the cause of the supplied crash.

**Change:** set an explicit busy flag before scheduling work, reject both button and keyboard submissions while busy, disable input during arrival, and use one generation queue. Bind images and results to immutable turn IDs. Only the main UI thread should apply UI updates.

**Source:** `.py:211–215, 276, 325–337, 378–385, 408`.

### P1. Failed generation can consume a turn or strand the game

An Ollama failure becomes ordinary narration containing an error message. The game still consumes a turn, changes spirit, stores the error as memory, and attempts to illustrate it. A controlled image exception escaped the turn worker after state mutation and left Submit disabled, without displaying the generated story. The real traceback confirms the same uncaught-worker pattern on arrival.

**Change:** treat success/error as separate results. Commit a turn only after valid narration and a valid game-state update. An optional illustration failure should keep the previous image and allow text play to continue. Use a guaranteed cleanup path for input/status restoration, a visible retry/skip action, and cancellation on window close.

**Source:** `.py:53–72, 278–323, 336–408`.

### P1. Ollama's token and temperature controls are wired incorrectly

The source calls the native `/api/generate` endpoint but sends `max_tokens` and `temperature` at the top level. That endpoint expects generation settings inside `options`, with `num_predict` for the output token limit. The intended 200/300-token limits are therefore not correctly expressed. The system rules are also inserted into ordinary prompt text instead of using the explicit system field.

**Change:** use `system`, `options.num_predict`, `options.temperature`, and an explicit `options.num_ctx` budget. Request structured JSON containing narration, event, visual description, and proposed outcome. Validate its schema and values; reject or repair invalid responses without charging a game turn. Keep authoritative game rules outside player-editable prompt text.

Structured output improves parsing, not truthfulness or narrative coherence by itself.

**Source:** `.py:33–68`; official [Ollama generate API](https://docs.ollama.com/api/generate).

### P1. The LoRA may not be applied at all through this loading path

The supplied adapter is a raw PEFT export. Its 128 tensor names begin with `base_model.model...`; the Diffusers pipeline route in the EXE's recorded upstream revision filters UNet weights by `unet.`. **None of the supplied names pass that filter.** That loader has a warning path for finding no matching LoRA weights, rather than necessarily failing the whole image generation.

This is a verified file-format/routing mismatch and a strong reason to check loading before blaming training. It is not a live proof of which adapter the desktop EXE actually used. The posted crash occurs before reaching this step.

**Change:** use a supported raw-PEFT loading path for the UNet, or correctly convert/export to Diffusers format. Preserve configuration, including rank **16** and alpha **32**; changing filename or key prefixes alone is not a complete conversion. Assert that the expected adapter is registered and weights actually attach. Then compare adapter off/on with identical prompt and random seed, at several strengths.

**Source:** `.py:90–91`; adapter configuration and safetensors header; [pipeline loader at the EXE's recorded revision](https://github.com/huggingface/diffusers/blob/152f7ca357c066c4af3d1a58cdf17662ef5a2f87/src/diffusers/loaders/lora_pipeline.py#L397-L409); [PEFT prefix filtering](https://github.com/huggingface/diffusers/blob/152f7ca357c066c4af3d1a58cdf17662ef5a2f87/src/diffusers/loaders/peft.py#L212-L217).

### P2. The ending throws away the final scene

The opening promises roughly five turns, but the controller stops at ten. At the normal limit it generates narration and an image, then discards the narration in favour of a generic thank-you. Both defeat and normal completion call a helper that labels spirit as zero, even if the internal score remains positive. A controlled ending retained **60** internally while displaying **0/100**.

**Change:** choose one session length, pass the remaining turns and narrative phase to the narrator, and give the last action an actual resolution. Separate completion from defeat. Preserve and display the real score, plus a concise account of consequential choices.

**Source:** `.py:288, 347–350, 387–408, 438–442`.

### P2. Memory does not reliably preserve choices or world facts

Memory consists of narration cut off at character limits. Player actions are not explicitly retained. The latest eight event snippets and last 500 context characters can lose promises, possession of an item, the identity of a character, or earlier consequences. Event codes are recorded as text but do not drive an encounter/quest system.

**Change:** keep a compact, explicit record of location, important characters, inventory, promises, objective, and resolved consequences. Retain recent player actions and narration alongside a rolling summary. Supply only relevant facts each turn; do not solve this by sending the entire transcript forever.

**Source:** `.py:139–146, 317, 339–340, 362–372`.

## 3. Practical efficiency plan for an 8 GB GPU

### First: fix work allocation, not the art style

| Priority | Change | Benefit and trade-off |
|---|---|---|
| 1 | Make FP16 effective and verify loaded types | Removes accidental weight-memory overhead. Needs a compatible, locked dependency set. |
| 2 | Allow only one generation job at a time | Prevents duplicate work and pipeline races; also protects game state. |
| 3 | Coordinate GPU ownership between Ollama and diffusion | More predictable peak memory. Offloading/unloading adds transfer or reload latency. |
| 4 | Generate art only when the visible scene meaningfully changes | Removes whole diffusion jobs, saving actual work rather than only changing a loading indicator. |
| 5 | Display validated narration before generating the image | Player can start reading immediately. Better perceived responsiveness, not inherently lower inference cost. |
| 6 | Benchmark SDPA against forced attention slicing | Modern PyTorch's efficient attention is a better starting point; slicing can replace the faster path and cause substantial slowdown. |
| 7 | Test a suitable sampler at 20 steps against the current 30 | Fewer denoising steps, with image-quality trade-offs. Not a promised proportional end-to-end speedup. |
| 8 | Bound output tokens and context | Reduces unnecessary text generation and memory use, subject to coherence testing. |

### Coordinate both AI systems explicitly

The image pipeline is moved wholly to CUDA and retained. Ollama receives no `keep_alive` setting; its documented default is to keep an AI model loaded for five minutes. If Ollama is GPU-resident, this can overlap with diffusion even though the Python requests happen in sequence. Actual placement depends on Ollama, the device, and available memory; it was not measured on the desktop.

**Recommended conservative 8 GB mode:** release diffusion's GPU residency before narration; complete narration; unload Ollama before illustration; generate the image; then offload image components again. Check that memory is genuinely released between phases. Keep CPU copies where practical to avoid reloading everything from disk. Start with Diffusers `enable_model_cpu_offload()` rather than immediately moving the whole pipeline to CUDA. Verify the installed version's hooks release residual components at the hand-off.

`torch.cuda.empty_cache()` alone cannot free live pipeline weights or unload Ollama in another process. Use it, if needed, only after live tensors have been offloaded/released. Per-submodule sequential CPU offload is a slower emergency setting, not the default recommendation. Offload also increases system-RAM needs, so publish RAM requirements alongside VRAM requirements.

Once measured, relax this conservative policy where both workloads fit reliably. Repeated unload/reload can itself become the bottleneck. On an unspecified i3, do not assume moving all narration to CPU will remain pleasant to play.

### Stop illustrating every sentence

Keep the current image while talking to the same person in the same place. Generate a replacement for a new location, major reveal, or important visual event. Key the image cache by relevant scene facts plus prompt/settings, not merely the latest prose. Cache in a user-writable application-data directory, not the process's current folder.

For illustration only: changing a ten-turn session from opening-plus-every-turn art (**11 images**) to **4 key images** is about **64% fewer image jobs**. This is arithmetic for a proposed policy, not a measured speedup, and it does not reduce the peak memory of an individual image job.

### Starting benchmark configuration, not a claimed optimum

- Keep **Stable Diffusion 1.5** initially; replacing it with a larger image AI works against this hardware target.
- Explicit **512 × 512**, batch one, FP16, and verified efficient attention.
- Compare the existing 30-step output against a suitable DPM-Solver-style 20-step configuration using fixed prompts and seeds.
- Explicitly choose the narrator's quantisation and context budget instead of relying on the floating `mistral` alias. A **2K–4K context** is a starting experiment for this short game, not a guaranteed sufficient limit.
- Evaluate a quantised **3B–4B narrator** only after fixing state, prompt structure, and parsing. Compare coherence and decision-following against the existing Mistral baseline, not only speed.
- A compatible distilled image approach can be investigated later. Do not simply lower ordinary SD1.5 to four steps and expect the same quality; that requires compatible weights, scheduler, and guidance settings.
- Keep a genuine text-only mode with lazy image dependencies, rather than making image failure fatal to the whole game.

Do not prioritise LoRA quantisation: the supplied adapter is only **6.10 MiB** on disk. The base AI workloads are the meaningful GPU-memory targets.

## 4. Make it a better adventure

### Give improvisation a small authored structure

At present the code asks for atmospheric encounters but has no explicit objective, escalation plan, world-rule enforcement, or consequence-driven ending. This is closer to an AI story improviser than a choice-driven adventure with reliable consequences.

Keep the free-text input, but place it inside a small scaffold: arrival, a clear problem, complications, a consequential decision, and resolution. Offer two or three contextual suggestions plus "do something else". The game resolves what is possible and what changes; the AI provides flexible description and dialogue. This protects freedom without asking the AI to invent the rules anew each turn.

### Make consequences legible

Show the spirit change and its concrete cause. Distinguish morally uncomfortable choices from random punishment. Let major actions persist through promises, relationships, access to places, or possessions, so the ending can reflect something the player recognises.

### Improve continuity and presentation

- Keep a readable history, not only the latest overwritten passage.
- Save/resume locally, including scene facts, decisions, prompt/settings, seeds, and image references.
- Offer restart, mute, voice speed, font scaling, and keyboard focus management.
- Keep image prompts in a debug view rather than the main story text.
- Do not announce technical progress repeatedly by voice unless the player wants it.
- Put speech ownership on one worker: the current COM speaker is created on one thread and reused from new threads without explicit COM marshaling. That is a reliability risk, not a crash reproduced in this audit.
- Queue UI updates to the main thread, cancel stale results on close/restart, and provide meaningful loading/error states.

**Source:** `.py:173–179, 191–215, 232–261, 267–272, 415–442`.

## 5. Improve the art only after validating the adapter

The LoRA card contains no useful dataset, training, or evaluation information. Its rank and file size alone cannot establish that it was badly trained. No generated examples were supplied for visual evaluation.

Use a fixed evaluation set covering interiors, exteriors, lone characters, conversations, creatures, objects, lighting, and compositions. Compare the base checkpoint and correctly loaded adapter with identical prompts/seeds and several adapter strengths. Check that the adapter changes style without repeatedly inserting the same subject.

If retraining is warranted, curate a consistent pixel scale/palette, remove duplicates and compression artefacts, diversify subjects and viewpoints, caption content separately from style, and reserve unseen evaluation prompts/images. Track the base checkpoint, trigger wording, training settings, dataset rights, and adapter version.

For recurring characters and locations, retain canonical visual descriptions and reuse established art. A fixed seed helps repeat a comparison; it does not guarantee character identity across changing prompts. For true pixel-art presentation, choose an intentional working pixel grid and nearest-neighbour integer scaling. The current unconditional resize to 400 × 400 does not enforce that discipline.

Finally, the prompts explicitly target a children's story while the image safety checker is disabled. Decide the intended age range and add appropriate content constraints and checking for text and images. Merely requesting child-friendly language is not a complete safety policy, nor is an image checker alone.

**Source:** `.py:87, 98–125, 149–163, 282–292, 426–432`; LoRA README and adapter configuration.

## 6. Packaging and maintainability

The EXE is **2.95 GB** on disk. Archive inspection shows large Torch/CUDA DLLs dominate the largest entries. That is distribution/storage size, not a VRAM measurement. Music is shipped although its playback calls are commented out, and the installer requests packages not used by the active game path.

- Separate the UI, story rules/state, narrator client, image worker, and persistence. This does not require replacing Python or adopting a large framework.
- Pin and build from a dedicated environment; use one-folder distribution or a conventional installer if repeated extraction/startup becomes costly. Benchmark that separately from inference.
- Remove unused dependencies/assets only after checking packaging requirements; do not arbitrarily delete CUDA libraries.
- Preflight Ollama availability, installed narrator tag, GPU capability, half-precision types, adapter attachment, writable storage, and first-run downloads.
- Show download sizes, progress, retry, and offline readiness instead of discovering missing prerequisites during the opening scene.
- Add ordinary unit tests and an integration smoke test. No test suite or dependency lock was present in the supplied folder.

## 7. Acceptance criteria for the next version

1. The desktop's selected Python can execute and synchronise a CUDA tensor operation before game launch.
2. A fresh installation uses the same locked dependency set as the release build; failures stop setup with a useful message.
3. Loaded image components have verified intended precision; adapter registration and fixed-seed off/on output are checked.
4. Arrival plus a complete session cannot enqueue overlapping turns through button or keyboard input.
5. AI timeout, invalid output, image failure, and GPU out-of-memory do not silently corrupt progress or strand input.
6. Positive/negative/neutral outcomes obey game rules; a normal ending retains the correct score and narrates the last choice.
7. Earlier promises and key state remain true across a full session and save/reload.
8. On the actual 3060 Ti/i3 machine, measure cold startup, time to readable narration, image latency, turn latency, peak total GPU memory, and peak system RAM. Record exact CPU, RAM, driver, AI versions/quantisation, image settings, and whether other GPU applications are open.
9. Compare identical actions/seeds before and after each optimisation. Report median and slow-turn behaviour over repeated complete sessions, not only the first successful image. Include Ollama's GPU usage: PyTorch's allocator statistics cover only the Python process, not both workloads.

**Suggested order:** reproducible GPU setup and effective FP16 → single-job queue and failure recovery → correct consequences and endings → fewer image jobs and coordinated memory → evaluate narrator alternatives and LoRA training.

## References and reproducible evidence

- [Ollama generate API](https://docs.ollama.com/api/generate)
- [Ollama API reference source: options, context, keep-alive and structured outputs](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [Diffusers memory optimisation and offloading](https://huggingface.co/docs/diffusers/en/optimization/memory)
- [Diffusers pipeline attention-slicing warning](https://huggingface.co/docs/diffusers/main/en/api/diffusion_pipeline)
- [PyTorch published package/version combinations](https://pytorch.org/get-started/previous-versions/)
- Local `audit_checks.py` and `audit-check-results.json`: controlled source execution and arithmetic.
- Local `inspect_exe.py` and `exe-archive-index.json`: read-only EXE archive inspection and embedded version metadata.

These artifacts sit in `C:\Users\laure\Documents\Glens game audit`, separate from the unchanged game folder. No desktop environment fixes, LoRA conversion, or performance gains are claimed as implemented.
