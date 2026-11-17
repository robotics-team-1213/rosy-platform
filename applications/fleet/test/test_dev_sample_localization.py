"""Sample localization scenario: fourteen labelled robots serving the FINAL relocalize/operator route
shapes (branch fix/fleet-relocalize-operator), operator-only writes with the real refusal codes, and
dev events that walk one robot from the operator's press to a localized pose, a failed search, or a
stale confirm (the dev event `expire`)."""
import math

import pytest

from test_sample_flows import call
from test_sample_server import load_engine

FLEET = '/api/fleet'
#: The mirror-twin window shared/web/localization-state.js uses (|dyaw - pi| < 0.35 rad).
MIRROR_TWIN_RAD = 0.35
ROBOTS = [f'loc-{n}' for n in range(1, 15)]


def login(engine):
    assert call(engine, 'POST', '/api/fleet/auth/login', {'login': 'sample', 'password': 'CHANGE_ME'})[0] == 204


def read(engine, robot_id):
    status, body = call(engine, 'GET', f'{FLEET}/robots/{robot_id}/localization')
    assert status == 200, body
    assert body['sample'] is True and body['label'] == '샘플 데이터'
    return body


def auto_locate(engine):
    status, body = call(engine, 'GET', f'{FLEET}/auto-locate')
    assert status == 200 and body['sample'] is True and body['label'] == '샘플 데이터'
    return {robot['robot_id']: robot for robot in body['robots']}


def wrapped_rad(a, b):
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def test_fourteen_robots_cover_the_panel_cases_and_every_payload_is_marked_sample():
    engine = load_engine()
    login(engine)
    fleet = auto_locate(engine)
    assert fleet['loc-2']['session_left_s'] > 0
    assert fleet['loc-6']['anchor_enabled'] is True and fleet['loc-6']['anchor_blocked'] is False
    blocked = fleet['loc-10']
    assert blocked['anchor_blocked'] is True and blocked['anchor_refused_reason'] == 'CAUTION_ACTIVE'
    status, body = call(engine, 'GET', f'{FLEET}/robots/loc-14/localization')
    assert status == 503 and body['detail']['code'] == 'LOCALIZATION_DISABLED'  # the real route's refusal
    robots = {robot_id: read(engine, robot_id) for robot_id in ROBOTS if robot_id != 'loc-14'}
    assert robots['loc-1']['localization'] is None and robots['loc-1']['ladder'] is None
    assert robots['loc-2']['localization']['state'] == 'UNKNOWN'
    rotating = robots['loc-3']
    assert rotating['motion_allowed'] is True and rotating['motion_allow_s'] == 120.0
    assert rotating['last_operator_request']['by'] == 'operator-b'
    assert rotating['last_operator_request']['expires_in_s'] > 0
    assert rotating['ladder']['last_mission'] == {'kind': 'rotate_in_place', 'rung': 'rotate',
                                                  'held': [], 'result': 'sent'}
    candidates = robots['loc-4']
    report = candidates['candidates']
    assert len(report['candidates']) == 3 and all('scan_fit' in c for c in report['candidates'])
    assert report['candidates'][0]['scan_fit'] == max(c['scan_fit'] for c in report['candidates'])
    assert wrapped_rad(report['candidates'][1]['yaw'], report['candidates'][0]['yaw']) - math.pi \
        < MIRROR_TWIN_RAD  # the twin is the 180-degree mirror of the top candidate
    assert candidates['localization']['state'] == 'CANDIDATES'
    assert candidates['localization']['request_id'] == report['request_id']
    checking = robots['loc-5']
    assert checking['localization']['state'] == 'CANDIDATES' and checking['localization']['reason'] == 'checking'
    assert checking['ladder']['last_decision']['candidate_index'] == 0
    assert robots['loc-6']['localization']['state'] == 'LOCALIZED' \
        and robots['loc-6']['localization']['age_s'] <= 30
    assert robots['loc-7']['localization']['state'] == 'LOCALIZED' \
        and robots['loc-7']['localization']['age_s'] > 30
    assert robots['loc-8']['localization']['state'] == 'SUSPECT'
    assert robots['loc-9']['localization'] is None
    assert robots['loc-9']['ladder']['last_mission']['result'] == 'path_not_clear'
    assert robots['loc-11']['ladder']['last_mission'] == {'kind': None, 'rung': 'rotate', 'held': [],
                                                          'result': 'operator_required'}
    assert robots['loc-12']['localization'] is None and robots['loc-12']['candidates'] is None
    assert robots['loc-13']['localization']['state'] == 'LOCALIZED'
    for body in robots.values():
        assert body['sample'] is True and body['label'] == '샘플 데이터'
        assert body['motion_allow_s'] == 120.0
        assert set(body) >= {'robot_id', 'localization', 'candidates', 'ladder', 'motion_allowed',
                             'motion_allow_s', 'last_operator_request'}


