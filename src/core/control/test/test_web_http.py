"""web_http decisions on real requests, without ROS (2026-09-06 criteria C1).

A real ThreadingHTTPServer on an ephemeral port serves the backend handler; a
fake node records what would have been published. Every gate below used to
live inside the rclpy node, where host pytest could only grep for it.
"""
import http.server
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from control import web_state
from control.web_http import GOAL_BOUND, _parse_xy, make_api_handler, make_page_handler


class FakeNode:
    def __init__(self):
        self.sent = []
        self.teleop = []
        self.calibration_pub = type('Pub', (), {'get_subscription_count': lambda self: 1})()

    def publish_text(self, attr, data):
        self.sent.append((attr, data))

    def publish_teleop(self, x, z):
        self.teleop.append((x, z))

    def load_metrics(self):
        return None


@pytest.fixture
def backend():
    with web_state.LOCK:
        web_state.STATE.clear()
    node = FakeNode()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), make_api_handler(node, b'<html/>'))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield node, f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


def post(base, path, body):
    request = urllib.request.Request(base + path, data=body.encode(), method='POST')
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def ready_and_released(planner=True):
    now = time.monotonic()
    with web_state.LOCK:
        web_state.STATE.update({
            'calibration_received': now, 'calibration_ready': True,
            'calibration': {'ready': True, 'phase': 'done'},
            web_state.K_ESTOP: False,
        })
        if planner:
            web_state.STATE['planner_received'] = now


def test_driving_verbs_are_refused_until_calibrated_and_released(backend):
    node, base = backend
    assert post(base, '/wander', 'start') == 409
    assert post(base, '/wander', 'stop') == 200          # stopping is always allowed
    assert node.sent == [('wander_pub', 'stop')]
    ready_and_released()
    assert post(base, '/wander', 'start') == 200
    assert post(base, '/wander', 'fly') == 400           # not in the whitelist
    assert node.sent[-1] == ('wander_pub', 'start')


def test_teleop_is_clamped_and_gated(backend):
    node, base = backend
    assert post(base, '/teleop', json.dumps({'x': 0.1})) == 409
    assert post(base, '/teleop', json.dumps({'x': 0, 'z': 0})) == 200   # zero twist is a stop
    ready_and_released()
    assert post(base, '/teleop', json.dumps({'x': 5, 'z': -9})) == 200
    assert post(base, '/teleop', 'not json') == 400
    assert node.teleop == [(0.0, 0.0), (0.2, -1.0)]


def test_manual_goal_needs_bound_planner_and_gates(backend):
    node, base = backend
    ready_and_released(planner=False)
    assert post(base, '/goal', '1,2') == 409                           # planner stale
    ready_and_released()
    assert post(base, '/goal', f'{GOAL_BOUND + 1},0') == 400
    assert post(base, '/goal', '1.5 -2') == 200
    assert node.sent == [('wander_pub', 'manual:1.500,-2.000')]


def test_camera_ground_enable_needs_a_validated_session(backend):
    node, base = backend
    assert post(base, '/camera/calibration', 'maybe') == 400
    assert post(base, '/camera/calibration', 'enable') == 409
    assert post(base, '/camera/calibration', 'disable') == 202
    with web_state.LOCK:
        web_state.STATE['camera_calibration'] = {'eligible': True}
    assert post(base, '/camera/calibration', 'enable') == 202
    assert node.sent == [('camera_calibration_pub', 'disable'), ('camera_calibration_pub', 'enable')]


def test_state_json_reports_stale_safety_inputs(backend):
    _, base = backend
    with web_state.LOCK:
        web_state.STATE['safety_profile'] = {'valid': True}
        web_state.STATE['safety_profile_received'] = time.monotonic() - 10
    with urllib.request.urlopen(base + '/state.json', timeout=5) as response:
        state = json.load(response)
    assert state['safety_profile'] == {'valid': False, 'reason': 'stale'}
    assert state['planner_fresh'] is False
    assert state['runtime_id'] == web_state.RUNTIME_ID


def test_page_handler_serves_no_api():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), make_page_handler(b'<html/>'))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        with urllib.request.urlopen(base + '/', timeout=5) as response:
            assert response.read() == b'<html/>'
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(base + '/state.json', timeout=5)
        assert error.value.code == 404
        assert post(base, '/wander', 'stop') == 404
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('text, expected', [
    ('1,2', (1.0, 2.0)), ('1 2', (1.0, 2.0)), ('nan,1', None), ('1', None), ('a,b', None),
])
def test_parse_xy(text, expected):
    assert _parse_xy(text) == expected
