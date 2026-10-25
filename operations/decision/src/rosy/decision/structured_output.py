"""D-878 structured model output: provider wire built from the consumer's schema, reply envelope checked once.

Callers keep their schema, error code, budgets and semantic validation. Every refusal here is
ValueError(error): a broken envelope, a truncated reply or unparseable JSON is the same fail-closed
answer as a choice outside the schema. No retry and no JSON repair.
"""
import json


def ollama_chat(model, messages, schema, *, num_predict=1024, **options):
    """Ollama /api/chat body with the schema as constrained decoding."""
    return {'model': model, 'messages': messages, 'format': schema, 'stream': False,
            'options': {'num_predict': num_predict, **options}}


def ollama_reply(value, model, error, *, max_output=1024, max_input=None):
    """(payload, usage) from one finished Ollama chat reply."""
    if type(value) is not dict:
        raise ValueError(error)
    message = value.get('message')
    usage = {'input_tokens': value.get('prompt_eval_count'), 'output_tokens': value.get('eval_count')}
    if (type(message) is not dict or value.get('model') != model or value.get('done') is not True
            or value.get('done_reason') != 'stop' or message.get('role') != 'assistant'
            or message.get('tool_calls') or message.get('function_call') or type(message.get('content')) is not str
            or any(type(count) is not int or count < 0 for count in usage.values())
            or not 0 < usage['output_tokens'] <= max_output
            or max_input is not None and usage['input_tokens'] > max_input):
        raise ValueError(error)
    return _decoded(message['content'], error), usage


def openai_chat(model, messages, schema=None, *, name='answer', max_tokens=1024, **extra):
    """OpenAI-compatible chat body. Without a schema the provider only promises syntax (json_object)."""
    response_format = ({'type': 'json_object'} if schema is None else
                       {'type': 'json_schema', 'json_schema': {'name': name, 'strict': True, 'schema': schema}})
    return {'model': model, 'messages': messages, 'max_tokens': max_tokens, 'stream': False,
            'response_format': response_format, **extra}


def openai_reply(response, model, error):
    """Payload of the single finished assistant message; usage stays with the caller's tariff checks."""
    choices = response.get('choices') if type(response) is dict else None
    choice = choices[0] if type(choices) is list and len(choices) == 1 and type(choices[0]) is dict else {}
    message = choice.get('message')
    if (type(message) is not dict or response.get('model') != model or choice.get('finish_reason') != 'stop'
            or message.get('role') != 'assistant' or message.get('tool_calls') or message.get('function_call')
            or type(message.get('content')) is not str):
        raise ValueError(error)
    return _decoded(message['content'], error)


def _decoded(content, error):
    try:
        return json.loads(content)
    except ValueError:
        raise ValueError(error) from None
