"""State, revisions and terminal results survive a second frontend read."""
import json

from test_sample_server import load_engine


def call(engine, method, path, body=None):
    response = engine.handle(method, path, {'Cookie': 'rosy_sample_session=sample-1'},
                             json.dumps(body).encode() if body is not None else b'')
    return response.status, json.loads(response.body) if response.body else None


def test_flow_ids_revisions_and_reset_are_consistent():
    engine = load_engine()
    call(engine, 'POST', '/api/fleet/auth/login', {'login': 'sample', 'password': 'sample-password'})
    code, plan = call(engine, 'POST', '/api/fleet/robots/sample-robot/trip', {'to': 'loading'})
    assert code == 200
    code, trip = call(engine, 'POST', f"/api/fleet/trips/{plan['plan_id']}/start", {})
    assert code == 200
    engine.advance('work', 'complete')
    code, result = call(engine, 'GET', f"/api/fleet/trips/{trip['trip_id']}")
    assert code == 200 and result['state'] == 'arrived'
    assert result['trip_id'] == trip['trip_id']
    engine.reset('normal')
    assert call(engine, 'GET', f"/api/fleet/trips/{trip['trip_id']}")[0] == 401


def test_unauthorized_and_stale_changes_do_not_mutate_state():
    engine = load_engine()
    assert call(engine, 'POST', '/api/fleet/estop', {})[0] == 401
    call(engine, 'POST', '/api/fleet/auth/login', {'login': 'sample', 'password': 'sample-password'})
    _, before = call(engine, 'GET', '/api/fleet/dispatch-control')
    assert call(engine, 'POST', '/api/fleet/dispatch/rearm', {'expected_generation': -1})[0] == 409
    assert call(engine, 'GET', '/api/fleet/dispatch-control')[1] == before


def test_assistant_idempotency_and_explicit_terminal_result():
    engine = load_engine()
    call(engine, 'POST', '/api/fleet/auth/login', {'login': 'sample', 'password': 'sample-password'})
    body = {'request_id': 'sample-request', 'conversation_id': 'sample-conversation', 'text': '현재 상태', 'locale': 'ko-KR'}
    code, result = call(engine, 'POST', '/api/fleet/assistant/messages', body)
    assert code == 202 and result['state'] == 'PENDING'
    assert call(engine, 'POST', '/api/fleet/assistant/messages', body) == (200, result)
    assert call(engine, 'POST', '/api/fleet/assistant/messages', {**body, 'text': '다른 요청'})[0] == 409
    engine.advance('assistant', 'answer')
    code, result = call(engine, 'GET', '/api/fleet/assistant/messages/sample-request')
    assert code == 200 and result['state'] == 'ANSWERED' and result['response']
    assert result['action_admissible'] is False


def test_media_grant_renewal_revoke_and_viewer_read_permission():
    engine = load_engine()
    engine.reset('viewer')
    response = engine.handle('POST', '/api/fleet/auth/login', {}, b'{"login":"sample","password":"sample-password"}')
    cookie = next(v for k, v in response.headers if k == 'Set-Cookie').split(';')[0]
    def media(method, suffix=''):
        response = engine.handle(method, '/api/fleet/robots/sample-robot/media-grant' + suffix, {'Cookie':cookie}, b'')
        return response.status, json.loads(response.body) if response.body else None
    code, grant = media('POST')
    assert code == 201 and grant['robot_id'] == 'sample-robot'
    identifier = grant['grant_id']
    assert media('POST', f'/{identifier}/renew')[1]['grant_id'] == identifier
    assert media('DELETE', f'/{identifier}')[0] == 204
    assert media('POST', f'/{identifier}/renew')[0] == 403


