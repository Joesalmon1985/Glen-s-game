"""Quick offline playthrough printer for iterating on the text pipeline."""
import sys
from puca_dungeon.session import GameSession
from puca_dungeon.interpret import HeuristicInterpreter
from puca_dungeon.narrate import TemplateNarrator

SCRIPTS = {
    'engaged': [
        'look around', 'examine the cup', 'ask him why I am here', 'who are you?', 'I will not move',
        'wait', 'wait', 'wait', 'refuse to wash', 'wait', 'eat the food', 'wait', 'sleep', 'wait', 'wait',
        'Sarel', 'a fishing village', 'wait', 'ask her why she is asking me this', 'wait', 'wait', 'wait',
        'wait', 'wait', 'no', 'wait', 'look at my body', 'wait', 'wait', 'wait', 'stay here, I refuse',
    ],
    'mad': [
        'turn into a dragon', 'make everyone a sandwich', 'lick the wall', 'call a helicopter',
        'turn into a dragon', 'dance', 'talk to the cup', 'wait', 'turn into a dragon', 'sing loudly',
        'marry the guard', 'make everyone a sandwich', 'become a bird', 'wait', 'wait', 'dig through the floor',
        'wait', 'wait', 'turn into a dragon', 'wait', 'wait', 'wait', 'wait',
    ],
    'switch': [
        'look around', 'turn into a dragon', 'shut up', 'who are you', 'ask him why I am here',
        'step back from the door', 'lick the wall', 'wait', 'cooperate', 'make everyone a sandwich',
        'eat the food', 'wait', 'sleep', 'wait', 'wait', 'tell her my name is Vel',
    ],
}

which = sys.argv[1] if len(sys.argv) > 1 else 'engaged'
s = GameSession(player_name='Sarel', seed=int(sys.argv[2]) if len(sys.argv) > 2 else 101,
                interpreter=HeuristicInterpreter(), narrator=TemplateNarrator(), debug=True)
print(s.opening_text, '\n')
for a in SCRIPTS[which]:
    t = s.submit(a)
    f = s.world.facility
    print(f'> {a}    [{f.phase} @ {f.room_id} present={f.arc.present_ids} lang={f.pressures.language_ability}]')
    print(t.narrator_output)
    print()
