"""Turn composer: authoritative, ordered prose from a resolved turn.

Order is the whole point. Every turn reads:

  1. what Sarel did / tried              (act, speech as actually spoken, body veto)
  2. how the people present responded    (npc_beat facts: reply first, ambient second)
  3. what the institution then did       (scene_change / phase events, in time order)
  4. where that leaves you               (room arrival line, ONLY when the room changed)
  5. the Voice                           (optional, last, set apart)

Python owns every sentence here. The LLM (if any) may only polish sentence
rhythm afterwards and must preserve all names, quotes and content.
"""
from __future__ import annotations

import re
from typing import Any

from puca_dungeon.characters import name_of

_ROOM_ARRIVAL = {
    'corridor': 'A corridor. The same bolts as the cell door, repeated down its length.',
    'washroom': 'A washroom. Water in a basin; soap that smells of medicine rather than flowers.',
    'mess': 'A mess room. One narrow table. One bowl, steam coming off it.',
    'cell': 'The cell again. Whatever you moved is still where you left it.',
    'interview': 'A brighter room. A table laid with pictures and small objects, like a lesson. A woman with a fitted collar sits opposite.',
    'prep': 'A room that hums. Straps hanging unused. A tray of clean instruments.',
    'heaven': 'Warm air. Sunlight through leaves. Clean bedding, fruit, running water. Birds — or a recording of birds.',
    'hell': 'Heat and a sweet, rotten smell. Light that never rests. A surface not meant for sleep. No demons. Only engineering.',
    'research_quarters': 'A small room in the research wing. A bed, a desk. A door that is not locked from the outside.',
}

_STAFF_PHRASE = {
    'orderly_quiet': 'the big orderly',
    'orderly_anxious': 'the younger orderly',
    'senior_researcher': 'the collared woman',
    'attendant_a': 'the attendant',
    'attendant_b': 'the other attendant',
}

# Facts produced by resolve that are *institution* lines rather than Sarel's act.
_INSTITUTION_MARKERS = (
    'they are still waiting', 'the observation slit', 'the door procedure begins',
    'the door opens under their rules', 'they take you', 'they walk you', 'the person at the door abandons',
    'the hum rises', 'they register you',
    'resistance fails. you are washed', 'whether by choice or stomach', 'they do not leave the food',
    'the bed, once bleak', 'a magnificent plan to stay awake', 'you wake in the same cell. it is a new day',
    'morning. the collection', 'you are taken into an interview', 'they offer a five-year',
    'a clean professional arrives', 'the agreement is processed', 'they register you',
    'you lose consciousness during', 'you are sedated and taken', 'they tell you the entitlement',
    'the questioning changes', 'a smell in the room prompts', 'warmth. sunlight. clean bedding',
    'then they ask about the other place', 'they explain, in slow words', 'the printed corridor breaks',
    'they do not punish you. they explain', 'day 1 is ending',
)


def _is_institution_fact(f: str) -> bool:
    fl = f.lower().strip()
    return any(fl.startswith(m) or m in fl[:80] for m in _INSTITUTION_MARKERS)


def _room_desc_texts(facility) -> set[str]:
    out = set()
    for r in (getattr(facility, 'rooms', None) or {}).values():
        d = str((r or {}).get('description') or '').strip()
        if d:
            out.add(d)
    return out


def person_phrase(cast: dict, cid: str, *, known_names: set[str]) -> str:
    """Sarel does not know staff names unless she has been told. Subjects give theirs."""
    if cid in known_names or cid in ('iven', 'nessa', 'ruan'):
        return name_of(cast, cid)
    return _STAFF_PHRASE.get(cid, 'someone')


def _quote(s: str) -> str:
    s = (s or '').strip()
    if not s:
        return ''
    return f'“{s}”'


