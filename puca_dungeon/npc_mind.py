"""NPC turn pipeline: perceive → goals/emotion/relationship → intention → feasible action.

Python owns who each character currently is. This module turns that state plus
what Sarel just did into concrete *beats* (short authored fragments) and, when
Sarel speaks, into a *reply* chosen from what the speaker knows and is allowed
to reveal. Nothing here consults an LLM.

Six recurring people, distinct by function:
  senior_researcher  (Maelin-type)  controlled, believes the work matters
  orderly_quiet      (Hadrik-type)  large, silent, concrete morality
  orderly_anxious    (Toma-type)    watchful, rule-bound, frightened bureaucracy
  iven               believer       gentle, wants to save Sarel by getting her to sign
  nessa              sceptic        abrasive, fragments of physical-transfer evidence
  ruan               fractured      lucid/erratic; sometimes right, sometimes wrong
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from puca_dungeon.characters import CharacterState, RelationshipState, name_of
from puca_dungeon.mediation import Utterance, foreignise, hear

STAFF = ('senior_researcher', 'orderly_quiet', 'orderly_anxious', 'attendant_a', 'attendant_b')
SUBJECTS = ('iven', 'nessa', 'ruan')


@dataclass
class NpcBeat:
    speaker: str
    kind: str                       # 'speech' | 'gesture' | 'action' | 'silence'
    meaning: str = ''               # what the NPC actually communicates (English)
    foreign: str = ''               # the sound Sarel hears (staff speak the other language)
    caught: str = ''                # what Sarel catches of it
    body: str = ''                  # visible body language / action
    to_sarel: bool = True
    weight: int = 1                 # ordering / salience

    def to_fact(self, cast: dict) -> dict:
        return {
            'type': 'npc_beat',
            'speaker': self.speaker,
            'speaker_name': name_of(cast, self.speaker),
            'kind': self.kind,
            'meaning': self.meaning,
            'foreign': self.foreign,
            'caught': self.caught,
            'body': self.body,
            'to_sarel': self.to_sarel,
        }


# --------------------------------------------------------------------------- helpers

def _char(cast: dict, cid: str) -> CharacterState:
    raw = (cast or {}).get(cid) or {}
    return CharacterState.from_dict(raw if isinstance(raw, dict) else None)


def _save(cast: dict, ch: CharacterState) -> None:
    cast[ch.id] = ch.to_dict()


def _rel(ch: CharacterState) -> RelationshipState:
    return ch.rel('sarel')


def speaks_sarels_language(cid: str) -> bool:
    """Other subjects share Sarel's tongue; staff do not (yet)."""
    return cid in SUBJECTS


def _speech(cid: str, meaning: str, language_ability: int, *, body: str = '', seed: int = 0,
            weight: int = 1) -> NpcBeat:
    if speaks_sarels_language(cid):
        return NpcBeat(speaker=cid, kind='speech', meaning=meaning, foreign='', caught=meaning,
                       body=body, weight=weight)
    foreign = foreignise(meaning, seed=seed)
    return NpcBeat(speaker=cid, kind='speech', meaning=meaning, foreign=foreign,
                   caught=hear(foreign, meaning, language_ability), body=body, weight=weight)


def _gesture(cid: str, body: str, meaning: str = '', weight: int = 1) -> NpcBeat:
    return NpcBeat(speaker=cid, kind='gesture', meaning=meaning, body=body, weight=weight)


# --------------------------------------------------------------------------- memory & relationship updates

