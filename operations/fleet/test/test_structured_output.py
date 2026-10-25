"""D-878: one wire per provider family, and every broken reply is the caller's own fail-closed error."""
import copy

import pytest

from rosy.decision.structured_output import ollama_chat, ollama_reply, openai_chat, openai_reply

SCHEMA = {'type': 'object', 'required': ['choice'], 'additionalProperties': False,
          'properties': {'choice': {'type': 'string', 'enum': ['human', 'reobserve']}}}
MESSAGES = [{'role': 'user', 'content': 'decide'}]


def ollama_value(**change):
    value = {'model': 'm', 'done': True, 'done_reason': 'stop', 'prompt_eval_count': 40, 'eval_count': 9,
             'message': {'role': 'assistant', 'content': '{"choice": "human"}'}}
    return value | change


def openai_value():
    return {'model': 'm', 'choices': [{'index': 0, 'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': '{"choice": "human"}'}}], 'usage': {}}


def test_wire_bodies_carry_the_consumer_schema():
    assert ollama_chat('m', MESSAGES, SCHEMA, temperature=0) == {
        'model': 'm', 'messages': MESSAGES, 'format': SCHEMA, 'stream': False,
        'options': {'num_predict': 1024, 'temperature': 0}}
    assert openai_chat('m', MESSAGES)['response_format'] == {'type': 'json_object'}
    strict = openai_chat('m', MESSAGES, SCHEMA, name='judgment', reasoning_effort='low')
    assert strict['response_format'] == {'type': 'json_schema', 'json_schema': {
        'name': 'judgment', 'strict': True, 'schema': SCHEMA}}
    assert strict['reasoning_effort'] == 'low' and strict['stream'] is False and strict['max_tokens'] == 1024


def test_finished_replies_decode():
    assert ollama_reply(ollama_value(), 'm', 'E') == ({'choice': 'human'}, {'input_tokens': 40, 'output_tokens': 9})
    assert openai_reply(openai_value(), 'm', 'E') == {'choice': 'human'}


@pytest.mark.parametrize('change', [
    {'model': 'other'}, {'done': False}, {'done_reason': 'length'}, {'eval_count': 0}, {'eval_count': 1025},
    {'prompt_eval_count': -1}, {'prompt_eval_count': None}, {'message': None},
    {'message': {'role': 'user', 'content': '{}'}},
    {'message': {'role': 'assistant', 'content': '{}', 'tool_calls': [{}]}},
    {'message': {'role': 'assistant', 'content': '{"choice": "hum'}},     # truncated, never repaired
    {'message': {'role': 'assistant', 'content': {'choice': 'human'}}},
])
def test_broken_ollama_reply_is_the_callers_error(change):
    with pytest.raises(ValueError, match='^E$'):
        ollama_reply(ollama_value(**change), 'm', 'E')


def test_ollama_input_cap_is_optional():
    ollama_reply(ollama_value(prompt_eval_count=9000), 'm', 'E')
    with pytest.raises(ValueError, match='^E$'):
        ollama_reply(ollama_value(prompt_eval_count=9000), 'm', 'E', max_input=8192)


@pytest.mark.parametrize('path, value', [
    (('model',), 'other'), (('choices',), []), (('choices', 0, 'finish_reason'), 'length'),
    (('choices', 0, 'message', 'role'), 'user'), (('choices', 0, 'message', 'tool_calls'), [{}]),
    (('choices', 0, 'message', 'function_call'), {'name': 'move'}), (('choices', 0, 'message', 'content'), '```json\n{}'),
    (('choices', 0, 'message', 'content'), None),
])
def test_broken_openai_reply_is_the_callers_error(path, value):
    data = openai_value()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match='^E$'):
        openai_reply(data, 'm', 'E')


def test_two_choices_are_refused():
    data = openai_value()
    data['choices'].append(copy.deepcopy(data['choices'][0]))
    with pytest.raises(ValueError, match='^E$'):
        openai_reply(data, 'm', 'E')
