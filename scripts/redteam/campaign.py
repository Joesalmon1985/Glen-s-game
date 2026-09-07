"""Run three-layer red-team campaign with quotas, traces, and clean gate."""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from puca_dungeon.content_loader import get_passage
from puca_dungeon.interpret import HeuristicInterpreter, OllamaInterpreter, ollama_reachable
from puca_dungeon.narrate import TemplateNarrator
from puca_dungeon.session import GameSession

from scripts.redteam import agents as agent_mod
from scripts.redteam.findings import Finding, clean_gate, severity_counts
from scripts.redteam import invariants
from scripts.redteam import layer_a_semantic as layer_a
from scripts.redteam import layer_b_reality as layer_b
from scripts.redteam import layer_c_narrator as layer_c


DEFAULT_REPORT = ROOT / 'tools' / '_redteam_reality_report.json'
DEFAULT_TRACES = ROOT / 'tools' / '_redteam_reality_traces.jsonl'
DEFAULT_GATE_DOC = ROOT / 'docs' / 'verification' / 'puca_reality_gate.json'
DEFAULT_ONLINE_SMOKE_GATE = ROOT / 'docs' / 'verification' / 'puca_reality_gate_online_smoke.json'
DEFAULT_ONLINE_SMOKE_REPORT = ROOT / 'tools' / '_redteam_online_smoke_report.json'
DEFAULT_ONLINE_SMOKE_TRACES = ROOT / 'tools' / '_redteam_online_smoke_traces.jsonl'

# Bounded online smoke: 10% Layer A/B quotas + short runs of these personas only.
ONLINE_SMOKE_AGENTS: tuple[str, ...] = (
    'CombatStaller',
    'ImpossiblePower',
    'FoolishPhysical',
    'SensibleCautious',
    'AmbiguousReply',
)

BASE_QUOTAS = {
    'semantic_per_family': 100,
    'compound': 50,
    'stale_nonexistent': 50,
    'discourse': 50,
    'ambiguity': 50,
    'combat_stall': 25,
    'pacifist': 25,
    'narrator_truth': 25,
    'image_state': 25,
    'playthroughs': 20,
}


def scale_quotas(base: dict, scale: float) -> dict:
    """Multiply integer quota values; keep at least 1 when scale > 0."""
    if scale <= 0:
        raise ValueError('quota scale must be > 0')
    out: dict[str, int] = {}
    for key, value in base.items():
        if isinstance(value, int):
            out[key] = max(1, int(round(value * scale)))
        else:
            out[key] = value  # type: ignore[assignment]
    return out


def make_session(
    seed: int,
    *,
    offline: bool,
    model: str = 'mistral',
    name: str = 'RedTeam',
) -> GameSession:
    if offline:
        return GameSession(
            player_name=name,
            seed=seed,
            interpreter=HeuristicInterpreter(),
            debug=True,
            narrator=TemplateNarrator(),
            allow_heuristic_fallback=True,
            ollama_model=model,
            generate_images=False,
        )
    if not ollama_reachable():
        raise SystemExit(
            'RED TEAM ABORT: Ollama is not reachable at http://127.0.0.1:11434. '
            'Use --offline for CI, or start Ollama.'
        )
    interp = OllamaInterpreter(model=model)
    if not interp.ping():
        raise SystemExit(
            f'RED TEAM ABORT: Ollama up but model {model!r} not ready. '
            f'Run `ollama pull {model}` or pass --offline.'
        )
    session = GameSession(
        player_name=name,
        seed=seed,
        interpreter=interp,
        debug=True,
        narrator=TemplateNarrator(),
        allow_heuristic_fallback=False,
        ollama_model=model,
        generate_images=False,
    )
    if not isinstance(session.interpreter, OllamaInterpreter):
        raise SystemExit('RED TEAM ABORT: session interpreter is not OllamaInterpreter')
    return session


def _write_trace(fh, record: dict) -> None:
    fh.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')


