"""web_node HTTP surface: routing, request validation and relay gating.

ROS-free so host pytest can import it (2026-09-06 criteria C1). Every decision
the backend makes — verb whitelists, the calibration/e-stop/planner gates, the
teleop clamp, the goal bound — lives here. Publishing is delegated to the node
(`publish_text`, `publish_teleop`), which owns the ROS message types.

Backend API (all CORS *, JSON contract unchanged since v1):
  GET  /state.json   pose/trail/map/scan/route/options + control labels
  GET  /map.png      occupancy raster (gen counter; browser refetches on change)
  GET  /camera.jpg   latest /camera/front frame, JPEG, ~4 Hz (gen counter)
  GET  /result.json  gstate + odom path total + optional check_map metrics
  POST /cmd          explore|coverage|stop        -> /goal/cmd
  POST /goal         "x,y" (map metres)           -> /goal/cmd (manual goal)
  POST /wander       start|stop|explore|coverage  -> /wander/cmd
  POST /navigation/start {strategy,duration_s,stall_s} -> bounded /wander/cmd session
  POST /estop        stop|release                 -> /estop/cmd
  POST /map/reset    stop commands + reset SLAM, paused; clear map caches
  POST /map/resume   resume SLAM measurements only (no motion commands)
  POST /map/pause    stop autonomous navigation, pause SLAM and verify readback
  POST /camera/calibration enable|disable -> optional ground homography session toggle
  POST /teleop       {"x":..,"z":..} Twist on /cmd_vel_raw, through safety.
"""
import http.server
import json
import math
import os
import time

from control.control.navigation_session import validate_options
from control.web_state import (
    CAM_JPG, K_ESTOP, K_GSTATE, K_PATH, K_WANDER, LOCK, MAP_PNG, RUNTIME_ID, STATE, state_json)

# POST routes that relay a fixed verb whitelist to one publisher.
POST_VERBS = {
    '/cmd': ('goal_pub', ('explore', 'coverage', 'stop')),
    '/wander': ('wander_pub', ('start', 'stop', 'explore', 'coverage')),
    '/estop': ('estop_pub', ('stop', 'release')),
}
GOAL_BOUND = 50.0   # metres; a dashboard goal beyond this is a typo


_COMMON_MEDIA = {
    "tokens.css": "text/css",
    "components.css": "text/css",
    "template.html": "text/html",
    "ui.js": "text/javascript",
    "core_ui_logic.js": "text/javascript",
}


def web_common_dir(share=None):
    """The installed web_common share when it carries the controls, else the
    source tree. The node resolves ``share``; this module stays ROS-free (D-171)."""
    if share and os.path.isfile(os.path.join(share, "components.css")):
        return share
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))),
        "core", "web_common")


