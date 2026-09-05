"""No downloads or inference: assert the real library's loading configuration."""
import pytest
from unittest.mock import Mock, patch

torch = pytest.importorskip('torch')
diffusers = pytest.importorskip('diffusers')
from puca_images import ImageGenerator

def test_fp16_weight_variant_is_requested(tmp_path):
    gen = ImageGenerator(tmp_path, tmp_path / 'lora', use_lora=False)
    pipe = Mock()
    pipe.scheduler.config = {}
    for name in ('unet', 'text_encoder', 'vae'):
        setattr(pipe, name, torch.nn.Linear(1, 1, dtype=torch.float16))
    with patch.object(diffusers.StableDiffusionPipeline, 'from_pretrained', return_value=pipe) as load, patch.object(torch.cuda, 'is_available', return_value=True):
        gen._load_pipeline()
    assert load.call_args.kwargs.get('variant') == 'fp16'
    pipe.enable_model_cpu_offload.assert_called_once()