def test_relocalize_success_and_every_refusal_use_the_real_codes_statuses_and_bodies():
    engine = load_engine()
    login(engine)

    def post(robot_id):
        return call(engine, 'POST', f'{FLEET}/robots/{robot_id}/relocalize', {})

    assert post('nope') == (404, {'detail': {'code': 'UNKNOWN_ROBOT',
                                             'message': 'robot is not on the roster'}})
    assert post('loc-14')[1]['detail']['code'] == 'LOCALIZATION_DISABLED' and post('loc-14')[0] == 503
    assert post('loc-13') == (409, {'detail': {'code': 'RELOCALIZE_TRIP_ACTIVE',
                                               'message': 'the robot is on a trip or formation; stop it before relocalizing'}})
    assert post('loc-12')[0] == 409 and post('loc-12')[1]['detail']['code'] == 'ROBOT_OFFLINE'
    status, body = post('loc-6')
    assert status == 409 and body['detail']['code'] == 'ALREADY_LOCALIZED'
    assert body['detail']['localization']['state'] == 'LOCALIZED'
    status, body = call(engine, 'GET', f'{FLEET}/robots/loc-14/localization')
    assert status == 503 and body['detail']['code'] == 'LOCALIZATION_DISABLED'
    status, body = call(engine, 'GET', f'{FLEET}/robots/nope/localization')
    assert status == 404 and body['detail']['code'] == 'UNKNOWN_ROBOT'
    status, body = post('loc-2')
    assert status == 200 and body['sample'] is True and body['requested_by'] == 'sample'
    assert body['motion_allowed'] is True and body['motion_allow_s'] == 120.0
    assert body['last_operator_request']['by'] == 'sample'
    assert body['last_operator_request']['expires_in_s'] > 0
    assert body['mission']['kind'] == 'rotate_in_place' and body['mission']['result'] == 'sent'
    after = read(engine, 'loc-2')
    assert after['motion_allowed'] is True and after['ladder']['last_mission']['result'] == 'sent'


def test_lift_block_clears_the_blocked_case_and_refuses_everything_else():
    engine = load_engine()
    login(engine)
    status, body = call(engine, 'POST', f'{FLEET}/auto-locate/loc-10/lift-block', {})
    assert status == 200
    assert body == {'sample': True, 'label': '샘플 데이터', 'robot_id': 'loc-10', 'anchor_blocked': False}
    lifted = auto_locate(engine)['loc-10']
    assert lifted['anchor_blocked'] is False and lifted['anchor_refused_reason'] is None
    for robot_id in ('loc-2', 'nope'):
        status, body = call(engine, 'POST', f'{FLEET}/auto-locate/{robot_id}/lift-block', {})
        assert status == 409 and body['detail']['code'] == 'AUTO_LOCATE_NOT_ENABLED'


