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

