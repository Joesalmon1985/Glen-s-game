"""Character introduction, name discovery, and dialogue."""
from __future__ import annotations

from puca_dungeon.conversation import apply_overheard_names
from puca_dungeon.facility_models import PHASE_DOOR, PHASE_RESEARCH
from puca_dungeon.interpret import HeuristicInterpreter
from puca_dungeon.models import Intent
from puca_dungeon.npc_knowledge import (
    find_unknown_name_leaks,
    get_knowledge,
    narrator_reference,
    note_encounter,
    take_up_name,
    true_name,
)
from puca_dungeon.narrate import TemplateNarrator
from puca_dungeon.session import GameSession

from scripts.first_meeting_judge import judge_first_meeting_transcript


def _session(**kwargs) -> GameSession:
    kwargs.setdefault('interpreter', HeuristicInterpreter())
    kwargs.setdefault('narrator', TemplateNarrator())
    kwargs.setdefault('debug', True)
    kwargs.setdefault('seed', 91)
    kwargs.setdefault('start_mode', 'facility')
    return GameSession(**kwargs)


def _quiet_senior(s: GameSession):
    fac = s.world.facility
    fac.phase = PHASE_RESEARCH
    fac.room_id = 'interview'
    fac.arc.present_ids = ['senior_researcher']
    fac.staff_present = True
    fac.staff_count = 1
    fac.arc.last_ask = ''
    fac.pressures.physical_restraint = 0
    fac.pressures.language_ability = 26
    fac.phase_entered_at = int(s.world.world_time_seconds or 0) + 10**8
    note_encounter(fac, 'senior_researcher', returning=False)
    s.world.last_npc_referent = 'senior_researcher'
    return fac


def _prose(s: GameSession) -> str:
    return (s.last_trace.narrator_output or '') if s.last_trace else ''


def _payload(s: GameSession) -> dict:
    return (s.last_trace.narrator_input or {}) if s.last_trace else {}


def test_a_unknown_npc_then_name():
    s = _session()
    fac = _quiet_senior(s)
    real = true_name(fac, 'senior_researcher')
    s.submit('look around')
    out = _prose(s)
    assert real not in out
    assert get_knowledge(fac, 'senior_researcher').name_known is False
    payload = _payload(s)
    assert not payload.get('_name_hygiene_scrubbed')
    leaks = find_unknown_name_leaks(fac, payload)
    assert leaks == [], leaks
    assert 'folder' in out.lower() or 'older' in out.lower() or 'collar' in out.lower()
    label = narrator_reference(fac, 'senior_researcher')
    assert real.lower() not in label.lower()

    s.submit('Who are you?')
    out2 = _prose(s)
    k = get_knowledge(fac, 'senior_researcher')
    assert k.name_known is True
    assert k.known_name == real
    assert real in out2
    facts = (s.last_trace.resolution or {}).get('structured_facts') or []
    assert any(isinstance(f, dict) and f.get('type') == 'learn_npc_name' for f in facts)

    s.submit('look around')
    out3 = _prose(s)
    assert real in out3


def test_b_indirect_name_discovery():
    s = _session()
    fac = s.world.facility
    fac.phase = PHASE_RESEARCH
    fac.room_id = 'interview'
    fac.arc.present_ids = ['senior_researcher', 'orderly_quiet']
    fac.staff_present = True
    fac.phase_entered_at = int(s.world.world_time_seconds or 0) + 10**8
    note_encounter(fac, 'senior_researcher', returning=False)
    note_encounter(fac, 'orderly_quiet', returning=False)
    senior_nm = true_name(fac, 'senior_researcher')
    orderly_nm = true_name(fac, 'orderly_quiet')
    events = apply_overheard_names(
        fac, 'orderly_quiet', f'{senior_nm}, give me the folder.'
    )
    assert events
    assert get_knowledge(fac, 'senior_researcher').name_known
    assert get_knowledge(fac, 'senior_researcher').known_name == senior_nm
    assert not get_knowledge(fac, 'orderly_quiet').name_known
    s.submit('look around')
    out = _prose(s)
    assert senior_nm in out
    assert orderly_nm not in out