def witness(cast: dict, present: list[str], event: str, *, tags: list[str]) -> None:
    """Every present character remembers the objective event and updates their view.

    tags: behavioural tags of Sarel's act this turn (aggression, compliance, ...).
    Different people interpret the same act differently.
    """
    for cid in present:
        if cid not in cast or cid == 'sarel':
            continue
        ch = _char(cast, cid)
        rel = _rel(ch)
        rel.familiarity = min(100, rel.familiarity + 1)
        interp = _interpret(cid, tags)
        if 'aggression' in tags or 'hostility' in tags:
            rel.fear = min(100, rel.fear + {'orderly_anxious': 12, 'iven': 8, 'ruan': 6}.get(cid, 3))
            rel.trust = max(-100, rel.trust - 5)
            if cid == 'nessa':
                rel.respect = min(100, rel.respect + 2)  # useful, maybe
            if cid == 'senior_researcher':
                rel.suspicion = min(100, rel.suspicion + 4)
            ch.emotion = {'orderly_anxious': 'frightened', 'iven': 'worried', 'orderly_quiet': 'watchful',
                          'senior_researcher': 'assessing', 'nessa': 'interested', 'ruan': 'unsettled'}.get(cid, 'wary')
        elif 'compliance' in tags:
            rel.trust = min(100, rel.trust + 2)
            if cid == 'orderly_quiet':
                rel.respect = min(100, rel.respect + 1)
            if cid == 'nessa':
                rel.suspicion = min(100, rel.suspicion + 3)  # too cooperative — plant?
            if cid == 'iven':
                rel.affection = min(100, rel.affection + 2)
            ch.emotion = 'settled' if cid.startswith('orderly') else ch.emotion
        elif 'defiance' in tags:
            if cid == 'nessa':
                rel.respect = min(100, rel.respect + 3)
            if cid == 'orderly_anxious':
                rel.fear = min(100, rel.fear + 4)
                ch.emotion = 'tense'
            if cid == 'senior_researcher':
                rel.suspicion = min(100, rel.suspicion + 2)
        if 'warmth' in tags or 'empathy' in tags:
            rel.affection = min(100, rel.affection + 3)
            rel.trust = min(100, rel.trust + 2)
            if cid == 'orderly_quiet':
                rel.respect = min(100, rel.respect + 2)
        if 'absurdity' in tags:
            rel.suspicion = min(100, rel.suspicion + 1)
            if cid == 'ruan':
                rel.affection = min(100, rel.affection + 2)  # kinship
            if cid == 'senior_researcher':
                ch.emotion = 'curious'
            if cid == 'orderly_anxious':
                ch.emotion = 'unsettled'
        if 'deception' in tags and cid in ('nessa', 'senior_researcher'):
            rel.suspicion = min(100, rel.suspicion + 5)
        if 'curiosity' in tags and cid == 'senior_researcher':
            rel.respect = min(100, rel.respect + 1)
        ch.set_rel('sarel', rel)
        if event:
            ch.remember_event({'what': event, 'about': 'sarel', 'read_as': interp})
            rel.remember(event)
            ch.set_rel('sarel', rel)
        _save(cast, ch)


def _interpret(cid: str, tags: list[str]) -> str:
    if 'aggression' in tags:
        return {
            'orderly_quiet': 'dangerous but straightforward',
            'orderly_anxious': 'frightening',
            'senior_researcher': 'unusual aggression response — worth noting',
            'iven': 'she needs help',
            'nessa': 'potentially useful',
            'ruan': 'loud',
        }.get(cid, 'aggressive')
    if 'absurdity' in tags:
        return {
            'senior_researcher': 'possible reconstruction instability',
            'orderly_anxious': 'unpredictable — keep distance',
            'orderly_quiet': 'harmless noise',
            'ruan': 'one of us',
            'nessa': 'either mad or performing',
            'iven': 'frightened, showing it strangely',
        }.get(cid, 'odd')
    if 'compliance' in tags:
        return {'nessa': 'too easy — maybe theirs', 'orderly_quiet': 'no trouble'}.get(cid, 'cooperative')
    return ''


# --------------------------------------------------------------------------- replies to Sarel's speech

