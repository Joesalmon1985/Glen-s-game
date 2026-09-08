"""Language mediation: player intention → what Sarel can actually get out.

The player may express arbitrarily sophisticated intentions. The protagonist's
utterance is constrained by her current language ability. We approximate the
intention rather than reject it, and we classify the *pragmatic force* of the
attempt so Python can decide how an NPC responds.

Everything here is deterministic. The LLM never decides what was said.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- Pragmatic force detection -------------------------------------------------

_Q_WHY = re.compile(r'\b(why|what for|how come|reason)\b', re.I)
_Q_WHERE = re.compile(r'\b(where|what place|what is this place|which place)\b', re.I)
_Q_WHO = re.compile(r'\b(who are you|who is (he|she|that)|your name|who you are|who\b)', re.I)
_Q_WHAT = re.compile(r'\b(what (is|are|do|does|will|happens|happened)|what\'?s)\b', re.I)
_Q_WHEN = re.compile(r'\b(when|how long)\b', re.I)
_REQ_WATER = re.compile(r'\b(water|drink|thirsty)\b', re.I)
_REQ_FOOD = re.compile(r'\b(food|eat|hungry|bread)\b', re.I)
_REQ_OUT = re.compile(r'\b(let me (out|go)|release|free|open the door|leave|get out|go home)\b', re.I)
_REQ_HELP = re.compile(r'\bhelp\b', re.I)
_THREAT = re.compile(
    r'\b(kill|hurt|break your|i\'?ll (get|make) you|you\'?ll (pay|regret)|threaten|or else)\b', re.I,
)
_INSULT = re.compile(r'\b(bastard|idiot|fool|pig|scum|coward|liar|monster|stupid|fuck|shit)\b', re.I)
_GREET = re.compile(r'\b(hello|hi|hey|good (morning|day)|greetings)\b', re.I)
_THANKS = re.compile(r'\b(thank|thanks|grateful)\b', re.I)
_APOLOGY = re.compile(r'\b(sorry|apologi[sz]e|forgive)\b', re.I)
_NAME_GIVE = re.compile(
    r"(?i:\b(?:my name is|i am called|call me|i'?m|call myself|name is|the name)\s+)([A-Z][a-z]+)\b"
    r"|(?i:\bfalse name\b.*?)\b([A-Z][a-z]{2,})\b",
)
_REFUSE = re.compile(r'\b(no|refuse|won\'?t|will not|never|not going to)\b', re.I)
_AGREE = re.compile(r'\b(yes|agree|fine|okay|ok|all right|alright|i will)\b', re.I)
_LIE = re.compile(r'\b(lie|pretend|falsely|claim|tell (him|her|them) (that )?i(\'m| am))\b', re.I)
_PLEAD = re.compile(r'\b(please|beg|plead|i\'?m begging)\b', re.I)
_ADDRESS_VOICE = re.compile(
    r'\b(voice|narrator|the one in my head|in my head|whoever is talking|are you the game|'
    r'shut up|be quiet|stop talking|who are you\??$|why shouldn\'?t i|how do you know)\b',
    re.I,
)

# Speech-verb prefixes we strip to find the propositional content
_SPEECH_PREFIX = re.compile(
    r'^\s*(?:i\s+)?(?:try to\s+)?(?:ask|tell|say|shout|scream|yell|whisper|demand|beg|plead|explain|'
    r'request|call|answer|reply|greet|thank|apologi[sz]e|insist|declare|announce|mutter|'
    r'speak|talk)(?:\s+(?:to|at|with))?\s*(?:him|her|them|it|the\s+\w+|\w+)?\s*'
    r'(?:that|to|if|whether|,|:)?\s*',
    re.I,
)
_QUOTED = re.compile(r'["“”\']([^"“”\']{2,})["“”\']')

# Words Sarel can already produce at very low ability (universal-ish, gestural)
_CORE_WORDS = {
    'no', 'yes', 'why', 'who', 'what', 'where', 'when', 'help', 'water', 'food', 'eat',
    'drink', 'out', 'go', 'home', 'name', 'me', 'you', 'here', 'please', 'sorry',
    'back', 'away', 'stop', 'hurt', 'pain', 'sleep', 'cold', 'hot', 'sick', 'give',
    'want', 'need', 'not', 'door', 'open', 'wait', 'now', 'later', 'good', 'bad',
}
_STOP = {
    'i', 'a', 'an', 'the', 'to', 'of', 'in', 'on', 'at', 'is', 'are', 'am', 'be', 'it',
    'this', 'that', 'do', 'does', 'did', 'my', 'your', 'his', 'her', 'their', 'and',
    'or', 'but', 'so', 'if', 'then', 'for', 'with', 'about', 'him', 'them', 'he', 'she',
    'they', 'we', 'us', 'will', 'would', 'can', 'could', 'should', 'have', 'has', 'had',
    'been', 'being', 'was', 'were', 'me', 'ask', 'tell', 'say', 'them', 'there', 'here',
    'just', 'really', 'very',
}


@dataclass
class Utterance:
    intended: str                 # what the player meant to communicate
    spoken: str                   # what actually came out of Sarel's mouth
    force: str                    # question_why | request_water | threat | ... | statement
    fidelity: str                 # full | partial | fragment | none
    gesture: str = ''             # supporting gesture, if any
    lost: list = field(default_factory=list)  # content that did not survive
    addressed_to_voice: bool = False
    given_name: str = ''
    is_lie: bool = False

    def to_fact(self) -> dict:
        return {
            'type': 'speech',
            'intended': self.intended,
            'spoken': self.spoken,
            'force': self.force,
            'fidelity': self.fidelity,
            'gesture': self.gesture,
            'lost': list(self.lost),
            'addressed_to_voice': self.addressed_to_voice,
            'given_name': self.given_name,
            'is_lie': self.is_lie,
        }


def propositional_content(text: str) -> str:
    """Strip 'ask him whether …' scaffolding; keep the thing to be said."""
    t = (text or '').strip()
    q = _QUOTED.search(t)
    if q:
        return q.group(1).strip()
    stripped = _SPEECH_PREFIX.sub('', t, count=1).strip()
    if stripped and stripped.lower() != t.lower():
        # 'ask him why I am here' -> 'why I am here'
        return stripped
    return t


def classify_force(text: str) -> str:
    t = (text or '').lower()
    if _THREAT.search(t):
        return 'threat'
    if _INSULT.search(t):
        return 'insult'
    if _NAME_GIVE.search(text or ''):
        return 'give_name'
    if _REQ_OUT.search(t):
        return 'request_release'
    if _REQ_WATER.search(t) and not _Q_WHY.search(t):
        return 'request_water'
    if _REQ_FOOD.search(t) and not _Q_WHY.search(t):
        return 'request_food'
    if _REQ_HELP.search(t):
        return 'request_help'
    if _APOLOGY.search(t):
        return 'apology'
    if _THANKS.search(t):
        return 'thanks'
    if _GREET.search(t) and len(t.split()) <= 4:
        return 'greeting'
    if _Q_WHY.search(t):
        return 'question_why'
    if _Q_WHERE.search(t):
        return 'question_where'
    if _Q_WHO.search(t):
        return 'question_who'
    if _Q_WHEN.search(t):
        return 'question_when'
    if _Q_WHAT.search(t) or t.rstrip().endswith('?'):
        return 'question_what'
    if _PLEAD.search(t):
        return 'plea'
    if _REFUSE.search(t) and len(t.split()) <= 6:
        return 'refusal'
    if _AGREE.search(t) and len(t.split()) <= 6:
        return 'assent'
    return 'statement'


def addressed_to_voice(text: str, *, staff_present: bool) -> bool:
    """Is the player talking to the Voice rather than to a person in the room?"""
    t = (text or '').lower().strip()
    if re.search(r'\b(voice|narrator|in my head|whoever is talking|are you the game|game narrator)\b', t):
        return True
    if re.search(r'^(shut up|be quiet|stop talking|quiet|silence|go away|leave me alone)[.!]*$', t):
        return not staff_present or 'voice' in t
    if not staff_present and re.search(r'\b(who are you|who said that|what are you|why shouldn\'?t i|how do you know)\b', t):
        return True
    return False


def _fidelity_words(ability: int) -> int:
    if ability >= 70:
        return 999
    if ability >= 55:
        return 7
    if ability >= 40:
        return 4
    if ability >= 25:
        return 2
    return 1


_FORCE_MINIMAL = {
    'question_why': 'Why?',
    'question_where': 'Where?',
    'question_who': 'Who?',
    'question_what': 'What?',
    'question_when': 'When?',
    'request_water': 'Water.',
    'request_food': 'Food.',
    'request_release': 'Out.',
    'request_help': 'Help.',
    'apology': 'Sorry.',
    'thanks': 'Thank.',
    'greeting': 'Hello.',
    'plea': 'Please.',
    'refusal': 'No.',
    'assent': 'Yes.',
    'threat': 'Hurt you.',
    'insult': '',   # insults barely survive; tone does
    'give_name': '',
    'statement': '',
}

_FORCE_GESTURE = {
    'question_why': 'open hands, a look at the door',
    'question_where': 'a hand sweeping at the walls',
    'question_who': 'a finger toward them, then a shrug',
    'request_water': 'a cupped hand at the mouth',
    'request_food': 'a hand at the stomach',
    'request_release': 'a hand flat against the door',
    'request_help': 'both hands out',
    'threat': 'a step forward, chin up',
    'insult': 'a look that needs no translation',
    'refusal': 'a hard shake of the head',
    'assent': 'a nod',
    'plea': 'palms together',
    'give_name': 'a hand on the chest',
}


def mediate(intended: str, language_ability: int, *, staff_present: bool = True,
            fatigue: int = 0) -> Utterance:
    """Reduce an intended communication to what Sarel can actually produce."""
    raw = (intended or '').strip()
    to_voice = addressed_to_voice(raw, staff_present=staff_present)
    content = propositional_content(raw)
    force = classify_force(raw if force_hint_needed(raw) else content)
    name_m = _NAME_GIVE.search(raw)
    given = ((name_m.group(1) or name_m.group(2) or '') if name_m else '').capitalize()
    is_lie = bool(_LIE.search(raw)) or bool(name_m and name_m.group(2))

    # Speech to the Voice is not spoken aloud in a foreign tongue: the Voice
    # understands the player perfectly. Full fidelity, no gesture.
    if to_voice:
        return Utterance(
            intended=raw, spoken=content, force=force, fidelity='full',
            addressed_to_voice=True, given_name=given, is_lie=is_lie,
        )

    ability = int(language_ability or 0)
    budget = _fidelity_words(ability)
    words = [w for w in re.findall(r"[A-Za-z']+", content)]
    if not words:
        return Utterance(intended=raw, spoken='', force=force, fidelity='none',
                         gesture=_FORCE_GESTURE.get(force, ''), given_name=given, is_lie=is_lie)

    if budget >= len(words):
        spoken = re.sub(r"^(?:'m|m)\s+", "I'm ", content.lstrip("'").strip())
        spoken = spoken[0].upper() + spoken[1:]
        if not spoken.endswith(('.', '?', '!')):
            spoken += '?' if force.startswith('question') else '.'
        return Utterance(intended=raw, spoken=spoken, force=force, fidelity='full',
                         given_name=given, is_lie=is_lie)

    # Pick the content words that survive: core vocabulary first, then nouns-ish.
    # Pronouns are the least valuable survivors — 'water' beats 'you'.
    weak_core = {'you', 'me', 'not', 'want', 'need', 'give', 'now', 'here', 'good', 'bad'}
    candidates: list[tuple[int, int, str]] = []
    for i, w in enumerate(words):
        lw = w.lower()
        if lw in _STOP and lw not in _CORE_WORDS:
            continue
        if lw in _CORE_WORDS and lw not in weak_core:
            rank = 0
        elif lw in weak_core:
            rank = 2
        elif len(lw) > 3 and ability >= 25:
            rank = 1
        elif len(lw) > 3 and ability >= 12:
            rank = 3  # a single foreign noun can be forced out with effort
        else:
            continue
        candidates.append((rank, i, lw))
    candidates.sort()
    chosen = candidates[:budget]
    if ability < 25:
        # Below 25 only one non-core word may survive, and only if nothing core did
        core_chosen = [c for c in chosen if c[0] in (0, 2)]
        if core_chosen:
            chosen = core_chosen[:budget]
        else:
            chosen = chosen[:1]
    chosen.sort(key=lambda c: c[1])  # restore sentence order
    keep = [c[2] for c in chosen]
    kept_set = set(keep)
    lost = [w.lower() for w in words if w.lower() not in kept_set and w.lower() not in _STOP]
    if given and given.lower() not in keep:
        # Proper names cross the barrier at any ability
        keep = [given] + keep[: max(0, budget - 1)]
    if not keep:
        minimal = _FORCE_MINIMAL.get(force, '')
        spoken = minimal
        fidelity = 'fragment' if minimal else 'none'
    else:
        spoken = ' '.join(keep)
        spoken = spoken[0].upper() + spoken[1:]
        spoken += '?' if force.startswith('question') else '.'
        fidelity = 'partial' if len(keep) >= 2 else 'fragment'
        if fatigue >= 75:
            spoken = spoken.lower()
    return Utterance(
        intended=raw, spoken=spoken, force=force, fidelity=fidelity,
        gesture=_FORCE_GESTURE.get(force, '') if fidelity in ('fragment', 'none') else '',
        lost=lost, given_name=given, is_lie=is_lie,
    )


def force_hint_needed(raw: str) -> bool:
    """Threats/insults/name-giving are carried by the whole sentence, not the quote."""
    t = (raw or '').lower()
    return bool(_THREAT.search(t) or _INSULT.search(t) or _NAME_GIVE.search(raw or ''))


def hear(raw_foreign: str, meaning: str, language_ability: int) -> str:
    """How much of an NPC sentence Sarel catches, rendered as a 'caught' string."""
    ability = int(language_ability or 0)
    if ability >= 60:
        return meaning
    words = meaning.split()
    if ability >= 40:
        # Most of it
        return meaning if len(words) <= 5 else ' '.join(words[:5]) + '…'
    if ability >= 25:
        core = [w for w in words if w.lower().strip('.,?!') in _CORE_WORDS or len(w) > 5]
        return '… ' + ' … '.join(core[:3]) + ' …' if core else '…'
    core = [w for w in words if w.lower().strip('.,?!') in _CORE_WORDS]
    return f'… {core[0].lower().strip(".,?!")} …' if core else '…'


def foreignise(meaning: str, seed: int = 0) -> str:
    """Render a staff sentence as the language Sarel does not yet speak.

    Deterministic pseudo-language: consistent enough that repeated words repeat,
    alien enough that it reads as a real barrier.
    """
    syll = ['keth', 'var', 'tho', 'ren', 'ola', 'mis', 'kaa', 'sel', 'ith', 'dun', 've', 'nor', 'ash', 'tel']
    out = []
    for i, w in enumerate(re.findall(r"[A-Za-z']+", meaning or '')):
        h = (sum(ord(c) for c in w.lower()) + seed) % len(syll)
        h2 = (h * 7 + len(w)) % len(syll)
        token = syll[h] + (syll[h2] if len(w) > 4 else '')
        out.append(token)
    s = ' '.join(out)
    return (s[0].upper() + s[1:] + '.') if s else ''
