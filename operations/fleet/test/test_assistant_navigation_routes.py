"""The explicit opt-in route uses the real HTTP authorization and Task store."""
from hashlib import sha256

from fastapi.testclient import TestClient
from core_common.protocol.assistant import AssistantMessage
from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from test_assistant_provider import configuration


def client(tmp_path, enabled=True):
    tasks = FleetTaskService(FleetTaskStore(tmp_path/'tasks.sqlite'), robot_ids={'r1'})
    tasks.store.rearm_dispatch(expected_generation=tasks.store.dispatch_control()['generation'], actor_id='op')
    users = {sha256(token.encode()).hexdigest():{'principal_id':name, 'role':'operator'}
             for token, name in [('test-token', 'op'), ('other-token', 'other')]}
    app = create_app(FleetConsole([RobotEndpoint('r1', 'http://127.0.0.1:8080', 't')], [FakeRobot('r1')]),
        task_service=tasks, site_users=users, start_task_dispatcher=False,
        assistant_config=configuration().model_copy(update={'execution_enabled':enabled}))
    journal = app.state.operator_assistant.journal
    journal.submit('op', AssistantMessage(request_id='q1', conversation_id='c1', text='Move r1',
                   selected_robot_id='r1'), admitted=True)
    journal.start('op', 'q1')
    journal.finish('op', 'q1', state='ANSWERED', response='work view', kind='CONTROL')
    return TestClient(app, headers={'Authorization':'Bearer test-token'}), tasks


def test_explicit_http_handoff_is_opt_in_idempotent_and_owned(tmp_path):
    web, tasks = client(tmp_path)
    assert web.get('/api/fleet/assistant/status').json()['execution_enabled'] is True
    path = '/api/fleet/assistant/messages/q1/navigation'
    body = dict(robot_id='r1', x=1., y=2.)
    first = web.post(path, json=body)
    assert first.status_code == 200, first.text
    assert web.post(path, json=body).json()['task']['task_id'] == first.json()['task']['task_id']
    assert web.post(path, json=body | {'x':9.}).status_code == 409
    assert web.post(path, json=body, headers={'Authorization':'Bearer other-token'}).status_code == 404
    assert len(tasks.store.queued_task_ids()) == 1
    assert web.post(path, json=body | {'shell':'command'}).status_code == 422
    web.headers.clear()
    assert web.post(path, json=body).status_code == 401


def test_disabled_handoff_does_not_queue_a_task(tmp_path):
    web, tasks = client(tmp_path, enabled=False)
    assert web.get('/api/fleet/assistant/status').json()['execution_enabled'] is False
    assert web.post('/api/fleet/assistant/messages/q1/navigation', json=dict(robot_id='r1', x=1., y=2.)).status_code == 503
    assert not tasks.store.queued_task_ids()


def test_changed_roster_returns_not_found_without_task(tmp_path):
    web, tasks = client(tmp_path)
    tasks.robot_ids = frozenset()
    response = web.post('/api/fleet/assistant/messages/q1/navigation', json=dict(robot_id='r1', x=1., y=2.))
    assert response.status_code == 404
    assert not tasks.store.queued_task_ids()


def test_navigation_storage_failure_returns_unavailable(tmp_path, monkeypatch):
    import sqlite3
    web, tasks = client(tmp_path)
    def unavailable(*_): raise sqlite3.OperationalError('unavailable')
    monkeypatch.setattr(web.app.state.operator_assistant.journal, 'control', unavailable)
    response = web.post('/api/fleet/assistant/messages/q1/navigation', json=dict(robot_id='r1', x=1., y=2.))
    assert response.status_code == 503
    assert not tasks.store.queued_task_ids()