def reply_to(cast: dict, speaker: str, utt: Utterance, *, phase: str, language_ability: int,
             ask: str, arc, seed: int = 0) -> list[NpcBeat]:
    """Choose what `speaker` says/does in response to Sarel's utterance.

    Restricted by the speaker's may_reveal / must_conceal, current goal (the
    open ask), emotion and relationship. Returns 1–2 beats.
    """
    ch = _char(cast, speaker)
    rel = _rel(ch)
    force = utt.force
    heard = utt.fidelity in ('full', 'partial')
    gist = utt.fidelity == 'fragment'
    nothing = utt.fidelity == 'none'
    beats: list[NpcBeat] = []

    def say(meaning, body='', w=2):
        beats.append(_speech(speaker, meaning, language_ability, body=body, seed=seed, weight=w))

    def ges(body, meaning='', w=1):
        beats.append(_gesture(speaker, body, meaning, weight=w))

    # --- staff who do not share a language: the ask dominates -------------------
    if speaker == 'orderly_quiet':
        if force == 'threat' or force == 'insult':
            ges('He does not step back. He looks at your hands, not your face.', 'unmoved')
        elif force in ('request_water', 'request_food') and nothing is False:
            if 'wash' in ask or 'door' in ask:
                say('After.', 'A short nod toward the corridor.')
            else:
                ges('He glances at the cup, then back at you. He does not fetch anything.')
        elif force == 'request_release':
            ges('A slow shake of the head. Not unkind. Not negotiable.')
        elif force.startswith('question') and ask:
            say(ask.capitalize() + '.', 'He repeats the gesture, slower, as if slowness were a language.')
        elif force.startswith('question'):
            ges('He hears the question in it. He gives you nothing back but his attention.')
        elif force == 'give_name':
            ges('The name registers. Something in his posture changes by a degree.', 'noted')
        elif force == 'apology':
            ges('He nods once. That is the whole reply.')
        elif force == 'greeting' or force == 'thanks':
            ges('A grunt that might be acknowledgement.')
        else:
            if ask:
                say(ask.capitalize() + '.', 'The same short sound as before.')
            else:
                ges('He listens. He does not answer.')
        return beats

    if speaker == 'orderly_anxious':
        frightened = rel.fear >= 20 or ch.emotion in ('frightened', 'tense')
        if force in ('threat', 'insult'):
            ges('She flinches before she can stop herself, then straightens too fast.', 'frightened')
            say('Back. Back.', w=2)
        elif force.startswith('question'):
            if frightened:
                ges('She looks to the larger one instead of answering.')
            else:
                say('Not for me to say.', 'Clipped. Eyes on the corridor.')
        elif force in ('request_water', 'request_food'):
            say('Not now.', 'Procedure first — you can read that much in her shoulders.')
        elif force == 'give_name':
            ges('She writes something without looking down at her hand.')
        elif force == 'apology' or force == 'thanks':
            ges('A small, surprised pause. Then she remembers herself.')
        else:
            if ask:
                say(ask.capitalize() + '.', 'Flat, careful, by the book.')
            else:
                ges('She watches you and says nothing.')
        return beats

    if speaker == 'senior_researcher':
        if force in ('threat', 'insult'):
            say('That is noted.', 'She does not raise her voice. She makes a mark.')
        elif force == 'question_why':
            say('You are a subject here. You are being looked after.',
                'Even, patient. As if she has said it many times and means it every time.')
        elif force == 'question_where':
            say('Somewhere safe. That is enough for now.')
        elif force == 'question_who':
            say('I am responsible for you.', 'A hand, briefly, at the collar.')
        elif force == 'question_what' or force == 'question_when':
            if 'contract' in phase or 'offer' in phase:
                say('Five years. Then Heaven. The terms are written down.')
            else:
                say('Questions first. Then answers.', 'Kind about it. Immovable about it.')
        elif force == 'give_name':
            say('Yes. We know.', 'She does not write it down. She already has it.')
        elif force in ('request_water', 'request_food', 'request_help'):
            say('You will be looked after.', 'She means it. That is the disturbing part.')
        elif force == 'request_release':
            say('Not yet. Not like that.')
        elif force == 'refusal':
            say('You may refuse. Nobody here is forcing you.', 'This is said gently, which is worse.')
        elif force == 'assent':
            ges('She inclines her head as if you had confirmed something she suspected.')
        elif force == 'apology':
            say('There is nothing to be sorry for.')
        else:
            ges('She listens all the way to the end. Then she waits to see if there is more.')
        return beats

    if speaker.startswith('attendant'):
        if force.startswith('question'):
            say('You are where you earned. Rest.', 'Gentle, rehearsed, a little too quick.')
        elif force in ('request_water', 'request_food'):
            say('Of course.', 'It arrives. That, at least, is real.')
        else:
            ges('A smile that does not ask anything of you.')
        return beats

    # --- other subjects: same language, own agendas -----------------------------
    if speaker == 'iven':
        if force in ('threat', 'insult'):
            say('Don\'t. Please. They remember that.', 'He is not warning you for their sake.')
        elif force == 'question_why':
            say('Because you died. Same as me. They brought you back — that\'s what this place is.',
                'He says it like comfort.')
        elif force == 'question_where':
            say('The facility. The Whispering Ones. You\'ll get used to it — it\'s not forever.')
        elif force == 'question_who':
            say('Iven. I\'ve been here… a while. I\'ve seen the other side. Both sides.')
        elif force == 'question_what':
            if 'contract' in phase or 'offer' in phase or rel.familiarity > 3:
                say('Sign. Please sign. Work isn\'t forever, and they keep their promises. Heaven is real. I\'ve been.',
                    'His hands are shaking a little. Not from fear of you.')
            else:
                say('Do what they ask. It goes easier. And then — after — it\'s good. It\'s so good.')
        elif force == 'give_name':
            say(f'{utt.given_name or "That"}. All right. I\'ll remember it.', 'He smiles like it costs him nothing.')
        elif force in ('request_water', 'request_food'):
            say('They\'ll bring it. They always do. That\'s the thing — they always do.')
        elif force == 'greeting':
            say('Hello. You\'re new. It\'s all right to be frightened, I was.')
        elif force == 'apology':
            say('You don\'t have to be sorry to me.')
        else:
            say('I don\'t know about that. But I know Heaven is real.', 'Quiet certainty.')
        return beats

    if speaker == 'nessa':
        trusting = rel.trust >= 6 and rel.suspicion < 8
        if force in ('threat', 'insult'):
            say('Save it. Save it for when it counts.', 'Not frightened. Calculating.')
        elif force == 'question_why':
            say('Why are any of us? Ask them. Watch what their faces do when you ask.')
        elif force == 'question_where':
            if trusting:
                say('Same building as everything else. Same bolts. Same pipes. Remember I said that.',
                    'Barely above a breath.')
            else:
                say('Somewhere with very good plumbing.', 'She watches whether you catch it.')
        elif force == 'question_who':
            say('Nessa. Don\'t bother liking me.')
        elif force == 'question_what':
            if trusting:
                say('Scratched myself before they put me under. Woke up in "Heaven". Scratch was still there. Think about it.',
                    'She does not look at you while saying it.')
            else:
                say('Ask Iven. He loves to explain.', 'Flat.')
        elif force == 'give_name':
            say('Is that what they told you it was?', 'A sceptic\'s courtesy.')
        elif force == 'assent' or force == 'statement':
            if utt.is_lie:
                ges('Something in her face closes. She has heard people lie before.')
            else:
                say('Fine.', 'Which from her is a lot.')
        elif force == 'greeting':
            ges('A look up, a look down, an assessment finished.')
        else:
            say('Keep your voice down. They listen more than they let on.')
        return beats

    if speaker == 'ruan':
        # Alternates between insight and error — deterministic by seed
        lucid = (seed + rel.familiarity) % 3 != 0
        if force in ('threat', 'insult'):
            say('Ha. Yes. Hit the wall too — it remembers better than they do.', 'Delighted, or something near it.')
        elif force == 'question_who':
            if lucid:
                say('Ruan. Mostly. Some days there\'s more of us in here than there should be.')
            else:
                say('I had two mothers. Not — not like that. Two. Different houses. Both true.')
        elif force == 'question_where':
            if lucid:
                say('Fourth door from the wash. Count them. You should always count them.',
                    'Correct, as it happens.')
            else:
                say('The sea, once. I drowned here. Or there. The water was warm, which is wrong.')
        elif force == 'question_why':
            say('Because you\'re the fourth. Or fifth. They lose count too, you know.',
                'It sounds like nonsense. It might not be.')
        elif force == 'give_name':
            say(f'{utt.given_name or "Mm"}. Good. Hold onto that one. They\'ll try to give you others.')
        elif force == 'question_what':
            if lucid:
                say('The collar means she belongs to them, not the other way round. Nobody says so.')
            else:
                say('Heaven has birds. Also no birds. I was there both times.')
        else:
            if lucid:
                say('You spoke like the last one. The last you. Sorry. That\'s probably not helpful.')
            else:
                ges('He is counting something on his fingers and loses his place when you speak.')
        return beats

    return beats