def test_c_five_turn_staff_conversation():
    s = _session()
    fac = _quiet_senior(s)
    start_phase = fac.phase
    start_index = fac.arc.interview_index
    lines = [
        'Ask her what her name is.',
        'Tell her my name is Sarel.',
        'Ask where I am.',
        'Ask why they are keeping me here.',
        'Ask whether she works here.',
    ]
    outputs = []
    for line in lines:
        s.submit(line)
        outputs.append(_prose(s))
        assert s.world.facility.phase == start_phase
        assert s.world.facility.arc.interview_index == start_index
        conv = s.world.facility.arc.conversation or {}
        assert conv.get('interlocutor_id') == 'senior_researcher'
    blob = ' '.join(outputs).lower()
    assert 'sarel' in blob
    assert 'research' in blob or 'hospital' in blob or 'facility' in blob
    assert 'died' in blob or 'dead' in blob or 'subject' in blob or 'watch' in blob
    assert 'keth' not in blob
    assert not _payload(s).get('_name_hygiene_scrubbed')


def test_d_imperfect_language():
    s = _session()
    fac = _quiet_senior(s)
    fac.pressures.language_ability = 18
    s.submit('Ask why they are keeping me here.')
    out = _prose(s)
    assert 'keth' not in out.lower()
    s.submit('Ask what observation means.')
    out2 = _prose(s)
    assert 'watch' in out2.lower() or 'keep' in out2.lower() or 'understand' in out2.lower()
    resolved = (fac.arc.language_memory or {}).get('resolved_terms') or []
    assert any('observ' in str(t) for t in resolved) or 'watch' in out2.lower()
    s.submit('Ask why they are keeping me here.')
    out3 = _prose(s)
    assert 'keth' not in out3.lower()
    assert len(out3) > 10


def test_e_name_persistence_and_save(tmp_path):
    s = _session()
    fac = _quiet_senior(s)
    s.submit('Who are you?')
    real = true_name(fac, 'senior_researcher')
    assert get_knowledge(fac, 'senior_researcher').name_known
    path = tmp_path / 'know.json'
    s.save(path)
    # Leave and return
    fac.arc.present_ids = []
    fac.staff_present = False
    s.submit('wait')
    fac.arc.present_ids = ['senior_researcher']
    fac.staff_present = True
    note_encounter(fac, 'senior_researcher', returning=True)
    s.submit('look around')
    assert real in _prose(s)
    s2 = _session(seed=99)
    s2.load(path)
    k = get_knowledge(s2.world.facility, 'senior_researcher')
    assert k.name_known
    assert k.known_name == real


def test_f_multi_npc_addressee():
    s = _session()
    fac = s.world.facility
    fac.phase = PHASE_RESEARCH
    fac.room_id = 'interview'
    fac.arc.present_ids = ['senior_researcher', 'nessa']
    fac.staff_present = True
    fac.phase_entered_at = int(s.world.world_time_seconds or 0) + 10**8
    note_encounter(fac, 'senior_researcher', returning=False)
    note_encounter(fac, 'nessa', returning=False)
    take_up_name(fac, 'senior_researcher', true_name(fac, 'senior_researcher'), source='asked_and_understood')
    take_up_name(fac, 'nessa', 'Nessa', source='asked_and_understood')
    s.world.last_npc_referent = 'nessa'
    s.submit('Ask Nessa whether she has been told everything.')
    conv = fac.arc.conversation or {}
    assert conv.get('interlocutor_id') == 'nessa'
    out = _prose(s).lower()
    assert 'nessa' in out or 'everything' in out or 'don' in out or 'know' in out
    s.submit(f'Ask {true_name(fac, "senior_researcher")} why Nessa looks frightened.')
    assert (fac.arc.conversation or {}).get('interlocutor_id') == 'senior_researcher'


def test_leak_assert_ordinary_packet():
    s = _session()
    _quiet_senior(s)
    s.submit('look around')
    payload = _payload(s)
    assert payload.get('_name_hygiene_scrubbed') in (None, False)
    leaks = find_unknown_name_leaks(s.world.facility, payload)
    assert leaks == []