def _handler(node, html, api):
    """HTTP handler closing over the node. api=True = backend (state/map/
    camera/result + POSTs); api=False = frontend (the page only). CORS on
    every response so the frontend page can fetch the backend."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send_response(self, code, *a):
            super().send_response(code, *a)
            self.send_header('Access-Control-Allow-Origin', '*')

        def _html(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(html)

        def _png_jpg(self, data, typ):
            if data is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', typ)
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def _common(self, name):
            media = _COMMON_MEDIA.get(name)
            root = getattr(node, 'web_common_dir', None) or web_common_dir()
            file = os.path.join(root, name)
            if media is None or not os.path.isfile(file):
                self.send_response(404)
                self.end_headers()
                return
            with open(file, 'rb') as handle:
                data = handle.read()
            self.send_response(200)
            self.send_header('Content-Type', media)
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split('?')[0]
            if path.startswith('/common/'):
                name = path[len('/common/'):]
                if '/' in name or name.startswith('.'):
                    self.send_response(404)
                    self.end_headers()
                    return
                self._common(name)
                return
            if path == '/':
                self._html()
                return
            if not api:
                self.send_response(404)
                self.end_headers()
                return
            if path == '/state.json':
                body = state_json()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
            elif path == '/map.png':
                from urllib.parse import parse_qs, urlsplit
                query = parse_qs(urlsplit(self.path).query)
                requested = query.get('g', [None])[0]
                session = query.get('session', [RUNTIME_ID])[0]
                with LOCK:
                    png = MAP_PNG['bytes']
                    generation = MAP_PNG['gen']
                # A newer image must never masquerade as the requested map.
                if session != RUNTIME_ID or (requested is not None and requested != str(generation)):
                    self.send_response(409)
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    return
                self._png_jpg(png, 'image/png')
            elif path == '/camera.jpg':
                with LOCK:
                    jpg = CAM_JPG['bytes']
                self._png_jpg(jpg, 'image/jpeg')
            elif path == '/result.json':
                with LOCK:
                    body = {'state': STATE.get(K_GSTATE),
                            'path_m': STATE.get(K_PATH, 0.0)}
                body['metrics'] = node.load_metrics()
                body = json.dumps(body).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if not api:
                self.send_response(404)
                self.end_headers()
                return
            ln = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(ln).decode()
            logged_action = self.path in ('/calibration', '/camera/calibration', '/estop', '/wander', '/navigation/start', '/goal', '/map/reset', '/map/resume', '/map/pause')
            if logged_action:
                print(json.dumps({'event': 'operator_request', 'path': self.path,
                                  'command': body[:180], 'client': self.client_address[0]}), flush=True)
            def reject(reason, status=409):
                if logged_action:
                    print(json.dumps({'event': 'operator_rejected', 'path': self.path,
                                      'reason': reason}), flush=True)
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': reason}).encode())

            with LOCK:
                ready = (time.monotonic() - STATE.get('calibration_received', -1e9) <= 3.0 and
                         STATE.get('calibration_ready') is True and
                         STATE.get('calibration', {}).get('ready') is True)
                phase = STATE.get('calibration', {}).get('phase')
                released = STATE.get(K_ESTOP) is False
                mapping_active = STATE.get('map_control', {}).get('paused') is False
                planner_fresh = 0 <= time.monotonic()-STATE.get('planner_received', -1e9) <= 5.
                calibration_received = STATE.get('calibration_received')
                camera_calibration = dict(STATE.get('camera_calibration', {}))
            if self.path == '/camera/calibration':
                if body not in ('enable', 'disable'):
                    reject('Camera calibration command must be enable or disable', status=400)
                    return
                if body == 'enable' and camera_calibration.get('eligible') is not True:
                    reject('Camera ground calibration has not passed validation')
                    return
                node.publish_text('camera_calibration_pub', body)
                self.send_response(202)
                self.end_headers()
                return
            if self.path == '/calibration':
                if body not in ('retry', 'retry:stay', 'retry:return_origin', 'retry:stay:full',
                                'retry:stay:skip_motion', 'retry:return_origin:full',
                                'retry:return_origin:skip_motion', 'validate_motion', 'abort',
                                'partial_calibration', 'sensing_only', 'use_existing_settings',
                                'use_limited_sensors'):
                    self.send_response(400)
                    self.end_headers()
                    return
                if body != 'abort' and not calibration_receiver_available(
                        calibration_received, time.monotonic(), node.calibration_pub):
                    reject('Calibration node connecting; wait for its heartbeat and retry', status=503)
                    return
                if body == 'validate_motion' and (
                        phase != 'waiting_motion' or not released or not mapping_active):
                    reject('Motion validation requires waiting_motion, active mapping and released emergency stop')
                    return
                if body in ('retry', 'retry:stay', 'retry:return_origin', 'retry:stay:full',
                            'retry:stay:skip_motion', 'retry:return_origin:full',
                            'retry:return_origin:skip_motion', 'abort', 'partial_calibration',
                            'sensing_only', 'use_existing_settings', 'use_limited_sensors'):
                    with LOCK:
                        STATE['calibration_ready'] = False
                node.publish_text('calibration_pub', body)
                self.send_response(200)
                self.end_headers()
                return
            if self.path in ('/map/reset', '/map/resume', '/map/pause'):
                status, result = node.map_control.execute(self.path.rsplit('/', 1)[1])
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
                return
            verb = POST_VERBS.get(self.path)
            if self.path == '/navigation/start':
                if not planner_fresh:
                    reject('Route planner unavailable; start the map capability with goal_node')
                    return
                try:
                    options = validate_options(json.loads(body))
                except (ValueError, TypeError) as error:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': str(error)}).encode())
                    return
                with LOCK:
                    session = STATE.get('navigation_session', {})
                    fresh = 0 <= time.monotonic()-STATE.get('navigation_session_received', -1e9) <= 1.5
                    stopped = str(STATE.get(K_WANDER, '')).startswith('stop')
                if not ready or not released or not fresh or not stopped or session.get('active') is not False:
                    reject('Fresh idle navigation, stopped driving, calibration and released emergency stop required')
                    return
                node.publish_text('wander_pub', 'session:' + json.dumps(options))
                self.send_response(202)
                self.end_headers()
                return
            if verb:
                attr, allowed = verb
                if body in allowed:
                    if self.path == '/wander' and body != 'stop' and not ready:
                        reject('Startup calibration must pass before driving')
                        return
                    if self.path == '/wander' and body != 'stop' and not released:
                        reject('Release emergency stop before selecting a driving mode')
                        return
                    if self.path == '/wander' and body in ('explore', 'coverage') and not planner_fresh:
                        reject('Route planner unavailable; start the map capability with goal_node')
                        return
                    node.publish_text(attr, body)
                    self.send_response(200)
                else:
                    self.send_response(400)
            elif self.path == '/teleop':
                try:
                    d = json.loads(body)
                    # Clamp at desk-robot scale; the safety gate still owns
                    # the final /cmd_vel on hardware.
                    x = max(-0.2, min(0.2, float(d.get('x', 0.0))))
                    z = max(-1.0, min(1.0, float(d.get('z', 0.0))))
                    if (x or z) and not ready:
                        reject('Startup calibration must pass before teleoperation')
                        return
                    if (x or z) and not released:
                        reject('Emergency stop must be released before teleoperation')
                        return
                    node.publish_teleop(x, z)
                    self.send_response(200)
                except (ValueError, TypeError):
                    self.send_response(400)
            elif self.path == '/goal':
                xy = _parse_xy(body)
                if xy is None or max(abs(xy[0]), abs(xy[1])) > GOAL_BOUND:
                    self.send_response(400)
                else:
                    if not planner_fresh:
                        reject('Route planner unavailable; start the map capability with goal_node')
                        return
                    if not ready or not released:
                        reject('Manual driving requires completed calibration and released emergency stop')
                        return
                    node.publish_text('wander_pub', f'manual:{xy[0]:.3f},{xy[1]:.3f}')
                    self.send_response(200)
            else:
                self.send_response(404)
            self.end_headers()

    return Handler


def make_api_handler(node, html):
    return _handler(node, html, api=True)


def make_page_handler(html):
    return _handler(None, html, api=False)


def calibration_receiver_available(received, now, publisher):
    """Do not acknowledge commands while the startup subscriber is absent."""
    if received is None or not 0 <= now-received <= 3.:
        return False
    count = getattr(publisher, 'get_subscription_count', None)
    if not callable(count):
        return True
    try:
        subscribers = count()
        return type(subscribers) is int and subscribers >= 1
    except RuntimeError:
        return False


def _parse_xy(text):
    """'x,y' or 'x y' -> (x, y) floats; None otherwise. Same semantics as
    planning.goals.parse_goal_cmd, kept local so the HTTP surface does not
    depend on the planner package."""
    try:
        a, b = str(text).replace(',', ' ').split()
        x, y = float(a), float(b)
    except ValueError:
        return None
    return (x, y) if (math.isfinite(x) and math.isfinite(y)) else None
