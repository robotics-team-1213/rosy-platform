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