def test_confirm_takes_a_reported_index_and_refuses_the_rest():
    engine = load_engine()
    login(engine)

    def confirm(robot_id, body):
        return call(engine, 'POST', f'{FLEET}/robots/{robot_id}/localization/confirm', body)

    status, body = confirm('loc-4', {'candidate_id': 0})
    assert status == 200 and body['sample'] is True and body['candidate_index'] == 0
    assert body['core'] == {'request_id': 'req-loc-4-41'}
    after = read(engine, 'loc-4')
    assert after['localization']['reason'] == 'checking'  # the robot's 3 s check runs
    assert after['ladder']['last_decision']['candidate_index'] == 0
    assert confirm('loc-4', {'candidate_id': 3})[1]['detail']['code'] == 'CANDIDATE_NOT_REPORTED'
    assert confirm('loc-4', {'candidate_id': 5})[0] == 404
    assert confirm('loc-4', {})[0] == 422  # neither candidate_id nor a pose
    assert confirm('loc-1', {'candidate_id': 0})[0] == 409
    assert confirm('loc-1', {'candidate_id': 0})[1]['detail']['code'] == 'NO_CANDIDATES'
    assert confirm('loc-14', {'candidate_id': 0})[1]['detail']['code'] == 'NO_CANDIDATES'
    assert confirm('nope', {'candidate_id': 0})[0] == 404
    assert confirm('nope', {'candidate_id': 0})[1]['detail']['code'] == 'UNKNOWN_ROBOT'
    status, body = confirm('loc-4', {'candidate_id': 1})
    assert status == 200 and body['candidate_index'] == 1  # the CURRENT report is always the index base


def test_a_viewer_reads_but_cannot_write():
    engine = load_engine()
    engine.reset('viewer')
    login(engine)  # a signed-in viewer: reads work, operator writes are 403
    writes = ((f'{FLEET}/robots/loc-2/relocalize', {}),
              (f'{FLEET}/robots/loc-4/localization/confirm', {'candidate_id': 0}),
              (f'{FLEET}/auto-locate/loc-10/lift-block', {}))
    for path, body in writes:
        assert call(engine, 'POST', path, body)[0] == 403, path
    assert read(engine, 'loc-4')['localization']['state'] == 'CANDIDATES'
    assert read(engine, 'loc-4')['sample'] is True
    assert 'loc-2' in auto_locate(engine)


def test_dev_events_walk_press_to_localized_and_stop_to_failed():
    engine = load_engine()
    login(engine)
    engine.advance('localization', 'relocalize')
    rotating = read(engine, 'loc-1')
    assert rotating['motion_allowed'] is True
    assert rotating['last_operator_request']['by'] == 'sample'
    assert rotating['ladder']['last_mission']['result'] == 'sent'
    engine.advance('localization', 'candidates')
    shown = read(engine, 'loc-1')['candidates']
    assert len(shown['candidates']) == 3
    engine.advance('localization', 'expire')  # CORE's open request moved on since the report the operator saw
    status, body = call(engine, 'POST', f'{FLEET}/robots/loc-1/localization/confirm', {'candidate_id': 0})
    assert status == 409 and body['detail']['code'] == 'STALE_REQUEST'
    assert body['detail']['message'].startswith('request req-loc-1-') and body['detail']['robot_id'] == 'loc-1'
    status, body = call(engine, 'POST', f'{FLEET}/robots/loc-1/localization/confirm', {'candidate_id': 0, 'request_id': 'x'})
    assert status == 422  # the real ConfirmRequest forbids extra keys
    status, body = call(engine, 'POST', f'{FLEET}/robots/loc-1/localization/confirm', {'candidate_id': 5})
    assert status == 404 and body['detail']['code'] == 'CANDIDATE_NOT_REPORTED'
    status, body = call(engine, 'POST', f'{FLEET}/robots/loc-1/localization/confirm', {'candidate_id': 1})
    assert status == 200 and body['candidate_index'] == 1
    assert read(engine, 'loc-1')['localization']['reason'] == 'checking'
    engine.advance('localization', 'localized')
    done = read(engine, 'loc-1')
    assert done['localization']['state'] == 'LOCALIZED' and done['localization']['pose_frame'] == 'map'
    assert done['candidates'] is None and done['ladder'] is None
    status, _ = call(engine, 'POST', f'{FLEET}/robots/loc-1/relocalize', {})
    assert status == 409  # already LOCALIZED: the press is refused, and so is the dev event
    with pytest.raises(ValueError):
        engine.advance('localization', 'relocalize')
    engine2 = load_engine()
    login(engine2)
    engine2.advance('localization', 'relocalize')
    engine2.advance('localization', 'candidates')
    engine2.advance('localization', 'stop')
    failed = read(engine2, 'loc-1')
    assert failed['localization'] is None and failed['candidates'] is None
    assert failed['ladder']['last_mission']['result'] == 'path_not_clear'
    with pytest.raises(ValueError):
        engine2.advance('localization', 'localized')


