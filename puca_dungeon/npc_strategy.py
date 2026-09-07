"""Bounded per-NPC reciprocity priors and conversational moves — internal only."""
from __future__ import annotations

from typing import Any

# Conversational move ids (never shown to player)
TEST = 'TEST'
VERIFY = 'VERIFY'
PERSUADE = 'PERSUADE'
REASSURE = 'REASSURE'
BARGAIN = 'BARGAIN'
WITHHOLD = 'WITHHOLD'
DEESCALATE = 'DEESCALATE'
SEEK_INFORMATION = 'SEEK_INFORMATION'
SEEK_REASSURANCE = 'SEEK_REASSURANCE'
TERMINATE = 'TERMINATE'
RECIPROCATE = 'RECIPROCATE'
WARN = 'WARN'
INSTRUCT = 'INSTRUCT'

# Map cast template ids → strategy prior (internal)
STRATEGY_PRIORS = {
    'orderly_quiet': {
        'label': 'generous_reciprocator',  # Hadrik-like
        'forgiveness': 0.7,
        'initial_trust': 0.55,
        'default_move': INSTRUCT,
        'disclose_depth': 0.2,
    },
    'orderly_anxious': {
        'label': 'outcome_sensitive',  # Toma-like
        'forgiveness': 0.35,
        'initial_trust': 0.4,
        'default_move': INSTRUCT,
        'disclose_depth': 0.15,
    },
    'senior_researcher': {
        'label': 'strategic_conditional',  # Maelin-like
        'forgiveness': 0.45,
        'initial_trust': 0.35,
        'default_move': VERIFY,
        'disclose_depth': 0.4,
    },
    'iven': {
        'label': 'high_cooperation',
        'forgiveness': 0.85,
        'initial_trust': 0.7,
        'default_move': SEEK_REASSURANCE,
        'disclose_depth': 0.55,
    },
    'nessa': {
        'label': 'cautious_tester',
        'forgiveness': 0.25,
        'initial_trust': 0.25,
        'default_move': TEST,
        'disclose_depth': 0.3,
    },
    'ruan': {
        'label': 'unstable_memory',
        'forgiveness': 0.5,
        'initial_trust': 0.4,
        'default_move': SEEK_INFORMATION,
        'disclose_depth': 0.45,
    },
}


def prior_for(cid: str) -> dict:
    return dict(STRATEGY_PRIORS.get(cid) or {
        'label': 'neutral',
        'forgiveness': 0.5,
        'initial_trust': 0.5,
        'default_move': SEEK_INFORMATION,
        'disclose_depth': 0.3,
    })


