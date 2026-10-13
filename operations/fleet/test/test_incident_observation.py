from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from fleet.incidents.automation.observation import IncidentObservationPort
from fleet.stuck.board import LineStuckBoard
from rosy.decision.deliberation import Problem


def context():
    now = [101.0]
    board = LineStuckBoard(clock=lambda: now[0], wall=lambda: now[0])
    row = dict(robot_id='pinky', online=True, state_age_s=1,
               state=dict(seq=1, timestamp=datetime.fromtimestamp(100, timezone.utc).isoformat(),
                          line_follow=dict(mode='CAMERA_LINE', stuck=dict(stuck_id='lane-1', phase='ASKING'))))
    board.observe([row])
    request = board.intervention_assessment('pinky').request
    problem = Problem('pinky', 'lane-1', request.revision, 'line_follow', 100,
                      (request.revision,), ('human', 'reobserve'), 'INTERVENE')
    step = dict(tool_name='get_incident_status', arguments={}, evidence_ids=[request.revision])
    port = IncidentObservationPort(board, human_owned=lambda *_: False, clock=lambda: now[0])
    return now, board, row, problem, step, port


def test_current_poll_readback_is_bounded_immutable_and_has_no_snapshot_extras():
    _, _, row, problem, step, port = context()
    row['secret'] = 'must-not-forward'
    readback = port.read(problem, step, snapshot={'robots': [row]})
    assert readback.payload['facts'] == {'state': 'blocked'}
    assert readback.payload['action_admissible'] is False
    assert len(readback.payload_json.encode()) <= 4096 and 'must-not-forward' not in readback.payload_json
    readback.payload['facts']['state'] = 'normal'
    assert readback.payload['facts']['state'] == 'blocked'
    with pytest.raises(FrozenInstanceError):
        readback.payload_json = '{}'


def test_same_case_next_revision_is_observed_without_relabeling_old_case():
    now, board, row, problem, step, port = context()
    now[0] = 102
    row['state'].update(seq=2, timestamp=datetime.fromtimestamp(101, timezone.utc).isoformat())
    board.observe([row])
    result = port.read(problem, step, snapshot={'robots': [row]}).payload
    assert result['generation'] != problem.generation and result['case_id'] == problem.case_id


@pytest.mark.parametrize('fault', ['foreign', 'stale', 'missing', 'duplicate', 'offline', 'revision',
                                  'human', 'human_exception', 'normal', 'tool', 'arguments', 'evidence', 'door'])
def test_scope_freshness_human_and_normal_without_closure_fail_closed(fault):
    now, board, row, problem, step, port = context()
    rows = [row]
    if fault == 'foreign': row['state']['line_follow']['stuck']['stuck_id'] = 'other'; board.observe(rows)
    elif fault == 'stale': now[0] = 104
    elif fault == 'missing': rows = []
    elif fault == 'duplicate': rows.append(row)
    elif fault == 'offline': row['online'] = False
    elif fault == 'revision': row['state']['seq'] = 2
    elif fault in {'human', 'human_exception'}:
        def owned(*_):
            if fault == 'human_exception': raise RuntimeError('private error')
            return True
        port = IncidentObservationPort(board, human_owned=owned, clock=lambda: now[0])
    elif fault == 'normal': row['state']['line_follow'] = dict(mode='OFF', stuck=None); board.observe(rows)
    elif fault == 'tool': step['tool_name'] = 'get_mission_status'
    elif fault == 'arguments': step['arguments'] = {'url': 'http://other'}
    elif fault == 'evidence': step['evidence_ids'] = ['invented']
    elif fault == 'door': problem = replace(problem, domain='door')
    with pytest.raises(ValueError):
        port.read(problem, step, snapshot={'robots': rows})
