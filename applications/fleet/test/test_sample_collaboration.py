"""Incoming work review, formation state and recorded incident review share app state."""
from test_sample_flows import call
from test_sample_server import load_engine


def test_channel_review_creates_one_task_and_tracks_its_result():
    engine = load_engine()
    call(engine, 'POST', '/api/fleet/auth/login', {'login':'sample', 'password':'CHANGE_ME'})
    code, listing = call(engine, 'GET', '/api/fleet/channel-requests')
    assert code == 200 and listing['rows']
    receipt = listing['rows'][0]
    path = '/api/fleet/channel-requests/' + receipt['request_id']
    code, review = call(engine, 'GET', path + '/review')
    assert code == 200 and review['state'] == 'REQUESTED'
    body = {'expected_hash': review['content_hash'], 'expected_revision': review['revision'], 'state': 'READY',
            'candidate': {'robot_id':'sample-robot', 'x':2, 'y':1, 'yaw':0}, 'reason':'원문 확인'}
    assert call(engine, 'PUT', path + '/review', {**body, 'expected_revision':-1})[0] == 409
    _, review = call(engine, 'PUT', path + '/review', body)
    assert review['state'] == 'READY'
    code, linked = call(engine, 'POST', path + '/submit', {'expected_hash':review['content_hash'], 'expected_revision':review['revision']})
    assert code == 200 and linked['state'] == 'LINKED' and linked['work_kind'] == 'task'
    engine.advance('monitoring', 'complete')
    assert call(engine, 'GET', path + '/review')[1]['work_status'] == 'GOAL_CONFIRMED'


def test_formation_hold_resume_stop_and_incident_review():
    engine = load_engine()
    call(engine, 'POST', '/api/fleet/auth/login', {'login':'sample', 'password':'CHANGE_ME'})
    call(engine, 'POST', '/api/fleet/enrollment/robots', {'discovery_name':'sample-new', 'code':'123456'})
    assert call(engine, 'POST', '/api/fleet/formation/resume')[0] == 409
    code, formation = call(engine, 'POST', '/api/fleet/formation/start',
                            {'leader':'sample-robot', 'formation':'COLUMN', 'spacing':.6, 'members':['sample-enrolled']})
    assert code == 200 and formation['state'] == 'RUNNING'
    engine.advance('traffic', 'hold')
    assert call(engine, 'GET', '/api/fleet/formation')[1]['state'] == 'HOLDING'
    assert call(engine, 'POST', '/api/fleet/formation/resume')[1]['state'] == 'RUNNING'
    assert call(engine, 'POST', '/api/fleet/cancel-all')[0] == 200
    assert call(engine, 'GET', '/api/fleet/formation')[1]['active'] is False
    assert call(engine, 'POST', '/api/fleet/formation/stop')[1]['active'] is False
    code, incidents = call(engine, 'GET', '/api/fleet/incidents')
    assert code == 200 and incidents['reports']
    report = incidents['reports'][0]
    path = f"/api/fleet/incidents/{report['robot_ids'][0]}/{report['stuck_id']}/review"
    assert call(engine, 'POST', path, {'root_cause':'invalid', 'note':'bad'})[0] == 422
    assert call(engine, 'POST', path, {'root_cause':'obstacle', 'note':'샘플 근거 확인'}) == (200, {'reviewed':True})
    assert call(engine, 'GET', '/api/fleet/incidents')[1]['reports'][0]['reviews'][-1]['note'] == '샘플 근거 확인'
