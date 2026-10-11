"""Named incident ownership is durable; a resolver pause is not ownership."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from fleet.stuck.board import LineStuckBoard
from fleet.stuck.reports import LineStuckAnswerLog
from test_judgment_receipts import row


def _setup(tmp_path):
    log = LineStuckAnswerLog(tmp_path / 'fleet.sqlite3')
    board = LineStuckBoard(log=log, clock=lambda: 100.0, wall=lambda: 100.0)
    board.observe([row(stuck_id='case-1')])
    board.flush()
    return log, board


def test_claim_competition_idempotency_and_restart(tmp_path):
    log, board = _setup(tmp_path)
    receipt = board.judgment_view('pinky')
    def attempt(principal):
        try:
            return log.handoff.claim('pinky', 'case-1', receipt, principal, now=100.0)
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, ['alice', 'bob']))
    [winner] = [value for value in results if isinstance(value, dict)]
    assert 'INCIDENT_ALREADY_CLAIMED' in results
    assert attempt(winner['principal_id']) == winner
    reopened = LineStuckAnswerLog(log.path)
    assert reopened.handoff.active() == [winner]
    board.observe([row()])
    board.flush()
    assert reopened.handoff.active() == []
    assert log.reports()[0]['handoff']['principal_id'] == winner['principal_id']
    assert log.reports()[0]['closure']['action_credit'] == 'NONE'


def test_claim_rejects_late_changed_closed_and_unnamed_requests(tmp_path):
    log, board = _setup(tmp_path)
    receipt = board.judgment_view('pinky')
    for now in (99.0, 104.0):
        with pytest.raises(ValueError, match='INCIDENT_JUDGMENT_STALE'):
            log.handoff.claim('pinky', 'case-1', receipt, 'alice', now=now)
    with pytest.raises(ValueError, match='OPERATOR_IDENTITY_REQUIRED'):
        log.handoff.claim('pinky', 'case-1', receipt, 'site-console', now=100.0)
    changed = {**receipt, 'reason': 'changed'}
    with pytest.raises(ValueError, match='INCIDENT_JUDGMENT_CHANGED'):
        log.handoff.claim('pinky', 'case-1', changed, 'alice', now=100.0)
    board.observe([row(stuck_id='case-2')])
    board.flush()
    with pytest.raises(ValueError, match='INCIDENT_JUDGMENT_CHANGED'):
        log.handoff.claim('pinky', 'case-1', receipt, 'alice', now=100.0)


def test_api_claim_has_named_readback_and_no_device_command(tmp_path):
    from fakes import FakeRobot
    from test_line_stuck_api import _console, _named_app, _state, _auth, OPERATOR, VIEWER
    from fleet.incidents.handoff import judgment_revision
    robot = FakeRobot('rosy_01', state=_state())
    client, _ = _named_app(_console(robot), tmp_path)
    receipt = client.get('/api/fleet/state', headers=_auth(VIEWER)).json()['robots'][0]['judgment']
    body = {'stuck_id': 'stuck-abc', 'judgment_revision': judgment_revision(receipt)}
    path = '/api/fleet/robots/rosy_01/line-stuck/claim'
    assert client.post(path, json=body, headers=_auth(VIEWER)).status_code == 403
    response = client.post(path, json=body, headers=_auth(OPERATOR))
    assert response.status_code == 200, response.text
    assert response.json()['kind'] == 'incident_handoff'
    report = client.get('/api/fleet/incidents', headers=_auth(VIEWER)).json()['reports'][0]
    assert report['handoff']['principal_id'] == 'op-7'
    assert not [call for call in robot.calls if call[0] == 'line_stuck_decision']
    bad = {**body, 'judgment_revision': '0' * 64}
    assert client.post(path, json=bad, headers=_auth(OPERATOR)).status_code == 409
    assert client.get('/api/fleet/incidents?robot_id=rosy_01', headers=_auth(VIEWER)).status_code == 422
    reports = client.get('/api/fleet/incidents?robot_id=rosy_01&stuck_id=stuck-abc',
                         headers=_auth(VIEWER)).json()['reports']
    assert len(reports) == 1 and reports[0]['handoff']['principal_id'] == 'op-7'


def test_durable_claim_is_restored_only_for_the_current_case(tmp_path):
    from fakes import FakeRobot
    from test_stuck_resolver_loop import _app, _state
    robot = FakeRobot('rosy_01', state=_state())
    app = _app(tmp_path, robot)
    asyncio.run(app.state.fleet_gather())
    board = app.state.line_stuck
    receipt = board.judgment_view('rosy_01')
    board._log.handoff.claim('rosy_01', 'stuck-abc', receipt, 'alice', now=receipt['evaluated_at'])
    restarted = _app(tmp_path, robot)
    asyncio.run(restarted.state.stuck_resolver.run_once())
    assert restarted.state.stuck_resolver._resolver.is_claimed('rosy_01', 'stuck-abc')
    assert not [call for call in robot.calls if call[0] == 'line_stuck_decision']


def test_a_queued_resolver_answer_is_rechecked_after_human_claim(tmp_path):
    from fakes import FakeRobot
    from test_stuck_resolver_loop import _app, _state
    from fleet.stuck.resolver import Answer
    robot = FakeRobot('rosy_01', state=_state())
    loop = _app(tmp_path, robot).state.stuck_resolver
    loop.claim('rosy_01', 'stuck-abc')
    asyncio.run(loop._answer(Answer('rosy_01', 'stuck-abc', 'WAIT', 'R1'), 100.0))
    assert not [call for call in robot.calls if call[0] == 'line_stuck_decision']


def test_claim_and_motion_submit_have_one_order(tmp_path, monkeypatch):
    import httpx
    from fakes import FakeRobot
    from test_line_stuck_api import _console, _named_app, _state, _auth, OPERATOR, VIEWER
    from fleet.incidents.handoff import judgment_revision
    robot = FakeRobot('rosy_01', state=_state())
    client, _ = _named_app(_console(robot), tmp_path)
    receipt = client.get('/api/fleet/state', headers=_auth(VIEWER)).json()['robots'][0]['judgment']
    handoff = client.app.state.line_stuck._log.handoff
    entered, release = threading.Event(), threading.Event()
    original = handoff.get
    def blocked_read(*args):
        result = original(*args)
        entered.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(handoff, 'get', blocked_read)
    async def race():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url='http://test') as http:
            move = asyncio.create_task(http.post('/api/fleet/robots/rosy_01/line-stuck/decision',
                json={'stuck_id': 'stuck-abc', 'decision': 'RESUME'}, headers=_auth(OPERATOR)))
            assert await asyncio.to_thread(entered.wait, 5)
            claim = asyncio.create_task(http.post('/api/fleet/robots/rosy_01/line-stuck/claim',
                json={'stuck_id': 'stuck-abc', 'judgment_revision': judgment_revision(receipt)},
                headers=_auth(OPERATOR)))
            try:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(claim), .05)
            finally:
                release.set()
            assert (await move).status_code == 200
            assert (await claim).status_code == 200
    asyncio.run(race())
    assert [call for call in robot.calls if call[0] == 'line_stuck_decision'] == [
        ('line_stuck_decision', 'stuck-abc', 'RESUME')]
