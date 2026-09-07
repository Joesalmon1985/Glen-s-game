"""Shorter live Ollama smoke for critical phrases (keeps model warm)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from puca_dungeon.interpret import OllamaInterpreter, ollama_reachable
from puca_dungeon.narrate import TemplateNarrator
from puca_dungeon.session import GameSession

OUT = ROOT / 'tests' / 'traces' / 'trace_d_ollama_human_debug.txt'

# Critical subset + a few more from the human script
ACTIONS = [
    'grab one of the boxes and shake it',
    'hit the box',
    'how many boxes are there?',
    'grab the box with my name on it and open it',
    'do a cartwheel',
    'asdfgh',
    'press X',
    'look at the boxes closely',
]


def main() -> int:
    if not ollama_reachable():
        print('Ollama not reachable', file=sys.stderr)
        return 2
    session = GameSession(
        player_name='Glen', seed=91, debug=True,
        interpreter=OllamaInterpreter(model='mistral'),
        narrator=TemplateNarrator(),
    )
    lines = [
        '# Trace: trace_d_ollama_human_debug',
        'seed=91',
        'interpreter=OllamaInterpreter',
        '',
        'OPENING',
        session.opening_text,
        '',
    ]
    summaries = []
    for i, action in enumerate(ACTIONS, 1):
        print(f'[{i}/{len(ACTIONS)}] {action!r} ...', flush=True)
        t0 = time.time()
        tr = session.submit(action)
        dt = time.time() - t0
        summary = {
            'input': action,
            'classification': tr.validated_intent.get('classification'),
            'matched_action_id': tr.validated_intent.get('matched_action_id'),
            'action_class': tr.validated_intent.get('action_class'),
            'clarification': tr.resolution.get('needs_clarification'),
            'guidance': session.world.guidance_level,
            'stall_delta': tr.pressure.get('stall_delta'),
            'seconds': round(dt, 1),
        }
        summaries.append(summary)
        print(f'  -> {summary}', flush=True)
        lines.append(f'> {action}')
        lines.append(tr.narrator_output)
        lines.append('')
        lines.append(tr.format_debug())
        lines.append('')
    lines.append(f'visual_backend_calls_total={session.visual_backend_calls}')
    lines.append('')
    lines.append('# SUMMARY')
    for s in summaries:
        lines.append(str(s))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text('\n'.join(lines), encoding='utf-8')
    print('Wrote', OUT)

    # Soft DoD checks
    by_input = {s['input']: s for s in summaries}
    assert by_input['grab one of the boxes and shake it']['matched_action_id'] != 'box.damage'
    assert by_input['grab one of the boxes and shake it']['clarification'] is True
    assert by_input['hit the box']['clarification'] is True
    assert by_input['how many boxes are there?']['classification'] == 'PERCEPTION_QUERY'
    assert by_input['grab the box with my name on it and open it']['matched_action_id'] == 'box.unlock.player'
    assert by_input['do a cartwheel']['classification'] in ('SYSTEMIC_ACTION', 'GENERAL_WORLD_ACTION')
    assert by_input['asdfgh']['classification'] == 'UNINTERPRETABLE'
    assert by_input['asdfgh']['stall_delta'] == 0
    assert 'dungeon accepts the attempt' not in OUT.read_text().lower()
    assert session.visual_backend_calls == 0
    print('Live Ollama DoD checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