def test_cell_documents_revision_preview_and_job_recovery():
    engine = load_engine()
    call(engine, 'POST', '/api/fleet/auth/login', {'login': 'sample', 'password': 'sample-password'})
    refs = {}
    for kind in ('recipe', 'cell'):
        code, row = call(engine, 'GET', f'/api/fleet/cell-app/documents/{kind}/sample')
        assert code == 200 and row['document']
        refs[kind + '_id'] = 'sample'
        refs[kind + '_digest'] = row['digest']
        assert call(engine, 'POST', f'/api/fleet/cell-app/documents/{kind}/sample',
                    {'document': row['document'], 'expected_digest': 'stale'})[0] == 409
    code, preview = call(engine, 'POST', '/api/fleet/cell-app/compile', refs)
    assert code == 200 and preview['summary']['transfer_count'] == 18
    body = {**refs, 'request_key': 'sample-cell-1', 'workcell_id': 'sample-cell', 'instance_id': 'sample-arm'}
    code, result = call(engine, 'POST', '/api/fleet/cell-app/proposals', body)
    assert code == 200 and result['mission']['status'] == 'PROPOSED'
    identifier = result['mission']['mission_id']
    assert call(engine, 'POST', f'/api/fleet/missions/{identifier}/admit', {'expected_generation': -1})[0] == 409
    assert call(engine, 'POST', f'/api/fleet/missions/{identifier}/admit', {'expected_generation': 1})[1]['mission']['status'] == 'READY'
    engine.advance('cell_jobs', 'hold')
    assert call(engine, 'GET', f'/api/fleet/cell-jobs/{identifier}')[1]['job']['status'] == 'HOLD'
    assert call(engine, 'POST', f'/api/fleet/cell-jobs/{identifier}/resume', {'expected_generation': 1})[0] == 200
    engine.advance('cell_jobs', 'complete')
    assert call(engine, 'GET', f'/api/fleet/cell-jobs/{identifier}')[1]['job']['status'] == 'GOAL_CONFIRMED'


def test_enrollment_pairing_and_calibration_readbacks():
    engine = load_engine()
    call(engine, 'POST', '/api/fleet/auth/login', {'login': 'sample', 'password': 'sample-password'})
    assert call(engine, 'POST', '/api/fleet/enrollment/robots', {'discovery_name': 'sample-new', 'code': 'bad'})[0] == 422
    code, robot = call(engine, 'POST', '/api/fleet/enrollment/robots', {'discovery_name': 'sample-new', 'code': '123456'})
    assert code == 201 and robot['robot_id'] == 'sample-enrolled'
    assert robot['robot_id'] in [row['robot_id'] for row in call(engine, 'GET', '/api/fleet/state')[1]['robots']]
    assert call(engine, 'GET', '/api/fleet/enrollment/robots')[1]['robots'][0]['robot_id'] == robot['robot_id']
    assert call(engine, 'DELETE', '/api/fleet/enrollment/robots/sample-enrolled')[1]['state'] == 'removed'
    code, pending = call(engine, 'GET', '/api/fleet/pairing/v2/pending')
    assert code == 200 and len(pending) == 1
    item = pending[0]
    base = '/api/fleet/pairing/v2/requests/' + item['request_id']
    body = {'action': 'approve', 'source_id': 'sample-camera', 'revision': item['revision'], 'persist_requested': True}
    assert call(engine, 'POST', base + '/decision', {**body, 'revision': -1})[0] == 409
    assert call(engine, 'POST', base + '/decision', body)[0] == 200
    relationships = call(engine, 'GET', '/api/fleet/pairing/v2/relationships')[1]
    assert relationships and relationships[0]['persistent']
    identifier = relationships[0]['relationship_id']
    assert call(engine, 'POST', f'/api/fleet/pairing/v2/relationships/{identifier}/revoke')[0] == 200
    assert call(engine, 'GET', '/api/fleet/pairing/v2/relationships')[1][0]['state'] == 'revoked'
    approval = {'source_id': 'sample-camera', 'map_to_image': [100, 0, 0, 0, -100, 360, 0, 0, 1],
                'image': {'width': 640, 'height': 360}, 'track_bounds_m': {'min_x': 0, 'min_y': 0, 'max_x': 6.4, 'max_y': 3.6},
                'fit_score': .81, 'lens': None, 'frame_seq': 12}
    code, record = call(engine, 'POST', '/api/fleet/calibrations', approval)
    assert code == 200 and record['use'] == 'display-only'
    assert call(engine, 'GET', '/api/fleet/calibrations')[1]['calibrations'] == [record]
    assert call(engine, 'DELETE', '/api/fleet/calibrations/sample-camera')[1]['removed']