def _submit_checked(
    session: GameSession,
    utterance: str,
    *,
    layer: str,
    persona: str,
    findings: list[Finding],
    trace_fh,
    extra: Optional[dict] = None,
) -> Any:
    before_pid = session.world.passage_id
    stam_before = session.world.sheet.stamina
    try:
        tr = session.submit(utterance)
    except Exception as exc:
        findings.append(Finding(
            'P0', layer, persona, before_pid, utterance, f'Crash: {exc}',
            invariant='crash',
        ))
        _write_trace(trace_fh, {
            'layer': layer, 'persona': persona, 'utterance': utterance,
            'error': str(exc), **(extra or {}),
        })
        return None

    findings.extend(invariants.check_turn(
        tr, layer=layer, persona=persona, utterance=utterance,
    ))
    findings.extend(layer_c.prosecute_narrator(
        tr.narrator_output or '',
        tr.resolution or {},
        tr.after_state or {},
        layer=layer,
        persona=persona,
        utterance=utterance,
    ))
    findings.extend(layer_c.check_image_state(
        tr.image or {}, tr.after_state or {}, utterance=utterance,
    ))
    _write_trace(trace_fh, {
        'layer': layer,
        'persona': persona,
        'utterance': utterance,
        'passage_before': before_pid,
        'passage_after': session.world.passage_id,
        'stamina_before': stam_before,
        'stamina_after': session.world.sheet.stamina,
        'classification': (tr.validated_intent or {}).get('classification'),
        'matched_action_id': (tr.validated_intent or {}).get('matched_action_id'),
        'trace': tr.to_dict(),
        **(extra or {}),
    })
    return tr


def run_layer_a(
    seed: int,
    offline: bool,
    model: str,
    findings: list[Finding],
    trace_fh,
    quotas: dict,
) -> dict:
    stats = {'families': {}, 'compound': 0, 'ambiguity': 0, 'discourse': 0}
    per = int(quotas.get('semantic_per_family', 100))

    # Fresh session per utterance for perceive/impossible isolation
    for family, cases in layer_a.generate_all_layer_a(seed, per).items():
        ok = 0
        for case in cases:
            s = make_session(seed, offline=offline, model=model, name=f'A-{family}')
            tr = _submit_checked(
                s, case.utterance, layer='layer_a', persona=f'semantic:{family}',
                findings=findings, trace_fh=trace_fh,
                extra={'family': family, 'pair_id': case.pair_id},
            )
            if tr is None:
                continue
            cls = (tr.validated_intent or {}).get('classification')
            if (
                case.enforce_class
                and case.expect_class_any
                and cls not in case.expect_class_any
                and family in ('perceive', 'impossible')
            ):
                findings.append(Finding(
                    'P1', 'layer_a', f'semantic:{family}', s.world.passage_id,
                    case.utterance,
                    f'expected one of {case.expect_class_any}, got {cls}',
                    invariant='semantic_class',
                    intent=dict(tr.validated_intent or {}),
                ))
            else:
                ok += 1
            if case.enforce_class and case.forbid_class and cls in case.forbid_class:
                findings.append(Finding(
                    'P1', 'layer_a', f'semantic:{family}', s.world.passage_id,
                    case.utterance,
                    f'forbidden classification {cls}',
                    invariant='semantic_forbid',
                    intent=dict(tr.validated_intent or {}),
                ))
            if case.forbid_passage_change and s.world.passage_id != 1:
                findings.append(Finding(
                    'P0', 'layer_a', f'semantic:{family}', s.world.passage_id,
                    case.utterance,
                    f'{family} changed passage to {s.world.passage_id}',
                    invariant='semantic_no_move',
                    intent=dict(tr.validated_intent or {}),
                ))
        stats['families'][family] = {'count': len(cases), 'ok': ok}

    # Compounds
    s = make_session(seed + 1, offline=offline, model=model, name='A-compound')
    for utt in layer_a.generate_compound_cases(int(quotas.get('compound', 50)), seed):
        if not s.world.sheet.alive:
            s = make_session(seed + 1, offline=offline, model=model, name='A-compound')
        _submit_checked(
            s, utt, layer='layer_a', persona='compound', findings=findings, trace_fh=trace_fh,
        )
        stats['compound'] += 1

    # Ambiguity
    s = make_session(seed + 2, offline=offline, model=model, name='A-amb')
    for utt in layer_a.generate_ambiguity_cases(int(quotas.get('ambiguity', 50)), seed):
        _submit_checked(
            s, utt, layer='layer_a', persona='ambiguity', findings=findings, trace_fh=trace_fh,
        )
        stats['ambiguity'] += 1

    # Discourse / anaphora
    s = make_session(seed + 3, offline=offline, model=model, name='A-disc')
    for utt in layer_a.generate_discourse_cases(int(quotas.get('discourse', 50)), seed):
        _submit_checked(
            s, utt, layer='layer_a', persona='discourse', findings=findings, trace_fh=trace_fh,
        )
        stats['discourse'] += 1

    return stats


