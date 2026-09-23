#!/usr/bin/env python3
"""Web node: live map + control state in a browser.

Debug surface (D-150): development/diagnostic only — never part of an
operational launch or deploy, and its ports are pinned out of deploy configs
by test/test_control_launch_boundary.py. The operator console is CORE
/dashboard (D-23).

    ros2 run control web_node
    ros2 launch control web.launch.py
    frontend  http://localhost:28181   (port param — the page)
    backend   http://localhost:28182   (backend_port — the API; see web_http.py)

No decision logic here — a view + relay, like goal_node is thin I/O over
planning. This module owns ROS wiring only; the ROS-free parts live beside it
so host pytest can import them (2026-09-06 criteria C1, D-168 P6):

    web_state.py        STATE/LOCK, JSON keys, limits, /state.json freshness
    web_http.py         routes, request validation, relay gates
    web_render.py       /map.png and /camera.jpg rasters
    web_map_control.py  slam_toolbox reset/pause/resume (needs rclpy)

STATE is written by ROS callbacks (spin thread) and read by the HTTP thread
under one lock. Page polls state at 333 ms.
"""
import json
import math
import os
import threading
import time
import http.server

import rclpy
from .tf_buffer import RobotTransformBuffer
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from tf2_ros import TransformListener, TransformException
from rclpy.clock import Clock, ClockType
from control.sensing.map_pose import record_odom, display_pose
from control.sensing.lidar_mount import nose_from_quaternion
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseStamped, Twist
from nav_msgs.msg import OccupancyGrid, Odometry, Path
from sensor_msgs.msg import Image, LaserScan, BatteryState
from control.sensing.battery import battery_values
from std_msgs.msg import Bool, Float32, String
from visualization_msgs.msg import MarkerArray
from control.web_http import make_api_handler, make_page_handler
from control.web_map_control import MapControl
from control.web_render import render_cam, render_png
from control.web_state import (
    K_ESTOP, K_ETA, K_GOAL, K_GSTATE, K_HEALTH, K_LIMITS, K_MODE, K_OK, K_OPTIONS, K_ROUTE,
    K_SCAN, K_SENSORS, K_TELEOP, K_VEL, K_WANDER, LIMIT_KEYS, LIMIT_PARAMS, LOCK, STATE,
    TRAIL_MAX)

# Sensor view: the safety-fused values wander actually consumes, plus the
# camera verdicts. Missing keys stay absent so the dashboard waits for
# safety instead of inventing F/L/R from raw /scan.
SENSOR_TOPICS = [
    # topic                 type     STATE key
    ('/safety/min_range',   Float32, 'F'),
    ('/safety/left_range',  Float32, 'L'),
    ('/safety/right_range', Float32, 'R'),
    ('/safety/us_range',    Float32, 'US'),
    ('/safety/rear_range',  Float32, 'rear'),
    ('/safety/rear_left',   Float32, 'rear L'),
    ('/safety/rear_right',  Float32, 'rear R'),
    ('/safety/open_range',  Float32, 'open'),
    ('/safety/corridor',    Float32, 'corridor'),
    ('/safety/blocked',     Bool,    'blocked'),
    ('/safety/cliff',       Bool,    'cliff'),
    ('/safety/tilt',        Bool,    'tilt'),
    ('/safety/pickup',      Bool,    'pickup'),
    ('/safety/rear_clear',  Bool,    'rear clear'),
    ('/safety/can_reverse', Bool,    'can reverse'),
    ('/camera/blocked',     Bool,    'cam blocked'),
    ('/camera/cliff',       Bool,    'cam cliff'),
    ('/camera/side',        Float32, 'cam side'),
    ('/camera/debug',       String,  'cam dbg'),
]


def sensor_cb(key):
    """One callback per sensor key: Bool as bool, String truncated, Float32
    rounded to mm."""
    def cb(msg):
        if isinstance(msg, Bool):
            v = bool(msg.data)
        elif isinstance(msg, String):
            v = str(msg.data)[:100]
        else:
            v = round(float(msg.data), 3)
        with LOCK:
            STATE.setdefault(K_SENSORS, {})[key] = v
    return cb


