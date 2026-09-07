"""Ollama multimodal vision judge for sprites and composed scenes."""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from puca_dungeon.interpret import ollama_model_ready, ollama_reachable
from scripts.redteam.findings import Finding

DEFAULT_VISION_MODEL = 'llava'
DEFAULT_OLLAMA_CHAT = 'http://127.0.0.1:11434/api/chat'
FAIL_OVERALL = 6.0

ASSET_RUBRIC_KEYS = (
    'style_match',
    'silhouette_clarity',
    'subject_correctness',
    'isolation',
    'no_text_watermark',
    'bg_emptiness',
    'overall',
)

COMPOSITION_RUBRIC_KEYS = (
    'readability',
    'placement',
    'occlusion',
    'style_coherence',
    'overall',
)


@dataclass
class VisionScore:
    target: str
    kind: str  # asset | composition
    ok: bool
    scores: dict[str, float] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)
    why: str = ''
    slot_nudges: dict[str, list[int]] = field(default_factory=dict)
    skipped: bool = False
    error: str = ''
    findings: list[Finding] = field(default_factory=list)
    raw: str = ''

    def to_dict(self) -> dict:
        return {
            'target': self.target,
            'kind': self.kind,
            'ok': self.ok,
            'scores': self.scores,
            'flags': self.flags,
            'why': self.why,
            'slot_nudges': self.slot_nudges,
            'skipped': self.skipped,
            'error': self.error,
            'findings': [f.to_dict() for f in self.findings],
        }


def _encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode('ascii')


