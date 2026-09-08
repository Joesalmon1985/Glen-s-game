"""Understood-but-not-enacted: the game always shows it understood you.

When the player types something the world cannot honour (turn into a dragon,
make everyone a sandwich, summon a helicopter), we do not reject it and we do
not pretend it happened. We name the wish precisely, then show what Sarel's
body actually did with it — which, for a mad enough Sarel, is often something
visible and odd that the people in the room react to.

Repetition matters: the tenth impossible wish is treated as habit, not event.
"""
from __future__ import annotations

import re
from typing import Optional

_TRANSFORM = re.compile(r'\b(turn into|become|transform into|shapeshift|morph into)\s+(?:an?\s+)?([a-z][a-z\- ]{2,30})', re.I)
_SUMMON = re.compile(r'\b(summon|conjure|call forth|cast|spell|magic|teleport|fly|levitate|invisible|time travel)\b', re.I)
_MAKE_FOR_ALL = re.compile(r'\b(make|cook|bake|prepare|serve)\b.*\b(everyone|everybody|them all|all of them|the staff)\b.*\b(sandwich|sandwiches|tea|dinner|soup|cake|breakfast|lunch)\b', re.I)
_MAKE = re.compile(r'\b(make|cook|bake|prepare)\b.*\b(sandwich|sandwiches|tea|dinner|soup|cake|omelette|breakfast)\b', re.I)
_VEHICLE = re.compile(r'\b(helicopter|tank|car|plane|spaceship|rocket|horse|motorbike|submarine|train)\b', re.I)
_MARRY = re.compile(r'\b(marry|propose to|kiss|seduce|make love)\b', re.I)
_DANCE = re.compile(r'\b(dance|sing|hum|whistle|do a jig|tap dance|twirl)\b', re.I)
_TALK_OBJECT = re.compile(r'\b(talk to|speak to|ask|tell|whisper to)\s+(the\s+)?(bed|cup|door|wall|floor|book|bowl|basin|ceiling|bedding|blanket)\b', re.I)
_LICK = re.compile(r'\b(lick|taste|bite|chew)\s+(the\s+)?(wall|floor|door|bed|bedding|ceiling|slit|bars)\b', re.I)
_DIG = re.compile(r'\b(dig|tunnel|burrow)\b', re.I)
_WALL = re.compile(r'\b(walk through|pass through|phase through)\s+(the\s+)?(wall|door)\b', re.I)
_SCREAM_NONSENSE = re.compile(r'\b(scream|shout|yell)\b.*\b(random|nonsense|gibberish|words|about)\b', re.I)
_PRETEND = re.compile(r'\b(pretend|act like|act as if|imagine|roleplay)\b', re.I)
_DEMAND_META = re.compile(r'\b(save|load|quit|restart|menu|settings|cheat|god mode|skip|inventory screen)\b', re.I)


def classify_wish(text: str) -> Optional[tuple[str, str]]:
    """Return (kind, detail) if this is a wish the world cannot honour literally."""
    t = (text or '').strip()
    m = _TRANSFORM.search(t)
    if m:
        return 'transform', m.group(2).strip().rstrip('.!?')
    if _MAKE_FOR_ALL.search(t):
        return 'feed_everyone', re.search(r'(sandwich(?:es)?|tea|dinner|soup|cake|breakfast|lunch)', t, re.I).group(1).lower()
    if _MAKE.search(t):
        return 'make_food', re.search(r'(sandwich(?:es)?|tea|dinner|soup|cake|omelette|breakfast)', t, re.I).group(1).lower()
    if _VEHICLE.search(t) and re.search(r'\b(call|summon|get in|drive|fly|ride|board|take)\b', t, re.I):
        return 'vehicle', _VEHICLE.search(t).group(1).lower()
    if _WALL.search(t):
        return 'phase', _WALL.search(t).group(3).lower()
    if _SUMMON.search(t):
        return 'magic', _SUMMON.search(t).group(1).lower()
    if _MARRY.search(t):
        return 'romance', _MARRY.search(t).group(1).lower()
    if _TALK_OBJECT.search(t):
        return 'talk_object', _TALK_OBJECT.search(t).group(3).lower()
    if _LICK.search(t):
        return 'lick', _LICK.search(t).group(3).lower()
    if _DIG.search(t):
        return 'dig', ''
    if _DANCE.search(t):
        return 'dance', _DANCE.search(t).group(1).lower()
    if _SCREAM_NONSENSE.search(t):
        return 'babble', ''
    if _DEMAND_META.search(t) and len(t.split()) <= 4:
        return 'meta', _DEMAND_META.search(t).group(1).lower()
    return None


def _with_article(noun: str) -> str:
    n = (noun or '').strip()
    if not n or n.endswith('s') or n in ('tea', 'soup', 'breakfast', 'lunch', 'dinner', 'cake'):
        return n
    return ('an ' if n[0] in 'aeiou' else 'a ') + n


