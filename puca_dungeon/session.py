"""Game session: interpret → ground → resolve → pressure → narrate → image decision."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from puca_dungeon.authored_actions import build_authored_actions
from puca_dungeon.encounters.encounter1 import OPENING_PROSE, make_opening_world, public_perception
from puca_dungeon.ground import ground_intent
from puca_dungeon.image_prompt import image_decision
from puca_dungeon.interpret import HeuristicInterpreter, InterpreterUnavailable, OllamaInterpreter
from puca_dungeon.models import state_diff, world_from_dict
from puca_dungeon.narrate import TemplateNarrator, narrate
from puca_dungeon.pressure import apply_time_and_pressure, maybe_hostile_attack
from puca_dungeon.resolve import resolve
from puca_dungeon.rng import GameRNG


DEBUG_COMMANDS = {
    '/state', '/fullstate', '/perception', '/time', '/rng', '/imageprompt',
    '/save', '/load', '/quit', '/help',
}


@dataclass
class TurnTrace:
    raw_input: str = ''
    debug_command: Optional[str] = None
    interpreter_input: dict = field(default_factory=dict)
    raw_interpreter_output: dict = field(default_factory=dict)
    validated_intent: dict = field(default_factory=dict)
    grounding: dict = field(default_factory=dict)
    resolution: dict = field(default_factory=dict)
    before_state: dict = field(default_factory=dict)
    after_state: dict = field(default_factory=dict)
    state_diff: list = field(default_factory=list)
    pressure: dict = field(default_factory=dict)
    narrator_input: dict = field(default_factory=dict)
    narrator_output: str = ''
    image: dict = field(default_factory=dict)
    visual_backend_calls: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'raw_input': self.raw_input,
            'debug_command': self.debug_command,
            'interpreter_input': self.interpreter_input,
            'raw_interpreter_output': self.raw_interpreter_output,
            'validated_intent': self.validated_intent,
            'grounding': self.grounding,
            'resolution': self.resolution,
            'before_state': self.before_state,
            'after_state': self.after_state,
            'state_diff': self.state_diff,
            'pressure': self.pressure,
            'narrator_input': self.narrator_input,
            'narrator_output': self.narrator_output,
            'image': self.image,
            'visual_backend_calls': self.visual_backend_calls,
            'error': self.error,
        }

    def format_debug(self) -> str:
        intent = self.validated_intent or {}
        lines = [
            '=' * 72,
            f'RAW INPUT: {self.raw_input!r}',
            '',
            '--- B. INTERPRETER INPUT (perception + authored actions) ---',
            json.dumps(self.interpreter_input, indent=2, ensure_ascii=False),
            '',
            '--- C. RAW INTERPRETER OUTPUT ---',
            json.dumps(self.raw_interpreter_output, indent=2, ensure_ascii=False),
            '',
            '--- D. VALIDATED INTENT ---',
            json.dumps(self.validated_intent, indent=2, ensure_ascii=False),
            f"classification={intent.get('classification')}",
            f"matched_action_id={intent.get('matched_action_id')}",
            f"confidence={intent.get('confidence')}",
            f"ambiguities={intent.get('ambiguities')}",
            f"needs_clarification={intent.get('needs_clarification')}",
            '',
            '--- E. ENTITY GROUNDING ---',
            json.dumps(self.grounding, indent=2, ensure_ascii=False),
            '',
            '--- F. PYTHON RESOLUTION ---',
            json.dumps(self.resolution, indent=2, ensure_ascii=False),
            '',
            '--- G. STATE DIFF ---',
        ]
        lines.extend(self.state_diff or ['(no changes)'])
        lines += [
            '',
            '--- H. FICTIONAL TIME / WORLD PRESSURE / GUIDANCE ---',
            json.dumps(self.pressure, indent=2, ensure_ascii=False),
            f"guidance_level (after)={self.after_state.get('guidance_level', self.pressure.get('guidance_after'))}",
            '',
            '--- I. NARRATOR INPUT ---',
            json.dumps(self.narrator_input, indent=2, ensure_ascii=False),
            '',
            '--- J. NARRATOR OUTPUT ---',
            self.narrator_output,
            '',
            '--- K/L. IMAGE ---',
            f"IMAGE DECISION: {self.image.get('decision')}",
            f"REASON: {self.image.get('reason')}",
            f"PROMPT: {self.image.get('full_prompt')}",
            self.image.get('note', 'DEBUG MODE — IMAGE GENERATION SUPPRESSED'),
            f'visual_backend_calls={self.visual_backend_calls}',
            '=' * 72,
        ]
        if self.error:
            lines.append(f'ERROR: {self.error}')
        return '\n'.join(lines)


class GameSession:
    def __init__(self, player_name: str = 'Adventurer', seed: int = 91,
                 interpreter=None, debug: bool = True, narrator=None,
                 allow_heuristic_fallback: bool = False,
                 ollama_model: str = 'mistral'):
        self.debug = debug
        self.rng = GameRNG.from_seed(seed)
        self.world = make_opening_world(player_name)
        self.allow_heuristic_fallback = allow_heuristic_fallback
        self.ollama_model = ollama_model
        if interpreter is not None:
            self.interpreter = interpreter
        else:
            self.interpreter = OllamaInterpreter(model=ollama_model)

        if isinstance(self.interpreter, OllamaInterpreter):
            if not self.interpreter.ping():
                if allow_heuristic_fallback:
                    self.interpreter = HeuristicInterpreter()
                else:
                    raise InterpreterUnavailable(
                        'Ollama is required for interactive dungeon play but is not ready at '
                        'http://127.0.0.1:11434 (service down or model '
                        f'{ollama_model!r} missing). Start Ollama, run `ollama pull {ollama_model}`, '
                        'or pass interpreter=HeuristicInterpreter() for tests, or '
                        '--heuristic / --allow-heuristic-fallback for offline use.'
                    )
        self.narrator = narrator or TemplateNarrator()
        self.visual_backend_calls = 0
        self.last_trace: Optional[TurnTrace] = None
        self.traces: list[TurnTrace] = []
        self.save_path = Path.home() / 'Puca' / 'dungeon-poc.json'
        self.opening_text = OPENING_PROSE

    def concise_state(self) -> dict:
        w = self.world
        boxes = {
            k: {
                'open': b.open, 'locked': b.locked, 'destroyed': b.destroyed,
                'trap_discovered': b.trap_discovered, 'trap_disabled': b.trap_disabled,
                'trap_fired': b.trap_fired, 'hp': b.hp,
            }
            for k, b in w.boxes.items()
        }
        return {
            'encounter': w.encounter,
            'player.location': w.player.location,
            'player.hp': w.player.hp,
            'player.gold': w.player.gold,
            'player.alive': w.player.alive,
            'player.inventory': list(w.player.inventory),
            'player.knowledge': list(w.player.knowledge),
            'clue_get_no_mess': w.clue_get_no_mess,
            'boxes': boxes,
            'world_time_seconds': w.world_time_seconds,
            'stall_time_seconds': w.stall_time_seconds,
            'guidance_level': w.guidance_level,
            'pursuer': {
                'state': w.pursuer.state, 'location': w.pursuer.location,
                'disposition': w.pursuer.disposition, 'hp': w.pursuer.hp,
            },
            'visible_entities': list(w.visible_entities),
            'last_image_prompt': w.last_image_prompt,
            'rng_seed': self.rng.seed,
            'turn_index': w.turn_index,
        }

    def full_state(self) -> dict:
        return {'world': self.world.to_dict(), 'rng': self.rng.snapshot(), 'debug': self.debug}

    def handle_debug_command(self, text: str) -> str:
        cmd, _, arg = text.strip().partition(' ')
        cmd = cmd.lower()
        if cmd == '/help':
            return 'Commands: ' + ', '.join(sorted(DEBUG_COMMANDS))
        if cmd == '/state':
            return json.dumps(self.concise_state(), indent=2, ensure_ascii=False)
        if cmd == '/fullstate':
            return json.dumps(self.full_state(), indent=2, default=str, ensure_ascii=False)
        if cmd == '/perception':
            return json.dumps(public_perception(self.world), indent=2, ensure_ascii=False)
        if cmd == '/time':
            return json.dumps({
                'world_time_seconds': self.world.world_time_seconds,
                'stall_time_seconds': self.world.stall_time_seconds,
                'pursuer_state': self.world.pursuer.state,
                'guidance_level': self.world.guidance_level,
            }, indent=2)
        if cmd == '/rng':
            return json.dumps({'seed': self.rng.seed, 'turn_index': self.world.turn_index}, indent=2)
        if cmd == '/imageprompt':
            return self.world.last_image_prompt or '(none yet)'
        if cmd == '/save':
            path = Path(arg) if arg else self.save_path
            self.save(path)
            return f'Saved to {path}'
        if cmd == '/load':
            path = Path(arg) if arg else self.save_path
            self.load(path)
            return f'Loaded {path}'
        if cmd == '/quit':
            return '__QUIT__'
        return f'Unknown debug command: {cmd}'

    def submit(self, text: str) -> TurnTrace:
        text = (text or '').strip()
        trace = TurnTrace(raw_input=text)

        if self.debug and text.startswith('/'):
            trace.debug_command = text.split()[0].lower()
            out = self.handle_debug_command(text)
            trace.narrator_output = out
            self.last_trace = trace
            self.traces.append(trace)
            return trace

        before = self.concise_state()
        perception = public_perception(self.world)
        # Ensure no hidden leakage markers in perception
        assert 'trap_present' not in json.dumps(perception)
        assert 'pursuer_trigger' not in json.dumps(perception)

        authored = build_authored_actions(self.world)
        trace.interpreter_input = {
            'player_text': text,
            'perception': perception,
            'authored_actions': authored,
        }

        try:
            raw_out, intent = self.interpreter.interpret(text, perception, authored_actions=authored)
        except InterpreterUnavailable as exc:
            if self.allow_heuristic_fallback:
                raw_out, intent = HeuristicInterpreter().interpret(text, perception, authored_actions=authored)
                trace.error = f'ollama_unavailable_fallback_heuristic: {exc}'
            else:
                raise

        trace.raw_interpreter_output = raw_out
        trace.validated_intent = intent.to_dict()

        grounding = ground_intent(intent, self.world)
        trace.grounding = grounding.to_dict()

        resolution = resolve(self.world, intent, grounding, self.rng)
        pressure = apply_time_and_pressure(self.world, intent, resolution)
        maybe_hostile_attack(self.world, intent, resolution, self.rng)
        trace.pressure = pressure
        trace.resolution = resolution.to_dict()

        narrator_in, prose = narrate(
            self.world, resolution, text,
            intent=trace.validated_intent,
            narrator=self.narrator,
        )
        trace.narrator_input = narrator_in
        trace.narrator_output = prose

        img = image_decision(self.world, resolution)
        # Debug mode never calls visual generator
        trace.image = img
        trace.visual_backend_calls = self.visual_backend_calls

        self.world.turn_index += 1
        after = self.concise_state()
        trace.before_state = before
        trace.after_state = after
        trace.state_diff = state_diff(before, after)

        self.last_trace = trace
        self.traces.append(trace)
        return trace

    def save(self, path: Optional[Path] = None) -> None:
        path = Path(path or self.save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'version': 1,
            'world': self.world.to_dict(),
            'rng': self.rng.snapshot(),
            'debug': self.debug,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding='utf-8')

    def load(self, path: Optional[Path] = None) -> None:
        path = Path(path or self.save_path)
        payload = json.loads(path.read_text(encoding='utf-8'))
        self.world = world_from_dict(payload['world'])
        self.rng = GameRNG.restore(payload['rng'])
        self.debug = bool(payload.get('debug', self.debug))


def _json_default(obj):
    if isinstance(obj, tuple):
        return list(obj)
    raise TypeError(type(obj))
