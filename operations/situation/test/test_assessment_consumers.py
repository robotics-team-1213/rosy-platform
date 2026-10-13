"""D-652 current-state binding, transport age and zero-action shadow consumers."""

import importlib
import importlib.util
import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest


def adapter():
    assert importlib.util.find_spec('rosy_situation.snapshot_assessment') is not None
    return importlib.import_module('rosy_situation.snapshot_assessment')


def robot(stuck=None, **changes):
    row = {'robot_id': 'pinky', 'online': True, 'state_age_s': 0.5,
           'state': {'seq': 9, 'timestamp': '1970-01-01T00:01:39+00:00',
                     'line_follow': {'mode': 'OFF' if stuck is None else 'CAMERA_LINE', 'stuck': stuck}}}
    row.update(changes)
    return row


def snapshot(row, pending=(), **changes):
    return {'observed_at': 100.0, 'state': {'robots': [row]},
            'line_stuck': {'pending': list(pending)}, **changes}


@pytest.mark.parametrize('phase,necessity,reason', [
    ('ASKING', 'INTERVENE', 'persistent_blockage'),
    ('WAITING_CONSOLE', 'INTERVENE', 'persistent_blockage'),
    ('BACKING', 'ABSTAIN', 'deadline_unknown'),
    ('SETTLING', 'ABSTAIN', 'deadline_unknown'),
    ('CRAWLING', 'ABSTAIN', 'deadline_unknown'),
    ('invented', 'ABSTAIN', 'condition_unknown'),
])
def test_existing_core_phases_have_explicit_necessity(phase, necessity, reason):
    row = robot({'stuck_id': 's1', 'phase': phase})
    result = adapter().snapshot_assessments(snapshot(row))['pinky']
    assert (result.necessity, result.reason) == (necessity, reason)


def test_normal_inactive_line_monitor_and_unknown_active_motion_are_different():
    row = robot()
    assert adapter().snapshot_assessments(snapshot(row))['pinky'].necessity == 'DO_NOT_INTERVENE'
    row['state']['line_follow']['mode'] = 'CAMERA_LINE'
    assert adapter().snapshot_assessments(snapshot(row))['pinky'].necessity == 'ABSTAIN'


def test_http_collection_delay_and_server_evidence_cannot_refresh_old_state():
    a = adapter()
    assert a.snapshot_assessments(snapshot(robot(), _state_requested_at=96.0))['pinky'].reason == 'evidence_stale'
    for changes in ({'online': False}, {'state_age_s': True}, {'state_age_s': -1.0}, {'state_age_s': None}):
        assert a.snapshot_assessments(snapshot(robot(**changes)))['pinky'].necessity == 'ABSTAIN'
    row = robot()
    row['state']['evidence'] = {'line_follow': {'evidence': 'delayed'}}
    assert a.snapshot_assessments(snapshot(row))['pinky'].necessity == 'ABSTAIN'
    row['state']['timestamp'] = '1970-01-01T00:01:41+00:00'
    assert a.snapshot_assessments(snapshot(row))['pinky'].reason == 'evidence_future'


def test_pending_case_is_not_the_current_core_case():
    row = robot({'stuck_id': 's2', 'phase': 'WAITING_CONSOLE'})
    pending = [{'robot_id': 'pinky', 'stuck_id': 's1'}]
    assert adapter().snapshot_assessments(snapshot(row, pending))['pinky'].reason == 'evidence_conflict'
    assert adapter().snapshot_assessments(snapshot(robot(), pending))['pinky'].necessity == 'ABSTAIN'


def test_fleet_shadow_read_expires_and_stays_bounded_without_a_transport():
    from fleet.stuck.board import LineStuckBoard
    now = [100.0]
    board = LineStuckBoard(clock=lambda: now[0], wall=lambda: now[0])
    row = robot()
    row['_state_mono'] = 99.5
    board.observe([row])
    first = board.intervention_assessment('pinky')
    assert first == adapter().snapshot_assessments(snapshot(robot()))['pinky']
    now[0] = 102.0
    assert board.intervention_assessment('pinky').necessity == 'ABSTAIN'
    assert board.pending() == []
    board.observe([])
    assert board.intervention_assessment('pinky') is None


