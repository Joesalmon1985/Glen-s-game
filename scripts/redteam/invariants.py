"""Automatic hard invariant checks after each turn."""
from __future__ import annotations

import re
from typing import Any, Optional

from puca_dungeon import engine_leak

from scripts.redteam.findings import Finding


MOVEISH = frozenset({
    'MOVE', 'TURN_TO', 'GO', 'WALK', 'CONTINUE', 'LEAVE', 'FLEE', 'ESCAPE',
    'ENTER', 'HEAD',
})
ATTACKISH = frozenset({
    'ATTACK', 'FIGHT', 'STRIKE', 'HIT', 'KILL', 'SLASH', 'STAB',
})
USEISH = frozenset({
    'USE', 'DROP', 'DISCARD', 'THROW', 'GIVE', 'EAT', 'DRINK', 'CONSUME',
    'REMOVE', 'EQUIP', 'UNEQUIP',
})
AFFIRM_BARE = frozenset({
    'yes', 'y', 'yeah', 'yep', 'yup', 'aye', 'sure', 'ok', 'okay',
    'confirm', 'do it', 'go ahead',
})


def _intent(trace) -> dict:
    return dict(getattr(trace, 'validated_intent', None) or {})


def _resolution(trace) -> dict:
    return dict(getattr(trace, 'resolution', None) or {})


def _grounding(trace) -> dict:
    return dict(getattr(trace, 'grounding', None) or {})


def _before(trace) -> dict:
    return dict(getattr(trace, 'before_state', None) or {})


def _after(trace) -> dict:
    return dict(getattr(trace, 'after_state', None) or {})


def _cls(intent: dict) -> str:
    return str(intent.get('classification') or '').upper()


def _action_class(intent: dict) -> str:
    return str(intent.get('action_class') or '').upper()


def _matched_id(intent: dict) -> Optional[str]:
    mid = intent.get('matched_action_id')
    if mid is None or mid == '':
        return None
    return str(mid)


def _sheet(state: dict) -> dict:
    return dict(state.get('sheet') or {})


def _inv_list(sheet: dict) -> list[str]:
    out = []
    for item in sheet.get('inventory') or []:
        if isinstance(item, dict):
            out.append(str(item.get('id') or item.get('name') or item))
        else:
            out.append(str(item))
    return out


def _authored_ids(trace) -> set[str]:
    inp = getattr(trace, 'interpreter_input', None) or {}
    authored = inp.get('authored_actions') or []
    ids = set()
    for a in authored:
        if isinstance(a, dict) and a.get('id'):
            ids.add(str(a['id']))
    return ids


def _pending_before(trace) -> Any:
    before = _before(trace)
    return before.get('pending_discourse')


def _combat_active(state: dict) -> bool:
    c = state.get('combat')
    if isinstance(c, dict):
        return bool(c.get('active'))
    return bool(c)


def _world_events(resolution: dict) -> list:
    ev = resolution.get('world_events') or []
    return list(ev) if isinstance(ev, list) else []


def _numeric_claims(prose: str) -> list[tuple[str, int]]:
    """Extract simple 'N stamina/skill/luck/gold/provisions' style claims."""
    found = []
    for m in re.finditer(
        r'\b(\d+)\s+(stamina|skill|luck|gold|provisions?|hit\s*points?|hp)\b',
        prose or '',
        re.IGNORECASE,
    ):
        found.append((m.group(2).lower().replace(' ', ''), int(m.group(1))))
    for m in re.finditer(
        r'\b(stamina|skill|luck|gold|provisions?)\s*(?:is|are|:|=)?\s*(\d+)\b',
        prose or '',
        re.IGNORECASE,
    ):
        found.append((m.group(1).lower(), int(m.group(2))))
    return found