def test_goal_idempotency_progress_and_terminal_read():
    engine = load_engine()
    call(engine, 'POST', '/api/fleet/auth/login', {'login': 'sample', 'password': 'sample-password'})
    headers = {'Cookie': 'rosy_sample_session=sample-1', 'Idempotency-Key': 'sample-goal'}
    target = '/api/fleet/robots/sample-robot/goal'
    first = engine.handle('POST', target, headers, b'{"x":2,"y":1,"yaw":0}')
    assert first.status == 200
    task = json.loads(first.body)['task']
    again = engine.handle('POST', target, headers, b'{"x":2,"y":1,"yaw":0}')
    assert json.loads(again.body)['task']['task_id'] == task['task_id']
    assert engine.handle('POST', target, headers, b'{"x":3,"y":1,"yaw":0}').status == 409
    engine.advance('monitoring', 'complete')
    assert call(engine, 'GET', '/api/fleet/tasks/' + task['task_id'])[1]['task']['status'] == 'GOAL_CONFIRMED'


def test_reset_does_not_restore_a_revoked_password_change_cookie():
    engine = load_engine()
    call(engine, 'POST', '/api/fleet/auth/login', {'login': 'sample', 'password': 'sample-password'})
    response = engine.handle('POST', '/api/fleet/auth/change-password', {'Cookie':'rosy_sample_session=sample-1'},
                             b'{"current_password":"sample-password","password":"changed-password"}')
    old = next(value for key, value in response.headers if key == 'Set-Cookie').split(';')[0]
    engine.reset('normal')
    engine.handle('POST', '/api/fleet/auth/login', {}, b'{"login":"sample","password":"sample-password"}')
    assert engine.handle('GET', '/api/fleet/auth/session', {'Cookie':old}, b'').status == 401


def test_policy_stage_rules_and_incident_require_another_person():
    engine = load_engine()
    call(engine, 'POST', '/api/fleet/auth/login', {'login': 'sample', 'password': 'sample-password'})
    base = '/api/fleet/workcells/sample-cell/policy'
    body = {'operator_confirmed': True, 'policy_revision': 'sample-policy', 'to_stage': 'L0',
            'rig_revision': 'sample-rig', 'calibration_revision': 'sample-calibration',
            'evidence_sha256': 'a' * 64, 'note': 'sample offline receipt'}
    code, proposal = call(engine, 'POST', base + '/proposals', body)
    assert code == 200 and proposal['state'] == 'PENDING'
    assert call(engine, 'POST', base + f"/proposals/{proposal['proposal_id']}/decision",
                {'operator_confirmed': True, 'approve': True})[1]['state'] == 'APPROVED'
    assert call(engine, 'POST', base + '/proposals', {**body, 'to_stage': 'L2'})[0] == 409
    _, incident = call(engine, 'POST', base + '/incidents', {'operator_confirmed': True, 'description': '샘플 점검'})
    clear = base + f"/incidents/{incident['incident_id']}/clear"
    assert call(engine, 'POST', clear, {'operator_confirmed': True, 'note': '원인 확인'})[0] == 403
    response = engine.handle('POST', '/api/fleet/auth/login', {}, b'{"login":"sample-reviewer","password":"sample-password"}')
    assert response.status == 204
    cookie = next(value for key, value in response.headers if key == 'Set-Cookie').split(';')[0]
    response = engine.handle('POST', clear, {'Cookie':cookie}, b'{"operator_confirmed":true,"note":"reviewed"}')
    assert response.status == 200 and json.loads(response.body)['cleared_by'] == 'sample-reviewer'