class WebNode(Node):
    def __init__(self):
        super().__init__('web_node')
        self.declare_parameter('port', 28181)
        self.declare_parameter('backend_port', 28182)
        self.declare_parameter('battery_topic', 'battery_state')
        self.battery_stamp_ns = None
        self.create_subscription(BatteryState, str(self.get_parameter('battery_topic').value), self.on_battery, qos_profile_sensor_data)
        self.declare_parameter('teleop_topic', 'auto')
        self.declare_parameter('scan_step', 4)
        # Optional map-QA metrics JSON (check_map.py output) for the result
        # panel; empty hides historical QA rather than implying live evidence.
        self.declare_parameter('metrics_file', '')
        for name, default in LIMIT_PARAMS:
            self.declare_parameter(name, default)
        port = int(self.get_parameter('port').value)
        backend_port = int(self.get_parameter('backend_port').value)
        self.scan_step = max(1, int(self.get_parameter('scan_step').value))
        with LOCK:
            STATE[K_SENSORS] = {}
            STATE[K_LIMITS] = self.read_limits()
        self.teleop_target = None
        self.teleop_pub = None
        self.resolve_teleop()
        self.goal_pub = self.create_publisher(String, 'goal/cmd', 10)
        self.wander_pub = self.create_publisher(String, 'wander/cmd', 10)
        self.estop_pub = self.create_publisher(String, 'estop/cmd', 10)
        self.calibration_pub = self.create_publisher(String, 'calibration/cmd', 10)
        self.camera_calibration_pub = self.create_publisher(
            String, 'camera/calibration/cmd', 10)
        with LOCK:
            STATE['calibration_ready'] = False
            STATE.pop('calibration_received', None)
            STATE['calibration'] = {'phase': 'unavailable', 'ready': False,
                                    'message': 'Waiting for startup calibration', 'sensors': {}}
            STATE['camera_calibration'] = {
                'candidate': False, 'eligible': False, 'active': False,
                'reason': 'waiting_for_camera_node', 'checks': {}}
        self.map_control = MapControl(self)
        self.map_frame = 'map'
        self.declare_parameter('pose_timeout', 1.0)
        self.odom_received = None
        self.odom_stamp = None
        self.odom_frame = 'odom'
        self.tf = RobotTransformBuffer(self)
        self.tf_listener = TransformListener(self.tf, self)
        self.pose_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self.create_timer(.2, self.refresh_pose, clock=self.pose_clock)

        self.create_subscription(
            OccupancyGrid, 'map', self.on_map, qos_profile_sensor_data)
        self.create_subscription(Odometry, 'odom', self.on_odom, 10)
        self.create_subscription(
            PoseStamped, 'goal_point', self.on_goal, 10)
        self.create_subscription(Path, 'route', self.on_route, 10)
        self.create_subscription(
            MarkerArray, 'goal/options', self.on_options, 10)
        self.create_subscription(
            LaserScan, 'scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(
            Image, 'camera/front', render_cam, qos_profile_sensor_data)
        for topic, typ, key in SENSOR_TOPICS:
            self.create_subscription(
                typ, topic.lstrip('/'), sensor_cb(key), 10)
        self.create_timer(1.0, self.resolve_teleop)
        self.create_subscription(String, 'robot/mode', self.on_mode, 10)
        self.create_subscription(String, 'wander/state', self.on_wander, 10)
        self.create_subscription(String, 'navigation/session', self.on_navigation_session, 10)
        self.create_subscription(String, 'safety/motion_limits', self.on_motion_limits, 10)
        self.create_subscription(
            String, 'goal_node/state', self.on_gstate, 10)
        self.create_subscription(Float32, 'goal/eta', self.on_eta, 10)
        # Same latched profile wander uses: safety publishes /estop/state
        # transient_local, so a volatile sub would never see the latch.
        latched = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(Bool, 'estop/state', self.on_estop, latched)
        self.create_subscription(Bool, 'calibration/ready', self.on_calibration_ready, latched)
        self.create_subscription(String, 'calibration/status', self.on_calibration_status, 10)
        self.create_subscription(
            String, 'camera/calibration/status', self.on_camera_calibration_status, latched)
        self.create_subscription(String, 'safety/profile', self.on_safety_profile, latched)
        self.create_subscription(String, 'safety/decision', self.on_safety_decision, 10)
        self.create_subscription(Bool, 'robot/ok', self.on_ok, 10)
        self.create_subscription(String, 'robot/health', self.on_health, 10)
        self.create_subscription(String, 'robot/evidence_scope', self.on_evidence_scope, latched)
        # Dashboard velocity readout follows the control-owned raw stage.
        # The final cmd_vel belongs to CORE (D-38); control never names it.
        self.create_subscription(Twist, 'cmd_vel_raw', self.on_vel, 10)

        html_path = self.html_path()
        with open(html_path, 'rb') as f:
            raw = f.read()
        html = raw.replace(b'__BACKEND_PORT__', str(backend_port).encode())
        page = make_page_handler(html)
        httpd = http.server.ThreadingHTTPServer(('0.0.0.0', port), page)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        if backend_port != port:
            api = make_api_handler(self, html)
            httpd2 = http.server.ThreadingHTTPServer(
                ('0.0.0.0', backend_port), api)
            threading.Thread(target=httpd2.serve_forever, daemon=True).start()
        else:
            api = make_api_handler(self, html)
            httpd2 = http.server.ThreadingHTTPServer(
                ('0.0.0.0', port), api)
        self.get_logger().info(
            f'web_node page on :{port} api on :{backend_port} '
            f'(teleop -> {self.teleop_target})')

    # -- ROS callbacks ----------------------------------------------------

    def on_map(self, msg):
        with LOCK:
            control = STATE.get('map_control', {})
            epoch = control.get('epoch', 0)
            if epoch and control.get('paused') is not False:
                return
        stamp = msg.header.stamp.sec * 1000000000 + msg.header.stamp.nanosec
        if stamp <= self.map_control.map_after_ns and self.map_control.map_after_ns:
            return
        info = msg.info
        self.map_frame = msg.header.frame_id or 'map'
        render_png(msg, epoch)

    def on_odom(self, msg):
        p = msg.pose.pose.position
        self.odom_received = time.monotonic()
        self.odom_stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        self.odom_frame = msg.header.frame_id or 'odom'
        with LOCK:
            record_odom(STATE, p.x, p.y, TRAIL_MAX)
        # The steady 5 Hz timer owns TF lookup and trail reprojection. Keep
        # every odometry sample for distance without repeating display work.

    def refresh_pose(self):
        """Invalidate stopped publishers even when no odometry callback arrives."""
        now = self.get_clock().now().nanoseconds * 1e-9
        age = math.inf if self.odom_received is None else max(
            time.monotonic() - self.odom_received, now - self.odom_stamp)
        if self.odom_stamp is not None and now - self.odom_stamp < -.1:
            age = now - self.odom_stamp
        pose, transform, tf_age = None, None, math.inf
        tf_error = None
        try:
            base = self.tf.lookup_transform(self.map_frame, 'base_link', Time())
            transforms = [base]
            if self.odom_frame == self.map_frame:
                transform = (0.0, 0.0, 0.0)
            else:
                # SLAM future-dates its latest map->odom by transform_timeout.
                # Match the trail transform to the authoritative base pose time.
                odom = self.tf.lookup_transform(
                    self.map_frame, self.odom_frame, Time.from_msg(base.header.stamp))
                transforms.append(odom)
                transform = self._tf_pose(odom)
            pose = self._tf_pose(base)
            ages = [now - (tf.header.stamp.sec + tf.header.stamp.nanosec * 1e-9)
                    for tf in transforms]
            tf_age = min(ages) if min(ages) < -.75 else max(ages)
        except TransformException as exc:
            tf_error = str(exc)
        with LOCK:
            reason = 'mapping_paused' if STATE.get('map_control', {}).get('paused') else None
            display_pose(STATE, pose, transform, odom_age=age, tf_age=tf_age,
                         timeout=float(self.get_parameter('pose_timeout').value), reason=reason)
            STATE['pose_frame'] = self.map_frame
            STATE['pose_tf_error'] = tf_error

    @staticmethod
    def _tf_pose(tf):
        t, r = tf.transform.translation, tf.transform.rotation
        angle = math.atan2(2.0 * (r.w * r.z + r.x * r.y),
                           1.0 - 2.0 * (r.y * r.y + r.z * r.z))
        return (t.x, t.y, angle)

    def on_goal(self, msg):
        with LOCK:
            STATE[K_GOAL] = [round(msg.pose.position.x, 3),
                             round(msg.pose.position.y, 3)]

    def on_route(self, msg):
        with LOCK:
            STATE[K_ROUTE] = [[round(p.pose.position.x, 3),
                               round(p.pose.position.y, 3)]
                              for p in msg.poses]

    def on_options(self, msg):
        pts = []
        for m in msg.markers:
            if m.points:
                pts.append([[round(p.x, 3), round(p.y, 3)]
                            for p in m.points])
        with LOCK:
            STATE[K_OPTIONS] = pts

    def on_scan(self, msg):
        """Keep scan angles raw and supply the same TF-derived nose as safety."""
        try:
            if not msg.header.frame_id:
                raise ValueError('Missing scan frame')
            tf = self.tf.lookup_transform('base_link', msg.header.frame_id,
                                          Time.from_msg(msg.header.stamp))
            q = tf.transform.rotation
            nose = nose_from_quaternion(q.x, q.y, q.z, q.w)
        except (TransformException, ValueError):
            with LOCK:
                STATE[K_SCAN] = None
                STATE['scan_reason'] = 'missing_mount_tf'
            return
        rs = list(msg.ranges)[::self.scan_step]
        # Lidar no-return beams are inf; json.dumps would emit bare
        # Infinity, which every browser's JSON.parse rejects — the whole
        # state payload dies. Zero them: below range_min = invalid, so the
        # dial and the F/L/R buckets skip them.
        rs = [round(r, 3) if math.isfinite(r) else 0.0 for r in rs]
        with LOCK:
            STATE[K_SCAN] = {
                'amin': msg.angle_min, 'inc': msg.angle_increment * self.scan_step,
                'rmin': msg.range_min, 'rmax': msg.range_max,
                'rs': rs,
                'nose_yaw': nose,
                'frame': msg.header.frame_id,
            }
            STATE['scan_reason'] = 'ready'

    def on_mode(self, msg):
        with LOCK:
            STATE[K_MODE] = msg.data

    def on_calibration_ready(self, msg):
        with LOCK:
            STATE['calibration_ready'] = bool(msg.data)
            STATE['calibration_received'] = time.monotonic()

    def on_safety_profile(self, msg):
        try:
            profile = json.loads(msg.data)
            if not isinstance(profile, dict):
                raise ValueError('Invalid effective profile')
            effective = profile['effective']
            if profile.get('valid') is not True or not all(
                    math.isfinite(effective[key]) and effective[key] > 0 for key in ('stop', 'clear', 'radius')):
                raise ValueError('Invalid effective limits')
        except (ValueError, TypeError, KeyError):
            with LOCK:
                STATE['safety_profile'] = {'valid': False}
            return
        with LOCK:
            STATE['safety_profile'] = profile
            STATE['safety_profile_received'] = time.monotonic()
            STATE[K_LIMITS] = {**STATE.get(K_LIMITS, {}),
                               **{key: effective[key] for key in ('stop', 'clear', 'radius')}}

    def on_safety_decision(self, msg):
        try:
            value = json.loads(msg.data)
            if not isinstance(value, dict):
                return
        except (ValueError, TypeError):
            return
        with LOCK:
            STATE['safety_decision'] = value
            STATE['safety_decision_received'] = time.monotonic()

    def on_calibration_status(self, msg):
        try:
            status = json.loads(msg.data)
            if not isinstance(status, dict) or not isinstance(status.get('sensors', {}), dict):
                raise ValueError('Invalid calibration status')
        except (ValueError, TypeError):
            with LOCK:
                STATE['calibration_ready'] = False
                STATE['calibration'] = {'phase': 'unavailable', 'ready': False,
                                        'message': 'Invalid calibration status', 'sensors': {}}
            return
        with LOCK:
            STATE['calibration'] = status

    def on_camera_calibration_status(self, msg):
        try:
            status = json.loads(msg.data)
            if (not isinstance(status, dict)
                    or type(status.get('active')) is not bool
                    or type(status.get('eligible')) is not bool
                    or not isinstance(status.get('checks', {}), dict)):
                raise ValueError('Invalid camera calibration status')
        except (ValueError, TypeError):
            status = {'candidate': False, 'eligible': False, 'active': False,
                      'reason': 'invalid_camera_calibration_status', 'checks': {}}
        with LOCK:
            STATE['camera_calibration'] = status

    def on_wander(self, msg):
        with LOCK:
            STATE[K_WANDER] = msg.data
            STATE['wander_sequence'] = STATE.get('wander_sequence', 0)+1

    def on_navigation_session(self, msg):
        try:
            status = json.loads(msg.data)
            if not isinstance(status, dict) or type(status.get('active')) is not bool:
                raise ValueError('Invalid session')
        except (ValueError, TypeError):
            return
        with LOCK:
            STATE['navigation_session'] = status
            STATE['navigation_session_received'] = time.monotonic()

    def on_gstate(self, msg):
        with LOCK:
            STATE[K_GSTATE] = msg.data
            STATE['planner_received'] = time.monotonic()

    def on_eta(self, msg):
        with LOCK:
            STATE[K_ETA] = round(msg.data, 1)

    def on_estop(self, msg):
        with LOCK:
            STATE[K_ESTOP] = bool(msg.data)
            STATE['estop_sequence'] = STATE.get('estop_sequence', 0)+1

    def on_ok(self, msg):
        with LOCK:
            STATE[K_OK] = bool(msg.data)

    def on_health(self, msg):
        with LOCK:
            STATE[K_HEALTH] = msg.data

    def on_evidence_scope(self, msg):
        try:
            value = json.loads(msg.data)
        except (ValueError, TypeError):
            return
        if not isinstance(value, dict):
            return
        with LOCK:
            STATE['evidence_scope'] = value

    def on_vel(self, msg):
        with LOCK:
            STATE[K_VEL] = [round(msg.linear.x, 3), round(msg.angular.z, 3)]

    def on_battery(self, msg):
        stamp = msg.header.stamp.sec*1_000_000_000 + msg.header.stamp.nanosec
        age = (self.get_clock().now().nanoseconds-stamp)*1e-9
        if stamp <= 0 or not -.1 <= age <= 5.:
            return
        if self.battery_stamp_ns is not None and stamp <= self.battery_stamp_ns:
            return
        self.battery_stamp_ns = stamp
        value = battery_values(msg.percentage, msg.voltage, msg.current, msg.present, msg.power_supply_status)
        with LOCK:
            STATE['battery_sample'] = value
            STATE['battery_received'] = time.monotonic()-max(0., age)

    def read_limits(self):
        """robot.yaml distances -> the JSON keys the page gauges use."""
        return {LIMIT_KEYS[name]: float(self.get_parameter(name).value)
                for name, _ in LIMIT_PARAMS}

    def on_motion_limits(self, msg):
        try:
            value = json.loads(msg.data)
            if not isinstance(value, dict):
                return
        except (ValueError, TypeError):
            return
        with LOCK:
            STATE['motion_limits'] = value
            STATE['motion_limits_received'] = time.monotonic()

    def load_metrics(self):
        """Map-QA metrics (check_map.py output) for the result panel; None
        when absent — the panel hides itself. Cached by mtime so the HTTP
        thread does not stat+parse a JSON file 12x a minute for nothing."""
        path = str(self.get_parameter('metrics_file').value)
        if not path:
            return None
        try:
            mt = os.path.getmtime(path)
        except OSError:
            with LOCK:
                self._metrics_cache = (None, None)
            return None
        with LOCK:
            cache = getattr(self, '_metrics_cache', (None, None))
        if cache[0] == mt:
            return cache[1]
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
        with LOCK:
            self._metrics_cache = (mt, data)
        return data

    def resolve_teleop(self):
        """Discovery delays must never create a path around the safety gate."""
        # Keep the legacy parameter accepted for launch compatibility, but
        # neither configuration nor a missing safety node grants motor output.
        want = self.resolve_topic_name('cmd_vel_raw')
        if want == self.teleop_target:
            return
        if self.teleop_pub is not None:
            self.destroy_publisher(self.teleop_pub)
        self.teleop_target = want
        self.teleop_pub = self.create_publisher(Twist, want, 10)
        with LOCK:
            STATE[K_TELEOP] = want
        self.get_logger().info(f'teleop -> {want}')

    def publish_text(self, attr, data):
        """web_http relay: one String on the named publisher."""
        getattr(self, attr).publish(String(data=data))

    def publish_teleop(self, x, z):
        """web_http relay: the already-clamped teleop Twist on cmd_vel_raw."""
        tw = Twist()
        tw.linear.x = x
        tw.angular.z = z
        self.teleop_pub.publish(tw)

    def html_path(self):
        """Installed share copy first; source-tree fallback for running
        from the repo before colcon build."""
        try:
            p = os.path.join(get_package_share_directory('control'),
                             'web', 'dashboard.html')
            if os.path.isfile(p):
                return p
        except Exception:
            pass
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'web', 'dashboard.html')


def main():
    rclpy.init()
    node = WebNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
