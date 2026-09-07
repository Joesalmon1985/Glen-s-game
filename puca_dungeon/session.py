"""Game session: discourse → interpret → ground → resolve → world_react → narrate → image."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from puca_dungeon import discourse, engine_leak, world_react
from puca_dungeon.authored_actions import build_authored_actions
from puca_dungeon.content_loader import get_passage
from puca_dungeon.ff_rules import make_adventure_sheet
from puca_dungeon.ground import ground_intent
from puca_dungeon.image_prompt import image_decision
from puca_dungeon.interpret import HeuristicInterpreter, InterpreterUnavailable, OllamaInterpreter, normalize_intent
from puca_dungeon.models import Intent, public_perception, state_diff, world_from_dict, WorldState
from puca_dungeon.narrate import TemplateNarrator, narrate
from puca_dungeon.pressure import apply_guidance
from puca_dungeon.resolve import Resolution, resolve
from puca_dungeon.rng import GameRNG


DEBUG_COMMANDS = {
    '/state', '/sheet', '/passage', '/fullstate', '/perception', '/help',
    '/save', '/load', '/quit', '/rng', '/imageprompt',
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
    engine_leaks: list = field(default_factory=list)
    compound_steps: list = field(default_factory=list)
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
            'engine_leaks': list(self.engine_leaks),
            'compound_steps': list(self.compound_steps),
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
            f"turn_to={intent.get('turn_to')}",
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
            '--- H. GUIDANCE ---',
            json.dumps(self.pressure, indent=2, ensure_ascii=False),
            f"guidance_level (after)={self.after_state.get('guidance_level', self.pressure.get('guidance_after'))}",
            '',
            '--- I. NARRATOR INPUT ---',
            json.dumps(self.narrator_input, indent=2, ensure_ascii=False),
            '',
            '--- J. NARRATOR OUTPUT ---',
            self.narrator_output,
            '',
            '--- ENGINE LEAKS ---',
            json.dumps(self.engine_leaks, indent=2, ensure_ascii=False),
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


def _intent_from_dict(data: dict, authored_actions: Optional[list] = None) -> Intent:
    """Build Intent from a confirmed discourse / sequence step dict."""
    if not isinstance(data, dict):
        return Intent(action_class='UNINTERPRETABLE', classification='UNINTERPRETABLE', understood=False)
    # Prefer full normalize when action/classification present
    return normalize_intent(data, authored_actions=authored_actions or [])


class GameSession:
    def __init__(
        self,
        player_name: str = 'Adventurer',
        seed: int = 91,
        potion_id: str = 'potion_skill',
        interpreter=None,
        debug: bool = True,
        narrator=None,
        allow_heuristic_fallback: bool = False,
        ollama_model: str = 'mistral',
        generate_images: bool = False,
        image_generator=None,
        image_cache_dir: Optional[Path] = None,
    ):
        self.debug = debug
        self.generate_images = bool(generate_images)
        self.rng = GameRNG.from_seed(seed)
        sheet = make_adventure_sheet(self.rng, name=player_name, potion_id=potion_id)
        self.world = WorldState(
            passage_id=1,
            sheet=sheet,
            rng_seed_note=str(seed),
        )
        self.allow_heuristic_fallback = allow_heuristic_fallback
        self.ollama_model = ollama_model
        self._image_generator = image_generator
        self._image_cache_dir = Path(image_cache_dir) if image_cache_dir else (Path.home() / 'Puca' / 'deathtrap_images')
        self.last_image_path: Optional[Path] = None

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
        self.save_path = Path.home() / 'Puca' / 'deathtrap-ff.json'

    @property
    def opening_text(self) -> str:
        """Player-facing opener from puca_trial passage 1."""
        passage = get_passage(1)
        return (passage.text or '').strip()

    def current_passage(self):
        return get_passage(self.world.passage_id)

    def concise_state(self) -> dict:
        w = self.world
        s = w.sheet
        c = w.combat
        return {
            'passage_id': w.passage_id,
            'ending': w.ending,
            'victory': w.victory,
            'sheet': {
                'name': s.name,
                'skill': s.skill,
                'stamina': s.stamina,
                'stamina_initial': s.stamina_initial,
                'luck': s.luck,
                'gold': s.gold,
                'provisions': s.provisions,
                'inventory': list(s.inventory),
                'potion': s.potion,
                'potion_used': s.potion_used,
                'flags': dict(s.flags),
                'knowledge': list(s.knowledge),
                'alive': s.alive,
                'body_state': dict(s.body_state or {}),
                'injuries': list(s.injuries or []),
            },
            'combat': {
                'active': c.active,
                'enemy_name': c.enemy_name,
                'enemy_skill': c.enemy_skill,
                'enemy_stamina': c.enemy_stamina,
                'round': c.round,
                'win_to': c.win_to,
                'lose_to': c.lose_to,
                'flee_to': c.flee_to,
            } if c.active else None,
            'guidance_level': w.guidance_level,
            'last_image_prompt': w.last_image_prompt,
            'rng_seed': self.rng.seed,
            'turn_index': w.turn_index,
            'world_time_seconds': w.world_time_seconds,
            'pending_discourse': w.pending_discourse,
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
        if cmd == '/sheet':
            return json.dumps(self.world.sheet.to_dict(), indent=2, ensure_ascii=False)
        if cmd == '/passage':
            p = self.current_passage()
            return json.dumps(p.to_dict(), indent=2, ensure_ascii=False)
        if cmd == '/fullstate':
            return json.dumps(self.full_state(), indent=2, default=str, ensure_ascii=False)
        if cmd == '/perception':
            return json.dumps(
                public_perception(self.world, self.current_passage(), stage='A'),
                indent=2,
                ensure_ascii=False,
            )
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

    def _compose_output(self, resolution, player_text: str, intent_dict: dict, passage) -> tuple[dict, str]:
        """Passage text is authoritative on enter; narrate combat/dismiss facts otherwise."""
        combat_or_dismiss_facts = [
            f for f in resolution.facts
            if not (isinstance(f, str) and f.startswith('Entered passage '))
        ]

        if resolution.show_passage_text and resolution.passage_entered is not None:
            new_passage = get_passage(resolution.passage_entered)
            body = (new_passage.text or '').strip()
            extras = [
                f for f in combat_or_dismiss_facts
                if f and not (isinstance(f, str) and f.startswith('You gain '))
            ]
            if resolution.combat_round or (extras and self.world.combat.active):
                narrator_in, interstitial = narrate(
                    self.world, resolution, player_text,
                    intent=intent_dict, narrator=self.narrator,
                )
                if resolution.combat_round and interstitial and interstitial not in body:
                    prose = f'{interstitial}\n\n{body}' if body else interstitial
                elif extras and not resolution.combat_round:
                    prose = body
                    narrator_in = {
                        'player_text_non_authoritative': player_text,
                        'passage_id': resolution.passage_entered,
                        'facts': list(resolution.facts),
                        'structured_facts': list(getattr(resolution, 'structured_facts', []) or []),
                        'mode': 'passage_text',
                    }
                else:
                    prose = body
                    narrator_in = {
                        'player_text_non_authoritative': player_text,
                        'passage_id': resolution.passage_entered,
                        'facts': list(resolution.facts),
                        'structured_facts': list(getattr(resolution, 'structured_facts', []) or []),
                        'mode': 'passage_text',
                    }
                return narrator_in, prose

            narrator_in = {
                'player_text_non_authoritative': player_text,
                'passage_id': resolution.passage_entered,
                'facts': list(resolution.facts),
                'structured_facts': list(getattr(resolution, 'structured_facts', []) or []),
                'mode': 'passage_text',
            }
            return narrator_in, body

        if resolution.needs_clarification and resolution.clarification_prompt:
            narrator_in = {
                'player_text_non_authoritative': player_text,
                'facts': list(resolution.facts),
                'mode': 'clarification',
            }
            return narrator_in, resolution.clarification_prompt

        return narrate(
            self.world, resolution, player_text,
            intent=intent_dict, narrator=self.narrator,
        )

    def _maybe_generate_image(self, img: dict) -> None:
        if self.debug or not self.generate_images:
            return
        if img.get('decision') == 'REUSE' and self.last_image_path and Path(self.last_image_path).is_file():
            img['path'] = str(self.last_image_path)
            img['suppressed'] = False
            img['note'] = 'image reused'
            return
        if img.get('decision') != 'REGENERATE':
            return
        prompt = img.get('full_prompt') or ''
        if not prompt:
            return
        try:
            if self._image_generator is None:
                from puca_images import ImageGenerator
                root = Path(__file__).resolve().parents[1]
                lora = root / 'pixel_style_lora_style_only'
                use_lora = (lora / 'adapter_model.safetensors').is_file()
                self._image_cache_dir.mkdir(parents=True, exist_ok=True)
                self._image_generator = ImageGenerator(
                    cache_dir=self._image_cache_dir,
                    lora_folder=lora,
                    use_lora=use_lora,
                )
            _key, path = self._image_generator.generate(f'passage_{self.world.passage_id}', prompt)
            self.visual_backend_calls += 1
            self.last_image_path = Path(path)
            img['path'] = str(path)
            img['note'] = 'image generated'
            img['suppressed'] = False
        except Exception as exc:
            img['note'] = f'image generation failed: {exc}'
            img['suppressed'] = True
            img['path'] = None

    def _build_perception_and_authored(self) -> tuple[Any, dict, list]:
        passage = self.current_passage()
        perception = public_perception(self.world, passage, stage='A')
        authored = build_authored_actions(self.world, passage)
        return passage, perception, authored

    def _resolve_one(
        self,
        intent: Intent,
        passage,
        authored: list,
    ) -> tuple[Any, Resolution]:
        grounding = ground_intent(self.world, intent, passage, authored_actions=authored)
        resolution = resolve(self.world, intent, grounding, self.rng, passage)
        world_react.after_player_action(self.world, intent, resolution, self.rng)
        return grounding, resolution

    def _run_compound(
        self,
        intent: Intent,
        player_text: str,
        trace: TurnTrace,
    ) -> Resolution:
        """Execute sequence steps transactionally; stop on fail/death/combat interrupt."""
        steps = list(intent.sequence or [])
        if not steps:
            passage, _perception, authored = self._build_perception_and_authored()
            grounding, resolution = self._resolve_one(intent, passage, authored)
            trace.grounding = grounding.to_dict()
            return resolution

        snapshot = self.world.clone()
        rng_snap = self.rng.snapshot()
        performed: list[Resolution] = []
        narrations: list[str] = []
        last_resolution: Optional[Resolution] = None
        combat_was_active = self.world.combat.active

        try:
            for i, step in enumerate(steps):
                step_dict = step if isinstance(step, dict) else {}
                # Rebuild authored/perception each step
                passage, _perception, authored = self._build_perception_and_authored()
                step_intent = _intent_from_dict(step_dict, authored_actions=authored)
                if not step_intent.utterance:
                    step_intent.utterance = player_text

                # If combat newly started mid-compound and this isn't an attack/flee, interrupt
                if self.world.combat.active and not combat_was_active and i > 0:
                    if (step_intent.action_class or '').upper() not in (
                        'ATTACK', 'FIGHT', 'STRIKE', 'FLEE',
                    ):
                        trace.compound_steps.append({'stopped': 'combat_interrupt', 'index': i})
                        break

                grounding, resolution = self._resolve_one(step_intent, passage, authored)
                performed.append(resolution)
                last_resolution = resolution
                trace.compound_steps.append({
                    'index': i,
                    'intent': step_intent.to_dict(),
                    'grounding': grounding.to_dict(),
                    'resolution': resolution.to_dict(),
                })

                # Compose per-step narration for steps actually performed
                _nin, prose = self._compose_output(
                    resolution, player_text, step_intent.to_dict(), passage,
                )
                if prose:
                    narrations.append(prose)

                failed = (
                    resolution.success is False
                    and not resolution.attempted
                    and resolution.rejection_reason in (
                        'intent_not_understood', 'entity_absent', 'player_dead',
                    )
                )
                if resolution.rejection_reason == 'player_dead' or not self.world.sheet.alive:
                    break
                if failed and resolution.none_reason in ('entity_absent', 'intent_not_understood'):
                    break
                if self.world.ending in ('death', 'victory'):
                    break
                # Hard fail on blocked movement/consume with fidelity
                if resolution.none_reason == 'intent_fidelity_blocked':
                    break

                combat_was_active = self.world.combat.active
        except Exception:
            # Roll back on unexpected error
            self.world = snapshot
            self.rng = GameRNG.restore(rng_snap)
            raise

        if last_resolution is None:
            last_resolution = Resolution(
                intent_understood=True,
                success=False,
                facts=['Nothing happens.'],
                advance_time=False,
            )

        # Merge facts from performed steps into last resolution for guidance/narrate fallback
        if len(performed) > 1:
            merged_facts: list = []
            merged_structured: list = []
            merged_events: list = []
            for r in performed:
                merged_facts.extend(r.facts or [])
                merged_structured.extend(getattr(r, 'structured_facts', None) or [])
                merged_events.extend(getattr(r, 'world_events', None) or [])
            last_resolution.facts = merged_facts
            last_resolution.structured_facts = merged_structured
            last_resolution.world_events = merged_events

        # Stash composed compound narration on resolution for _compose_output override
        if narrations:
            last_resolution.facts = list(last_resolution.facts or [])
            # Prefer joined step prose via a dedicated attribute on trace
            trace.narrator_output = '\n\n'.join(narrations)

        if not trace.grounding and performed:
            # Use last step grounding from compound_steps
            if trace.compound_steps:
                last_g = trace.compound_steps[-1].get('grounding')
                if isinstance(last_g, dict):
                    trace.grounding = last_g

        return last_resolution

    def submit(self, text: str) -> TurnTrace:
        text = (text or '').strip()
        trace = TurnTrace(raw_input=text)

        if text.startswith('/'):
            allowed = text.split()[0].lower() in DEBUG_COMMANDS
            if self.debug or allowed:
                trace.debug_command = text.split()[0].lower()
                out = self.handle_debug_command(text)
                trace.narrator_output = out
                self.last_trace = trace
                self.traces.append(trace)
                return trace

        before = self.concise_state()
        passage, perception, authored = self._build_perception_and_authored()

        # 1) Discourse short-circuit for pending yes/no / exclusive
        discourse_intent: Optional[Intent] = None
        if self.world.pending_discourse:
            kind, payload = discourse.resolve_affirmative(text, self.world)
            if kind == 'confirm' and isinstance(payload, dict):
                discourse_intent = _intent_from_dict(payload, authored_actions=authored)
                trace.raw_interpreter_output = {
                    'from_discourse': True,
                    'confirm': payload,
                }
                trace.validated_intent = discourse_intent.to_dict()
            elif kind == 'reject':
                res = Resolution(
                    intent_understood=True,
                    grounded=True,
                    feasible=True,
                    success=False,
                    attempted=False,
                    facts=['You let that go.'],
                    advance_time=False,
                )
                trace.resolution = res.to_dict()
                narrator_in, prose = self._compose_output(res, text, {}, passage)
                trace.narrator_input = narrator_in
                trace.narrator_output = prose
                self.world.turn_index += 1
                after = self.concise_state()
                trace.before_state = before
                trace.after_state = after
                trace.state_diff = state_diff(before, after)
                self.last_trace = trace
                self.traces.append(trace)
                return trace
            elif kind == 'ambiguous':
                prompt = str(payload or 'Please clarify.')
                res = Resolution(
                    intent_understood=True,
                    grounded=False,
                    needs_clarification=True,
                    clarification_prompt=prompt,
                    facts=[prompt],
                    advance_time=False,
                )
                trace.resolution = res.to_dict()
                narrator_in, prose = self._compose_output(res, text, {}, passage)
                trace.narrator_input = narrator_in
                trace.narrator_output = prose
                self.world.turn_index += 1
                after = self.concise_state()
                trace.before_state = before
                trace.after_state = after
                trace.state_diff = state_diff(before, after)
                self.last_trace = trace
                self.traces.append(trace)
                return trace
            # kind == 'not_reply' → fall through to interpret

        if discourse_intent is None:
            trace.interpreter_input = {
                'player_text': text,
                'perception': perception,
                'authored_actions': authored,
            }
            try:
                raw_out, intent = self.interpreter.interpret(
                    text, perception, authored_actions=authored,
                )
            except InterpreterUnavailable as exc:
                if self.allow_heuristic_fallback:
                    raw_out, intent = HeuristicInterpreter().interpret(
                        text, perception, authored_actions=authored,
                    )
                    trace.error = f'ollama_unavailable_fallback_heuristic: {exc}'
                else:
                    raise
            trace.raw_interpreter_output = raw_out
            trace.validated_intent = intent.to_dict()
        else:
            intent = discourse_intent
            trace.interpreter_input = {
                'player_text': text,
                'perception': perception,
                'authored_actions': authored,
                'from_discourse': True,
            }

        # Exclusive clarification → set pending discourse when resolve asks for it
        # (resolve may call discourse.set_pending_exclusive itself)

        # 4–5) Compound vs single
        classification = (intent.classification or '').upper()
        if intent.sequence and (
            classification == 'COMPOUND_ACTION' or len(intent.sequence) > 0
        ):
            # Only treat as compound when classification says so OR sequence non-empty with COMPOUND
            if classification == 'COMPOUND_ACTION' or (
                isinstance(intent.sequence, list) and len(intent.sequence) > 1
            ):
                resolution = self._run_compound(intent, text, trace)
            else:
                grounding, resolution = self._resolve_one(intent, passage, authored)
                trace.grounding = grounding.to_dict()
        else:
            grounding, resolution = self._resolve_one(intent, passage, authored)
            trace.grounding = grounding.to_dict()

        # Clarification with exclusive options: ensure discourse pending if needed
        if (
            resolution.needs_clarification
            and resolution.clarification_prompt
            and not self.world.pending_discourse
        ):
            ambs = (intent.ambiguities or [])
            if ambs and len(ambs) <= 6:
                discourse.set_pending_exclusive(
                    self.world,
                    resolution.clarification_prompt,
                    [{'id': str(a), 'label': str(a)} for a in ambs],
                )

        pressure = apply_guidance(self.world, resolution)
        trace.pressure = pressure
        trace.resolution = resolution.to_dict()

        # 6) Narrate — compound may have pre-filled narrator_output
        if trace.narrator_output and trace.compound_steps:
            narrator_in = {
                'player_text_non_authoritative': text,
                'facts': list(resolution.facts),
                'structured_facts': list(getattr(resolution, 'structured_facts', []) or []),
                'mode': 'compound',
            }
            prose = trace.narrator_output
        else:
            narrator_in, prose = self._compose_output(
                resolution, text, trace.validated_intent, passage,
            )
        trace.narrator_input = narrator_in
        trace.narrator_output = prose

        # 7) Image from final visible state
        colour = (not self.debug) and not isinstance(self.narrator, TemplateNarrator)
        img = image_decision(
            self.world,
            resolution,
            passage=self.current_passage(),
            colour_with_llm=colour,
            ollama_model=self.ollama_model,
        )
        if self.debug or not self.generate_images:
            img = dict(img)
            img['suppressed'] = True
            img['note'] = (
                'DEBUG MODE — IMAGE GENERATION SUPPRESSED'
                if self.debug else
                'Image generation off (pass generate_images=True / --images)'
            )
        else:
            self._maybe_generate_image(img)
        trace.image = img
        trace.visual_backend_calls = self.visual_backend_calls

        # 8) Engine leak scan on player-facing text (debug traces)
        if self.debug:
            leaks = engine_leak.scan_player_facing_text(prose or '')
            trace.engine_leaks = leaks

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
            'version': 2,
            'world': self.world.to_dict(),
            'rng': self.rng.snapshot(),
            'debug': self.debug,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding='utf-8',
        )

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