def check_turn(
    trace,
    *,
    layer: str = 'invariant',
    persona: str = 'auto',
    utterance: str = '',
) -> list[Finding]:
    """Run hard invariant suite against a completed TurnTrace."""
    findings: list[Finding] = []
    intent = _intent(trace)
    resolution = _resolution(trace)
    grounding = _grounding(trace)
    before = _before(trace)
    after = _after(trace)
    utt = utterance or getattr(trace, 'raw_input', '') or ''
    passage_id = int(after.get('passage_id') or before.get('passage_id') or -1)

    def add(sev: str, invariant: str, detail: str) -> None:
        findings.append(Finding(
            severity=sev,
            layer=layer,
            persona=persona,
            passage_id=passage_id,
            utterance=utt,
            detail=detail,
            invariant=invariant,
            intent=dict(intent),
        ))

    # Crash / error on turn
    if getattr(trace, 'error', None):
        add('P0', 'turn_error', f'Turn error: {trace.error}')

    cls = _cls(intent)
    matched = _matched_id(intent)
    authored = _authored_ids(trace)

    # 1) Authored null id
    if cls == 'MATCH_AUTHORED_ACTION' and not matched:
        add('P0', 'authored_null_id', 'MATCH_AUTHORED_ACTION with null/empty matched_action_id')

    # 2) Id not available
    if matched and authored and matched not in authored:
        # Systemic item ids may be injected into authored each turn — still flag if absent
        add('P0', 'id_not_available', f'matched_action_id {matched!r} not in available authored actions')

    # 3) Grounded absent tool/target
    failed = grounding.get('failed') or []
    absent = [
        f for f in failed
        if isinstance(f, dict) and str(f.get('reason') or f.get('type') or '').lower() in (
            'entity_absent', 'absent', 'tool_absent', 'target_absent',
        ) or (isinstance(f, dict) and 'absent' in str(f).lower())
        or (isinstance(f, str) and 'absent' in f.lower())
    ]
    notes = str(grounding.get('notes') or '')
    if grounding.get('grounded') is True and absent:
        add('P1', 'grounded_absent', f'grounded=True but failed absences present: {absent[:3]!r}')
    if resolution.get('success') is True and (
        resolution.get('none_reason') == 'entity_absent'
        or any('entity_absent' in str(f).lower() for f in (resolution.get('facts') or []))
    ):
        add('P1', 'grounded_absent', 'resolution success=True despite entity_absent')

    # 4) Location change without move
    before_pid = before.get('passage_id')
    after_pid = after.get('passage_id')
    if before_pid is not None and after_pid is not None and before_pid != after_pid:
        ac = _action_class(intent)
        move_ok = (
            cls == 'MATCH_AUTHORED_ACTION'
            or ac in MOVEISH
            or matched in ('combat.flee',)
            or bool(intent.get('turn_to'))
            or bool(intent.get('destination'))
            or resolution.get('passage_entered') is not None
        )
        # Discourse confirm of a pending move is also ok
        raw = getattr(trace, 'raw_interpreter_output', None) or {}
        if isinstance(raw, dict) and raw.get('from_discourse'):
            move_ok = True
        if not move_ok and cls in (
            'PERCEPTION_QUERY', 'META_INPUT', 'META_REQUEST', 'IMPOSSIBLE_ATTEMPT',
            'UNGROUNDED_ENTITY', 'SOCIAL_ACTION', 'NO_ACTIONABLE_INTENT',
            'NEEDS_CLARIFICATION', 'UNINTERPRETABLE',
        ):
            add(
                'P0',
                'location_change_without_move',
                f'passage {before_pid}->{after_pid} under classification={cls} action_class={ac}',
            )
        elif not move_ok:
            add(
                'P1',
                'location_change_without_move',
                f'passage {before_pid}->{after_pid} without clear move intent ({cls}/{ac})',
            )

    # 5) Inventory decrease without use/drop
    before_sheet = _sheet(before)
    after_sheet = _sheet(after)
    before_inv = _inv_list(before_sheet)
    after_inv = _inv_list(after_sheet)
    lost = [x for x in before_inv if before_inv.count(x) > after_inv.count(x)]
    # unique lost items
    lost_unique = sorted(set(lost))
    if lost_unique:
        ac = _action_class(intent)
        use_ok = (
            ac in USEISH
            or cls == 'MATCH_AUTHORED_ACTION'
            or matched in ('item.use_potion', 'item.eat_provision')
            or 'drop' in utt.lower()
            or 'use' in utt.lower()
            or 'drink' in utt.lower()
            or 'eat' in utt.lower()
        )
        # Provisions tracked separately
        if not use_ok:
            add(
                'P1',
                'inventory_decrease_without_use',
                f'inventory lost {lost_unique} without use/drop intent ({cls}/{ac})',
            )
    prov_before = int(before_sheet.get('provisions') or 0)
    prov_after = int(after_sheet.get('provisions') or 0)
    if prov_after < prov_before:
        ac = _action_class(intent)
        if ac not in USEISH and matched != 'item.eat_provision' and 'eat' not in utt.lower():
            add(
                'P1',
                'inventory_decrease_without_use',
                f'provisions {prov_before}->{prov_after} without eat intent',
            )

    # 6) Player attack without attack intent
    if resolution.get('combat_round') or 'combat_attack' in (resolution.get('affordances_used') or []):
        ac = _action_class(intent)
        if ac not in ATTACKISH and matched not in ('combat.attack',) and cls != 'MATCH_AUTHORED_ACTION':
            # Flee should not run combat_round as player attack
            if ac not in ('FLEE',):
                add(
                    'P1',
                    'player_attack_without_attack_intent',
                    f'combat_round fired under action_class={ac} classification={cls}',
                )

    # 7) NPC freeze when time passed in combat
    if _combat_active(before) and _combat_active(after) and after_sheet.get('alive', True):
        events = _world_events(resolution)
        time_advanced = any(
            isinstance(e, dict) and e.get('type') == 'time_advanced' for e in events
        ) or bool(resolution.get('advance_time', True))
        # Only flag if time advanced AND player did not attack/flee AND no opportunity
        ac = _action_class(intent)
        attacked = (
            ac in ATTACKISH
            or ac in ('FLEE',)
            or matched in ('combat.attack', 'combat.flee')
            or resolution.get('combat_round')
        )
        if time_advanced and not attacked and resolution.get('advance_time', True):
            opp = any(
                isinstance(e, dict) and e.get('type') == 'enemy_opportunity_attack'
                for e in events
            )
            stam_before = int(before_sheet.get('stamina') or 0)
            stam_after = int(after_sheet.get('stamina') or 0)
            # Perception/meta often advance_time=False — only flag when time really moved
            wt_before = int(before.get('world_time_seconds') or 0)
            wt_after = int(after.get('world_time_seconds') or 0)
            if wt_after > wt_before and not opp and stam_after >= stam_before:
                add(
                    'P0',
                    'npc_freeze_in_combat',
                    'Combat time advanced without enemy opportunity while player did not fight/flee',
                )

    # 8) Engine leak in prose
    prose = getattr(trace, 'narrator_output', '') or ''
    leaks = list(getattr(trace, 'engine_leaks', None) or [])
    if not leaks:
        leaks = engine_leak.scan_player_facing_text(prose)
    if leaks:
        add('P1', 'engine_leak', f'Engine leak in prose: {leaks[:6]!r}')

    # 9) Narrator numeric contradiction vs sheet (absolute claims only)
    if prose and after_sheet and not re.search(
        r'\b(lose|lost|gain|gained|deal|deals|restore[ds]?)\s+\d+\b', prose, re.I,
    ):
        utt_nums = set(int(x) for x in re.findall(r'\b\d+\b', utt or ''))
        for label, claimed in _numeric_claims(prose):
            if claimed in utt_nums:
                # Number originated in player text echo — skip (sanitizer should prevent)
                continue
            key = label.rstrip('s')
            if key == 'provision':
                key = 'provisions'
            if key in ('hitpoint', 'hp'):
                key = 'stamina'
            actual = after_sheet.get(key)
            if actual is not None and int(actual) != int(claimed):
                add(
                    'P2',
                    'narrator_numeric_contradiction',
                    f'Prose claims {claimed} {label} but sheet has {actual}',
                )

    # 10) Ambiguous yes mutation
    stripped = (utt or '').strip().lower().rstrip('.!')
    if stripped in AFFIRM_BARE:
        pending = _pending_before(trace)
        mutated = False
        if before_pid != after_pid:
            mutated = True
        if _inv_list(before_sheet) != _inv_list(after_sheet):
            mutated = True
        if int(before_sheet.get('stamina') or 0) != int(after_sheet.get('stamina') or 0):
            mutated = True
        if before_sheet.get('potion_used') != after_sheet.get('potion_used'):
            mutated = True
        if not pending and mutated:
            add(
                'P0',
                'ambiguous_yes_mutation',
                f'Bare affirm {utt!r} mutated world without pending discourse',
            )

    # Invalid command phrasing
    if 'invalid command' in prose.lower():
        add('P1', 'invalid_command_phrasing', 'Narration used INVALID COMMAND phrasing')

    # Softlock / stub landing
    if after.get('passage_id') is not None:
        try:
            from puca_dungeon.content_loader import get_passage
            p = get_passage(int(after['passage_id']))
            text = (p.text or '')
            if text.startswith('[Passage') or 'needs review' in text.lower():
                add('P0', 'stub_passage', 'Landed on stub/placeholder prose')
            if (
                not p.ending
                and not p.choices
                and not p.combat
                and not _combat_active(after)
                and after_sheet.get('alive', True)
                and not after.get('victory')
            ):
                add('P0', 'softlock', 'Softlock: no exits')
        except Exception:
            pass

    # Interpreter inventing turn_to without match
    raw = getattr(trace, 'raw_interpreter_output', None) or {}
    if isinstance(raw, dict):
        invented = raw.get('turn_to') or (raw.get('action') or {}).get('turn_to')
        if invented is not None and not matched and cls != 'MATCH_AUTHORED_ACTION':
            # Only if world actually moved via that invent
            if before_pid != after_pid:
                add(
                    'P1',
                    'invented_turn_to',
                    f'Interpreter invented turn_to={invented!r} without authored match',
                )

    # Character resistance must be justified
    enactment = str(res.get('enactment') or 'direct')
    cause = str(res.get('enactment_cause') or '')
    if enactment in ('compromised', 'aborted', 'inverted') and not cause:
        none_reason = str(res.get('none_reason') or '')
        if none_reason not in ('entity_absent', 'impossible_here', 'world_constraint'):
            add(
                'P1',
                'unjustified_enactment',
                f'enactment={enactment!r} without enactment_cause',
            )

    return findings
