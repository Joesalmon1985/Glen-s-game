import json
from puca_core import StoryState
from puca_services import Narrator

def test_internal_labels_are_retried_not_shown_as_fiction():
    base = {'event':'promise','spirit':'positive','image_prompt':'old bridge','location':'bridge','choices':['Listen'],'facts':[],'visual_changed':False}
    responses = [dict(base, narration='The spirit positive outcome suggests your journey will be worthwhile.'),
                 dict(base, narration='The gate opens as the keeper accepts your promise.')]
    calls = []
    def send(url, body, timeout):
        calls.append(body)
        return {'response':json.dumps(responses.pop(0))}
    scene = Narrator(transport=send).ask(StoryState(name='Glen',origin='Home'), '(begin)')
    assert scene.narration == 'The gate opens as the keeper accepts your promise.'
    assert len(calls) == 2