def test_localization_adds_no_unhandled_requests():
    engine = load_engine()
    login(engine)
    auto_locate(engine)
    read(engine, 'loc-4')
    call(engine, 'POST', f'{FLEET}/robots/loc-2/relocalize', {})
    call(engine, 'POST', f'{FLEET}/robots/loc-4/localization/confirm', {'candidate_id': 0})
    call(engine, 'POST', f'{FLEET}/auto-locate/loc-10/lift-block', {})
    assert engine.unhandled == []


def test_round3_real_route_order_and_auto_locate_start():
    engine = load_engine()
    login(engine)
    confirm = lambda rid, body: call(engine, 'POST', f'{FLEET}/robots/{rid}/localization/confirm', body)
    assert confirm('nope', {})[0] == 422  # body validation runs before the roster, like pydantic
    assert confirm('loc-4', {'candidate_id': 8})[0] == 422 and confirm('loc-4', {'candidate_id': -1})[0] == 422
    assert confirm('loc-4', {'x': 1.0})[0] == 422
    engine.advance('localization', 'relocalize')
    engine.advance('localization', 'candidates')
    engine.advance('localization', 'expire')
    assert confirm('loc-1', {'candidate_id': 5})[1]['detail']['code'] == 'CANDIDATE_NOT_REPORTED'  # index before CORE
    assert confirm('loc-1', {'candidate_id': 0})[1]['detail']['code'] == 'STALE_REQUEST'
    assert confirm('loc-1', {'candidate_id': 0})[0] == 200  # the stale refusal is one-shot
    status, body = call(engine, 'POST', f'{FLEET}/auto-locate', {})
    assert status == 200 and body['sample'] is True and 'loc-2' in {r['robot_id'] for r in body['robots']}
    viewer = load_engine()
    viewer.reset('viewer')
    login(viewer)
    assert call(viewer, 'POST', f'{FLEET}/auto-locate', {})[0] == 403


def test_gate_is_one_press_one_motion_with_the_revoked_shape():
    engine = load_engine()
    login(engine)
    assert read(engine, 'loc-9')['last_operator_request'] == {'revoked': {'reason': 'mission_obstacle', 'at': 1792454200.0}}
    assert read(engine, 'loc-9')['motion_allowed'] is False
    engine.advance('localization', 'relocalize')
    assert read(engine, 'loc-1')['last_operator_request']['expires_in_s'] == 120.0
    engine.advance('localization', 'candidates')  # the rotation ended: the gate closed, no requester in the view
    done = read(engine, 'loc-1')
    assert done['motion_allowed'] is False
    assert done['last_operator_request'] == {'revoked': {'reason': 'mission_done', 'at': done['last_operator_request']['revoked']['at']}}
    assert set(done['last_operator_request']) == {'revoked'}
    engine.advance('localization', 'stop')  # already closed: an e-stop leaves the recorded reason
    assert read(engine, 'loc-1')['last_operator_request']['revoked']['reason'] == 'mission_done'
    status, body = call(engine, 'POST', f'{FLEET}/robots/loc-1/relocalize', {})  # a new press opens a new gate
    assert status == 200 and body['last_operator_request']['expires_in_s'] == 120.0 and 'revoked' not in body['last_operator_request']
    assert read(engine, 'loc-1')['motion_allowed'] is True
    engine.advance('localization', 'stop')  # an e-stop while the gate is open closes it with reason estop
    stopped = read(engine, 'loc-1')
    assert stopped['motion_allowed'] is False and stopped['last_operator_request']['revoked']['reason'] == 'estop'
    engine.advance('localization', 'relocalize')
    engine.advance('localization', 'obstacle')
    assert read(engine, 'loc-1')['last_operator_request']['revoked']['reason'] == 'mission_obstacle'
    engine.advance('localization', 'relocalize')
    engine.advance('localization', 'candidates')
    status, _ = call(engine, 'POST', f'{FLEET}/robots/loc-1/localization/confirm', {'candidate_id': 0})
    assert status == 200
    engine.advance('localization', 'localized')
    assert read(engine, 'loc-1')['last_operator_request']['revoked']['reason'] == 'mission_done'
    with pytest.raises(ValueError):
        engine.advance('localization', 'obstacle')