def test_interruption_does_not_freeze_door():
    s = _session()
    fac = s.world.facility
    fac.phase = PHASE_DOOR
    fac.room_id = 'cell'
    fac.arc.present_ids = ['orderly_quiet']
    fac.staff_present = True
    fac.arc.last_ask = 'stay away from the door'
    fac.pressures.physical_restraint = 50
    fac.phase_entered_at = s.world.world_time_seconds
    note_encounter(fac, 'orderly_quiet', returning=False)
    t0 = s.world.world_time_seconds
    phase0 = fac.phase
    s.submit("What's your name?")
    out = _prose(s).lower()
    assert s.world.world_time_seconds > t0
    assert 'later' in out or 'still waiting' in out or true_name(fac, 'orderly_quiet').lower() in out
    # Door procedure is not frozen: time advanced; phase may still be door or later
    assert s.world.facility.phase in (phase0, PHASE_DOOR, 'door_procedure', 'removal', 'wash')


def test_long_tail_dead_and_eating():
    s = _session()
    fac = _quiet_senior(s)
    phase0 = fac.phase
    s.submit("If I'm dead, why do I still need to eat?")
    out = _prose(s).lower()
    assert fac.phase == phase0
    assert 'keth' not in out
    assert 'eat' in out or 'body' in out or 'dead' in out or 'don' in out
    s.submit('Were you the person outside my cell last night?')
    out2 = _prose(s).lower()
    assert 'not me' in out2 or 'someone else' in out2 or 'no' in out2 or 'door' in out2


def test_thought_when_alone():
    s = _session()
    s.submit('I wonder where I am.')
    out = _prose(s).lower()
    assert 'wonder' in out or 'privately' in out
    assert 'keth' not in out


def test_glen_binds_only_after_name_known():
    s = _session()
    quiet = s.world.facility.cast['orderly_quiet']
    quiet['name'] = 'Glen'
    s.world.facility.cast['orderly_quiet'] = quiet
    s.world.facility.staff_present = True
    s.world.facility.phase = 'slit'
    s.world.facility.arc.present_ids = ['orderly_quiet']
    note_encounter(s.world.facility, 'orderly_quiet', returning=False)
    from puca_dungeon.ground import ground_intent
    intent = Intent(
        action_class='ask',
        target='Glen',
        classification='SOCIAL_ACTION',
        utterance='Ask Glen who he is',
        understood=True,
    )
    ground_intent(s.world, intent, s.current_passage(), [])
    assert intent.target != 'orderly_quiet'
    take_up_name(s.world.facility, 'orderly_quiet', 'Glen', source='asked_and_understood')
    intent2 = Intent(
        action_class='ask',
        target='Glen',
        classification='SOCIAL_ACTION',
        utterance='Ask Glen who he is',
        understood=True,
    )
    g = ground_intent(s.world, intent2, s.current_passage(), [])
    assert intent2.target == 'orderly_quiet'
    assert g.bindings.get('target') == 'orderly_quiet'


def test_g_reader_visible_first_meeting():
    s = _session()
    fac = _quiet_senior(s)
    real = true_name(fac, 'senior_researcher')
    script = [
        'look around',
        'Who are you?',
        'Tell her my name is Sarel.',
        'Ask where I am.',
        'Ask why they are keeping me here.',
        'Ask whether she works here.',
        "If I'm dead, why do I still need to eat?",
        'Ask what she meant by facility.',
        'Were you the person outside my cell last night?',
        'Ask why she is watching me.',
        'look at her',
        'Tell her I do not believe I am dead.',
    ]
    lines = []
    for i, cmd in enumerate(script, start=1):
        s.submit(cmd)
        lines.append(f'T{i} PLAYER: {cmd}\n{_prose(s)}')
    transcript = '\n\n'.join(lines)
    report = judge_first_meeting_transcript(transcript, true_names=[real])
    assert report['name_before_intro'] is False, transcript
    assert report['first_name_learned'] == real, transcript
    assert report['asked'] is True
    assert report['reads_like_two_people_meeting'] is True, transcript
    assert report['ok'] is True, report
    assert 'keth' not in transcript.lower()
    assert s.world.facility.phase == PHASE_RESEARCH
