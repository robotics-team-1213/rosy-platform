"""Common learning references retain project authorization through real HTTP dispatch."""
import uuid

import pytest

from test_learning_collaboration import Accounts
from test_omx_center_http import request, running
from test_sim_web import Runs


def robot():
    return dict(request_id=str(uuid.uuid4()), name='Mobile robot', kind='pinky',
                model_revision='revision-1', device_id='pinky-01')


def registered_task(base):
    _, initial = request(base, '/api/learning/tasks', session='reviewer')
    token = initial['token']
    code, saved = request(base, '/api/learning/robots', robot(), token=token, session='reviewer')
    assert code == 200
    body = dict(request_id=str(uuid.uuid4()), name='Carry sample', objective='Deliver sample',
        success='Sample reaches tray', failure='Sample drops', reset='Return sample',
        adapter='pinky', mode='independent',
        participants=[dict(robot_id=saved['id'], component_id='base', role='carrier')])
    code, task = request(base, '/api/learning/tasks', body, token=token, session='reviewer')
    assert code == 200
    return token, dict(task_id=task['id'], task_revision=task['revision'], run_id='b' * 32)


def finished_runs(status='SUCCEEDED'):
    runs = Runs()
    runs.row.update(status=status, snapshot='FINAL', result={'status': status, 'task_success': status == 'SUCCEEDED'})
    return runs


@pytest.mark.parametrize('status', ['SUCCEEDED', 'FAILED', 'STOPPED'])
def test_sim_context_fetches_server_evidence_under_project_write_fences(tmp_path, status):
    runs = finished_runs(status)
    with running(tmp_path, accounts=Accounts(), sim_runs=runs) as (base, _):
        token, body = registered_task(base)
        route = '/api/learning/tasks/sim-context'
        for session in ('reader', 'editor'):
            assert request(base, route, body, token=token, session=session)[0] == 403
        assert request(base, route, body, session='reviewer')[0] == 403
        assert request(base, route, body, token=token, session='reviewer',
                       headers={'Origin': 'https://other.example'})[0] == 403
        assert request(base, route, dict(body, evidence={'status': 'SUCCEEDED'}),
                       token=token, session='reviewer')[0] == 400
        code, saved = request(base, route, body, token=token, session='reviewer')
        assert code == 200 and saved['kind'] == 'scenario_validation'
        assert saved['evidence']['status'] == status
        assert saved['created_by'] == {'kind': 'authenticated', 'id': 'reviewer'}
        assert '/private/operator' not in str(saved)
        assert request(base, route, body, token=token, session='reviewer') == (200, saved)
        code, snapshot = request(base, '/api/learning/tasks', session='reader')
        assert code == 200 and snapshot['sim_contexts'] == [saved]
        assert snapshot['physical_learning_verified'] is False
        assert request(base, '/api/learning/omx/center/run', {'steps': 1},
                       token=token, session='reviewer')[0] == 200


@pytest.mark.parametrize('corruption', ['running', 'snapshot', 'hash', 'source', 'run_id',
    'result', 'status_mismatch', 'revision'])
def test_sim_context_rejects_unfinished_or_mismatched_server_records(tmp_path, corruption):
    runs = finished_runs()
    if corruption == 'running':
        runs.row['status'] = 'RUNNING'
    elif corruption == 'snapshot':
        runs.row['snapshot'] = 'OBSERVATION_NOT_ATOMIC'
    elif corruption == 'hash':
        runs.row['input_sha256'] = 'not-a-hash'
    elif corruption == 'source':
        runs.row['input']['source_sha'] = 'd' * 40
    elif corruption == 'run_id':
        runs.row['run_id'] = 'e' * 32
    elif corruption == 'result':
        runs.row['result'] = None
    elif corruption == 'status_mismatch':
        runs.row['result']['status'] = 'FAILED'
    else:
        runs.row['revision'] = True
    with running(tmp_path, accounts=Accounts(), sim_runs=runs) as (base, _):
        token, body = registered_task(base)
        assert request(base, '/api/learning/tasks/sim-context', body,
                       token=token, session='reviewer')[0] == 502
        assert request(base, '/api/learning/tasks', session='reader')[1]['sim_contexts'] == []