# --------------------------------------------------------------------------- ambient beats

def ambient(cast: dict, present: list[str], *, phase: str, language_ability: int, tags: list[str],
            enactment: str, ask: str, seed: int, arc) -> list[NpcBeat]:
    """One unprompted beat from the most salient present person, driven by goals/emotion.

    Kept sparse: at most one ambient beat per turn so the scene does not chatter.
    """
    out: list[NpcBeat] = []
    if not present:
        return out
    aggressive = 'aggression' in tags or 'hostility' in tags
    absurd = 'absurdity' in tags
    defiant = 'defiance' in tags
    compliant = 'compliance' in tags

    # Choose who reacts: the one whose goal is most touched by the act
    order = [c for c in present if c in cast and c != 'sarel']
    pick: Optional[str] = None
    if aggressive:
        pick = 'orderly_quiet' if 'orderly_quiet' in order else (order[0] if order else None)
    elif absurd:
        for c in ('orderly_anxious', 'senior_researcher', 'ruan', 'nessa', 'iven', 'orderly_quiet'):
            if c in order:
                pick = c
                break
    elif defiant:
        for c in ('orderly_anxious', 'orderly_quiet', 'senior_researcher', 'nessa'):
            if c in order:
                pick = c
                break
    elif compliant:
        for c in ('orderly_quiet', 'iven', 'nessa', 'senior_researcher'):
            if c in order:
                pick = c
                break
    else:
        # Quiet turns: subjects introduce themselves once; staff mostly hold the ask
        for c in ('nessa', 'iven', 'ruan'):
            if c in order:
                ch = _char(cast, c)
                if _rel(ch).familiarity <= 1:
                    pick = c
                    break
        if pick is None and (seed % 3 == 0):
            pick = order[0]
    if pick is None:
        return out

    ch = _char(cast, pick)
    rel = _rel(ch)

    if pick == 'orderly_quiet':
        if aggressive:
            if enactment in ('aborted', 'compromised'):
                out.append(_gesture(pick, 'The big one absorbs it the way a wall absorbs a shoulder. His grip shifts — firmer, not crueller.', 'restrains'))
            else:
                out.append(_gesture(pick, 'He steps in and it is over before it is a fight. He is not angry. He is finishing a task.', 'restrains'))
        elif compliant and rel.respect >= 2:
            out.append(_gesture(pick, 'His hold loosens by a fraction. You are not sure he knows he did it.'))
        elif absurd:
            out.append(_gesture(pick, 'He watches the performance without expression, the way you might watch weather.'))
        elif ask:
            out.append(_speech(pick, ask.capitalize() + '.', language_ability,
                               body='Again. Same volume. He could do this all day.', seed=seed))
    elif pick == 'orderly_anxious':
        if aggressive:
            out.append(_gesture(pick, 'The younger one has gone white. Her hand is on something at her belt and she does not seem to know it.', 'frightened'))
        elif absurd:
            out.append(_gesture(pick, 'The younger one glances at the senior, then at the door, then at you, and does not know where to leave her eyes.'))
        elif defiant:
            out.append(_gesture(pick, 'The younger one straightens as if the refusal were addressed to her record.'))
        elif ask and rel.fear >= 10:
            out.append(_speech(pick, ask.capitalize() + '. Please.', language_ability,
                               body='The last word is not procedure. It slips out.', seed=seed))
    elif pick == 'senior_researcher':
        if aggressive:
            out.append(_gesture(pick, 'She does not flinch. She writes. Whatever you are, you are data.'))
        elif absurd:
            out.append(_gesture(pick, 'She tilts her head. For the first time you have her full interest, and you are not sure you wanted it.'))
        elif defiant:
            out.append(_gesture(pick, 'She lets the silence sit. She is comfortable in it. You are meant to notice that you are not.'))
        elif compliant:
            out.append(_gesture(pick, 'A small approving stillness. Like a teacher whose pupil has stopped fidgeting.'))
    elif pick == 'iven':
        if rel.familiarity <= 1:
            out.append(_speech(pick, 'You\'re new. I\'m Iven. Don\'t fight them — it isn\'t worth it, and it isn\'t forever.',
                               language_ability, body='Soft voice. Hands folded like he has been told to keep them still.'))
        elif aggressive:
            out.append(_speech(pick, 'Stop. Stop — they\'ll write it down. Please.', language_ability))
        elif compliant:
            out.append(_gesture(pick, 'Iven relaxes visibly, as though your obedience were his.'))
        elif absurd:
            out.append(_gesture(pick, 'Iven looks at you with real pain. He has seen people come apart before.'))
    elif pick == 'nessa':
        if rel.familiarity <= 1:
            out.append(_speech(pick, 'Don\'t talk to me in front of them. Later.', language_ability,
                               body='Said without moving her lips much. She has practised that.'))
        elif aggressive:
            out.append(_gesture(pick, 'Nessa watches which staff member moves first. She is learning something from your mistake.'))
        elif compliant and rel.suspicion >= 6:
            out.append(_gesture(pick, 'Nessa\'s eyes narrow. Compliant ones are either broken or planted.'))
        elif absurd:
            out.append(_gesture(pick, 'Nessa looks away in something like disgust. Or disappointment. Hard to tell on her.'))
    elif pick == 'ruan':
        if rel.familiarity <= 1:
            out.append(_speech(pick, 'New one. New one, new one. Which house did you grow up in? I had two.',
                               language_ability, body='He seems genuinely to want the answer.'))
        elif absurd:
            out.append(_speech(pick, 'Yes! Yes, exactly. Nobody else here understands that.', language_ability,
                               body='He is beaming. This is not reassuring.'))
        elif aggressive:
            out.append(_gesture(pick, 'Ruan counts the blows out loud, softly, and gets the number wrong.'))
    elif pick.startswith('attendant'):
        out.append(_gesture(pick, 'The attendant refills something that was not empty.'))
    return out
