"""Workflow reads and recorder preparation retain project and write boundaries."""
from learning_tasks import Tasks
from test_learning_tasks import task_fixture, ACTOR
from test_learning_collaboration import Accounts
from test_omx_center_http import request, running


def prepared_task(tmp_path, base):
    _, initial = request(base, '/api/learning/tasks')
    tasks = Tasks(tmp_path/'state/reviews.sqlite3', initial['project_id'])
    body, profile = task_fixture(tasks, mode='independent')
    task = tasks.task(body, ACTOR, profile)
    return task, initial['token']


def test_workflow_response_and_recorder_card_do_not_create_device_authority(tmp_path):
    with running(tmp_path) as (base, _):
        task, token = prepared_task(tmp_path, base)
        code, state = request(base, '/api/learning/tasks')
        assert code == 200 and state['capabilities']['lerobot_version'] == '0.4.4'
        flow = state['workflows'][task['id']]
        assert flow['stage'] == 'record' and flow['setup']['device_verified'] is False
        assert flow['recording']['available'] is False
        code, template = request(base, '/api/learning/tasks/recording-card?task_id='+task['id'])
        assert code == 200 and template['task_card'] is None and template['device_execution'] is False
        body = dict(task_id=task['id'], record=dict(root_prefix='/bench/demonstrations',
                    episode_time_s=30, reset_time_s=10, num_episodes=5))
        assert request(base, '/api/learning/tasks/recording-card', body)[0] == 403
        code, result = request(base, '/api/learning/tasks/recording-card', body, token=token)
        assert code == 200 and result['device_execution'] is False
        assert result['requires_owner_preflight'] is True
        assert result['card']['rosy_learning_task']['id'] == task['id']
        assert result['card']['record'] == body['record']
        for bad in [dict(body, path='/arbitrary'), dict(body, record={}),
                    dict(body, task_id='other'), dict(body, record=dict(body['record'], num_episodes=True))]:
            assert request(base, '/api/learning/tasks/recording-card', bad, token=token)[0] == 400


def test_task_native_and_recorder_mutations_require_manage_and_exact_body(tmp_path):
    with running(tmp_path, accounts=Accounts()) as (base, center):
        _, state = request(base, '/api/learning/tasks', session='reader')
        for path in ('/api/learning/tasks/native-input', '/api/learning/tasks/recording-card'):
            for session in ('reader', 'editor'):
                assert request(base, path, {}, token=state['token'], session=session)[0] == 403
            assert request(base, path, {'path': '/arbitrary', 'project_id': 'other'},
                           token=state['token'], session='reviewer')[0] == 400
        assert not center.calls


def test_periodic_task_reads_do_not_rehash_recorded_videos(tmp_path, monkeypatch):
    import learning_tasks_web
    calls = []
    def inspect(*args):
        calls.append(True)
        return []
    monkeypatch.setattr(learning_tasks_web, 'list_inputs', inspect)
    with running(tmp_path) as (base, _):
        assert request(base, '/api/learning/tasks')[0] == 200
        assert not calls
        assert request(base, '/api/learning/tasks/native-inputs')[0] == 200
        for _ in range(3):
            code, result = request(base, '/api/learning/tasks')
            assert code == 200 and result['native_inputs_cached'] is True
            assert result['native_inputs_checked_at']
        assert len(calls) == 1
        assert request(base, '/api/learning/tasks/native-inputs')[0] == 200
        assert len(calls) == 2