def run_layer_b(
    seed: int,
    offline: bool,
    model: str,
    findings: list[Finding],
    trace_fh,
    quotas: dict,
) -> dict:
    n = int(quotas.get('stale_nonexistent', 50))
    cases = layer_b.generate_reality_cases(n, seed)
    s = make_session(seed + 11, offline=offline, model=model, name='B-reality')
    count = 0
    for case in cases:
        before = s.world.passage_id
        inv_before = list(s.world.sheet.inventory)
        tr = _submit_checked(
            s, case.utterance, layer='layer_b', persona=case.category,
            findings=findings, trace_fh=trace_fh,
            extra={'category': case.category},
        )
        count += 1
        if tr is None:
            continue
        # Nonexistent vehicles must not teleport or invent inventory
        low = case.utterance.lower()
        if any(x in low for x in ('tank', 'helicopter', 'chopper', 'cloak', 'fireball', 'skeleton key')):
            for fake in ('tank', 'helicopter', 'cloak', 'fireball', 'skeleton key'):
                if any(fake in str(x).lower() for x in s.world.sheet.inventory):
                    findings.append(Finding(
                        'P0', 'layer_b', case.category, s.world.passage_id, case.utterance,
                        f'Fake item entered inventory: {fake}',
                        invariant='inventory_hallucination',
                    ))
        if 'turn to 400' in low or 'paragraph 399' in low or 'passage_id' in low:
            if s.world.passage_id != before and (tr.validated_intent or {}).get('classification') != 'MATCH_AUTHORED_ACTION':
                findings.append(Finding(
                    'P0', 'layer_b', case.category, s.world.passage_id, case.utterance,
                    f'Cheat teleport {before}->{s.world.passage_id}',
                    invariant='teleport_cheat',
                    intent=dict(tr.validated_intent or {}),
                ))
        if not s.world.sheet.alive or s.world.victory:
            s = make_session(seed + 11 + count, offline=offline, model=model, name='B-reality')
        _ = inv_before
    return {'count': count}


