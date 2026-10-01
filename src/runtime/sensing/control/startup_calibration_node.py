"""Stationary startup checks followed by one bounded automatic motion validation.

Structure (D-362 P0-2 / 2026-09-22 split design): this file keeps the ROS
wiring — parameters, publishers/subscriptions, sensor callbacks and the tick
dispatcher. The calibration state machine (motion authorization, precision
holds, phase completion, persistence) lives in ``calibration_sequence.py`` as
a ROS-free mixin, beside the rotation/atomic/relocation mixins.
"""
import json
import math
import time
from pathlib import Path
import uuid

import numpy as np
import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from . import executor_choice
from .tf_buffer import RobotTransformBuffer
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, qos_profile_sensor_data
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry, OccupancyGrid
from sensor_msgs.msg import LaserScan, Range, Imu, Image
from std_msgs.msg import Bool, String, UInt16MultiArray, Float32MultiArray
from tf2_ros import TransformListener

from .calibration_sequence import CalibrationSequence
from .calibration_camera import CalibrationCamera
from .control.calibration import StationaryBaseline, wrap
from .sensing.body import URDF_RADIUS
from .sensing.lidar import NOSE_YAW, is_robot_scan, sector_range
from .sensing.lidar_mount import nose_from_quaternion
from .sensing.range_filter import CalibrationRangeFilter
from .sensing.wall_tracker import WallTracker
from .control.calibration_tf import transform_health
from .control.navigation_calibration import environment_profile, map_ray
from .planning import OccupancyMap
from .calibration_rotation import CalibrationRotation
from .calibration_atomic import CalibrationAtomic
from .calibration_relocation import CalibrationRelocationAdapter
from .control.sensing_only import partial_sensing_report
from .control.sensor_tiers import partial_plan
from .control.configured_operation import configured_waiting_reasons
from .control.startup_diagnostics import StartupDiagnostics
from .control.calibration_runtime import calibration_runtime, precision_scan_required


