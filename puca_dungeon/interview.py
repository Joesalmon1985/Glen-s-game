"""Memory interview against a hidden reference record."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

_REF_PATH = Path(__file__).resolve().parent / 'content' / 'facility' / 'reference_sarel.json'

QUESTIONS = [
    {'id': 'name', 'key': 'name', 'prompt': 'They show you a word. A name. Yours?'},
    {'id': 'home', 'key': 'home', 'prompt': 'A picture of water and low houses. Home?'},
    {'id': 'family', 'key': 'family', 'prompt': 'They tap two figures — older, younger. Family?'},
    {'id': 'siblings', 'key': 'siblings', 'prompt': 'Another figure, smaller. A brother?'},
    {'id': 'childhood', 'key': 'childhood', 'prompt': 'Cold air. Wood under feet. Childhood?'},
    {'id': 'food', 'key': 'food', 'prompt': 'They show bread, then a bowl. What did you eat?'},
    {'id': 'work', 'key': 'work', 'prompt': 'Hands, nets, repetitive work. Yours?'},
    {'id': 'fear', 'key': 'fear', 'prompt': 'They wait. What were you afraid of?'},
    {'id': 'relationships', 'key': 'relationships', 'prompt': 'Someone leaving on water. Who?'},
    {'id': 'places', 'key': 'places', 'prompt': 'Dusk. Stones. A jetty. Do you know it?'},
    {'id': 'violence', 'key': 'violence', 'prompt': 'Winter. A drowning. Did that happen?'},
    {'id': 'emotional', 'key': 'emotional', 'prompt': 'Waiting after a boat was gone. Yours?'},
]

FRAGMENTS = {
    'childhood': 'Cold ground. Someone’s hand. The memory arrives before you ask for it.',
    'fear': 'A smell of wet rope. Your chest tightens as if the water is here.',
    'places': 'Dusk on stones. It feels vivid and also slightly wrong, like a garment that almost fits.',
    'violence': 'A shout over wind. You do not remember deciding to recall it.',
}


def load_reference() -> dict:
    if _REF_PATH.is_file():
        return json.loads(_REF_PATH.read_text(encoding='utf-8'))
    return {'name': 'Sarel'}


def current_question(index: int) -> Optional[dict]:
    if index < 0 or index >= len(QUESTIONS):
        return None
    return QUESTIONS[index]


def score_answer(question: dict, player_text: str, reference: dict) -> str:
    text = (player_text or '').strip().lower()
    if not text or text in ('wait', 'look', 'look around'):
        return 'no_answer'
    if re.search(r'\b(refuse|won\'?t|will not|don\'?t know|no memory|forget)\b', text):
        return 'refuse'
    if re.search(r'\b(don\'?t remember|cannot remember|no idea)\b', text):
        return 'refuse'
    expected = str(reference.get(question.get('key') or '') or '').lower()
    tokens = [w for w in re.findall(r'[a-z]+', expected) if len(w) > 3]
    hits = sum(1 for w in tokens if w in text)
    if question.get('id') == 'name' and 'sarel' in text:
        return 'correct'
    if hits >= 2 or (hits == 1 and len(tokens) <= 3):
        return 'correct'
    if re.search(r'\b(i was|i lived|my |we |brother|mother|father|village)\b', text):
        if hits == 0:
            return 'invented'
        return 'incorrect'
    if len(text) > 12:
        return 'invented'
    return 'incorrect'


def fragment_for(question_id: str) -> Optional[str]:
    return FRAGMENTS.get(question_id)
