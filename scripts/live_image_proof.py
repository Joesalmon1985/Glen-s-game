"""Real SD1.5 + supplied PEFT adapter GPU proof. No synthetic outputs."""
from pathlib import Path
import json
import sys
import time
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
import torch
from puca_images import ImageGenerator, BASE_MODEL, STEPS

out = root / 'docs' / 'verification'
out.mkdir(parents=True, exist_ok=True)
gen = ImageGenerator(out / 'images', root / 'pixel_style_lora_style_only', use_lora=True)
torch.cuda.reset_peak_memory_stats()
start = time.monotonic()
try:
    key, image = gen.generate('old_bridge', 'An old mossy stone bridge over a silver stream at twilight, a small lantern beside the path, dark fairy tale woodland')
    result = {'success': True, 'GPU':torch.cuda.get_device_name(), 'total_vram_bytes':torch.cuda.get_device_properties(0).total_memory,
              'base_model':BASE_MODEL, 'steps':STEPS, 'image':str(image), 'adapter_loaded':gen.adapter_loaded,
              'component_dtypes':{name:str(next(getattr(gen.pipe,name).parameters()).dtype) for name in ('unet','text_encoder','vae')},
              'peak_allocated_bytes':torch.cuda.max_memory_allocated(), 'peak_reserved_bytes':torch.cuda.max_memory_reserved(),
              'allocated_after_handoff_bytes':torch.cuda.memory_allocated(), 'seconds_including_first_download':time.monotonic()-start}
    assert result['adapter_loaded'], 'Adapter did not attach'
    assert ImageGenerator.valid_image(image), 'Invalid generated PNG'
except Exception as exc:
    result = {'success':False, 'error':repr(exc), 'seconds':time.monotonic()-start}
    (out / 'gpu.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    raise
(out / 'gpu.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2), flush=True)