def _extract_json(text: str) -> Optional[dict]:
    text = (text or '').strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class VisionJudge:
    def __init__(
        self,
        model: str = DEFAULT_VISION_MODEL,
        url: str = DEFAULT_OLLAMA_CHAT,
        timeout: float = 120.0,
        enabled: bool = True,
    ):
        self.model = model
        self.url = url
        self.timeout = timeout
        self.enabled = enabled
        self._available: Optional[bool] = None

    def available(self) -> bool:
        if not self.enabled:
            return False
        if self._available is None:
            tags = self.url.rsplit('/api/', 1)[0] + '/api/tags'
            self._available = bool(
                ollama_reachable(url=tags, timeout=2.0)
                and ollama_model_ready(self.model, url=tags, timeout=2.0)
            )
        return self._available

    def _chat(self, prompt: str, image_path: Path) -> str:
        payload = {
            'model': self.model,
            'stream': False,
            'format': 'json',
            'messages': [
                {
                    'role': 'user',
                    'content': prompt,
                    'images': [_encode_image(image_path)],
                }
            ],
        }
        data = json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(
            self.url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode('utf-8'))
        message = body.get('message') if isinstance(body, dict) else None
        if isinstance(message, dict):
            return str(message.get('content') or '')
        return str(body.get('response') or '')

    def score_asset(
        self,
        path: Path,
        *,
        sprite_id: str,
        kind: str,
        prompt: str,
    ) -> VisionScore:
        if not self.available():
            return VisionScore(
                target=sprite_id,
                kind='asset',
                ok=True,
                skipped=True,
                error='vision_skipped: ollama/model unavailable',
            )
        if not path.is_file():
            finding = Finding(
                severity='P0',
                layer='sprite_vision',
                persona='vision_judge',
                passage_id=0,
                utterance=sprite_id,
                detail='Cannot vision-score missing file',
                invariant='asset_exists',
                extra={'sprite_id': sprite_id},
            )
            return VisionScore(sprite_id, 'asset', False, findings=[finding], error='missing')

        instruction = (
            'You are a strict pixel-art QA judge for a grim institutional fantasy game.\n'
            f'Sprite id: {sprite_id}\nKind: {kind}\nIntended subject: {prompt}\n'
            'Score each field 0-10. Also set boolean flags.\n'
            'Return ONLY JSON with keys: '
            'style_match, silhouette_clarity, subject_correctness, isolation, '
            'no_text_watermark (bool true if NO text), bg_emptiness (for backgrounds; '
            'props/characters may set 10), overall, why (short), '
            'critical_subject_fail (bool), critical_text_fail (bool).\n'
            'For props/characters, isolation means single subject on clean transparent/magenta field usable as an overlay.\n'
            'For backgrounds, bg_emptiness means no people and no floating inventory props.'
        )
        try:
            raw = self._chat(instruction, path)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return VisionScore(
                target=sprite_id,
                kind='asset',
                ok=True,
                skipped=True,
                error=f'vision_error: {exc}',
            )

        data = _extract_json(raw) or {}
        scores = {k: _num(data.get(k), 0.0) for k in ASSET_RUBRIC_KEYS if k != 'overall'}
        scores['overall'] = _num(data.get('overall'), 0.0)
        flags = {
            'critical_subject_fail': bool(data.get('critical_subject_fail')),
            'critical_text_fail': bool(data.get('critical_text_fail')),
            'no_text_watermark': bool(data.get('no_text_watermark', True)),
        }
        why = str(data.get('why') or '')
        findings: list[Finding] = []
        overall = scores.get('overall', 0.0)
        if flags['critical_subject_fail'] or scores.get('subject_correctness', 10) < 4:
            findings.append(Finding(
                severity='P1',
                layer='sprite_vision',
                persona='vision_judge',
                passage_id=0,
                utterance=sprite_id,
                detail=f'subject_correctness fail: {why or "wrong subject"}',
                invariant='subject_correctness',
                extra={'scores': scores},
            ))
        if flags['critical_text_fail'] or flags.get('no_text_watermark') is False:
            findings.append(Finding(
                severity='P1',
                layer='sprite_vision',
                persona='vision_judge',
                passage_id=0,
                utterance=sprite_id,
                detail=f'text/watermark detected: {why}',
                invariant='no_text_watermark',
                extra={'scores': scores},
            ))
        if overall < FAIL_OVERALL:
            sev = 'P1' if overall < 4 else 'P2'
            findings.append(Finding(
                severity=sev,
                layer='sprite_vision',
                persona='vision_judge',
                passage_id=0,
                utterance=sprite_id,
                detail=f'overall={overall:.1f} < {FAIL_OVERALL}: {why}',
                invariant='vision_overall',
                extra={'scores': scores},
            ))
        elif scores.get('style_match', 10) < 5:
            findings.append(Finding(
                severity='P2',
                layer='sprite_vision',
                persona='vision_judge',
                passage_id=0,
                utterance=sprite_id,
                detail=f'weak style_match={scores.get("style_match")}: {why}',
                invariant='style_match',
                extra={'scores': scores},
            ))

        return VisionScore(
            target=sprite_id,
            kind='asset',
            ok=len(findings) == 0,
            scores=scores,
            flags=flags,
            why=why,
            findings=findings,
            raw=raw,
        )

    def score_composition(
        self,
        path: Path,
        *,
        fixture_id: str,
        room_id: str,
        layer_summary: str,
    ) -> VisionScore:
        if not self.available():
            return VisionScore(
                target=fixture_id,
                kind='composition',
                ok=True,
                skipped=True,
                error='vision_skipped: ollama/model unavailable',
            )
        if not path.is_file():
            finding = Finding(
                severity='P0',
                layer='sprite_vision',
                persona='vision_judge',
                passage_id=0,
                utterance=fixture_id,
                detail='Cannot vision-score missing composed scene',
                invariant='compose_exists',
                extra={'room_id': room_id},
            )
            return VisionScore(fixture_id, 'composition', False, findings=[finding], error='missing')

        instruction = (
            'You are a strict layout QA judge for a 512x512 pixel-art facility room scene.\n'
            f'Room: {room_id}\nFixture: {fixture_id}\nLayers: {layer_summary}\n'
            'Score 0-10. Return ONLY JSON with keys: readability, placement, occlusion, '
            'style_coherence, overall, why (short), '
            'slot_nudges (object mapping slot names like player/staff_0 to [dx,dy] integer pixel nudges; '
            'empty object if fine).\n'
            'Flag unreadable or badly placed scenes with low overall.'
        )
        try:
            raw = self._chat(instruction, path)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return VisionScore(
                target=fixture_id,
                kind='composition',
                ok=True,
                skipped=True,
                error=f'vision_error: {exc}',
            )

        data = _extract_json(raw) or {}
        scores = {k: _num(data.get(k), 0.0) for k in COMPOSITION_RUBRIC_KEYS}
        why = str(data.get('why') or '')
        nudges_raw = data.get('slot_nudges') if isinstance(data.get('slot_nudges'), dict) else {}
        nudges: dict[str, list[int]] = {}
        for key, value in nudges_raw.items():
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                nudges[str(key)] = [int(value[0]), int(value[1])]
        findings: list[Finding] = []
        overall = scores.get('overall', 0.0)
        if overall < FAIL_OVERALL:
            sev = 'P1' if overall < 4 or scores.get('readability', 10) < 4 else 'P2'
            findings.append(Finding(
                severity=sev,
                layer='sprite_vision',
                persona='vision_judge',
                passage_id=0,
                utterance=fixture_id,
                detail=f'composition overall={overall:.1f}: {why}',
                invariant='composition_overall',
                extra={'room_id': room_id, 'scores': scores, 'slot_nudges': nudges},
            ))
        if scores.get('occlusion', 10) < 4:
            findings.append(Finding(
                severity='P1',
                layer='sprite_vision',
                persona='vision_judge',
                passage_id=0,
                utterance=fixture_id,
                detail=f'bad occlusion={scores.get("occlusion")}: {why}',
                invariant='occlusion',
                extra={'room_id': room_id, 'scores': scores},
            ))

        return VisionScore(
            target=fixture_id,
            kind='composition',
            ok=len(findings) == 0,
            scores=scores,
            why=why,
            slot_nudges=nudges,
            findings=findings,
            raw=raw,
        )