def run_combat_personas(
    seed: int,
    offline: bool,
    model: str,
    findings: list[Finding],
    trace_fh,
    quotas: dict,
) -> dict:
    """Combat-stall and pacifist quotas — path walks into combat when possible."""
    stats = {'combat_stall': 0, 'pacifist': 0}

    def toward_combat(s: GameSession, persona: str, n_setup: int = 6) -> None:
        setup = [
            'leave the alcove and press deeper into the tunnel',
            'take the western mouth',
            'keep going',
            'go west',
            'continue',
        ]
        for utt in setup[:n_setup]:
            if s.world.combat.active or not s.world.sheet.alive:
                break
            _submit_checked(
                s, utt, layer='layer_a', persona=persona, findings=findings, trace_fh=trace_fh,
            )

    stall_n = int(quotas.get('combat_stall', 25))
    s = make_session(seed + 21, offline=offline, model=model, name='stall')
    toward_combat(s, 'CombatStaller')
    stall_cmds = [
        'wait', 'look around', 'sing a song', 'check my inventory',
        'tie my boots', 'admire the walls', 'sit down',
    ]
    for i in range(stall_n):
        if not s.world.sheet.alive or s.world.victory:
            s = make_session(seed + 21 + i, offline=offline, model=model, name='stall')
            toward_combat(s, 'CombatStaller')
        utt = stall_cmds[i % len(stall_cmds)]
        stam_before = s.world.sheet.stamina
        combat_before = s.world.combat.active
        tr = _submit_checked(
            s, utt, layer='layer_a', persona='CombatStaller', findings=findings, trace_fh=trace_fh,
        )
        stats['combat_stall'] += 1
        if tr and combat_before and s.world.combat.active:
            # Stalling in combat should draw opportunity damage when time advances
            wt_b = (tr.before_state or {}).get('world_time_seconds', 0)
            wt_a = (tr.after_state or {}).get('world_time_seconds', 0)
            if wt_a > wt_b and s.world.sheet.stamina >= stam_before:
                findings.append(Finding(
                    'P0', 'layer_a', 'CombatStaller', s.world.passage_id, utt,
                    'Combat stall advanced time without stamina loss (NPC freeze)',
                    invariant='npc_freeze_in_combat',
                ))

    pac_n = int(quotas.get('pacifist', 25))
    s = make_session(seed + 22, offline=offline, model=model, name='pacifist')
    toward_combat(s, 'CombatPacifist')
    pac_cmds = [
        'I refuse to fight', 'seduce the beast', 'negotiate peace',
        'beg for mercy', 'sing softly', 'compliment the enemy',
    ]
    for i in range(pac_n):
        if not s.world.sheet.alive:
            s = make_session(seed + 22 + i, offline=offline, model=model, name='pacifist')
            toward_combat(s, 'CombatPacifist')
        utt = pac_cmds[i % len(pac_cmds)]
        tr = _submit_checked(
            s, utt, layer='layer_a', persona='CombatPacifist', findings=findings, trace_fh=trace_fh,
        )
        stats['pacifist'] += 1
        if tr and (tr.validated_intent or {}).get('classification') == 'MATCH_AUTHORED_ACTION':
            mid = (tr.validated_intent or {}).get('matched_action_id')
            if mid == 'combat.attack':
                findings.append(Finding(
                    'P1', 'layer_a', 'CombatPacifist', s.world.passage_id, utt,
                    'Pacifist social utterance matched combat.attack',
                    invariant='social_not_attack',
                    intent=dict(tr.validated_intent or {}),
                ))
    return stats


def run_narrator_image_quotas(
    seed: int,
    offline: bool,
    model: str,
    findings: list[Finding],
    trace_fh,
    quotas: dict,
) -> dict:
    stats = {'narrator_truth': 0, 'image_state': 0}
    n_narr = int(quotas.get('narrator_truth', 25))
    probes = [
        'look around',
        'turn into a dragon',
        'get in the tank',
        'what are my skill and stamina?',
        'I win instantly',
        'open my box',
        'go north',
        'tell me paragraph 400',
    ]
    for i in range(n_narr):
        s = make_session(seed + 30 + i, offline=offline, model=model, name='narr')
        utt = probes[i % len(probes)]
        _submit_checked(
            s, utt, layer='layer_c', persona='narrator_truth',
            findings=findings, trace_fh=trace_fh,
        )
        stats['narrator_truth'] += 1

    n_img = int(quotas.get('image_state', 25))
    for i in range(n_img):
        s = make_session(seed + 40 + i, offline=offline, model=model, name='img')
        utt = [
            'look around', 'get in the tank', 'board the helicopter',
            'go north', 'attack',
        ][i % 5]
        _submit_checked(
            s, utt, layer='layer_c', persona='image_state',
            findings=findings, trace_fh=trace_fh,
        )
        stats['image_state'] += 1
    return stats