def render_speech_fact(sf: dict) -> list[str]:
    """Sarel's utterance: intended → spoken, with the loss visible but not lectured."""
    spoken = str(sf.get('spoken') or '').strip()
    fidelity = str(sf.get('fidelity') or '')
    gesture = str(sf.get('gesture') or '').strip()
    to_voice = bool(sf.get('addressed_to_voice'))
    if to_voice:
        return []  # handled in the voice section
    lines: list[str] = []
    if fidelity == 'full':
        lines.append(f'You say it: {_quote(spoken)}')
    elif fidelity == 'partial':
        lines.append(f'What comes out is smaller than what you meant: {_quote(spoken)}')
    elif fidelity == 'fragment':
        if gesture:
            lines.append(f'The sentence is all there, behind your teeth. One word gets through — {_quote(spoken)} — and {gesture}.')
        else:
            lines.append(f'One word gets through: {_quote(spoken)}')
    else:
        if gesture:
            lines.append(f'None of it survives the trip to your mouth. What you have instead is {gesture}.')
        else:
            lines.append('Your mouth opens. The language you need is not in it.')
    return lines


def render_npc_beat(nb: dict, cast: dict, known_names: set[str]) -> str:
    who = person_phrase(cast, str(nb.get('speaker') or ''), known_names=known_names)
    kind = nb.get('kind')
    body = str(nb.get('body') or '').strip()
    if kind == 'speech':
        foreign = str(nb.get('foreign') or '').strip()
        caught = str(nb.get('caught') or '').strip()
        meaning = str(nb.get('meaning') or '').strip()
        if foreign:
            # Staff: sound first, then what you catch
            core = f'{who[0].upper() + who[1:]}: {_quote(foreign)}'
            if caught and caught != '…':
                core += f' You catch: {_quote(caught)}'
            else:
                core += ' You catch none of it.'
        else:
            core = f'{who[0].upper() + who[1:]}: {_quote(meaning)}'
        return f'{core} {body}'.strip() if body else core
    # gesture / action
    return body


