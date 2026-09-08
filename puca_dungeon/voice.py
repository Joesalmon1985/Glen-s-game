"""The Voice: a diegetic second intelligence that comments on what Sarel perceives.

Rules (from the design brief):
  * It is a character, not Python's omniscient authority. It only knows what Sarel
    can perceive plus its own (fallible) opinions. It never states hidden world state.
  * It has an agenda: keep Sarel alive, keep her curious, keep her sceptical of the
    institution. It can be wrong, sarcastic, frightened, perceptive.
  * The player can address it. Boundary-testing ("are you the game?") is gameplay.
  * It can be told to shut up. It sulks, then returns when something matters.
  * Its tone shifts with Sarel's accumulated behaviour: absurd/impulsive habits make
    it treat strange impulses as familiar; hostility makes it blunter; curiosity
    makes it foreground anomalies.

Deterministic. Text only. Never exposes meters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class VoiceLine:
    text: str
    kind: str = 'comment'   # comment | reply | silence | return

    def to_fact(self) -> dict:
        return {'type': 'voice', 'kind': self.kind, 'text': self.text}


_MOOD_BY_TENDENCY = (
    ('absurdity', 5, 'weary_fond'),
    ('aggression', 5, 'blunt'),
    ('curiosity', 5, 'sharp'),
    ('compliance', 6, 'uneasy'),
    ('defiance', 5, 'approving'),
)


def mood(tendencies: dict) -> str:
    t = tendencies or {}
    best = 'level'
    best_v = 0
    for key, thresh, name in _MOOD_BY_TENDENCY:
        v = int(t.get(key, 0) or 0)
        if v >= thresh and v > best_v:
            best, best_v = name, v
    return best


# --------------------------------------------------------------------------- addressing the voice

def reply(player_text: str, *, state: dict, tendencies: dict, room: str, present_names: list[str],
          knows: list[str]) -> Optional[VoiceLine]:
    """Player spoke to the Voice. `state` is a mutable dict persisted on the arc."""
    t = (player_text or '').lower().strip()
    silenced = int(state.get('silenced_turns', 0) or 0)
    asked_identity = int(state.get('asked_identity', 0) or 0)
    m = mood(tendencies)

    if re.search(r'\b(shut up|be quiet|stop talking|quiet|silence|go away|leave me alone)\b', t):
        state['silenced_turns'] = 3
        state['times_silenced'] = int(state.get('times_silenced', 0) or 0) + 1
        n = state['times_silenced']
        if n == 1:
            return VoiceLine('Fine.', 'reply')
        if n == 2:
            return VoiceLine('Fine. Again. You know I come back.', 'reply')
        return VoiceLine('…', 'reply')

    if re.search(r'\b(are you (the )?(game|narrator|computer|program|ai)|is this a game|am i in a game)\b', t):
        state['asked_meta'] = int(state.get('asked_meta', 0) or 0) + 1
        if state['asked_meta'] == 1:
            return VoiceLine(
                'If I were, would I tell you? Look at the door instead. The door is real. Start there.', 'reply')
        return VoiceLine('You keep asking that as if the answer would open the door.', 'reply')

    if re.search(r'\b(who|what) (are|is) (you|this|that)\b|\bwho said that\b|\bwhose voice\b', t):
        state['asked_identity'] = asked_identity + 1
        if asked_identity == 0:
            return VoiceLine(
                'The part of you that is still paying attention. Or something that got in while you were asleep. '
                'I have not decided which I would rather be.', 'reply')
        if asked_identity == 1:
            return VoiceLine('Still here. Still not sure. You woke up with me — that is all either of us knows.', 'reply')
        return VoiceLine('Ask the woman with the collar. She looks like someone who knows what is in people\'s heads.', 'reply')

    if re.search(r'\bhow do you know\b|\bwhy shouldn\'?t i\b|\bwhy not\b', t):
        if present_names:
            return VoiceLine(
                f'I don\'t know. I notice. {present_names[0]} keeps looking at the corridor, not at you. '
                'People look where the danger is, or where the help is. Decide which.', 'reply')
        return VoiceLine('I don\'t know. I guess, and I guess carefully. You would do well to copy that.', 'reply')

    if re.search(r'\b(tell me|what.?s|what is) (behind|outside|beyond) (the )?door\b', t):
        return VoiceLine('I can see exactly what you can see, which is a door. Disappointing, I know.', 'reply')

    if re.search(r'\b(help me|what (do|should) i do|what now|advice)\b', t):
        if 'door' in ' '.join(knows):
            return VoiceLine('They want you away from the door. Everything else is optional. Whether you *give* it to them is the only interesting question in the room.', 'reply')
        return VoiceLine('Learn the room. Learn the people. Nobody has hurt you yet — that is information too.', 'reply')

    if re.search(r'\b(thank|thanks)\b', t):
        return VoiceLine('Don\'t. I might be wrong about everything.', 'reply')

    if re.search(r'\b(are you real|am i mad|am i crazy|insane|hearing voices)\b', t):
        return VoiceLine(
            'You are in a locked room with no memory of arriving, and the question that worries you is *me*? '
            'Prioritise.', 'reply')

    if silenced > 0:
        return None
    # Generic: it answers like a person, not a help system
    if m == 'weary_fond':
        return VoiceLine('Mm. I heard you. I usually do.', 'reply')
    return VoiceLine('I heard you. I am thinking about it.', 'reply')


# --------------------------------------------------------------------------- unprompted comment

def comment(*, state: dict, tendencies: dict, phase: str, room: str, enactment: str, tags: list[str],
            force: str, present_names: list[str], ask: str, fear: int, fatigue: int, hunger: int,
            discoveries: list[str], turn_seed: int, first_turn: bool, new_scene: bool) -> Optional[VoiceLine]:
    """Occasional unprompted line. Returns None most turns; the Voice is not a narrator."""
    silenced = int(state.get('silenced_turns', 0) or 0)
    if silenced > 0:
        state['silenced_turns'] = silenced - 1
        if silenced == 1 and (new_scene or fear >= 60):
            return VoiceLine('— all right, I know you told me to stop. But look.', 'return')
        return None
    m = mood(tendencies)
    absurd = 'absurdity' in tags
    aggressive = 'aggression' in tags or 'hostility' in tags

    if first_turn:
        return VoiceLine('Something is off about the light. Or about you. Start with the room; the room can\'t lie.', 'comment')

    if absurd:
        n = int(state.get('absurd_seen', 0) or 0) + 1
        state['absurd_seen'] = n
        if n == 1:
            return VoiceLine('That was… a choice. I am going to pretend I did not see it, once.', 'comment')
        if n == 2:
            return VoiceLine('Again? You are consistent, at least. They are watching, you know.', 'comment')
        if n <= 5:
            return VoiceLine('Yes. Of course. Why not.', 'comment')
        return VoiceLine('Right. Business as usual, then.', 'comment') if turn_seed % 2 else None

    if aggressive:
        if enactment in ('aborted', 'compromised'):
            return VoiceLine('Your body has opinions about that. Stronger ones than you, apparently.', 'comment')
        if m == 'blunt':
            return VoiceLine('Good. Now count them. There are more of them than there are of you, and they know it.', 'comment')
        return VoiceLine('That is one way to introduce yourself.', 'comment')

    if new_scene:
        seen = list(state.get('scene_comments', []) or [])
        key = f'{room}:{phase}'
        if room in seen:
            # Second visit to the same kind of room: shorter, different
            second = {
                'corridor': 'The corridor again. You are learning its length by feel.',
                'cell': None,
                'interview': 'Back at the table. Same pictures, probably. Watch what she skips.',
                'mess': None,
                'washroom': None,
            }.get(room, None)
            return VoiceLine(second, 'comment') if second else None
        seen.append(room)
        state['scene_comments'] = seen[-12:]
        if room == 'corridor':
            return VoiceLine('Same bolts as the door. Whoever built this built all of it.', 'comment')
        if room == 'washroom':
            return VoiceLine('They are not punishing you. Notice that. It would be simpler if they were.', 'comment')
        if room == 'mess':
            return VoiceLine('Food is a fact. Eat the fact.', 'comment') if hunger >= 50 else VoiceLine('Warm. Real. Look at their faces while you decide.', 'comment')
        if room == 'interview':
            return VoiceLine('The collar. Look at the collar. She wears it like a wedding ring.', 'comment')
        if room == 'heaven':
            return VoiceLine('Well. It is lovely. That is exactly what worries me. Check your arm — the bruise.', 'comment')
        if room == 'hell':
            return VoiceLine('Breathe. Slowly. Someone built this to make you stop thinking. Don\'t give it to them.', 'comment')
        if room == 'research_quarters':
            return VoiceLine('Inside now. Doors open both ways when they trust you. Remember that.', 'comment')
        if 'slit' in phase:
            return VoiceLine('He wants something. I think — distance. He is not afraid of you. He is careful about you.', 'comment')
        if 'door' in phase:
            return VoiceLine('They will come in whether you move or not. The question is what you want them to see.', 'comment')
        return None

    # Occasional perceptive lines gated by seed so it does not chatter
    if turn_seed % 4 != 0:
        return None
    if force.startswith('question') and present_names and 'orderly' in ' '.join(present_names).lower():
        return VoiceLine('He understood the *shape* of that. Not the words.', 'comment')
    if fear >= 60:
        return VoiceLine('You are afraid. Fine. Afraid people notice things. Use it.', 'comment')
    if fatigue >= 70:
        return VoiceLine('You are going to sleep soon whether you decide to or not.', 'comment')
    if 'bodily_continuity' in discoveries and room in ('heaven', 'hell'):
        return VoiceLine('The mark travelled with you. Minds don\'t bruise.', 'comment')
    if m == 'sharp' and ask:
        return VoiceLine(f'They keep asking for one thing: {ask}. Ask yourself why only that.', 'comment')
    return None
