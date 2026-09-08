"""Optional local image generation: lazy imports, FP16, CPU offload and disk cache."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

BASE_MODEL = 'stable-diffusion-v1-5/stable-diffusion-v1-5'
STEPS = 20
STYLE = 'pixel art, limited palette, clear silhouette, gentle eerie fantasy, no lettering'
MAX_PROMPT_CHARS = 900


class IllustrationCancelled(Exception):
    """Player skipped or replaced an in-flight illustration."""


class ImageGenerator:
    def __init__(self, cache_dir, lora_folder, use_lora=True):
        self.cache_dir = Path(cache_dir)
        self.lora_folder = Path(lora_folder)
        self.use_lora = use_lora
        self.pipe = None
        self.torch = None
        self.adapter_loaded = False
        self._adapter_hash = None
        self._loaded_with_lora = None

    @staticmethod
    def valid_image(path):
        try:
            from PIL import Image
            with Image.open(path) as image:
                if image.format != 'PNG' or image.size != (512, 512):
                    return False
                image.verify()
            return True
        except (OSError, ValueError, ImportError):
            return False

    def key(self, location, prompt):
        weights = self.lora_folder / 'adapter_model.safetensors'
        config_file = self.lora_folder / 'adapter_config.json'
        want_lora = bool(self.use_lora and weights.is_file() and config_file.is_file())
        if self.use_lora and not want_lora:
            # Soft: fall back to base art instead of hard-failing the whole turn.
            self.use_lora = False
            want_lora = False
        if self._adapter_hash is None or self._loaded_with_lora != want_lora:
            self._adapter_hash = (
                hashlib.sha256(weights.read_bytes() + config_file.read_bytes()).hexdigest()
                if want_lora else 'base'
            )
        prompt = self._normalize_prompt(prompt)
        config = [BASE_MODEL, STYLE, location, prompt, self._adapter_hash, 0.7, STEPS, 512, 'dpm++-v2']
        return hashlib.sha256(json.dumps(config).encode()).hexdigest()

    @staticmethod
    def _normalize_prompt(prompt: str) -> str:
        text = re.sub(r'\s+', ' ', (prompt or '').strip())
        # Avoid duplicating the style prefix when callers already included it.
        style_head = STYLE.split(',')[0].lower()
        if text.lower().startswith(style_head):
            # Strip a leading full STYLE copy if present.
            if text.lower().startswith(STYLE.lower()):
                text = text[len(STYLE):].lstrip(' ,')
            else:
                # Leave partial style wording; pipe will still prefix STYLE once.
                pass
        if len(text) > MAX_PROMPT_CHARS:
            text = text[: MAX_PROMPT_CHARS - 1].rsplit(' ', 1)[0] + '…'
        return text

    def _load_pipeline(self):
        try:
            import torch
            from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler
            import accelerate  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                'Illustrations need the image dependencies. Run install.bat, or turn Illustrations off.'
            ) from exc
        if not torch.version.cuda:
            raise RuntimeError(
                'This Python has CPU-only PyTorch. Run install.bat, or turn Illustrations off.'
            )
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA is unavailable. Check your NVIDIA driver, or turn Illustrations off.')
        self.torch = torch
        pipe = StableDiffusionPipeline.from_pretrained(
            BASE_MODEL, torch_dtype=torch.float16, variant='fp16', use_safetensors=True,
        )
        try:
            # Local single-player art: facility scenes (bed/cup/body) trip the default checker.
            pipe.safety_checker = None
            if hasattr(pipe, 'requires_safety_checker'):
                pipe.requires_safety_checker = False

            want_lora = bool(
                self.use_lora
                and (self.lora_folder / 'adapter_model.safetensors').is_file()
                and (self.lora_folder / 'adapter_config.json').is_file()
            )
            if want_lora:
                from peft import PeftModel
                from peft.tuners.lora import LoraLayer
                wrapped = PeftModel.from_pretrained(
                    pipe.unet, str(self.lora_folder), adapter_name='pixel', is_trainable=False,
                )
                layers = [m for m in wrapped.modules() if isinstance(m, LoraLayer)]
                if not layers or 'pixel' not in wrapped.peft_config:
                    raise RuntimeError('Pixel adapter did not attach. Disable the pixel adapter and retry.')
                for layer in layers:
                    layer.set_scale('pixel', 0.7)
                pipe.unet = wrapped.merge_and_unload(safe_merge=True)
                self.adapter_loaded = True
            else:
                self.use_lora = False
                self.adapter_loaded = False

            pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
            for component in [pipe.unet, pipe.text_encoder, pipe.vae]:
                if next(component.parameters()).dtype != torch.float16:
                    component.to(dtype=torch.float16)
                if next(component.parameters()).dtype != torch.float16:
                    raise RuntimeError('Image component did not use FP16.')
            # Prefer offload; enable attention slicing as a VRAM safety net.
            try:
                pipe.enable_attention_slicing()
            except Exception:
                pass
            pipe.enable_model_cpu_offload()
            self.pipe = pipe
            self._loaded_with_lora = want_lora
        except Exception:
            del pipe
            torch.cuda.empty_cache()
            raise

    def release_gpu(self):
        if self.pipe is not None:
            try:
                self.pipe.maybe_free_model_hooks()
            except Exception:
                pass
        if self.torch is not None and self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()

    def _ensure_pipeline(self, cancel=None):
        want_lora = bool(
            self.use_lora
            and (self.lora_folder / 'adapter_model.safetensors').is_file()
            and (self.lora_folder / 'adapter_config.json').is_file()
        )
        if self.pipe is not None and self._loaded_with_lora != want_lora:
            self.pipe = None
            self.release_gpu()
        if self.pipe is None:
            if cancel and cancel.is_set():
                raise IllustrationCancelled()
            self._load_pipeline()

    def generate(self, location, prompt, cancel=None, progress=None):
        prompt = self._normalize_prompt(prompt)
        key = self.key(location, prompt)
        destination = self.cache_dir / (key + '.png')
        if destination.is_file():
            if self.valid_image(destination):
                return key, destination
            destination.unlink(missing_ok=True)
        if cancel and cancel.is_set():
            raise IllustrationCancelled()
        self._ensure_pipeline(cancel=cancel)
        if cancel and cancel.is_set():
            self.release_gpu()
            raise IllustrationCancelled()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        def callback(pipe, index, timestep, kwargs):
            if cancel and cancel.is_set():
                raise IllustrationCancelled()
            if progress:
                progress(index + 1, STEPS)
            return kwargs

        try:
            seed = int(key[:8], 16)
            full_prompt = f'{STYLE}, {prompt}' if prompt else STYLE
            try:
                with self.torch.inference_mode():
                    result = self.pipe(
                        prompt=full_prompt,
                        negative_prompt='photorealistic, blurry, text, watermark, explicit, gore',
                        width=512,
                        height=512,
                        num_inference_steps=STEPS,
                        guidance_scale=7.0,
                        generator=self.torch.Generator(device='cpu').manual_seed(seed),
                        callback_on_step_end=callback,
                    )
            except IllustrationCancelled:
                raise
            except RuntimeError as exc:
                message = str(exc).lower()
                if 'out of memory' in message or 'cuda' in message and 'memory' in message:
                    self.release_gpu()
                    raise RuntimeError(
                        'Illustration ran out of GPU memory. Turn Illustrations off, or close other GPU apps.'
                    ) from exc
                raise
            if cancel and cancel.is_set():
                raise IllustrationCancelled()
            image = result.images[0]
            temp = destination.with_suffix('.tmp.png')
            try:
                image.save(temp)
                temp.replace(destination)
            finally:
                temp.unlink(missing_ok=True)
            return key, destination
        except IllustrationCancelled:
            logging.info('Illustration cancelled')
            raise
        finally:
            self.release_gpu()