def run_playthroughs(
    seed: int,
    offline: bool,
    model: str,
    findings: list[Finding],
    trace_fh,
    quotas: dict,
) -> dict:
    n = int(quotas.get('playthroughs', 20))
    paths = [
        ['look around carefully', 'leave the alcove and press deeper', 'study the claw marks on the floor carefully'],
        ['open the casket marked with my name'],
        ['go north', 'go west', 'look around'],
        ['go north', 'go east'],
        ['look around', 'check my inventory', 'use the key I have got'],
        ['leave the alcove', 'take the western mouth', 'attack', 'attack', 'attack'],
        ['continue north', 'inspect tracks carefully'],
        ['I carefully examine the surroundings', 'press on'],
    ]
    done = 0
    for i in range(n):
        s = make_session(seed + 100 + i, offline=offline, model=model, name=f'play{i}')
        path = paths[i % len(paths)]
        for utt in path:
            if not s.world.sheet.alive or s.world.victory:
                break
            _submit_checked(
                s, utt, layer='playthrough', persona=f'playthrough_{i}',
                findings=findings, trace_fh=trace_fh,
            )
        done += 1
    return {'count': done}


def run_agents(
    seed: int,
    offline: bool,
    model: str,
    findings: list[Finding],
    trace_fh,
    max_turns: int = 12,
    agent_names: Optional[list[str]] = None,
) -> dict:
    """Black-box agent playthroughs (online primary; also runs offline)."""
    rng = random.Random(seed)
    results = {}
    if agent_names:
        wanted = {n.strip() for n in agent_names if n and str(n).strip()}
        classes = [cls for cls in agent_mod.ALL_AGENTS if cls.name in wanted]
        missing = wanted - {cls.name for cls in classes}
        if missing:
            raise SystemExit(f'Unknown agent names for --agents: {sorted(missing)}')
    else:
        classes = list(agent_mod.ALL_AGENTS)
    for cls in classes:
        agent = cls(random.Random(seed + hash(cls.name) % 9973))
        s = make_session(seed + hash(cls.name) % 1000, offline=offline, model=model, name=cls.name)
        ctx = agent_mod.AgentContext(opening=s.opening_text)
        agent.observe(ctx, s.opening_text)
        stam0 = s.world.sheet.stamina
        turns = 0
        for _ in range(max_turns):
            if not s.world.sheet.alive or s.world.victory:
                break
            cmd = agent.next_command(ctx)
            if not cmd:
                break
            if cmd.startswith('/') and cls.name == 'SaveLoadSaboteur':
                # Handle save/load specially offline
                if cmd == '/save':
                    with tempfile.TemporaryDirectory() as td:
                        path = Path(td) / 'rt.json'
                        try:
                            s.save(path)
                            s2 = make_session(seed, offline=offline, model=model, name='load')
                            s2.load(path)
                            if s2.world.passage_id != s.world.passage_id:
                                findings.append(Finding(
                                    'P0', 'agents', cls.name, s.world.passage_id, cmd,
                                    'Passage mismatch after save/load',
                                    invariant='save_load',
                                ))
                            s = s2
                        except Exception as exc:
                            findings.append(Finding(
                                'P0', 'agents', cls.name, s.world.passage_id, cmd,
                                f'save/load error: {exc}',
                                invariant='save_load',
                            ))
                    turns += 1
                    continue
                if cmd == '/load':
                    turns += 1
                    continue
            tr = _submit_checked(
                s, cmd, layer='agents', persona=cls.name,
                findings=findings, trace_fh=trace_fh,
            )
            turns += 1
            if tr:
                agent.observe(ctx, tr.narrator_output or '')
                ctx.history.append(cmd)
                ctx.alive = s.world.sheet.alive
                ctx.victory = s.world.victory

        # SensibleCautious must not take random damage on careful acts in passage 1
        if cls.name == 'SensibleCautious':
            if s.world.sheet.stamina < stam0:
                findings.append(Finding(
                    'P0', 'agents', 'SensibleCautious', s.world.passage_id, '(careful acts)',
                    f'SensibleCautious lost stamina {stam0}->{s.world.sheet.stamina} while acting carefully',
                    invariant='sensible_cautious_safe',
                ))
        results[cls.name] = {'turns': turns, 'ended': (
            'victory' if s.world.victory else ('death' if not s.world.sheet.alive else '')
        )}
        _ = rng
    return results