def test_sim_context_unavailable_does_not_disable_existing_tasks(tmp_path):
    with running(tmp_path, accounts=Accounts()) as (base, _):
        token, body = registered_task(base)
        route = '/api/learning/tasks/sim-context'
        assert request(base, route, body, token=token, session='reviewer')[0] == 503
        code, snapshot = request(base, '/api/learning/tasks', session='reader')
        assert code == 200 and len(snapshot['tasks']) == 1 and snapshot['sim_contexts'] == []
    runs = finished_runs()
    def unavailable(payload):
        raise ValueError('private upstream details')
    runs.call = unavailable
    with running(tmp_path / 'failed', accounts=Accounts(), sim_runs=runs) as (base, _):
        token, body = registered_task(base)
        code, response = request(base, route, body, token=token, session='reviewer')
        assert code == 503 and 'private' not in response['error']
        assert request(base, '/api/learning/tasks', session='reader')[0] == 200


def test_common_references_work_without_a_learner_and_keep_legacy_routes(tmp_path):
    with running(tmp_path, enabled=False) as (base, _):
        code, initial = request(base, '/api/learning/tasks')
        assert code == 200
        assert initial['robots'] == initial['tasks'] == []
        assert initial['host_id'] is None and initial['center_configured'] is False
        body = robot()
        assert request(base, '/api/learning/robots', body)[0] == 403
        for headers in ({'Origin': 'https://other.example'}, {'Host': 'other.example'}):
            assert request(base, '/api/learning/robots', body,
                           token=initial['token'], headers=headers)[0] == 403
        code, saved = request(base, '/api/learning/robots', body, token=initial['token'])
        assert code == 200 and saved['id'] == body['request_id']
        assert saved['device_verified'] is False
        task = dict(request_id=str(uuid.uuid4()), name='Carry sample', objective='Deliver sample',
                    success='Sample reaches tray', failure='Sample drops', reset='Return sample',
                    adapter='pinky', mode='independent',
                    participants=[dict(robot_id=saved['id'], component_id='base', role='carrier')])
        code, result = request(base, '/api/learning/tasks', task, token=initial['token'])
        assert code == 200 and result['runnable'] is False and result['blocked_reason']
        code, package = request(base, '/api/learning/tasks/export?id=' + result['id'])
        assert code == 200 and package['task_revision'] == result['revision']
        code, imported = request(base, '/api/learning/tasks/import', package, token=initial['token'])
        assert code == 200 and imported['id'] == result['id']
        assert len(request(base, '/api/learning/tasks')[1]['tasks']) == 1
        assert request(base, '/api/learning')[0] == 200
        assert request(base, '/api/workspace')[0] == 200
        assert request(base, '/api/learning/tasks/export?id=' + result['id'] + '&id=other')[0] == 400


def test_project_viewers_cannot_register_and_server_binds_creator(tmp_path):
    with running(tmp_path, enabled=False, accounts=Accounts()) as (base, _):
        assert request(base, '/api/learning/tasks')[0] == 401
        code, initial = request(base, '/api/learning/tasks', session='reader')
        assert code == 200 and initial['project_id'] == 'alpha'
        body = robot()
        for session in ('reader', 'editor'):
            assert request(base, '/api/learning/robots', body,
                           token=initial['token'], session=session)[0] == 403
        code, saved = request(base, '/api/learning/robots', body,
                              token=initial['token'], session='reviewer')
        assert code == 200
        assert saved['created_by'] == {'kind': 'authenticated', 'id': 'reviewer'}
        assert saved['project_id'] == 'alpha'
        assert request(base, '/api/learning/robots', dict(body, project_id='other'),
                       token=initial['token'], session='reviewer')[0] == 400