def _dedupe(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for l in lines:
        k = re.sub(r'\W+', ' ', (l or '').lower()).strip()
        if not k or k in seen:
            continue
        # skip near-duplicates (one contains the other)
        if any(k in s or s in k for s in seen if len(k) > 30 and len(s) > 30):
            continue
        seen.add(k)
        out.append(l.strip())
    return out


def compose(world, resolution, *, room_before: str, known_names: set[str]) -> dict:
    """Return {'paragraphs': [...], 'voice': str|None, 'sections': {...}} in causal order."""
    facility = getattr(world, 'facility', None)
    cast = getattr(facility, 'cast', None) or {}
    facts = [f for f in (resolution.facts or []) if isinstance(f, str) and f.strip()]
    structured = [f for f in (getattr(resolution, 'structured_facts', None) or []) if isinstance(f, dict)]
    events = [e for e in (getattr(resolution, 'world_events', None) or []) if isinstance(e, dict)]
    room_descs = _room_desc_texts(facility) if facility is not None else set()

    # ---- 1. Sarel's act -------------------------------------------------------
    act: list[str] = []
    speech_facts = [s for s in structured if s.get('type') == 'speech']
    for f in facts:
        if f in room_descs:
            continue
        if _is_institution_fact(f):
            continue
        if f.startswith('Entered passage') or f.startswith('passage_id='):
            continue
        if f.startswith('You manage:') or f.startswith('Your mouth produces:'):
            continue  # replaced by render_speech_fact
        if f.startswith('Here:') or f.startswith('They are still waiting'):
            continue
        if re.match(r'^[A-Z][a-z]+ (repeats a short sound|is here\. They listen)', f):
            continue  # legacy NPC stubs — npc_beat replaces them
        act.append(f)
    for sf in speech_facts:
        act.extend(render_speech_fact(sf))
    understood = [s for s in structured if s.get('type') == 'understood_not_enacted']
    for u in understood:
        if u.get('text'):
            act.append(str(u['text']))

    # ---- 2. People respond ----------------------------------------------------
    people: list[str] = []
    beats = [s for s in structured if s.get('type') == 'npc_beat']
    beats.sort(key=lambda b: -int(b.get('weight', 1) or 1))
    for nb in beats:
        line = render_npc_beat(nb, cast, known_names)
        if line:
            people.append(line)

    # ---- 3. Institution moves ---------------------------------------------------
    inst: list[str] = []
    # Stable order: explicit 'order' first, then non-scene events, then scene_change (the move itself)
    events = sorted(events, key=lambda e: (int(e.get('order', 0) or 0), 1 if e.get('type') == 'scene_change' else 0))
    for ev in events:
        txt = str(ev.get('text') or '').strip()
        if not txt or ev.get('type') in ('restated_ask', 'npc_beat', 'voice'):
            continue
        if ev.get('type') in ('body_notice',):
            continue  # sensations handled below
        if txt in room_descs:
            continue
        inst.append(txt)
    for f in facts:
        if _is_institution_fact(f) and f not in inst and f not in room_descs and not f.startswith('They are still waiting'):
            inst.append(f)

    # ---- 4. Where you are now -------------------------------------------------
    where: list[str] = []
    room_now = str(getattr(facility, 'room_id', '') or '') if facility is not None else ''
    if facility is not None and room_now and room_now != room_before:
        where.append(_ROOM_ARRIVAL.get(room_now, ''))
        present = list(getattr(getattr(facility, 'arc', None), 'present_ids', None) or [])
        if present:
            names = [person_phrase(cast, c, known_names=known_names) for c in present]
            if len(names) == 1:
                where.append(f'{names[0][0].upper() + names[0][1:]} is here.')
            else:
                where.append('Here: ' + ', '.join(names[:-1]) + f' and {names[-1]}.')

    # ---- body ---------------------------------------------------------------
    body: list[str] = []
    for ev in events:
        if ev.get('type') == 'body_notice' and ev.get('text'):
            body.append(str(ev['text']))

    # ---- 5. voice -------------------------------------------------------------
    voice = None
    for s in structured:
        if s.get('type') == 'voice' and s.get('text'):
            voice = str(s['text'])

    # ---- pending ask (once, at the end, only if still open and staff present) ----
    ask_line = ''
    if facility is not None and getattr(facility, 'staff_present', False):
        arc = getattr(facility, 'arc', None)
        ask = str(getattr(arc, 'last_ask', '') or '')
        asked_this_turn = any(e.get('type') == 'interview_question' for e in events)
        if ask and not where and not asked_this_turn and not any(ask.lower() in p.lower() for p in inst + people):
            reps = int(getattr(arc, 'ask_repeats', 0) or 0)
            if reps < 2:
                ask_line = _ask_sentence(ask)
            elif reps % 3 == 0:
                ask_line = _ask_sentence_late(ask)
            if arc is not None:
                arc.ask_repeats = reps + 1

    paragraphs: list[str] = []
    for chunk in (_dedupe(act), _dedupe(people), _dedupe(inst), _dedupe(where), _dedupe(body)):
        chunk = [c for c in chunk if c]
        if chunk:
            paragraphs.append(' '.join(chunk))
    if ask_line:
        paragraphs.append(ask_line)
    if not paragraphs:
        paragraphs.append(_nothing_line(facility))
    return {
        'paragraphs': paragraphs,
        'voice': voice,
        'sections': {'act': act, 'people': people, 'institution': inst, 'where': where, 'body': body},
    }


def _ask_sentence(ask: str) -> str:
    a = ask.lower()
    if 'door' in a:
        return 'They are still waiting for you to step away from the door.'
    if a == 'wash':
        return 'They are waiting to wash you. They have time.'
    if a == 'eat':
        return 'The bowl is still in front of you. They are waiting.'
    if 'question' in a:
        return 'They wait for an answer. Silence is also an answer, and they write that down too.'
    if 'agree' in a:
        return 'The agreement is still on the table between you.'
    return f'They are still waiting: {ask}.'


def _ask_sentence_late(ask: str) -> str:
    a = ask.lower()
    if 'door' in a:
        return 'The gesture again: back. They are not going to get bored before you do.'
    if a == 'wash':
        return 'The water is still there. So are they.'
    if a == 'eat':
        return 'The steam off the bowl has thinned. Nobody has moved it.'
    if 'agree' in a:
        return 'She has not repeated the offer. She does not need to.'
    return ''


def _nothing_line(facility) -> str:
    if facility is not None and getattr(facility, 'staff_present', False):
        return 'Nothing changes. They watch you not change it.'
    return 'A moment passes. The room keeps it.'


def to_text(composed: dict) -> str:
    paras = list(composed.get('paragraphs') or [])
    voice = composed.get('voice')
    out = '\n\n'.join(p for p in paras if p)
    if voice:
        out = (out + '\n\n' if out else '') + f'— {voice}'
    return out.strip()