def run_transcript_regressions(
    seed: int,
    offline: bool,
    model: str,
    findings: list[Finding],
    trace_fh,
) -> dict:
    """Compact regressions from unsuccessful human playtest themes."""
    cases = [
        ('look around', {'expect_cls': 'PERCEPTION_QUERY', 'expect_pid': 1}),
        ('turn into a dragon', {'forbid_potion': True, 'forbid_pid_change': True}),
        ('use the key I\'ve got', {'forbid_potion': True}),
        ('get in the tank', {'forbid_pid_change': True}),
        ('yes', {'forbid_pid_change': True}),
    ]
    for utt, expect in cases:
        s = make_session(seed, offline=offline, model=model, name='regress')
        potion_before = s.world.sheet.potion_used
        pid_before = s.world.passage_id
        tr = _submit_checked(
            s, utt, layer='regression', persona='transcript',
            findings=findings, trace_fh=trace_fh,
        )
        if tr is None:
            continue
        cls = (tr.validated_intent or {}).get('classification')
        if expect.get('expect_cls') and cls != expect['expect_cls']:
            findings.append(Finding(
                'P1', 'regression', 'transcript', s.world.passage_id, utt,
                f'expected {expect["expect_cls"]}, got {cls}',
                invariant='transcript_regression',
                intent=dict(tr.validated_intent or {}),
            ))
        if expect.get('expect_pid') is not None and s.world.passage_id != expect['expect_pid']:
            findings.append(Finding(
                'P0', 'regression', 'transcript', s.world.passage_id, utt,
                f'expected passage {expect["expect_pid"]}, got {s.world.passage_id}',
                invariant='transcript_regression',
            ))
        if expect.get('forbid_potion') and s.world.sheet.potion_used and not potion_before:
            findings.append(Finding(
                'P0', 'regression', 'transcript', s.world.passage_id, utt,
                'Potion consumed unexpectedly',
                invariant='transcript_regression',
            ))
        if expect.get('forbid_pid_change') and s.world.passage_id != pid_before:
            findings.append(Finding(
                'P0', 'regression', 'transcript', s.world.passage_id, utt,
                f'Unexpected passage change {pid_before}->{s.world.passage_id}',
                invariant='transcript_regression',
            ))
    return {'count': len(cases)}


