"""web_http decisions on real requests, without ROS (2026-09-06 criteria C1).

A real ThreadingHTTPServer on an ephemeral port serves the backend handler; a
fake node records what would have been published. Every gate below used to
live inside the rclpy node, where host pytest could only grep for it.
"""
import http.server
import json
import os
import threading
import time
import urllib.error
import urllib.request

import pytest

from control import web_state
from control.web_http import (
    GOAL_BOUND, _parse_xy, make_api_handler, make_page_handler, page_origin_allowed, shared_assets,
    web_common_dir)

PAGE_PORT = 28181


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
    server = http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), make_api_handler(node, b'<html/>', page_port=PAGE_PORT))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield node, f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


def post(base, path, body, origin=None):
    headers = {} if origin is None else {'Origin': origin}
    request = urllib.request.Request(base + path, data=body.encode(), method='POST', headers=headers)
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


def test_page_handler_serves_web_common_manifest_assets():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), make_page_handler(b'<html/>'))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        with urllib.request.urlopen(base + '/common/hold-ticker.js', timeout=5) as response:
            assert response.headers['Content-Type'] == 'text/javascript'
            assert b'createHoldTicker' in response.read()
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(base + '/common/manifest.json', timeout=5)
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_web_common_dir_falls_back_to_the_source_tree(tmp_path):
    root = web_common_dir(str(tmp_path))                 # no manifest.json: not a web_common share
    assert os.path.isfile(os.path.join(root, 'manifest.json'))
    assert 'hold-ticker.js' in shared_assets(root)


def test_post_from_a_foreign_origin_is_refused_without_effect(backend):
    node, base = backend
    assert post(base, '/wander', 'stop', origin='http://evil.example') == 403
    assert post(base, '/estop', 'stop', origin=f'http://127.0.0.1:{PAGE_PORT + 1}') == 403
    assert post(base, '/estop', 'stop', origin='null') == 403
    assert node.sent == []
    assert post(base, '/estop', 'stop', origin=f'http://localhost:{PAGE_PORT}') == 200
    assert post(base, '/estop', 'stop', origin=f'http://127.0.0.1:{PAGE_PORT}') == 200
    assert post(base, '/estop', 'stop') == 200                  # no Origin: not a browser page
    assert node.sent == [('estop_pub', 'stop')] * 3


def test_cors_answers_only_the_page_origin(backend):
    _, base = backend
    page = f'http://127.0.0.1:{PAGE_PORT}'
    request = urllib.request.Request(base + '/state.json', headers={'Origin': page})
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.headers['Access-Control-Allow-Origin'] == page
    request = urllib.request.Request(base + '/state.json', headers={'Origin': 'http://evil.example'})
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.headers['Access-Control-Allow-Origin'] is None
    with urllib.request.urlopen(base + '/state.json', timeout=5) as response:
        assert response.headers['Access-Control-Allow-Origin'] is None


def test_page_origin_follows_the_requested_host_name():
    assert page_origin_allowed('http://10.0.0.5:28181', '10.0.0.5:28182', 28181)
    assert page_origin_allowed('http://[::1]:28181', '[::1]:28182', 28181)
    assert not page_origin_allowed('http://10.0.0.6:28181', '10.0.0.5:28182', 28181)
    assert not page_origin_allowed('http://10.0.0.5:28181', '10.0.0.5:28182', None)
    assert not page_origin_allowed(None, '10.0.0.5:28182', 28181)
    # DNS rebinding: an attacker domain resolved to this host names itself in both headers
    assert not page_origin_allowed('http://evil.example:28181', 'evil.example:28182', 28181)
