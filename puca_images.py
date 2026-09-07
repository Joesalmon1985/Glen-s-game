"""Optional local image generation: lazy imports, FP16, CPU offload and disk cache."""
import hashlib
import json
from pathlib import Path

BASE_MODEL = 'stable-diffusion-v1-5/stable-diffusion-v1-5'
STEPS = 20
BAKEOFF_STEPS = 28
STYLE = 'pixel art, limited palette, clear silhouette, gentle eerie fantasy, no lettering'
DEFAULT_NEGATIVE = (
    'photorealistic, blurry, text, watermark, explicit, gore, '
    'noise, static, grain, dithering, multiple subjects, wrong subject, animal, bird'
)


class ImageGenerator:
    def __init__(self, cache_dir, lora_folder, use_lora=True):
        self.cache_dir = Path(cache_dir)
        self.lora_folder = Path(lora_folder)
        self.use_lora = use_lora
        self.pipe = None
        self.torch = None
        self.adapter_loaded = False
        self._adapter_hash = None

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

    def key(self, location, prompt, negative_prompt=None, seed=None):
        weights = self.lora_folder / 'adapter_model.safetensors'
        config_file = self.lora_folder / 'adapter_config.json'
        if self.use_lora and (not weights.is_file() or not config_file.is_file()):
            raise RuntimeError('Pixel adapter files are missing. Disable the pixel adapter to use base art.')
        if self._adapter_hash is None:
            self._adapter_hash = hashlib.sha256(weights.read_bytes() + config_file.read_bytes()).hexdigest() if self.use_lora else 'base'
        neg = negative_prompt if negative_prompt is not None else DEFAULT_NEGATIVE
        config = [
            BASE_MODEL, STYLE, location, prompt, self._adapter_hash, 0.7, STEPS, 512, 'dpm++-v1',
            neg, seed if seed is not None else 'auto',
        ]
        return hashlib.sha256(json.dumps(config).encode()).hexdigest()

    def _load_pipeline(self):
        try:
            import torch
            from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler
            import accelerate  # noqa: F401
        except ImportError as exc:
            raise RuntimeError('Illustrations need the image dependencies. Run install.bat, or continue with images off.') from exc
        if not torch.version.cuda:
            raise RuntimeError('This Python has CPU-only PyTorch. Run install.bat and launch.bat; the story remains playable with images off.')
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA is unavailable. Check your NVIDIA driver, or play with images off.')
        self.torch = torch
        pipe = StableDiffusionPipeline.from_pretrained(BASE_MODEL, torch_dtype=torch.float16, variant='fp16', use_safetensors=True)
        try:
            if self.use_lora:
                from peft import PeftModel
                from peft.tuners.lora import LoraLayer
                if not (self.lora_folder / 'adapter_config.json').is_file():
                    raise RuntimeError('The pixel-style adapter is missing. Disable the adapter to use base art.')
                wrapped = PeftModel.from_pretrained(pipe.unet, str(self.lora_folder), adapter_name='pixel', is_trainable=False)
                layers = [m for m in wrapped.modules() if isinstance(m, LoraLayer)]
                if not layers or 'pixel' not in wrapped.peft_config:
                    raise RuntimeError('Pixel adapter did not attach. Base art was not silently substituted.')
                for layer in layers:
                    layer.set_scale('pixel', 0.7)
                pipe.unet = wrapped.merge_and_unload(safe_merge=True)
                self.adapter_loaded = True
            pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
            for component in [pipe.unet, pipe.text_encoder, pipe.vae]:
                if next(component.parameters()).dtype != torch.float16:
                    component.to(dtype=torch.float16)
                if next(component.parameters()).dtype != torch.float16:
                    raise RuntimeError('Image component did not use FP16.')
            # PyTorch's efficient attention is retained. No forced attention slicing.
            # Do NOT move the pipeline to CUDA before installing offload hooks.
            pipe.enable_model_cpu_offload()
            self.pipe = pipe
        except Exception:
            del pipe
            torch.cuda.empty_cache()
            raise

    def release_gpu(self):
        if self.pipe is not None:
            # Diffusers offloads its last active component via the pipeline hook.
            self.pipe.maybe_free_model_hooks()
        if self.torch is not None and self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()

    def generate(self, location, prompt, cancel=None, progress=None, negative_prompt=None, seed=None, steps=None):
        neg = negative_prompt if negative_prompt is not None else DEFAULT_NEGATIVE
        use_steps = int(steps) if steps is not None else STEPS
        key = self.key(location, prompt, negative_prompt=neg, seed=seed)
        # Include steps in on-disk key path via location tag already; also salt cache file
        destination = self.cache_dir / (key + (f'_s{use_steps}' if use_steps != STEPS else '') + '.png')
        if destination.is_file():
            if self.valid_image(destination):
                return key, destination
            destination.unlink()
        if cancel and cancel.is_set():
            raise RuntimeError('Illustration cancelled')
        if self.pipe is None:
            self._load_pipeline()
        if cancel and cancel.is_set():
            self.release_gpu()
            raise RuntimeError('Illustration cancelled')
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        def callback(pipe, index, timestep, kwargs):
            if cancel and cancel.is_set():
                raise RuntimeError('Illustration cancelled')
            if progress:
                progress(index + 1, use_steps)
            return kwargs
        try:
            use_seed = int(seed) if seed is not None else int(key[:8], 16)
            with self.torch.inference_mode():
                result = self.pipe(prompt=f'{STYLE}, {prompt}',
                                   negative_prompt=neg,
                                   width=512, height=512, num_inference_steps=use_steps, guidance_scale=7.5,
                                   generator=self.torch.Generator(device='cpu').manual_seed(use_seed),
                                   callback_on_step_end=callback)
            if cancel and cancel.is_set():
                raise RuntimeError('Illustration cancelled')
            if getattr(result, 'nsfw_content_detected', None) and any(result.nsfw_content_detected):
                raise RuntimeError('Illustration was filtered. The story can continue without it.')
            temp = destination.with_suffix('.tmp.png')
            try:
                result.images[0].save(temp)
                temp.replace(destination)
            finally:
                temp.unlink(missing_ok=True)
            return key, destination
        finally:
            self.release_gpu()