def _nth(n: int) -> str:
    return 'first' if n == 1 else 'second' if n == 2 else 'third' if n == 3 else f'{n}th'


def acknowledge(kind: str, detail: str, *, count_same: int, count_total: int, staff_present: bool,
                restrained: bool, room: str) -> dict:
    """Produce the understood-not-enacted text and the visible body result.

    Returns {'text': ..., 'visible': bool, 'body_act': short phrase for NPC witnesses}
    """
    d = detail or ''
    habitual = count_total >= 6
    same_again = count_same >= 3

    if kind == 'transform':
        if same_again:
            text = (f'You reach for the {d} again. You know how this goes. Your skin stays skin; your shoulders roll '
                    f'the way they have learned to roll when you try this, and that is all the {d} you get.')
        elif count_total == 1:
            text = (f'You will yourself to become a {d}. You are very clear about it. The room is not interested. '
                    f'Your skin stays skin. Your fingers, which were meant to be claws, are fingers, and they are shaking.')
        else:
            text = (f'A {d}, this time. You concentrate until your jaw aches. Nothing. '
                    f'Your body has never once done what you asked of it in here, and it is not starting now.')
        visible = restrained is False
        body_act = f'stands rigid, jaw working, staring at own hands' if visible else 'goes rigid in their grip'
    elif kind == 'feed_everyone':
        text = (f'You would make everyone {d}. You have the whole gesture ready — the offering, the small ceremony of it. '
                f'There is no bread, no knife, no kitchen, and the people you would feed are the ones holding the keys. '
                f'Your hands make the shape of it anyway, in the air, for a second.')
        visible = True
        body_act = 'mimes offering something with both hands'
    elif kind == 'make_food':
        d = _with_article(d)
        text = (f'You want to make {d}. The want is real and specific and it has nowhere to go: there is nothing here '
                f'to make anything from. Your hands remember the motions and do them, small and empty.')
        visible = True
        body_act = 'goes through small pointless hand motions'
    elif kind == 'vehicle':
        text = (f'A {d}. You look for it as if it might be behind the bed. It is not. There is a bed, a cup, a door '
                f'without a handle, and a person who wants you away from it. No {d} was ever part of this room.'
                if room == 'cell' else
                f'A {d}, here. You actually look. The people present watch you look for a {d} in a {room}.')
        visible = True
        body_act = 'looks wildly about for something that is not there'
    elif kind == 'phase':
        text = (f'You walk at the {d} as though it were a suggestion. It is not a suggestion. '
                f'Your shoulder finds out first.')
        visible = True
        body_act = f'walks into the {d}'
    elif kind == 'magic':
        text = (f'You try to {d}. Nothing in this place has ever once done that for anyone, and it does not do it for you. '
                f'The effort leaves a taste like a coin at the back of your mouth.')
        visible = not restrained
        body_act = 'makes an odd deliberate gesture at nothing'
    elif kind == 'romance':
        who = 'the nearest of them' if staff_present else 'no one, because there is no one'
        text = (f'You want to {d} {who}. The wanting is noted, somewhere behind your eyes, by the part of you that is still counting exits. '
                f'Your face does something. It is not attractive.')
        visible = staff_present
        body_act = 'makes an unreadable face at the staff'
    elif kind == 'talk_object':
        text = (f'You address the {d}. You are polite about it. The {d} has the good manners not to answer, '
                f'which is more than can be said for most things here.')
        visible = True
        body_act = f'talks to the {d}'
    elif kind == 'lick':
        text = (f'You put your tongue to the {d}. Cold. Mineral. A faint chemical bite. '
                f'Now you know what the {d} tastes like, which is not nothing.')
        visible = True
        body_act = f'licks the {d}'
    elif kind == 'dig':
        text = ('You dig. The floor is one piece of something harder than fingernails. Your fingernails find this out.')
        visible = True
        body_act = 'scrabbles at the floor'
    elif kind == 'dance':
        text = (f'You {d}. Badly, in a locked room, for no one. Or for someone: the slit in the door is open.'
                if room == 'cell' and staff_present else
                f'You {d}. Your body is stiff and tired and does it anyway, which says something about you.')
        visible = True
        body_act = f'{d}s, badly'
    elif kind == 'babble':
        text = ('Words come out of you in no order that means anything. It feels good for exactly as long as it lasts.')
        visible = True
        body_act = 'shouts nonsense'
    elif kind == 'meta':
        text = (f'You think, very clearly, "{d}". As if there were somewhere to say it to. The room offers no {d}. '
                f'The cup is still a cup.')
        visible = False
        body_act = ''
    else:
        text = 'You understand exactly what you want. The world declines, without comment.'
        visible = False
        body_act = ''

    if habitual and kind not in ('meta',):
        text += ' Nobody here is surprised any more. Including you.'
    return {'text': text, 'visible': visible, 'body_act': body_act}
