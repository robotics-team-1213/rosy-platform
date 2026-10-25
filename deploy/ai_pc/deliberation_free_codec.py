"""One fixed synthetic v2 request; no real robot or runtime model admission."""
import json

from rosy.decision.deliberation import Problem, canonical
from rosy.decision.deliberation.judgment import judgment
from rosy.decision.deliberation.profiles import BoundProfile, ModelProfile
from rosy.decision.deliberation.versioned_request import prepare_request
from rosy.decision.structured_output import openai_reply
from .deliberation_glm_receipt import usage

MODEL = 'mimo-v2.6-flash-free'
PROBLEM = Problem('synthetic-no-robot', 'free-mimo-first-review', 'probe-v2', 'line_follow', 1,
                  ('synthetic-core-state',), ('human', 'reobserve'), 'INTERVENE',
                  facts_json='{"state":"blocked"}', fleet_choice='human')
PROFILE = ModelProfile('free-mimo-probe', 'free-probe-v1', 'evaluator', 'opencode',
    'opencode/' + MODEL, MODEL, 'opencode-1.18.35-free-probe-v2',
    ('line_follow',), ('text',), 30, 16384, 1, 0)
BOUND = BoundProfile(PROFILE, PROBLEM.digest)


def body():
    return prepare_request(PROBLEM, BOUND, (), 30, budget_usd=0)[1]


def trusted_body(raw):
    if canonical(json.loads(raw)) != body().decode():
        raise ValueError('EXACT_SYNTHETIC_FREE_JOB_REQUIRED')
    return PROBLEM, body().decode()


def checked_response(response):
    raw = openai_reply(response, MODEL, 'FREE_RESULT_NOT_BOUND')
    counts = {key: response['usage'][key] for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    if 'completion_tokens_details' in response['usage']:
        counts['completion_tokens_details'] = response['usage']['completion_tokens_details']
    usage(counts)
    payload = judgment(PROBLEM, BOUND, raw).payload
    return dict(id='rosy-free-one-shot', object='chat.completion', model=MODEL,
        choices=[dict(index=0, message=dict(role='assistant', content=canonical(payload)), finish_reason='stop')],
        usage=counts)
