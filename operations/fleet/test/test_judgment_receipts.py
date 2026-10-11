"""Current evidence, normal denominator and observed closure stay separate."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from core_common.protocol.schemas import FleetJudgmentReceipt

from fleet.stuck.board import LineStuckBoard
from fleet.stuck.reports import LineStuckAnswerLog


def row(now=100.0, *, stuck_id=None, phase='ASKING', online=True):
    stuck = None if stuck_id is None else dict(stuck_id=stuck_id, phase=phase, cause='lane_lost')
    return {'robot_id': 'pinky', 'online': online, 'state_age_s': 0.0,
            'state': {'seq': 1, 'timestamp': datetime.fromtimestamp(now, timezone.utc).isoformat(),
                      'line_follow': {'mode': 'OFF' if stuck is None else 'CAMERA_LINE', 'stuck': stuck}}}


def test_normal_receipts_are_durable_without_opening_a_problem(tmp_path):
    now = [100.0]
    log = LineStuckAnswerLog(tmp_path / 'fleet.sqlite3')
    board = LineStuckBoard(log=log, clock=lambda: now[0], wall=lambda: now[0])
    board.observe([row()])
    board.flush()
    assert board.judgment_view('pinky')['necessity'] == 'DO_NOT_INTERVENE'
    assert log.episodes() == [] and log.rows() == []
    assert len(log.judgments()) == 1
    for _ in range(10):
        board.observe([row()])
        board.flush()
    assert len(log.judgments()) == 1
    now[0] = 160.0
    board.observe([row(160.0)])
    board.flush()
    reopened = LineStuckAnswerLog(log.path)
    assert len(reopened.judgments()) == 2
    assert all(item['assessment']['necessity'] == 'DO_NOT_INTERVENE' for item in reopened.judgments())


def test_current_receipt_rechecks_age_and_preserves_original_evidence():
    now = [100.0]
    board = LineStuckBoard(clock=lambda: now[0], wall=lambda: now[0])
    board.observe([row(stuck_id='case-1')])
    receipt = board.judgment_view('pinky')
    assert receipt['necessity'] == 'INTERVENE'
    assert receipt['shadow'] is True and receipt['action_admissible'] is False
    with pytest.raises(ValidationError):
        FleetJudgmentReceipt.model_validate({**receipt, 'action_admissible': True})
    now[0] = 104.0
    stale = board.judgment_view('pinky')
    assert stale['necessity'] == 'ABSTAIN' and stale['reason'] == 'evidence_stale'
    assert stale['request']['evidence'][0]['observed_at'] == 100.0
    board.observe([row(104.0, stuck_id='case-2')])
    assert board.judgment_view('pinky')['request']['case_id'] == 'case-2'


def test_natural_clearance_has_no_action_success_credit(tmp_path):
    log = LineStuckAnswerLog(tmp_path / 'fleet.sqlite3')
    board = LineStuckBoard(log=log, clock=lambda: 100.0, wall=lambda: 100.0)
    board.observe([row(stuck_id='case-1')])
    board.observe([row()])
    board.flush()
    [report] = log.reports()
    assert report['closure']['status'] == 'NATURAL_CLEARANCE'
    assert report['closure']['action_credit'] == 'NONE'
    assert report['closure']['reason'] == 'cleared'


def test_restart_or_roster_removal_is_not_problem_resolution(tmp_path):
    log = LineStuckAnswerLog(tmp_path / 'fleet.sqlite3')
    board = LineStuckBoard(log=log, clock=lambda: 100.0, wall=lambda: 100.0)
    board.observe([row(stuck_id='case-1')])
    board.flush()
    restarted = LineStuckBoard(log=LineStuckAnswerLog(log.path), wall=lambda: 101.0)
    assert log.reports()[0]['closure']['status'] == 'OBSERVATION_ENDED'
    restarted.observe([row(101.0, stuck_id='case-1')])
    restarted.observe([])
    restarted.flush()
    assert log.reports()[0]['closure']['status'] == 'OBSERVATION_ENDED'


def test_receipt_history_retention_and_limits(tmp_path):
    now = [100.0]
    log = LineStuckAnswerLog(tmp_path / 'fleet.sqlite3')
    board = LineStuckBoard(log=log, clock=lambda: now[0], wall=lambda: now[0])
    for instant in (100.0, 8 * 86400.0):
        now[0] = instant
        board.observe([row(instant)])
        board.flush()
    assert len(log.judgments()) == 1
    for limit in (True, 0, -1, 1001):
        with pytest.raises(ValueError):
            log.judgments(limit)


def test_judgment_api_is_viewer_only_and_never_sends_commands(tmp_path):
    from fakes import FakeRobot
    from test_line_stuck_api import _console, _named_app, _auth, VIEWER
    robot = FakeRobot('rosy_01')
    client, _ = _named_app(_console(robot), tmp_path)
    assert client.get('/api/fleet/judgments').status_code == 401
    response = client.get('/api/fleet/state', headers=_auth(VIEWER))
    assert response.status_code == 200
    receipt = response.json()['robots'][0]['judgment']
    assert receipt['action_admissible'] is False
    assert client.get('/api/fleet/judgments', headers=_auth(VIEWER)).status_code == 200
    assert client.get('/api/fleet/judgments?limit=0', headers=_auth(VIEWER)).status_code == 422