def choose_move(facility, speaker_id: str, *, player_text: str = '') -> dict:
    """Resolve current conversational move from expectations + personality."""
    from puca_dungeon.social_meaning import get_expectation

    prior = prior_for(speaker_id)
    arc = getattr(facility, 'arc', None)
    conf = get_expectation(arc, speaker_id, 'sarel', 'confidentiality', prior['initial_trust'])
    recip = get_expectation(arc, speaker_id, 'sarel', 'reciprocity', prior['initial_trust'])
    text = (player_text or '').lower()
    ask = str(getattr(arc, 'last_ask', '') or '') if arc else ''
    phase = str(getattr(facility, 'phase', '') or '')

    move = prior['default_move']
    may_reveal: list[str] = []
    must_conceal: list[str] = [
        'prior_iterations', 'programme_theory', 'relationship_scores', 'strategy_label',
    ]
    objective = 'maintain procedure'
    tone = 'guarded'

    if speaker_id.startswith('orderly') or speaker_id == 'orderly_quiet':
        if ask:
            move = INSTRUCT
            objective = f'get Sarel to comply: {ask}'
            may_reveal = ['simple_instructions']
            tone = 'practical'
            if recip > 0.6:
                objective = f'ask clearly and without unnecessary force: {ask}'
                tone = 'careful'
        else:
            move = DEESCALATE
            objective = 'keep the subject calm and contained'

    elif speaker_id == 'orderly_anxious':
        move = INSTRUCT if ask else WARN
        objective = f'avoid blame while securing compliance: {ask or "stay controlled"}'
        tone = 'tense'
        if recip < 0.35:
            tone = 'strict'
            must_conceal.append('personal_fear')

    elif speaker_id == 'senior_researcher':
        if 'contract' in phase or 'offer' in ask.lower():
            move = PERSUADE
            objective = 'obtain informed cooperation with the agreement'
            may_reveal = ['contract_terms', 'official_continuity_model']
        elif recip < 0.4 or conf < 0.4:
            move = VERIFY
            objective = 'verify answers rather than trusting them'
            tone = 'controlled'
        else:
            move = REASSURE
            objective = 'keep long-term cooperation credible'
            tone = 'professionally kind'

    elif speaker_id == 'nessa':
        if conf < 0.4:
            move = WITHHOLD
            objective = 'limit disclosure until Sarel proves safe'
            may_reveal = []
            must_conceal += ['escape_thought', 'pipe_inspection', 'this_is_a_trust_test']
            tone = 'abrasive'
        elif conf < 0.6:
            move = TEST
            objective = 'disclose low-risk information and watch what Sarel does with it'
            may_reveal = ['low_risk_observation']
            must_conceal += ['this_is_a_trust_test', 'full_escape_thought']
            tone = 'guarded'
        else:
            move = RECIPROCATE
            objective = 'share a more useful fragment because confidence was kept'
            may_reveal = ['bodily_continuity_fragments']
            tone = 'wary but open'

    elif speaker_id == 'iven':
        if recip < 0.35:
            move = WITHHOLD
            objective = 'help less after repeated exploitation'
            tone = 'hurt'
        else:
            move = SEEK_REASSURANCE
            objective = 'confirm Heaven and the work still mean safety'
            may_reveal = ['heaven_is_real_to_him', 'work_is_finite']
            tone = 'gentle'

    elif speaker_id == 'ruan':
        move = SEEK_INFORMATION
        objective = 'sort whether a memory fragment matches Sarel\'s account'
        may_reveal = ['contradictory_fragments']
        tone = 'fractured'

    # Player hostility nudges
    if any(w in text for w in ('attack', 'kill', 'threaten', 'hit', 'punch')):
        if speaker_id.startswith('orderly') or speaker_id == 'senior_researcher':
            move = WARN
            objective = 'stop violence and restore control'
            tone = 'firm'

    name = facility.character_name(speaker_id) if hasattr(facility, 'character_name') else speaker_id
    return {
        'speaker': speaker_id,
        'speaker_name': name,
        'move': move,
        'objective': objective,
        'may_reveal': may_reveal,
        'must_conceal': must_conceal,
        'tone': tone,
        # Diegetic projection for narrator — no strategy labels
        'surface': {
            'who': name,
            'appears_to_want': objective,
            'manner': tone,
        },
    }


def apply_move_to_speech_facts(facility, move: dict, *, raw: str, understood: str) -> list:
    """Produce structured npc_speech facts from a resolved move."""
    from puca_dungeon.speaker import build_speaker_packet, packet_to_fact
    packet = build_speaker_packet(
        facility.cast,
        move['speaker'],
        objective=move.get('objective') or '',
        language_ability=int(getattr(facility.pressures, 'language_ability', 40) or 40),
        may_add=list(move.get('may_reveal') or []),
    )
    # Overlay conceal/reveal from strategy
    packet['may_reveal'] = list(move.get('may_reveal') or packet.get('may_reveal') or [])
    packet['must_conceal'] = list(dict.fromkeys(
        list(packet.get('must_conceal') or []) + list(move.get('must_conceal') or [])
    ))
    packet['emotion'] = move.get('tone') or packet.get('emotion')
    fact = packet_to_fact(packet, raw, understood)
    # Keep move id off player-facing / narrator packets — internal only on resolution debug
    fact['manner'] = move.get('tone') or fact.get('emotion')
    return [fact]