def test_situation_logs_normal_and_abstention_without_problems_or_actions(tmp_path):
    from rosy_situation.service import Situation
    now, calls = [100.0], []
    row = robot()

    class Fleet:
        def call(self, path, body=None):
            calls.append((path, body))
            if path == '/api/fleet/state':
                current = deepcopy(row)
                current['state']['timestamp'] = datetime.fromtimestamp(now[0] - 1, timezone.utc).isoformat()
                return {'robots': [current]}
            return {}

    mode = tmp_path / 'mode'
    mode.write_text('shared')
    service = Situation(Fleet(), tmp_path / 'state', mode, clock=lambda: now[0], wall=lambda: now[0])
    service.step()
    now[0] += 1
    service.step()
    now[0] += 59
    service.step()
    row['online'] = False
    service.step()
    records = [json.loads(line) for p in (tmp_path / 'state/logs').glob('*-assessments.jsonl')
               for line in p.read_text().splitlines()]
    assert [r['necessity'] for r in records] == ['DO_NOT_INTERVENE', 'DO_NOT_INTERVENE', 'ABSTAIN']
    assert all(path == '/api/fleet/ai/heartbeat' for path, body in calls if body is not None)
    assert not list((tmp_path / 'state/logs').glob('*-proposals.jsonl'))


def test_context_refreshes_active_case_at_ttl_and_trims_closed_cases():
    from rosy_situation.incident_context import ContextDraft
    stuck = {'robot_id': 'pinky', 'stuck_id': 's1', 'phase': 'WAITING_CONSOLE', 'cause': 'lane_lost'}
    view = snapshot(robot(deepcopy(stuck)), [stuck])
    drafts = ContextDraft()
    assert len(drafts(view)) == 1
    view['observed_at'] = 102.9
    assert drafts(view) == []
    view['observed_at'] = 103.0
    view['state']['robots'][0]['state']['timestamp'] = '1970-01-01T00:01:42+00:00'
    assert len(drafts(view)) == 1
    view['state']['robots'][0]['state']['line_follow']['stuck']['stuck_id'] = 's2'
    view['observed_at'] = 106.0
    assert drafts(view) == []
    view['line_stuck']['pending'] = []
    drafts(view)
    assert drafts.seen == set()


def test_context_cannot_relabel_old_transport_or_cleared_state_as_current():
    from rosy_situation.incident_context import ContextDraft
    stuck = {'robot_id': 'pinky', 'stuck_id': 's1', 'phase': 'WAITING_CONSOLE', 'cause': 'lane_lost'}
    assert ContextDraft()(snapshot(robot(deepcopy(stuck)), [stuck], _state_requested_at=96.0)) == []
    assert ContextDraft()(snapshot(robot(), [stuck])) == []
    assert ContextDraft()(snapshot(robot(deepcopy(stuck), online=False), [stuck])) == []


def test_legacy_context_draft_cannot_supply_missing_core_revision_or_time():
    from rosy_situation.incident_context import ContextDraft
    stuck = {'robot_id': 'pinky', 'stuck_id': 's1', 'phase': 'WAITING_CONSOLE', 'cause': 'lane_lost'}
    row = robot(deepcopy(stuck))
    del row['state']['seq'], row['state']['timestamp']
    view = snapshot(row, [stuck])
    drafts = ContextDraft()(view)
    assert len(drafts) == 1
    assert drafts[0]['value']['status'] == 'needs_review'
    view['incident_context'] = {'pinky': drafts[0]}
    result = adapter().snapshot_assessments(view)['pinky']
    assert result.necessity == 'ABSTAIN'
    assert result.request.revision == ''
    assert result.request.evidence[0].observed_at is None
