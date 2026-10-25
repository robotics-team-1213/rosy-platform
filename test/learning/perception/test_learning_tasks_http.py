"""Common learning references retain project authorization through real HTTP dispatch."""
import uuid

from test_learning_collaboration import Accounts
from test_omx_center_http import request, running


def robot():
    return dict(request_id=str(uuid.uuid4()), name='Mobile robot', kind='pinky',
                model_revision='revision-1', device_id='pinky-01')


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
