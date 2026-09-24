"""Shared web_node state: the JSON contract with the page, and its freshness rules.

ROS-free so host pytest can import it (2026-09-06 criteria C1). STATE is
written by ROS callbacks (spin thread) and read by the HTTP thread under one
lock; every module of the web debug surface shares these objects.
"""
import json
import threading
import time
import uuid

from control.sensing.battery import battery_snapshot

# STATE keys — the JSON contract with the page; never rename these strings.
K_TELEOP = 'teleop_topic'
K_SENSORS = 'sensors'
K_POSE = 'pose'
K_PREV = 'pose_prev'
K_TRAIL = 'trail'
K_PATH = 'path_m'
K_MAP = 'map'
K_SCAN = 'scan'
K_GOAL = 'goal_pt'
K_ROUTE = 'route'
K_OPTIONS = 'options'
K_MODE = 'mode'
K_WANDER = 'wander'
K_GSTATE = 'gstate'
K_ETA = 'eta'
K_ESTOP = 'estop'
K_OK = 'ok'
K_HEALTH = 'health'
K_VEL = 'vel'
K_CAM = 'cam'
K_LIMITS = 'limits'

STATE = {}
RUNTIME_ID = uuid.uuid4().hex
LOCK = threading.Lock()
MAP_PNG = {'bytes': None, 'gen': 0}
CAM_JPG = {'bytes': None, 'gen': 0, 't': 0.0}
TRAIL_MAX = 3000
CAM_MIN_DT = 0.25          # ~4 Hz JPEG re-encode ceiling
CAM_WIDTH = 320            # inspection scale, not documentation
CAM_QUALITY = 70


# The distances the page draws its gauges and dial thresholds against. Same
# names as config/robot.yaml, which every launch loads first under the /**
# wildcard — so the browser shows the numbers safety is actually running on
# rather than a second copy that can drift.
LIMIT_PARAMS = [
    ('stop_distance', 0.12),
    ('clear_distance', 0.14),
    ('warn_front', 0.18),
    ('us_stop_distance', 0.020),
    ('us_clear_distance', 0.028),
    ('robot_radius', 0.076),
    ('open_max', 0.40),
]
LIMIT_KEYS = {'stop_distance': 'stop', 'clear_distance': 'clear',
              'warn_front': 'warn', 'us_stop_distance': 'us_stop',
              'us_clear_distance': 'us_clear', 'robot_radius': 'radius',
              'open_max': 'open_max'}


def state_json(now=None):
    """Refresh every freshness verdict, then serialize STATE for /state.json."""
    now = time.monotonic() if now is None else now
    with LOCK:
        STATE['navigation_session_fresh'] = 0 <= now-STATE.get('navigation_session_received', -1e9) <= 1.5
        # goal.yaml publishes at 0.5 Hz, slower than session status.
        STATE['planner_fresh'] = 0 <= now-STATE.get('planner_received', -1e9) <= 5.
        STATE['battery'] = battery_snapshot(STATE.get('battery_sample', {}), STATE.get('battery_received'), now)
        STATE['motion_limits_fresh'] = 0 <= now-STATE.get('motion_limits_received', -1e9) <= .75
        if now - STATE.get('calibration_received', -1e9) > 3.0:
            STATE['calibration_ready'] = False
        if now - STATE.get('safety_profile_received', -1e9) > 1.5:
            STATE['safety_profile'] = {'valid': False, 'reason': 'stale'}
        if now - STATE.get('safety_decision_received', -1e9) > 1.5:
            STATE['safety_decision'] = None
        return json.dumps({**STATE, 'runtime_id': RUNTIME_ID}).encode()
