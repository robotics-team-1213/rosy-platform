"""Sample arm_ai scenario: ten labelled cases that serve the A3 sample-data contract (shared/web/sample-data.js), the proposer
cannot approve their own proposal, and the dev events move one case without ever swapping a stopped skill in place."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_sample_flows import call
from test_sample_server import load_engine

REPO = Path(__file__).resolve().parents[3]
CONTRACT_JS = REPO / 'shared/web/sample-data.js'
LIFECYCLES = {'proposed', 'waiting_approval', 'approved', 'running', 'measured_success', 'measured_failure', 'stopped',
              'timed_out', 'fallback_proposed'}
FORBIDDEN_KEY = {'x', 'y', 'z', 'yaw', 'xyz', 'pose', 'joint', 'joints', 'angles', 'position', 'coordinates', 'target', 'waypoints', 'cmd_vel', 'goal'}


def login(engine):
    assert call(engine, 'POST', '/api/fleet/auth/login', {'login': 'sample', 'password': 'CHANGE_ME'})[0] == 204


def cases(engine):
    status, body = call(engine, 'GET', '/api/fleet/arm-proposals')
    assert status == 200 and body['sample'] is True and body['label'] == '샘플 데이터'
    return {case['id']: case for case in body['cases']}


def keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from keys(child)


def problems(case):
    """The Python twin of armAiCaseProblems (sample-data.js); the node check below runs the real one when it is installed."""
    out = []
    if case.get('sample') is not True:
        out.append('sample')
    if case['lifecycle'] not in LIFECYCLES:
        out.append('lifecycle')
    if case['lifecycle'] == 'measured_success' and not case.get('measured'):
        out.append('measured_success without a measurement')
    if case.get('executor') not in (None, 'ik_chunk', 'act', 'smolvla'):
        out.append('executor')
    if any(e['source'] not in ('ledger', 'measured', 'model') for e in case['evidence']):
        out.append('evidence source')
    if any(set(c) != {'id', 'label', 'reason'} for c in case['candidates']):
        out.append('candidate shape')
    out += [f'forbidden key {k}' for k in keys(case) if k in FORBIDDEN_KEY]
    attempt = case.get('approval_attempt')
    if attempt and attempt['by'] in (case['requested_by'], case.get('proposed_by')) and attempt['result'] != 'refused':
        out.append('proposer approved their own proposal')
    return out


def test_ten_cases_all_sample_true_cover_the_nine_lifecycles_and_follow_the_contract():
    engine = load_engine()
    login(engine)
    served = cases(engine)
    assert len(served) == 10
    assert {c['lifecycle'] for c in served.values()} == LIFECYCLES - {'proposed'}  # proposed shares the waiting_approval row
    assert all(c['sample'] is True for c in served.values())
    for case in served.values():
        assert problems(case) == [], case['id']
    assert {c['guard'] for c in served.values() if c['lifecycle'] == 'stopped'} == {'estop'}  # owner HOLD comes from the hold event
    assert any(c['blocking'] for c in served.values() if 'blocking' in c) and any(e['source'] == 'model' for c in served.values() for e in c['evidence'])
    stale = served['arm-ai-10']['evidence'][0]
    assert stale['ageS'] > stale['staleAfterS'], 'the fallback case shows evidence that has gone stale'


@pytest.mark.skipif(not CONTRACT_JS.is_file() or shutil.which('node') is None, reason='A3 contract module not on this branch yet, or no node')
def test_cases_pass_the_shared_node_contract(tmp_path):
    engine = load_engine()
    login(engine)
    data = tmp_path / 'cases.json'
    data.write_text(json.dumps(list(cases(engine).values())), encoding='utf-8')
    script = (f"import {{armAiCaseProblems}} from {CONTRACT_JS.as_uri()!r}; import fs from 'node:fs';"
              f"const bad = JSON.parse(fs.readFileSync({str(data)!r}, 'utf8')).flatMap(c => armAiCaseProblems(c).map(p => c.id + ': ' + p));"
              "if (bad.length) { console.error(bad.join('\\n')); process.exit(1); }")
    result = subprocess.run([shutil.which('node'), '--input-type=module', '-e', script], capture_output=True, text=True, encoding='utf-8', cwd=tmp_path)
    assert result.returncode == 0, result.stderr


def test_the_proposer_cannot_approve_but_another_operator_can():
    engine = load_engine()
    login(engine)
    own = cases(engine)['arm-ai-1']
    assert own['requested_by'] == 'sample'
    body = {'expected_proposal_digest': own['digest'], 'expected_generation': own['generation']}
    status, refused = call(engine, 'POST', '/api/fleet/arm-proposals/arm-ai-1/admit', body)
    assert status == 403 and refused['detail']['code'] == 'PROPOSER_CANNOT_APPROVE'
    assert cases(engine)['arm-ai-1']['lifecycle'] == 'waiting_approval'
    other = cases(engine)['arm-ai-2']
    stale = call(engine, 'POST', '/api/fleet/arm-proposals/arm-ai-2/admit', {'expected_proposal_digest': 'old', 'expected_generation': other['generation']})
    assert stale[0] == 409
    status, approved = call(engine, 'POST', '/api/fleet/arm-proposals/arm-ai-2/admit',
                            {'expected_proposal_digest': other['digest'], 'expected_generation': other['generation']})
    assert status == 200 and approved['lifecycle'] == 'approved' and approved['generation'] == other['generation'] + 1
    assert call(engine, 'POST', '/api/fleet/arm-proposals/arm-ai-3/admit', {'expected_proposal_digest': 'x', 'expected_generation': 1})[0] == 409


def test_a_viewer_cannot_approve_and_unknown_proposals_are_errors():
    engine = load_engine()
    engine.reset('viewer')
    assert call(engine, 'POST', '/api/fleet/arm-proposals/arm-ai-2/admit', {})[0] in (401, 403)
    engine2 = load_engine()
    login(engine2)
    assert call(engine2, 'POST', '/api/fleet/arm-proposals/nope/admit', {})[0] == 404


def test_dev_events_walk_the_lifecycle_and_a_stop_never_falls_back():
    engine = load_engine()
    login(engine)
    live = lambda: cases(engine)['arm-ai-2']  # noqa: E731
    for event, expected in [('admit', 'approved'), ('step', 'running'), ('step', 'running'), ('fail', 'measured_failure'), ('fallback', 'fallback_proposed')]:
        engine.advance('arm_ai', event)
        assert live()['lifecycle'] == expected, event
    assert live()['executor'] == 'ik_chunk' and live()['supersedes'] == 'arm-ai-2' and 'step' not in live()
    engine.advance('arm_ai', 'propose')
    for event in ('admit', 'step'):
        engine.advance('arm_ai', event)
    engine.advance('arm_ai', 'hold')
    assert live()['lifecycle'] == 'stopped' and live()['guard'] == 'hold'
    with pytest.raises(ValueError):
        engine.advance('arm_ai', 'fallback')  # the stop is released by a person, never swapped in place
    engine.advance('arm_ai', 'propose')
    for event in ('admit', 'step'):
        engine.advance('arm_ai', event)
    for _ in range(5):
        engine.advance('arm_ai', 'step')
    assert live()['lifecycle'] == 'measured_success' and live()['measured'] == 'verify_placed'
    with pytest.raises(ValueError):
        engine.advance('arm_ai', 'step')
    assert problems(live()) == []


def test_arm_ai_adds_no_unhandled_requests():
    engine = load_engine()
    login(engine)
    cases(engine)
    assert engine.unhandled == []
