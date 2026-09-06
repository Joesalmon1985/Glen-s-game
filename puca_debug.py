"""Turn debug traces for command → narrator → engine → image payload."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path

from puca_images import BASE_MODEL, STEPS, STYLE

NEGATIVE_PROMPT = 'photorealistic, blurry, text, watermark, explicit, gore'


@dataclass
class TurnDebug:
    player_command: str = ''
    action_source: str = 'typed'
    options_available_at_submit: list = field(default_factory=list)
    sent_to_narrator: dict = field(default_factory=dict)
    interpretation: dict = field(default_factory=dict)
    sent_to_game_engine: dict = field(default_factory=dict)
    sent_to_image_generation: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    def format_text(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def scene_as_dict(scene):
    return {
        'narration': scene.narration,
        'event': scene.event,
        'spirit': scene.spirit,
        'image_prompt': scene.image_prompt,
        'location': scene.location,
        'choices': list(scene.choices),
        'facts': list(scene.facts),
        'visual_changed': scene.visual_changed,
    }


def narrator_request_meta(url, body):
    system = body.get('system') or ''
    prompt = body.get('prompt') or ''
    try:
        context = json.loads(prompt) if isinstance(prompt, str) else prompt
    except (TypeError, ValueError, json.JSONDecodeError):
        context = prompt
    fmt = body.get('format') or {}
    return {
        'url': url,
        'model': body.get('model'),
        'system_sha256': hashlib.sha256(system.encode('utf-8')).hexdigest()[:16],
        'system_chars': len(system),
        'prompt_context': context,
        'format_required': fmt.get('required'),
        'options': body.get('options'),
        'keep_alive': body.get('keep_alive'),
        'stream': body.get('stream'),
    }


def image_payload(location, prompt, *, use_lora, need_image, reasons, images_enabled, cancelled=False,
                  cache_key='', cache_hit=False, generated=False):
    full_prompt = f'{STYLE}, {prompt}' if prompt else STYLE
    status = 'would_generate'
    if not images_enabled:
        status = 'skipped_illustrations_off'
    elif cancelled:
        status = 'skipped_cancelled'
    elif not need_image:
        status = 'skipped_not_needed'
    elif cache_hit:
        status = 'cache_hit'
    elif generated:
        status = 'generated'
    return {
        'status': status,
        'need_image': need_image,
        'reasons': list(reasons),
        'location': location,
        'image_prompt': prompt,
        'full_prompt': full_prompt,
        'negative_prompt': NEGATIVE_PROMPT,
        'base_model': BASE_MODEL,
        'style': STYLE,
        'width': 512,
        'height': 512,
        'steps': STEPS,
        'guidance_scale': 7.0,
        'lora_enabled': use_lora,
        'lora_scale': 0.7 if use_lora else 0.0,
        'cache_key': cache_key,
        'seed_from_key_prefix': int(cache_key[:8], 16) if cache_key and len(cache_key) >= 8 else None,
    }


def write_last_turn(path, turn_debug):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(turn_debug.to_dict(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