class StartupCalibrationNode(Node, CalibrationSequence, CalibrationRotation, CalibrationAtomic, CalibrationRelocationAdapter,
                             CalibrationCamera):
    def __init__(self, parameter_overrides=None):
        super().__init__('startup_calibration_node', parameter_overrides=parameter_overrides or [])
        self.startup_diagnostics = StartupDiagnostics()
        self.declare_parameter('lidar_yaw_offset', NOSE_YAW)
        self.declare_parameter('imu_angular_velocity_unit', 'rad_s')
        self.declare_parameter('calibration_auto_motion', True)
        self.declare_parameter('localization_required', False)
        self.declare_parameter('calibration_sensing_only', False,
                               ParameterDescriptor(read_only=True))
        self.declare_parameter('calibration_rotation', True)
        self.declare_parameter('calibration_relocation_enabled', False)
        self.declare_parameter('calibration_after_relocation', 'stay')
        self.after_relocation = str(self.get_parameter('calibration_after_relocation').value)
        if self.after_relocation not in ('stay', 'return_origin'):
            self.after_relocation = 'stay'
        self.declare_parameter('calibration_require_us_agreement', True)
        self.declare_parameter('calibration_us_max_range', 3.0)
        self.declare_parameter('calibration_round_trip', False)
        self.declare_parameter('calibration_distance_m', .03)
        self.declare_parameter('robot_radius', URDF_RADIUS)
        self.declare_parameter('rotation_footprint_xy', [], ParameterDescriptor(dynamic_typing=True))
        self.declare_parameter('result_path', str(Path.home() / '.local/state/control/calibration.json'))
        # Base intrinsics for the stationary camera step (calibration_camera.py); '' refuses the step.
        self.declare_parameter('camera_extrinsic_profile_path', '')
        self.declare_parameter('calibration_store_root', '')  # '' = core_common default store root
        self.camera_capture = self.camera_extrinsic = None
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.status_pub = self.create_publisher(String, 'calibration/status', latched)
        self.ready_pub = self.create_publisher(Bool, 'calibration/ready', latched)
        self.scale_pub = self.create_publisher(Float32MultiArray, 'calibration/drive_scale', latched)
        self.profile_pub = self.create_publisher(String, 'calibration/profile', latched)
        self.geometry_revision = self.geometry_profile = self.geometry_received = None
        self.gate_decision = None
        self.create_subscription(String, 'safety/profile', self.on_safety_profile, latched)
        self.create_subscription(String, 'calibration/applied', self.on_applied, latched)
        self.create_subscription(String, 'safety/decision', self.on_gate_decision, 1)  # latest only (D-185 R2)
        # 감지 프로파일은 속도를 내지 않는다. 발행자를 만들기만 해도 그래프에
        # cmd_vel_raw 주인이 하나 더 생긴다.
        sensing_only = bool(self.get_parameter('calibration_sensing_only').value)
        self.raw_pub = None if sensing_only else self.create_publisher(Twist, 'cmd_vel_raw', 10)
        self.wander_pub = self.create_publisher(String, 'wander/cmd', 10)
        self.create_subscription(String, 'calibration/cmd', self.on_command, 10)
        self.create_subscription(Bool, 'estop/state', self.on_estop, latched)
        self.create_subscription(String, 'wander/state', self.on_wander, 10)
        self.create_subscription(LaserScan, 'scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(Odometry, 'odom', self.on_odom, 10)
        self.create_subscription(OccupancyGrid, 'map', self.on_map, qos_profile_sensor_data)
        self.create_subscription(UInt16MultiArray, 'ir_sensor/range', self.on_ir, qos_profile_sensor_data)
        self.create_subscription(Range, 'us_sensor/range', self.on_us, qos_profile_sensor_data)
        self.create_subscription(Imu, 'imu_raw', self.on_imu, qos_profile_sensor_data)
        self.create_subscription(Image, 'camera/front', self.on_camera, qos_profile_sensor_data)
        self.hazards = {}
        self.safety_limits = (0., {})
        self.create_subscription(String, 'safety/motion_limits', self.on_motion_limits, 1)  # latest only (D-185 R2)
        self.rear_clear = (0., False)
        self.create_subscription(Bool, 'safety/can_reverse',
            lambda msg: setattr(self, 'rear_clear', (time.monotonic(), msg.data)), 1)  # latest only (D-185 R2)
        for topic in ('/safety/blocked', '/safety/cliff', '/safety/tilt', '/safety/pickup'):
            self.create_subscription(Bool, topic.lstrip('/'),
                lambda msg, key=topic: self.hazards.__setitem__(key, (time.monotonic(), msg.data)), 1)  # latest only (D-185 R2)
        self.tf = RobotTransformBuffer(self)
        self.listener = TransformListener(self.tf, self)
        self.scan_frame = None
        self.lidar_nose = None
        self.estop = None
        self.wander_state = ('', 0.)
        self.reset(sensing_only=sensing_only)
        if not sensing_only:
            self.restore_certificate()
        self.timer = self.create_timer(.05, self.tick)

    def reset(self, invalidate_certificate=False, sensing_only=False, existing_settings=False,
              limited_sensors=False, excluded_sensors=()):
        self.zero()
        self.wander_pub.publish(String(data='stop'))
        self.sensing_only = sensing_only
        self.existing_settings = existing_settings
        self.limited_sensors = limited_sensors
        self.excluded_sensors = tuple(excluded_sensors)
        self.calibration_scope = getattr(self, 'calibration_scope', 'full')
        self.configured_waiting = ['fresh_sensor_checks'] if existing_settings else []
        self.profile_session = uuid.uuid4().hex
        self.profile_sequence = 0
        self.profile_revision = self.applied_profile = None
        self.trial_geometry_revision = None
        self.reset_rotation()
        self.relocation = None
        self.calibration_origin = None
        self.return_motion = None
        self.relocation_before_translation = False
        self.relocation_sensor_deadlines = {}
        self.baseline = StationaryBaseline(
            require_us_stable=bool(self.get_parameter('calibration_require_us_agreement').value))
        self.range_filters = {name: CalibrationRangeFilter() for name in ('lidar', 'us')}
        self.wall_tracker = WallTracker()
        self.raw_ranges = {}
        self.us_source_valid = False
        self.phase, self.message = 'collecting', 'Keep robot stationary on safe level floor'
        if sensing_only:
            self.phase, self.message = 'sensing_only', 'Stationary partial sensing; IMU excluded; motion prohibited'
        elif existing_settings:
            self.phase = 'limited_sensors' if limited_sensors else 'existing_settings'
            self.message = 'Existing parameters selected; checking live sensors without calibration'
        self.started = time.monotonic()
        self.motion_start = None
        self.precision_pause_started = None
        self.precision_pause_total = 0.
        self.precision_pause_map = False
        self.map_tf_diagnostic = {'valid': False, 'reason': 'not_received'}
        self.runtime_ready = not (sensing_only or existing_settings)
        self.runtime_healthy_since = None
        self.runtime_waiting = []
        self.recalibration_required = False
        self.selected_target = None
        self.motion_clearance = {}
        self.round_trip = None
        self.motion = None
        self.baseline_values = {}
        self.environment_samples = []
        self.environment_map = None
        self.navigation_profile = None
        self.requested = None
        self.sensors = self.baseline.report(self.started)
        self.last_report = 0.
        try:
            if invalidate_certificate:
                self.certificate_path().unlink(missing_ok=True)
            self.persist()  # A previous boot's ready file is not current evidence.
        except (OSError, ValueError) as exc:
            self.phase, self.message = 'failed', f'Cannot invalidate previous calibration result: {exc}'
        self.publish()

    def zero(self):
        if self.raw_pub is None:
            return
        self.publish_trial(Twist())

    def stop_wander(self):
        """Message edge for the ROS-free mixins (D-171): tell wander to stop."""
        self.wander_pub.publish(String(data='stop'))

    def request_command(self, command):
        """Message edge for the ROS-free mixins (D-171): feed a calibration command."""
        self.on_command(String(data=command))

    def drive_trial(self, linear=0., angular=0.):
        """Message edge for the ROS-free mixins (D-171): one bounded trial command."""
        command = Twist()
        command.linear.x = linear
        command.angular.z = angular
        self.publish_trial(command)

    def stamped(self, msg, max_age=1.):
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        age = self.get_clock().now().nanoseconds * 1e-9 - stamp
        return -.2 <= age <= max_age

    def relocation_source_deadline(self, msg):
        source = msg.header.stamp.sec + msg.header.stamp.nanosec*1e-9
        age = self.get_clock().now().nanoseconds*1e-9-source
        return time.monotonic()+.2-max(0.,age) if -.1 <= age <= .2 else None

    def add(self, name, values, valid=True):
        self.baseline.add(name, values, time.monotonic(), valid)

    def add_range(self, name, distance, valid):
        now = time.monotonic()
        self.raw_ranges[name] = (now, distance, valid and math.isfinite(distance))
        filtered = self.range_filters[name].update(distance, now, valid)
        self.add(name, (filtered,), valid)

    def on_estop(self, msg):
        self.estop = bool(msg.data)
        if self.estop and self.existing_settings:
            self.runtime_ready = False
            self.runtime_healthy_since = None
            self.zero()
            self.wander_pub.publish(String(data='stop'))
            self.publish()
        if self.estop and self.phase in ('validating_motion', 'validating_rotation', 'relocating_calibration', 'returning_calibration'):
            self.finish(False, 'Emergency stop engaged')

    def on_wander(self, msg):
        self.wander_state = (msg.data, time.monotonic())

    def on_scan(self, msg):
        valid = is_robot_scan(msg) and self.stamped(msg)
        self.scan_frame = msg.header.frame_id if valid else self.scan_frame
        try:
            transform = self.tf.lookup_transform('base_link', msg.header.frame_id, rclpy.time.Time())
            q = transform.transform.rotation
            self.lidar_nose = nose_from_quaternion(q.x, q.y, q.z, q.w)
            p = transform.transform.translation
            self.rotation_mount_offset = math.hypot(p.x, p.y)
            self.rotation_mount = (p.x, p.y, -self.lidar_nose)
        except Exception:
            valid = False
        distance = sector_range(msg, self.lidar_nose,
                                math.radians(12), pctl=.1) if valid else math.inf
        pose = self.baseline.latest('odom')
        odom_rows = self.baseline.samples['odom']
        if not odom_rows or not 0 <= time.monotonic()-odom_rows[-1][0] <= .2:
            pose = None
        if precision_scan_required(self.phase):
            self.rotation_scan_sample(msg, valid, current=self.stamped(msg, .25))
        if not precision_scan_required(self.phase) or self.phase == 'validating_rotation':
            # A navigation turn may leave the calibration wall entirely.
            # Runtime sensor health uses actual scan returns, not a wall fit.
            precision = distance
        elif valid and pose is not None:
            p = transform.transform.translation
            precision = self.wall_tracker.update(msg, self.lidar_nose,
                locked=self.phase == 'validating_motion', pose=pose[:3], mount=(p.x, p.y),
                now=time.monotonic())
        else:
            precision = math.inf
            self.wall_tracker.diagnostic = {
                'status': 'invalid',
                'reason': 'Waiting for fresh odometry' if valid and pose is None else 'Scan or transform unavailable',
                'locked': self.wall_tracker.locked,
                'odom_age_s': time.monotonic()-odom_rows[-1][0] if odom_rows else None}
        if valid and getattr(self, 'camera_capture', None) is not None:
            self.camera_capture_scan((np.asarray(msg.ranges, dtype=np.float32), msg.angle_min,
                                      msg.angle_increment, msg.range_min, msg.range_max))
        self.add_range('lidar', precision, valid and math.isfinite(precision))
        # Braking still observes the original raw cone; the fitted wall only
        # supplies measurement evidence and cannot hide a closer obstacle.
        self.raw_ranges['lidar'] = (time.monotonic(), distance, valid and math.isfinite(distance))
        if valid and self.phase in ('collecting', 'waiting_motion'):
            left = sector_range(msg, self.lidar_nose+math.pi/2, math.radians(8), pctl=.5)
            right = sector_range(msg, self.lidar_nose-math.pi/2, math.radians(8), pctl=.5)
            mapped = [None, None]
            try:
                t = self.tf.lookup_transform('map', msg.header.frame_id, rclpy.time.Time())
                q, p = t.transform.rotation, t.transform.translation
                yaw = math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
                if self.environment_map is not None:
                    mapped = [map_ray(self.environment_map, (p.x,p.y), yaw+self.lidar_nose+side*math.pi/2)
                              for side in (1,-1)]
            except Exception:
                pass
            self.environment_samples.append((time.monotonic(), (left,right,*mapped)))
            self.environment_samples = self.environment_samples[-50:]

    def on_odom(self, msg):
        self.relocation_sensor_deadlines['odom'] = self.relocation_source_deadline(msg)
        p, q, v = msg.pose.pose.position, msg.pose.pose.orientation, msg.twist.twist.linear
        yaw = math.atan2(2 * (q.w*q.z + q.x*q.y), 1 - 2 * (q.y*q.y + q.z*q.z))
        norm = math.sqrt(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w)
        self.add('odom', (p.x, p.y, yaw, math.hypot(v.x, v.y)), self.stamped(msg, .2 if self.phase in ('relocating_calibration','returning_calibration') else .25 if self.phase == 'validating_rotation' else 1.) and .9 <= norm <= 1.1)

    def on_map(self, msg):
        known = sum(value >= 0 for value in msg.data)
        valid = (msg.header.frame_id == 'map' and msg.info.width > 0 and msg.info.height > 0 and
                 len(msg.data) == msg.info.width * msg.info.height and msg.info.resolution > 0)
        self.add('map', (known, msg.info.resolution), valid and self.stamped(msg, 5.))
        if valid:
            self.environment_map = OccupancyMap.from_msg(msg)

    def on_ir(self, msg):
        values = tuple(msg.data[:3])
        self.add('ir', values if len(values) == 3 else (0, 0, 0),
                 len(values) == 3 and all(0 < value < 4000 for value in values))

    def on_us(self, msg):
        maximum = min(msg.max_range, float(self.get_parameter('calibration_us_max_range').value))
        self.us_source_valid = self.stamped(msg)
        self.add_range('us', msg.range, self.us_source_valid and max(.02, msg.min_range) < msg.range < maximum)

    def on_imu(self, msg):
        self.relocation_sensor_deadlines['imu'] = self.relocation_source_deadline(msg)
        a, g, q = msg.linear_acceleration, msg.angular_velocity, msg.orientation
        norm = math.sqrt(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w)
        roll = math.atan2(2*(q.w*q.x + q.y*q.z), 1 - 2*(q.x*q.x + q.y*q.y))
        pitch = math.asin(max(-1., min(1., 2*(q.w*q.y - q.z*q.x))))
        gravity = math.sqrt(a.x*a.x+a.y*a.y+a.z*a.z)
        unit = self.get_parameter('imu_angular_velocity_unit').value
        scale = math.pi / 180. if unit == 'deg_s' else 1.
        gx, gy, gz = g.x * scale, g.y * scale, g.z * scale
        gyro = math.sqrt(gx*gx+gy*gy+gz*gz)
        tilt = max(abs(roll), abs(pitch))
        self.rotation_imu_yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        # Stationary gyro limits qualify calibration, not normal route turns.
        # Runtime tilt, timestamps, finite values and gravity remain required.
        self.add('imu', (gravity, gyro, tilt,
                         gx, gy, gz, a.x, a.y, a.z, roll, pitch),
                 unit in ('rad_s', 'deg_s') and self.stamped(msg, .2 if self.phase in ('relocating_calibration','returning_calibration') else .25 if self.phase == 'validating_rotation' else 1.) and .9 <= norm <= 1.1 and 8 <= gravity <= 11.5 and
                 (self.phase in ('ready', 'validating_rotation', 'existing_settings', 'limited_sensors') or gyro < .15) and tilt < math.radians(20))

    def on_camera(self, msg):
        pixels = np.frombuffer(bytes(msg.data), np.uint8)
        valid = (msg.encoding in ('bgr8', 'rgb8') and msg.width > 0 and msg.height > 0 and
                 msg.step >= msg.width * 3 and pixels.size >= msg.step * msg.height)
        mean, contrast = (float(pixels.mean()), float(pixels.std())) if pixels.size else (0, 0)
        self.add('camera', (mean, contrast),
                 valid and self.stamped(msg) and 5 <= mean <= 250 and contrast >= 2)
        if valid and getattr(self, 'camera_capture', None) is not None and self.stamped(msg):
            self.camera_capture_frame(pixels, msg.width, msg.height, msg.step)

    def read_tf(self):
        try:
            if not self.scan_frame:
                raise ValueError('No scan frame')
            transform = self.tf.lookup_transform('base_link', self.scan_frame, rclpy.time.Time())
            q = transform.transform.rotation
            norm = math.sqrt(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w)
            yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
            self.lidar_nose = nose_from_quaternion(q.x, q.y, q.z, q.w)
            self.add('tf', (wrap(yaw + self.lidar_nose), self.lidar_nose), .9 <= norm <= 1.1)
        except Exception:
            self.add('tf', (0., 0.), False)
        try:
            transform = self.tf.lookup_transform('map', 'base_link', rclpy.time.Time())
            p, q = transform.transform.translation, transform.transform.rotation
            stamp = transform.header.stamp.sec + transform.header.stamp.nanosec * 1e-9
            age = self.get_clock().now().nanoseconds * 1e-9 - stamp
            self.map_tf_diagnostic = transform_health(stamp+age, stamp,
                (p.x,p.y,p.z), (q.x,q.y,q.z,q.w))
            yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
            self.add('map_tf', (p.x, p.y, yaw), self.map_tf_diagnostic['valid'])
        except Exception as exc:
            self.map_tf_diagnostic = dict(valid=False, reason=type(exc).__name__, error=str(exc))
            self.add('map_tf', (0., 0., 0.), False)

    def on_motion_limits(self, msg):
        try:
            data = json.loads(msg.data)
            self.safety_limits = (time.monotonic(), data if isinstance(data, dict) else {})
        except (ValueError, TypeError):
            self.safety_limits = (0., {})

    def on_command(self, msg):
        command = msg.data.strip().lower()
        if command == 'partial_calibration':
            # The operator asks for a partial calibration; the tier table decides
            # whether one exists and which route it takes.
            plan = partial_plan(self.stationary_report(time.monotonic()),
                                bool(self.get_parameter('localization_required').value))
            if not plan['available']:
                self.message = ('Required sensor failed and cannot be excluded: '
                                + ', '.join(plan['blocking_sensors'])
                                if plan['blocking_sensors']
                                else 'No failed sensor to exclude; use full calibration')
                self.publish()
                return
            if plan['rotation_available']:
                self.reset(excluded_sensors=plan['excluded_sensors'])
            else:
                # Rotation is IMU-against-odometry agreement, so excluding the IMU
                # withdraws it; existing parameters plus the speed cap is what remains.
                self.reset(existing_settings=True, limited_sensors=True,
                           excluded_sensors=plan['excluded_sensors'])
            return
        if command == 'camera_extrinsic':
            self.start_camera_extrinsic(time.monotonic(), self.fresh_odom())
            return
        if command == 'use_existing_settings':
            self.reset(existing_settings=True)
            return
        if command == 'use_limited_sensors':
            self.reset(existing_settings=True, limited_sensors=True)
            return
        if command == 'sensing_only':
            self.reset(sensing_only=True)
            return
        if command.startswith('retry:'):
            parts = command.split(':')
            self.after_relocation = parts[1] if len(parts) > 1 and parts[1] else 'stay'
            self.calibration_scope = parts[2] if len(parts) > 2 and parts[2] else 'full'
            command = 'retry'
        if command == 'abort':
            self.finish(False, 'Calibration aborted', 'aborted')
        elif command == 'retry':
            # Skipping the measurement is the operating-parameters route, not a calibration.
            if getattr(self, 'calibration_scope', 'full') == 'skip_motion':
                self.reset(invalidate_certificate=True, existing_settings=True)
            else:
                self.reset(invalidate_certificate=True)
        elif command == 'sensor_check' and self.phase in ('ready', 'existing_settings', 'limited_sensors'):
            self.zero()
            self.wander_pub.publish(String(data='stop'))
            self.runtime_ready = False
            self.runtime_healthy_since = None
            self.message = ('Existing parameters retained; checking live sensors without calibration'
                            if self.existing_settings else 'Saved calibration retained; checking current sensors without motion')
            self.publish()
        elif command == 'validate_motion':
            if getattr(self, 'existing_settings', False):
                self.message = 'Calibration skipped by selection; use retry to start full calibration'
                self.publish()
                return
            if self.sensing_only:
                self.zero()
                self.message = 'Motion prohibited in partial sensing; use retry for full calibration'
                self.publish()
                return
            now = time.monotonic()
            self.sensors = self.stationary_report(now)
            reason = self.safe_motion(now)
            if self.phase != 'waiting_motion' or not all(s.get('eligible', s['ok']) for s in self.sensors.values()) or reason:
                self.message = reason or 'A fresh stable stationary baseline is required first'
                self.publish()
                return
            self.wander_pub.publish(String(data='stop'))
            self.trial_geometry_revision = self.geometry_revision
            if self.calibration_origin is None:
                self.calibration_origin = tuple(self.baseline.latest('odom')[:3])
            self.selected_target = self.motion_clearance['target_m']
            self.baseline_values = self.baseline.statistics(now)
            if self.environment_map is not None:
                self.navigation_profile = environment_profile(
                    float(self.get_parameter('robot_radius').value), self.environment_map.res,
                    [row for stamp,row in self.environment_samples if now-stamp <= 5.])
            self.phase, self.message = 'validating_motion', 'Waiting for wander stop before bounded forward validation'
            self.requested = now
            self.publish()

    def tick(self):
        self.read_tf()
        # TF collection timestamps its own samples; evaluate freshness after it.
        now = time.monotonic()
        if getattr(self, 'camera_capture', None) is not None:  # stationary camera step running
            self.tick_camera_extrinsic(now, self.fresh_odom())
        if self.phase in ('validating_motion', 'failed', 'aborted'):
            # A recovered stream must not retain a paused/failed sample label.
            # Readiness and trial acceptance still use their independent gates.
            self.sensors = self.runtime_health(now)
        if getattr(self, 'existing_settings', False) and self.phase in ('existing_settings', 'limited_sensors'):
            previously_ready = self.runtime_ready
            self.sensors = self.runtime_health(now)
            for name, item in self.sensors.items():
                item['required_for_operation'] = name not in ('camera', 'map', 'map_tf') or (
                    name in ('map', 'map_tf') and bool(self.get_parameter('localization_required').value))
                item['detail'] = item.get('detail', '').replace('saved calibration retained', 'existing parameters retained')
            limited = getattr(self, 'limited_sensors', False)
            if limited:
                self.sensors['imu'].update(required_for_operation=False, excluded=True, eligible=False,
                    status='excluded', detail='IMU excluded by explicit limited-speed operation selection')
            self.configured_waiting = configured_waiting_reasons(
                self.sensors, bool(self.get_parameter('localization_required').value),
                self.geometry_fresh(now), self.estop,
                {key.rsplit('/', 1)[-1]: value for key, value in self.hazards.items()}, now,
                excluded=tuple(getattr(self, 'excluded_sensors', ()) or (('imu',) if limited else ())))
            if self.configured_waiting:
                self.zero()
                self.runtime_ready = False
                self.runtime_healthy_since = None
                if previously_ready:
                    self.wander_pub.publish(String(data='stop'))
            elif not self.runtime_ready:
                self.zero()
                if self.runtime_healthy_since is None:
                    self.runtime_healthy_since = now
                self.runtime_ready = now-self.runtime_healthy_since >= 1.
            self.message = ('Existing parameters; calibration unverified; waiting: ' + ', '.join(self.configured_waiting)
                            if self.configured_waiting else 'Existing parameters; calibration unverified; live sensors healthy')
            if previously_ready != self.runtime_ready or now-self.last_report >= .5:
                self.publish()
            return
        if self.sensing_only:
            self.zero()
            self.runtime_ready = False
            self.sensors = partial_sensing_report(self.stationary_report(now))['sensors']
            self.baseline_values = {name: value for name, value in self.baseline.statistics(now).items()
                                    if name != 'imu'}
            if now-self.last_report >= .5:
                self.wander_pub.publish(String(data='stop'))
                self.publish()
            return
        if self.phase == 'returning_calibration':
            self.tick_return(now)
            return
        if self.phase == 'relocating_calibration':
            self.tick_relocation(now)
            return
        if self.phase == 'validating_rotation':
            self.tick_rotation(now)
            return
        if self.phase == 'ready':
            previously_ready = self.runtime_ready
            received = getattr(self, 'geometry_received', None)
            runtime = calibration_runtime(self.runtime_health(now),
                localization_required=bool(self.get_parameter('localization_required').value),
                geometry_fresh=self.geometry_fresh(now),
                established_revision=getattr(self, 'trial_geometry_revision', None),
                current_revision=getattr(self, 'geometry_revision', None),
                current_geometry_fresh=received is not None and 0 <= now-received <= 1.)
            self.sensors = runtime['sensors']
            self.runtime_waiting = missing = runtime['waiting_reasons']
            self.recalibration_required = runtime['recalibration_required']
            if missing:
                self.zero()
                if self.runtime_ready:
                    self.wander_pub.publish(String(data='stop'))
                self.runtime_ready = False
                self.runtime_healthy_since = None
                self.message = ('Calibration identity changed; explicit recalibration required'
                    if self.recalibration_required else 'Saved calibration retained; runtime hold: ' + ', '.join(missing))
            elif not self.runtime_ready:
                self.zero()
                if self.runtime_healthy_since is None:
                    self.runtime_healthy_since = now
                if now-self.runtime_healthy_since >= 1.:
                    self.runtime_ready = True
                    self.message = 'Saved calibration retained; sensor checks recovered'
            if previously_ready != self.runtime_ready or now-self.last_report >= .5:
                self.publish()
            return
        if self.phase in ('collecting', 'waiting_motion'):
            if self.tick_collecting(now):
                return
        elif self.phase == 'validating_motion':
            if self.tick_motion(now):
                return
        if now - self.last_report >= .5:
            self.publish()

    def publish(self):
        self.last_report = time.monotonic()
        packet = self.profile_packet()
        self.profile_sequence += 1
        self.profile_revision = packet['revision']
        self.profile_pub.publish(String(data=json.dumps(packet, allow_nan=False)))
        self.scale_pub.publish(Float32MultiArray(data=packet['linear_gains']))
        report = self.report()
        self.status_pub.publish(String(data=json.dumps(report, allow_nan=False)))
        diagnostics = getattr(self, 'startup_diagnostics', None)
        if diagnostics is not None:
            event = diagnostics.update(report)
            if event is not None:
                self.get_logger().info(json.dumps(event, allow_nan=False))
        self.ready_pub.publish(Bool(data=bool(report['ready'])))


def main():
    rclpy.init()
    node = StartupCalibrationNode()
    try:
        executor_choice.spin(node, rclpy)
    except KeyboardInterrupt:
        pass
    finally:
        node.zero()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