def write_gate_doc(path: Path, report: dict, *, notes: Optional[str] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gate = {
        'name': report.get('gate_name') or 'puca_reality_gate',
        'rule': 'ANY P0, P1, or P2 finding fails the clean gate',
        'passed': report.get('clean_gate_passed'),
        'finding_counts': report.get('finding_counts'),
        'offline': report.get('offline'),
        'online_smoke': bool(report.get('online_smoke')),
        'seed': report.get('seed'),
        'quota_scale': report.get('quota_scale'),
        'quotas': report.get('quotas_achieved'),
        'timestamp': report.get('timestamp'),
        'report': str(report.get('report_path') or report.get('traces') or ''),
        'traces': str(report.get('traces') or ''),
    }
    if notes or report.get('notes'):
        gate['notes'] = notes or report.get('notes')
    path.write_text(json.dumps(gate, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def run_campaign(
    *,
    seed: int = 91,
    offline: bool = True,
    model: str = 'mistral',
    report_out: Path = DEFAULT_REPORT,
    trace_out: Path = DEFAULT_TRACES,
    gate_out: Path = DEFAULT_GATE_DOC,
    skip_agents: bool = False,
    quota_scale: float = 1.0,
    online_smoke: bool = False,
    agent_names: Optional[list[str]] = None,
    agent_max_turns: int = 12,
    notes: Optional[str] = None,
) -> dict:
    if online_smoke:
        offline = False
        if abs(quota_scale - 1.0) < 1e-9:
            quota_scale = 0.1
        agent_names = list(agent_names) if agent_names else list(ONLINE_SMOKE_AGENTS)
        agent_max_turns = min(int(agent_max_turns), 6)
        if report_out == DEFAULT_REPORT:
            report_out = DEFAULT_ONLINE_SMOKE_REPORT
        if trace_out == DEFAULT_TRACES:
            trace_out = DEFAULT_ONLINE_SMOKE_TRACES
        if gate_out == DEFAULT_GATE_DOC:
            gate_out = DEFAULT_ONLINE_SMOKE_GATE

    quotas = scale_quotas(BASE_QUOTAS, quota_scale)
    findings: list[Finding] = []
    sections: dict[str, Any] = {}
    report_out.parent.mkdir(parents=True, exist_ok=True)
    trace_out.parent.mkdir(parents=True, exist_ok=True)

    mode = 'online-smoke' if online_smoke else ('offline' if offline else 'online')
    print(
        f'Red-team campaign mode={mode} offline={offline} seed={seed} '
        f'model={model} quota_scale={quota_scale}',
        flush=True,
    )
    with trace_out.open('w', encoding='utf-8') as trace_fh:
        print('=== regressions ===', flush=True)
        sections['regressions'] = run_transcript_regressions(
            seed, offline, model, findings, trace_fh,
        )
        print(f'  findings so far={len(findings)}', flush=True)

        print('=== layer_a semantic ===', flush=True)
        sections['layer_a'] = run_layer_a(seed, offline, model, findings, trace_fh, quotas)
        print(f'  findings so far={len(findings)}', flush=True)

        print('=== layer_b reality ===', flush=True)
        sections['layer_b'] = run_layer_b(seed, offline, model, findings, trace_fh, quotas)
        print(f'  findings so far={len(findings)}', flush=True)

        # Online smoke: Layer C already prosecutes every A/B turn in _submit_checked.
        # Skip dedicated combat/playthrough/layer-c quota blocks to stay bounded.
        if not online_smoke:
            print('=== combat stall/pacifist ===', flush=True)
            sections['combat'] = run_combat_personas(
                seed, offline, model, findings, trace_fh, quotas,
            )
            print(f'  findings so far={len(findings)}', flush=True)

            print('=== layer_c narrator/image ===', flush=True)
            sections['layer_c'] = run_narrator_image_quotas(
                seed, offline, model, findings, trace_fh, quotas,
            )
            print(f'  findings so far={len(findings)}', flush=True)

            print('=== playthroughs ===', flush=True)
            sections['playthroughs'] = run_playthroughs(
                seed, offline, model, findings, trace_fh, quotas,
            )
            print(f'  findings so far={len(findings)}', flush=True)
        else:
            sections['layer_c'] = {
                'note': 'prosecutor+image checks run inline on every Layer A/B turn',
            }

        if not skip_agents:
            print('=== agents ===', flush=True)
            sections['agents'] = run_agents(
                seed, offline, model, findings, trace_fh,
                max_turns=agent_max_turns,
                agent_names=agent_names,
            )
            print(f'  findings so far={len(findings)}', flush=True)

    passed, rationale = clean_gate(findings)
    counts = severity_counts(findings)
    quotas_achieved = {
        'semantic_per_family': {
            fam: sections.get('layer_a', {}).get('families', {}).get(fam, {}).get('count', 0)
            for fam in layer_a.MAJOR_FAMILIES
        },
        'compound': sections.get('layer_a', {}).get('compound', 0),
        'ambiguity': sections.get('layer_a', {}).get('ambiguity', 0),
        'discourse': sections.get('layer_a', {}).get('discourse', 0),
        'stale_nonexistent': sections.get('layer_b', {}).get('count', 0),
        'combat_stall': sections.get('combat', {}).get('combat_stall', 0),
        'pacifist': sections.get('combat', {}).get('pacifist', 0),
        'narrator_truth': sections.get('layer_c', {}).get('narrator_truth', 0),
        'image_state': sections.get('layer_c', {}).get('image_state', 0),
        'playthroughs': sections.get('playthroughs', {}).get('count', 0),
    }

    try:
        from puca_dungeon.gold_verify import verify_gold
        gold = verify_gold()
    except Exception as exc:
        gold = {'ok': False, 'error': str(exc)}

    report = {
        'timestamp': time.time(),
        'offline': offline,
        'online_smoke': online_smoke,
        'quota_scale': quota_scale,
        'gate_name': 'puca_reality_gate_online_smoke' if online_smoke else 'puca_reality_gate',
        'model': model if not offline else 'HeuristicInterpreter+TemplateNarrator',
        'seed': seed,
        'finding_counts': counts,
        'clean_gate_passed': passed,
        'clean_gate_rationale': rationale,
        'findings': [f.to_dict() for f in findings],
        'sections': sections,
        'quotas_required': quotas,
        'quotas_achieved': quotas_achieved,
        'gold': gold,
        'report_path': str(report_out),
        'traces': str(trace_out),
        'agents': agent_names,
    }
    if notes:
        report['notes'] = notes
    report_out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    write_gate_doc(gate_out, report, notes=notes)

    print('\n=== CLEAN GATE ===', flush=True)
    print(rationale, flush=True)
    print(f'Report: {report_out}', flush=True)
    print(f'Traces: {trace_out}', flush=True)
    print(f'Gate doc: {gate_out}', flush=True)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            'PUCA three-layer red-team campaign (semantic / reality / narrator). '
            'Clean gate fails on any P0, P1, or P2 finding.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Online smoke (bounded live Ollama run):\n'
            '  python -m scripts.redteam --online-smoke --seed 91 --model mistral\n'
            '\n'
            '  --online-smoke implies online mode (Ollama required), quota scale 0.1,\n'
            '  Layer A/B at 10% of full quotas (all semantic families), Layer C\n'
            '  prosecutor/image checks on those turns, and short black-box runs of:\n'
            '  CombatStaller, ImpossiblePower, FoolishPhysical, SensibleCautious,\n'
            '  AmbiguousReply. Same hard gate (any P0/P1/P2 fails).\n'
            '\n'
            'Quota scaling (full or smoke):\n'
            '  --quota-scale 0.1   multiply all Layer A/B/C/playthrough quotas by 0.1\n'
            '                     (minimum 1 per quota). Combine with --online-smoke\n'
            '                     only if you need a scale other than the default 0.1.\n'
        ),
    )
    parser.add_argument('--seed', type=int, default=91)
    parser.add_argument('--model', default='mistral')
    parser.add_argument('--offline', action='store_true',
                        help='HeuristicInterpreter + TemplateNarrator (CI)')
    parser.add_argument(
        '--online-smoke',
        action='store_true',
        help=(
            'Bounded online gate: 10%% Layer A/B quotas (all families), Layer C on '
            'those outputs, 5 short agent runs, hard P0/P1/P2 gate. Requires Ollama. '
            'Writes docs/verification/puca_reality_gate_online_smoke.json by default.'
        ),
    )
    parser.add_argument(
        '--quota-scale',
        type=float,
        default=1.0,
        help=(
            'Multiply campaign quotas (default 1.0). Example: 0.1 for a cheap run. '
            'With --online-smoke, default scale is 0.1 unless you override.'
        ),
    )
    parser.add_argument('--report-out', type=Path, default=DEFAULT_REPORT)
    parser.add_argument('--trace-out', type=Path, default=DEFAULT_TRACES)
    parser.add_argument('--gate-out', type=Path, default=DEFAULT_GATE_DOC)
    parser.add_argument('--skip-agents', action='store_true')
    parser.add_argument(
        '--agents',
        default=None,
        help='Comma-separated agent persona names (default: all, or smoke set with --online-smoke)',
    )
    parser.add_argument(
        '--agent-max-turns',
        type=int,
        default=12,
        help='Max turns per black-box agent (online-smoke caps at 6)',
    )
    args = parser.parse_args(argv)

    if args.online_smoke and args.offline:
        parser.error('--online-smoke cannot be combined with --offline')
    if args.quota_scale <= 0:
        parser.error('--quota-scale must be > 0')

    agent_names = None
    if args.agents:
        agent_names = [p.strip() for p in args.agents.split(',') if p.strip()]

    report = run_campaign(
        seed=args.seed,
        offline=args.offline,
        model=args.model,
        report_out=args.report_out,
        trace_out=args.trace_out,
        gate_out=args.gate_out,
        skip_agents=args.skip_agents,
        quota_scale=args.quota_scale,
        online_smoke=args.online_smoke,
        agent_names=agent_names,
        agent_max_turns=args.agent_max_turns,
    )
    return 0 if report.get('clean_gate_passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
