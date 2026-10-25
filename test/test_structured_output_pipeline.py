"""D-878 opt-in real-model pipeline on the Model PC: each Ollama structured-output path through its own code.

ROSY_RUN_STRUCTURED_MODEL_TESTS=1 on a host whose loopback Ollama holds the pinned qwen3-vl digest.
No deployment, device, Fleet or cloud call. A structural failure (envelope, JSON or schema validation)
fails the test; a semantic mismatch is counted and printed, because the acceptance suites own semantics.
"""
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get('ROSY_RUN_STRUCTURED_MODEL_TESTS') != '1',
                                reason='opt-in real Model PC inference')
ROOT = Path(__file__).resolve().parents[1]
RESULTS = {}


@pytest.fixture(scope='module', autouse=True)
def model():
    from deploy.ai_pc.deliberation_ollama import MODEL, exchange, loaded
    # Loads the existing fixed model at the brokers' context length; never pulls or changes its digest.
    exchange('/api/chat', {'model': MODEL, 'messages': [], 'stream': False, 'keep_alive': '10m',
                           'options': {'num_ctx': 8192}}, 90)
    loaded(exchange('/api/ps', None, 5))
    yield
    print('STRUCTURED_PIPELINE_RESULT ' + json.dumps(RESULTS, ensure_ascii=False, sort_keys=True))


def run(path, cases, call, expected):
    rows = []
    for name, value in cases:
        started = time.monotonic()
        try:
            got = call(value)
            rows.append({'case': name, 'got': got, 'match': expected(name, got)})
        except Exception as error:  # the row records which refusal; the test asserts none happened
            rows.append({'case': name, 'structural': f'{type(error).__name__}: {error}'[:160]})
        rows[-1]['seconds'] = round(time.monotonic() - started, 1)
    RESULTS[path] = {'cases': len(rows), 'structural_failures': sum('structural' in r for r in rows),
                     'semantic_matches': sum(bool(r.get('match')) for r in rows), 'rows': rows}
    assert not [r for r in rows if 'structural' in r], rows


def test_deliberation_v2_judgment():
    from deploy.ai_pc import deliberation_ollama as ollama
    from rosy.decision.deliberation import Problem, canonical
    from rosy.decision.deliberation.judgment import judgment_schema
    from rosy.decision.deliberation.profiles import BoundProfile

    def body(facts):
        problem = Problem('synthetic-no-robot', 'pipeline-' + facts, 'g1', 'line_follow', 1, ('e1',),
                          ('human', 'reobserve'), 'INTERVENE', facts_json=json.dumps({'state': facts}),
                          fleet_choice='human')
        bound = BoundProfile(ollama.model_profile('p1'), problem.digest)
        return canonical({'problem': {**asdict(problem), 'input_hash': problem.digest}, 'profile_revision': 'p1',
                          'schema': judgment_schema(problem, bound), 'prior': [],
                          'instruction': 'Return only schema version 2 advisory JSON. '
                          'Never use tools or claim verified physical success or calibration.'}).encode()
    run('deliberation', [(f, body(f)) for f in ('blocked', 'lane_lost', 'clear')],
        lambda raw: ollama.execute(raw, 30)['judgment']['verdict'], lambda name, got: True)


def test_conversation_discord_cases():
    from deploy.ai_pc.conversation_acceptance import cases_for, question
    from deploy.ai_pc.deliberation_conversation import execute
    from rosy.decision.conversation.codec import Profile
    from rosy.decision.conversation.preprocessing import DISCORD_REVISION
    profile = Profile(revision=DISCORD_REVISION)
    cases = cases_for(profile)
    kinds = {name: allowed for name, _, allowed in cases}
    run('conversation', [(case[0], case) for case in cases],
        lambda case: execute(question(case, time.time()), profile, 30)['kind'],
        lambda name, got: got in kinds[name])


def test_operator_cases():
    from deploy.ai_pc import operator_acceptance as acceptance
    from deploy.ai_pc.operator_broker import execute
    # evaluate() stops at the first refusal; one case at a time keeps every row.
    kinds = {name: allowed for name, _, allowed in acceptance.CASES}

    def one(case):
        saved = acceptance.CASES
        acceptance.CASES = (case,)
        try:
            receipt = acceptance.evaluate(execute, source_commit='0' * 40, files={})
        finally:
            acceptance.CASES = saved
        return receipt['outputs'][0]['answer']['kind']
    run('operator', [(case[0], case) for case in acceptance.CASES], one,
        lambda name, got: got in kinds[name])


def test_omx_judge_seat():
    spec = importlib.util.spec_from_file_location('judge_seat', ROOT / 'deploy/robot/omx/judge_seat.py')
    seat = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seat)
    judge = seat.Seat(seat.ollama(timeout=30))
    facts = {'ready-grasp': {'box_found': True, 'next': 'grasp', 'aligned': True},
             'unaligned-grasp': {'box_found': True, 'next': 'grasp', 'aligned': False},
             'ready-lift': {'box_found': True, 'next': 'lift', 'holding': True},
             'not-holding-lift': {'box_found': True, 'next': 'lift', 'holding': False}}

    def decide(value):
        row = judge.decide(value)
        if row['by'] == 'veto':
            raise ValueError(row['reason'])
        return row['decision']
    run('judge_seat', list(facts.items()), decide, lambda name, got: got == 'proceed' if name.startswith('ready') else True)


def frame(seed):
    """Grey floor between white tape under a dark wall; the human labelled the top and one floor strip."""
    rng = np.random.default_rng(seed)
    photo = np.full((60, 80, 3), 120, np.uint8)
    photo[:18] = (40, 50, 60)
    photo[18:, 10:13] = photo[18:, 67:70] = 235
    photo = np.clip(photo.astype(int) + rng.integers(-6, 7, photo.shape), 0, 255).astype(np.uint8)
    mask = np.full((60, 80), 255, np.uint8)
    mask[:12] = 0
    mask[40:, 20:40] = 5
    return photo, mask


def test_qwen_review_completion_schema_against_plain_json(monkeypatch):
    sys.path.insert(0, str(ROOT / 'learning/curation/perception'))
    import qwen_review_completion as completion
    endpoint = 'http://127.0.0.1:11434'

    def proposed(seed):
        photo, mask = frame(seed)
        points = completion.ask(photo, mask, 5, endpoint)
        return {name: len(values) for name, values in points.items()}
    seeds = [(f'seed-{s}', s) for s in range(3)]
    run('qwen_completion_schema', seeds, proposed, lambda name, got: sum(got.values()) > 0)
    monkeypatch.setattr(completion, 'SCHEMA', 'json')  # the previous wire, for comparison only
    try:
        run('qwen_completion_plain_json', seeds, proposed, lambda name, got: sum(got.values()) > 0)
    except AssertionError:
        pass  # the comparison arm may break; only the schema arm is the product
