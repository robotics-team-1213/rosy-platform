#!/usr/bin/env python3
"""Safety ROS node. Subjects: bumper, hazard, gate."""
import math
import json
import time
import os

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from geometry_msgs.msg import Twist
from ..tf_buffer import RobotTransformBuffer
from rclpy.node import Node
from rclpy.time import Time
from tf2_ros import TransformException, TransformListener
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import Imu, LaserScan, Range
from std_msgs.msg import Bool, Float32, String, UInt16MultiArray, Float32MultiArray

from ..sensing.filt import IrMedian, MedianLp
from ..sensing.body import URDF_RADIUS, use_radius
from ..sensing.lidar import NOSE_YAW
from ..sensing.localization import lease_ready
from ..sensing.pose import planar_pose
from ..control.lidar_guard import (lidar_blocked, lidar_can_rotate,
                                   translation_footprint_eligible, TranslationEvidence)
from ..control.command_gate import GateInputs, evaluate_command
from ..control.policy_handoff import ControlPolicyProducer
from ..control.obstacle_risk import TrackedEvidence
from ..control.actuation import prepare_command
from ..control.rotation_clearance import rotation_clearance_allowed
from ..control.rotation_envelope import pivot_clearance, suggest_rotation_translation, straight_translation_limits
from ..control.motion_sweep import command_sweep_clearance, bounded_translation_limits
from ..control.footprint_sweep import footprint_translation_limits
from ..control.escape_space import escape_space_plan
from .bumper import Bumper
from .gate import Gate
from .hazard import Hazard
from .scale import Scale
from .obstacles import Obstacles
from .evidence import Evidence


class SafetyNode(Node, Bumper, Hazard, Gate, Scale, Evidence, Obstacles):

    @classmethod
    def from_calibration(cls, snapshot, *, sensor_only=False):
        """Construct a stopped comparison consumer; never activate beside CORE.

        The digest records constructor readback only, not continuing policy
        adoption. Later parameter changes require a new verification.
        """
        from rclpy.parameter import Parameter
        from ..calibration_snapshot import CalibrationSnapshot
        if not isinstance(snapshot, CalibrationSnapshot):
            raise ValueError('A validated calibration snapshot is required')
        values = snapshot.node_parameters('safety_node')
        measured = {'cliff_raw_max', 'cliff_clear_raw', 'cliff_mode', 'cmd_linear_sign',
                    'imu_roll0', 'imu_pitch0', 'lidar_yaw_offset'}
        if not set(values).issubset(measured):
            raise ValueError('Calibration cannot override unrelated operating parameters')
        overrides = [Parameter(name, value=value) for name, value in values.items()]
        overrides.append(Parameter('start_estopped', value=True))
        node = cls(parameter_overrides=overrides, sensor_only=sensor_only)
        try:
            snapshot.verify_parameters(node)
            if node.get_parameter('start_estopped').value is not True:
                raise ValueError('Calibration consumer must start stopped')
            node.calibration_parameter_digest = snapshot.digest
            return node
        except Exception:
            node.destroy_node()
            raise

    def __init__(self, *, parameter_overrides=None, sensor_only=False, namespace=None):
        if type(sensor_only) is not bool:
            raise ValueError('sensor_only must be a boolean constructor choice')
        if namespace is not None and (not isinstance(namespace, str) or not namespace.strip()):
            raise ValueError('namespace must be a non-empty string when provided')
        self._sensor_only = sensor_only
        self.sensor_state = None
        self._policy_producer = None
        self.sensor_policy_published = None
        node_kwargs = {'parameter_overrides': parameter_overrides}
        if namespace is not None:
            node_kwargs['namespace'] = namespace
        super().__init__('safety_node', **node_kwargs)
        self.declare_parameter('cmd_in', 'cmd_vel_raw')
        self.declare_parameter('cmd_out', 'cmd_vel')
        self.declare_parameter('start_estopped', True)
        self.declare_parameter('localization_required', False)
        self.localization_status = None
        self.create_subscription(String, 'localization/status', self.on_localization, 10)
        # Verified Pinky mesh envelope; only straight commands <=14mm/s use it.
        self.declare_parameter('footprint_guard_enabled', False)
        # Commissioned only on the isolated wheel rig; physical stopping and
        # mixed-motion slip have not yet been measured on Pinky hardware.
        self.declare_parameter('simulation_motion_sweep_enabled', False)
        self.init_obstacles()
        self.declare_parameter('scan_topic', 'scan')
        self.declare_parameter('us_topic', 'us_sensor/range')
        self.declare_parameter('ir_topic', 'ir_sensor/range')
        self.declare_parameter('stop_distance', 0.12)
        self.declare_parameter('clear_distance', 0.14)
        self.declare_parameter('us_stop_distance', 0.020)
        self.declare_parameter('us_clear_distance', 0.028)
        self.declare_parameter('front_half_width_deg', 45.0)
        self.declare_parameter('lidar_yaw_offset', NOSE_YAW)
        self.declare_parameter('lidar_use_tf', True)
        self.declare_parameter('scan_pctl', 0.10)
        self.declare_parameter('scan_ignore_m', 0.04)
        self.declare_parameter('sensor_timeout', 1.0)
        self.declare_parameter('imu_angular_velocity_unit', 'deg_s')
        self.declare_parameter('safety_max_linear', .014)
        self.declare_parameter('safety_max_angular', .10)
        self.declare_parameter('us_scale', 1.0)
        self.declare_parameter('us_invalid_hold', 5)
        self.declare_parameter('us_hits', 3)
        self.declare_parameter('cmd_linear_sign', 1.0)
        self.declare_parameter('auto_linear_sign', False)
        self.declare_parameter('camera_as_wall', False)
        self.declare_parameter('camera_block_as_wall', False)
        self.declare_parameter('imu_topic', 'imu_raw')
        self.declare_parameter('tilt_deg', 20.0)
        self.declare_parameter('gyro_dps', 90.0)
        self.declare_parameter('pickup_acc', 3.5)
        self.declare_parameter('imu_roll0', 0.0)
        self.declare_parameter('imu_pitch0', 0.0)
        self.declare_parameter('cliff_enable', True)
        self.declare_parameter('cliff_raw_max', 800)
        self.declare_parameter('cliff_clear_raw', 1500)
        self.declare_parameter('cliff_mode', 'low')
        self.declare_parameter('cliff_hits', 2)
        self.declare_parameter('camera_cliff_topic', 'camera/cliff')
        self.declare_parameter('camera_block_topic', 'camera/blocked')
        self.declare_parameter('filt_median', 5)
        self.declare_parameter('filt_hz', 1.5)
        self.declare_parameter('auto_map', True)
        self.declare_parameter('map_range', 0.28)
        self.declare_parameter('map_range_min', 0.18)
        self.declare_parameter('map_range_max', 0.40)
        self.declare_parameter('open_max', 0.40)
        self.declare_parameter('robot_radius', URDF_RADIUS)
        self.declare_parameter('rotation_footprint_xy', [], ParameterDescriptor(dynamic_typing=True))
        self.declare_parameter('wall_front', 0.08)
        self.declare_parameter('warn_front', 0.11)

        self.stop_d = float(self.get_parameter('stop_distance').value)
        self.clear_d = float(self.get_parameter('clear_distance').value)
        self.us_stop = float(self.get_parameter('us_stop_distance').value)
        self.us_clear = float(self.get_parameter('us_clear_distance').value)
        self.half_w = math.radians(float(self.get_parameter('front_half_width_deg').value))
        self.lidar_yaw = float(self.get_parameter('lidar_yaw_offset').value)
        self.lidar_tf = RobotTransformBuffer(self)
        self.lidar_tf_listener = TransformListener(self.lidar_tf, self)
        self.lidar_yaw_source = 'waiting_tf'
        self.timeout = float(self.get_parameter('sensor_timeout').value)
        self.cmd_out = self.get_parameter('cmd_out').value
        nmed = max(1, int(self.get_parameter('filt_median').value))
        fchz = float(self.get_parameter('filt_hz').value)
        dt = 0.05
        self._lp = {
            k: MedianLp(nmed, fchz, dt)
            for k in (
                'front', 'rear', 'us', 'left', 'right',
                'rear_left', 'rear_right',
            )
        }
        self._ir_f = IrMedian(nmed)

        self.pub = None if sensor_only else self.create_publisher(Twist, self.cmd_out, 10)
        self.raw_zero_pub = (None if sensor_only else
                             self.create_publisher(Twist, self.get_parameter('cmd_in').value, 10))
        self.block_pub = self.create_publisher(Bool, 'safety/blocked', 10)
        self.cliff_pub = self.create_publisher(Bool, 'safety/cliff', 10)
        self.tilt_pub = self.create_publisher(Bool, 'safety/tilt', 10)
        self.pickup_pub = self.create_publisher(Bool, 'safety/pickup', 10)
        self.range_pub = self.create_publisher(Float32, 'safety/min_range', 10)
        self.us_pub = self.create_publisher(Float32, 'safety/us_range', 10)
        self.rear_pub = self.create_publisher(Float32, 'safety/rear_range', 10)
        self.rear_clear_pub = self.create_publisher(Bool, 'safety/rear_clear', 10)
        self.left_pub = self.create_publisher(Float32, 'safety/left_range', 10)
        self.right_pub = self.create_publisher(Float32, 'safety/right_range', 10)
        self.rear_left_pub = self.create_publisher(Float32, 'safety/rear_left', 10)
        self.rear_right_pub = self.create_publisher(Float32, 'safety/rear_right', 10)
        self.can_rev_pub = self.create_publisher(Bool, 'safety/can_reverse', 10)
        self.open_pub = self.create_publisher(Float32, 'safety/open_range', 10)
        self.open_yaw_pub = self.create_publisher(Float32, 'safety/open_yaw', 10)
        self.map_pub = self.create_publisher(Float32, 'safety/map_range', 10)
        self.open_max_pub = self.create_publisher(Float32, 'safety/open_max', 10)
        self.corr_pub = self.create_publisher(Float32, 'safety/corridor', 10)
        self.narrow_pub = self.create_publisher(Float32, 'safety/narrow', 10)
        self.frontier_yaw_pub = self.create_publisher(Float32, 'safety/frontier_yaw', 10)
        self.frontier_pub = self.create_publisher(Float32, 'safety/frontier_range', 10)
        self.route_yaw_pub = self.create_publisher(Float32, 'safety/route_yaw', 10)
        self.route_pub = self.create_publisher(Float32, 'safety/route_range', 10)
        self.exit_yaw_pub = self.create_publisher(Float32, 'safety/exit_yaw', 10)
        self.exit_pub = self.create_publisher(Float32, 'safety/exit_range', 10)
        self.radius_pub = self.create_publisher(Float32, 'safety/robot_radius', 10)
        self.motion_limits_pub = self.create_publisher(String, 'safety/motion_limits', 10)
        self.wander_cmd = None if sensor_only else self.create_publisher(String, 'wander/cmd', 10)
        self.calib_step = None if sensor_only else self.create_publisher(String, 'calib/step', 10)
        latched = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.init_evidence(latched)
        self.estop_pub = None if sensor_only else self.create_publisher(Bool, 'estop/state', latched)
        self.drive_scales = [1., 1.]
        self.drive_scale_time = 0.
        self.drive_ready = False
        if not sensor_only:
            self.create_subscription(Float32MultiArray, 'calibration/drive_scale', self.on_drive_scale, latched)
            self.create_subscription(Bool, 'calibration/ready', self.on_drive_ready, latched)
            self.create_subscription(Twist, self.get_parameter('cmd_in').value, self.on_cmd, 10)
            self.create_subscription(Bool, 'estop', self.on_estop, latched)
            self.create_subscription(String, 'estop/cmd', self.on_estop_cmd, 10)
        self.create_subscription(
            LaserScan, self.get_parameter('scan_topic').value, self.on_scan, qos_profile_sensor_data
        )
        self.create_subscription(
            Range, self.get_parameter('us_topic').value, self.on_us, qos_profile_sensor_data
        )
        self.create_subscription(
            UInt16MultiArray, self.get_parameter('ir_topic').value, self.on_ir, qos_profile_sensor_data
        )
        self.create_subscription(
            Bool, self.get_parameter('camera_cliff_topic').value, self.on_cam_cliff, 10
        )
        self.create_subscription(
            Bool, self.get_parameter('camera_block_topic').value, self.on_cam_block, 10
        )
        self.create_subscription(
            Imu, self.get_parameter('imu_topic').value, self.on_imu, qos_profile_sensor_data
        )
        self.create_timer(0.05, self.tick)

        self.last_cmd = Twist()
        self.last_cmd_time = None
        self.last_scan_time = None
        self.last_us_time = None
        self.last_ir_time = None
        self.last_cam_time = None
        self.last_imu_time = None
        self.lidar_front = float('inf')
        self.lidar_rear = float('inf')
        self.lidar_left = float('inf')
        self.lidar_right = float('inf')
        self.lidar_rear_left = float('inf')
        self.lidar_rear_right = float('inf')
        self.open_range = float('inf')
        self.open_yaw = 0.0
        self.frontiers = []
        self.frontier_yaw = 0.0
        self.frontier_range = float('inf')
        self.route_yaw = 0.0
        self.route_range = float('inf')
        self.exit_yaw = 0.0
        self.exit_range = float('inf')
        self.map_range = float(self.get_parameter('map_range').value)
        self.open_max = float(self.get_parameter('open_max').value)
        self.robot_r = use_radius(self.get_parameter('robot_radius').value)
        self._corr_buf = []
        self._scan_drop = 0
        self._scan_ok = 0
        self.us_front = float('inf')
        self.rear_blocked = False
        self._imu_n = 0
        self.ir_raw = ()
        self.blocked = False
        self.us_blocked = False
        self.cliff = False
        self.cam_cliff = False
        self.cam_block = False
        self.tilt = False
        self.pickup = False
        self._cam_cliff_logged = False
        self._cam_block_logged = False
        self._tilt_logged = False
        self._pickup_logged = False
        self._us_invalid = 0
        self._us_hits = 0
        self._imu_has_g = False
        self._sign_t = None
        self._sign_front0 = None
        self._sign_vx0 = 0.0
        self._sign_flip_t = None
        self._sign_hits = 0
        self.estop = bool(self.get_parameter('start_estopped').value)
        self.us_scale = float(self.get_parameter('us_scale').value)
        self.us_invalid_hold = max(1, int(self.get_parameter('us_invalid_hold').value))
        self.cmd_linear_sign = float(self.get_parameter('cmd_linear_sign').value)
        if self.cmd_linear_sign >= 0.0:
            self.cmd_linear_sign = 1.0
        else:
            self.cmd_linear_sign = -1.0
        self.get_logger().info(
            f'safety_node ready | lidar_stop={self.stop_d:.2f}m us_stop={self.us_stop:.2f}m '
            f'linear_sign={self.cmd_linear_sign:.0f} cam_wall='
            f'{int(bool(self.get_parameter("camera_as_wall").value))} '
            f'cam_block={int(bool(self.get_parameter("camera_block_as_wall").value))} '
            f'cliff_mode={self.get_parameter("cliff_mode").value} '
            f'th={self.get_parameter("cliff_raw_max").value} '
            f'lidar_yaw={math.degrees(self.lidar_yaw):.0f}deg '
            f'radius={self.robot_r*100:.1f}cm '
            f'filt={int(self.get_parameter("filt_median").value)}/'
            f'{float(self.get_parameter("filt_hz").value):.1f}Hz | '
            'E-STOP /estop Bool or /estop/cmd stop|release'
        )
        if sensor_only:
            self.get_logger().info('sensor-only mode: no command or legacy calibration authority')
        elif self.estop:
            self.engage_estop('startup')
        else:
            self.estop_pub.publish(Bool(data=False))

    def now(self):
        return self.get_clock().now()

    def age(self, stamp):
        if stamp is None:
            return 1e9
        return (self.now() - stamp).nanoseconds / 1e9

    def tick(self):
        self.sensor_state = None
        self.sensor_policy_published = None
        try:
            self._refresh_distances()
            self.refresh_profile()
        except (ValueError, TypeError, OverflowError):
            self.profile_valid = False
        if not self.profile_valid:
            if self._sensor_only:
                self.sensor_state = GateInputs(profile_valid=False, observation_failure='invalid_geometry')
                return
            self.halt_with_reason('invalid_geometry')
            self.last_cmd = Twist()
            self.last_cmd_time = None
            return
        if self.estop and not self._sensor_only:
            self.raw_zero_pub.publish(Twist())
            self._publish_zero()
            self.estop_pub.publish(Bool(data=True))
            # Keep sensing and publishing while stopped so clearance can
            # be inspected without releasing the emergency stop.
        lidar_d = self._filt('front', self.lidar_distance())
        us = self._filt('us', self.us_distance())
        left = self._filt('left', self.lidar_left)
        right = self._filt('right', self.lidar_right)
        self._scale_update(left, right)
        rleft = self._filt('rear_left', self.lidar_rear_left)
        rright = self._filt('rear_right', self.lidar_rear_right)
        # Speed/think uses lidar only. US flicker at 2 cm must not look like a wall 2 cm away.
        self.range_pub.publish(Float32(data=float(lidar_d if math.isfinite(lidar_d) else -1.0)))
        self.us_pub.publish(Float32(data=float(us if math.isfinite(us) else -1.0)))
        def _m(v):
            return float(v if math.isfinite(v) else -1.0)
        self.left_pub.publish(Float32(data=_m(left)))
        self.right_pub.publish(Float32(data=_m(right)))
        self.rear_left_pub.publish(Float32(data=_m(rleft)))
        self.rear_right_pub.publish(Float32(data=_m(rright)))
        self.open_pub.publish(Float32(data=_m(self.open_range)))
        self.open_yaw_pub.publish(Float32(data=float(self.open_yaw)))
        self.frontier_yaw_pub.publish(Float32(data=float(self.frontier_yaw)))
        self.frontier_pub.publish(Float32(data=_m(self.frontier_range)))
        self.route_yaw_pub.publish(Float32(data=float(self.route_yaw)))
        self.route_pub.publish(Float32(data=_m(self.route_range)))
        self.exit_yaw_pub.publish(Float32(data=float(self.exit_yaw)))
        self.exit_pub.publish(Float32(data=_m(self.exit_range)))
        self.radius_pub.publish(Float32(data=float(self.robot_r)))

        # Cliff is independent of lidar. Always evaluate IR even if /scan is missing.
        if self.age(self.last_ir_time) > self.timeout:
            self.get_logger().warn('no IR — cliff unknown', throttle_duration_sec=2.0)
        cliff_now = self.ir_looks_like_cliff()
        if cliff_now and not self.cliff:
            self.get_logger().error(f'CLIFF IR={self.ir_raw}')
        elif self.cliff and not cliff_now:
            self.get_logger().info(f'cliff clear IR={self.ir_raw}')
        self.cliff = cliff_now
        self.cliff_pub.publish(Bool(data=self.cliff))

        lidar_ok = self.sensors_ok()
        rear_d = self._filt('rear', self.rear_distance())
        self.rear_pub.publish(Float32(data=float(rear_d if math.isfinite(rear_d) else -1.0)))
        if not lidar_ok:
            self.get_logger().warn('no lidar — motion disabled until scan', throttle_duration_sec=2.0)
        previous_front, previous_rear = self.blocked, self.rear_blocked
        self.blocked = lidar_blocked(
            self.lidar_distance(), lidar_d, self.blocked,
            self.stop_d, self.clear_d, lidar_ok)
        self.rear_blocked = lidar_blocked(
            self.rear_distance(), rear_d, self.rear_blocked,
            self.rear_stop_d, self.rear_clear_d, lidar_ok)
        self._policy_previous_front = previous_front
        self._policy_previous_rear = previous_rear
        can_rev = lidar_ok and not self.rear_blocked and rear_d > self.rear_stop_d
        travel = getattr(self, 'translation_clearance', None)
        footprint = translation_footprint_eligible(
            self.corrected_drive_speed(self.last_cmd.linear.x), self.last_cmd.angular.z,
            enabled=self.get_parameter('footprint_guard_enabled').value, lidar_fresh=lidar_ok,
            scan_age=self.age(self.last_scan_time),
            source_age=self.age(getattr(self, 'lidar_measurement_time', None)),
            mount=getattr(self, 'lidar_mount', None), travel=travel, radius=self.robot_r,
            ranges=(self.lidar_front, self.lidar_rear, self.lidar_left,
                    self.lidar_right, self.lidar_rear_left, self.lidar_rear_right))
        # Sensor-only observations must retain radial state. The CORE policy
        # evaluates a translation override against its own selected candidate.
        footprint = footprint and not self._sensor_only
        if footprint:
            # Distances already exclude the verified box and 10mm stand-off.
            self.blocked = lidar_blocked(travel[0], travel[0], previous_front, 0., .010, True)
            self.rear_blocked = lidar_blocked(travel[1], travel[1], previous_rear, 0., .010, True)
            can_rev = not self.rear_blocked
        body_radius = max(self.robot_r, .083) if self.get_parameter('footprint_guard_enabled').value else self.robot_r
        flat = self.get_parameter('rotation_footprint_xy').value or []
        rotation_estimate = self.calibration_lease.rotation_envelope(time.monotonic(), body_radius,
            list(zip(flat[::2], flat[1::2])))
        swept_radius = rotation_estimate['required_radius_m'] if rotation_estimate else None
        can_rotate = lidar_can_rotate(
            (self.lidar_front, self.lidar_rear, self.lidar_left, self.lidar_right,
             self.lidar_rear_left, self.lidar_rear_right),
            max(self.robot_r, .083) if self.get_parameter('footprint_guard_enabled').value else self.robot_r,
            lidar_ok, getattr(self, 'lidar_rotation_clearance', None), sweep_radius=swept_radius)
        pivot_margin = None
        if rotation_estimate is not None:
            pivot_margin = pivot_clearance(getattr(self, 'lidar_rotation_points', None),
                rotation_estimate['center_m'], rotation_estimate['pivot_radius_m'])
            # Exact pivot clearance needs complete coverage. Otherwise retain
            # the conservative learned swept-radius check above.
            can_rotate = rotation_clearance_allowed(
                can_rotate, getattr(self, 'lidar_rotation_observed', False), lidar_ok,
                pivot_margin, (self.lidar_front, self.lidar_rear, self.lidar_left,
                    self.lidar_right, self.lidar_rear_left, self.lidar_rear_right))
        elif self.calibration_lease.rotation_estimate_required():
            can_rotate = False
        rotation_trial = self.calibration_lease.rotation_trial_live(time.monotonic())
        translation_trial = self.calibration_lease.translation_trial_live(time.monotonic())
        bounded_motion = bool(not self._sensor_only and self.get_parameter('simulation_motion_sweep_enabled').value and
            self.get_parameter('use_sim_time').value and os.environ.get('ROS_DOMAIN_ID') == '227' and
            os.environ.get('GZ_PARTITION') == 'pinky_calmap227' and not rotation_trial and
            (rotation_estimate is not None or self.calibration_lease.rotation_estimate_required()))
        bounded_travel = None
        planning_escape_travel = None
        if bounded_motion:
            # The commissioned sweep owns translation geometry too. A radial
            # sector threshold otherwise vetoes a clear corridor before the
            # actual command can reach the full swept-body check below.
            source_age = self.age(getattr(self, 'lidar_measurement_time', None))
            scan_age = max(self.age(self.last_scan_time), source_age)
            if (rotation_estimate is not None and lidar_ok and
                    getattr(self, 'lidar_rotation_observed', False) and 0 <= source_age <= .2):
                trusted_shape=rotation_estimate.get('footprint_xy')
                if trusted_shape:
                    bounded_travel=footprint_translation_limits(self.lidar_rotation_points,trusted_shape,
                        rotation_estimate['center_m'],rotation_estimate['center_uncertainty_m'],body_radius,scan_age)
                    planning_escape_travel=footprint_translation_limits(self.lidar_rotation_points,trusted_shape,
                        rotation_estimate['center_m'],rotation_estimate['center_uncertainty_m'],body_radius,.2,.12) if 0<=scan_age<=.2 else None
                else:
                    bounded_travel = bounded_translation_limits(self.lidar_rotation_points,
                        rotation_estimate['center_m'], rotation_estimate['center_uncertainty_m'],
                        body_radius, scan_age)
            self.blocked = (bounded_travel is None or lidar_blocked(
                bounded_travel[0], bounded_travel[0], previous_front, 0., .001, True))
            self.rear_blocked = (bounded_travel is None or lidar_blocked(
                bounded_travel[1], bounded_travel[1], previous_rear, 0., .001, True))
            can_rev = not self.rear_blocked
        if rotation_trial and (self.last_cmd.linear.x != 0. or abs(self.last_cmd.angular.z) > .06):
            can_rotate = False
        if translation_trial:
            can_rotate = False
        relocation = None
        relocation_limits = None
        if (rotation_estimate is not None and not rotation_trial and lidar_ok and
                getattr(self, 'lidar_rotation_observed', False)):
            relocation_limits = straight_translation_limits(self.lidar_rotation_points, body_radius)
        if (rotation_estimate is not None and not rotation_trial and lidar_ok and
                getattr(self, 'lidar_rotation_observed', False) and not can_rotate):
            relocation = suggest_rotation_translation(self.lidar_rotation_points,
                rotation_estimate['center_m'], rotation_estimate['pivot_radius_m'], body_radius)
        escape = None
        source_age = self.age(getattr(self, 'lidar_measurement_time', None))
        scan_age = max(self.age(self.last_scan_time), source_age)
        if (footprint and rotation_estimate is not None and not rotation_trial and
                not translation_trial and 0 <= source_age <= .2 and 0 <= scan_age <= .2):
            fully_observed = bool(getattr(self, 'lidar_rotation_observed', False))
            cache_key = (self.lidar_measurement_time.nanoseconds, self.profile.revision,
                         rotation_estimate['required_radius_m'], rotation_estimate['pivot_radius_m'],
                         tuple(rotation_estimate['center_m']), fully_observed, can_rotate, tuple(travel))
            cache = getattr(self, '_escape_space_cache', None)
            if cache is None or cache[0] != cache_key:
                prediction = escape_space_plan(getattr(self, 'lidar_rotation_points', None),
                    rotation_radius=rotation_estimate['required_radius_m'],
                    center=rotation_estimate['center_m'], pivot_radius=rotation_estimate['pivot_radius_m'],
                    fully_observed=fully_observed, can_rotate=can_rotate,
                    forward_room=travel[0], reverse_room=travel[1])
                self._escape_space_cache = (cache_key, prediction)
            escape = dict(self._escape_space_cache[1])
            scan_age = max(self.age(self.last_scan_time), self.age(self.lidar_measurement_time))
            if not 0 <= scan_age <= .2:
                escape = None
            else:
                escape.update(geometry_revision=self.profile.revision,
                              issued_s=self.get_clock().now().nanoseconds*1e-9, scan_age_s=scan_age)
        self.motion_limits_pub.publish(String(data=json.dumps({
            'execution_escape': escape,
            'can_rotate': can_rotate,
            'bounded_motion_enabled': bounded_motion,
            'bounded_translation_limits_m': bounded_travel,
            'planning_escape_limits_m': planning_escape_travel,
            'bounded_geometry': ('trusted_footprint' if rotation_estimate and rotation_estimate.get('footprint_xy')
                                 else 'body_circle') if bounded_motion else None,
            'geometry_revision': self.profile.revision if self.profile_valid else None,
            'front_stop_m': .043-self.lidar_mount[0]+.010 if footprint else self.stop_d,
            'front_clear_m': .043-self.lidar_mount[0]+.020 if footprint else self.clear_d,
            'rear_stop_m': .077+self.lidar_mount[0]+.010 if footprint else self.rear_stop_d,
            'rear_clear_m': .077+self.lidar_mount[0]+.020 if footprint else self.rear_clear_d,
            'translation_mode': footprint,
            'rotation_radius_m': swept_radius if swept_radius is not None else body_radius,
            'body_radius_m': body_radius,
            'rotation_estimate': rotation_estimate,
            'rotation_pivot_clearance_m': pivot_margin,
            'rotation_scan_observed': bool(getattr(self, 'lidar_rotation_observed', False)),
            'rotation_trial': rotation_trial,
            'translation_trial': translation_trial,
            'rotation_recovery_m': relocation,
            'rotation_translation_limits_m': relocation_limits,
            'footprint_half_width_m': .077 if footprint else None,
            'forward_travel_m': travel[0] if footprint else None,
            'reverse_travel_m': travel[1] if footprint else None,
            'us_stop_m': self.us_stop,
            'front_m': self.lidar_distance() if lidar_ok and math.isfinite(self.lidar_distance()) else None,
            'rear_m': self.rear_distance() if lidar_ok and math.isfinite(self.rear_distance()) else None,
            'mount_source': self.lidar_yaw_source,
        }, allow_nan=False)))
        # Same value on both topics: /safety/can_reverse is a same-value alias
        # kept for the external LCD/web — one computation, like /safety/mode.
        self.rear_clear_pub.publish(Bool(data=can_rev))
        self.can_rev_pub.publish(Bool(data=can_rev))

        us_need = max(1, int(self.get_parameter('us_hits').value))
        us_generation = self.observations.generation('us')
        new_us = us_generation != self._us_hit_generation
        self._us_hit_generation = us_generation
        us_raw = self.us_distance()
        us_fresh = self.observations.fresh('us', time.monotonic())
        if us_fresh and min(us_raw, us) <= self.us_stop and new_us:
            self._us_hits += 1
            if self._us_hits >= us_need:
                if not self.us_blocked:
                    self.get_logger().warn(f'WALL us={us:.3f} m (stop {self.us_stop:.3f})')
                self.us_blocked = True
        elif (new_us and us_fresh and math.isfinite(us_raw) and math.isfinite(us)
              and us_raw > self.us_stop and us > self.us_stop):
            self._us_hits = 0
            if us_raw >= self.us_clear and us >= self.us_clear and self.us_blocked:
                self.get_logger().info(f'wall clear us={us:.3f} m')
                self.us_blocked = False

        # RGB observations have no metric distance or motor authority.

        imu_ok = self.age(self.last_imu_time) < self.timeout
        tilt = bool(self.tilt) if imu_ok else False
        pickup = bool(self.pickup) if imu_ok else False
        if tilt and not self._tilt_logged:
            self.get_logger().error('TILT/gyro — reverse then stop')
            self._tilt_logged = True
        elif not tilt:
            self._tilt_logged = False
        if pickup and not self._pickup_logged:
            self.get_logger().error('PICKUP — motors 0')
            self._pickup_logged = True
        elif not pickup:
            self._pickup_logged = False
        self.tilt_pub.publish(Bool(data=tilt))
        self.pickup_pub.publish(Bool(data=pickup))

        # IR detects floor hazards; LiDAR/US provide physical range protection.
        obstacle = self.blocked or self.us_blocked
        self.block_pub.publish(Bool(data=obstacle))

        if self._sensor_only:
            handoff_now = time.monotonic()
            translation_evidence = self._translation_policy_evidence(handoff_now)
            tracking_evidence = self._tracking_policy_evidence(handoff_now)
            failure = self.required_observation_failure()
            if ((self.get_parameter('obstacle_tracking_enabled').value and
                 tracking_evidence is None) or
                    self.get_parameter('simulation_motion_sweep_enabled').value or
                    (self.get_parameter('footprint_guard_enabled').value and
                     translation_evidence is None)):
                failure = 'candidate_evidence_handoff_required'
            self.sensor_state = GateInputs(
                profile_valid=self.profile_valid, observation_failure=failure,
                localization_ready=(not self.get_parameter('localization_required').value or
                                    lease_ready(self.localization_status, self.now().nanoseconds * 1e-9)),
                pickup=pickup, tilt=tilt, rear_blocked=self.rear_blocked,
                obstacle=obstacle, cliff=self.cliff, can_rotate=can_rotate)
            if self._policy_producer is not None:
                self.sensor_policy_published = self._policy_producer.publish(
                    self.sensor_state, now=handoff_now, translation=translation_evidence,
                    tracking=tracking_evidence, linear_limit=self.profile.max_linear)
            return

        if self.estop:
            self.record_decision(0., 0., 'estop')
            return

        failure = self.required_observation_failure()
        localized = (not self.get_parameter('localization_required').value or
                     lease_ready(self.localization_status, self.now().nanoseconds * 1e-9))
        obstacle_hold = (self.obstacle_tracking_hold()
                         if self.profile_valid and not failure and localized and not pickup else None)
        result = evaluate_command(self.last_cmd.linear.x, self.last_cmd.angular.z, GateInputs(
            profile_valid=self.profile_valid, observation_failure=failure,
            localization_ready=localized, pickup=pickup, obstacle_hold=obstacle_hold,
            command_age=self.age(self.last_cmd_time), rotation_trial=rotation_trial,
            translation_trial=translation_trial, tilt=tilt, rear_blocked=self.rear_blocked,
            obstacle=obstacle, cliff=self.cliff, can_rotate=can_rotate,
            bounded_motion=bounded_motion, legacy_tilt_recovery=True))
        if result.reason not in ('allow', 'motion_limited'):
            self.halt_with_reason(result.reason)
            if result.discard:
                self.last_cmd = Twist()
                self.last_cmd_time = None
            return
        cmd = Twist()
        cmd.linear.x = result.linear
        cmd.angular.z = result.angular
        if abs(cmd.linear.x) >= 0.004:
            self._auto_linear_sign(us, lidar_d, self.last_cmd.linear.x, self.last_cmd.angular.z)
        else:
            self._sign_t = None
            self._sign_front0 = None
            self._sign_hits = 0
        # Pin one lease time and one prepared candidate through sweep/publication.
        lease_now = time.monotonic()
        try:
            prepared = prepare_command(cmd.linear.x, cmd.angular.z,
                requested_angular=self.last_cmd.angular.z,
                linear_gains=self.calibration_lease.gains(lease_now),
                angular_gains=self.calibration_lease.angular_gains(lease_now),
                profile_caps=(self.profile.max_linear, self.profile.max_angular),
                limited_caps=self.calibration_lease.motion_limits(lease_now), linear_sign=self.cmd_linear_sign)
        except ValueError:
            self.halt_with_reason('invalid_actuation')
            return
        cmd.linear.x, cmd.angular.z = prepared.linear, prepared.angular
        if bounded_motion and (cmd.linear.x or cmd.angular.z):
            source_age = self.age(getattr(self, 'lidar_measurement_time', None))
            scan_age = max(self.age(self.last_scan_time), source_age)
            sweep = command_sweep_clearance(points=getattr(self, 'lidar_rotation_points', None), estimate=rotation_estimate,
                body_radius=body_radius, v=cmd.linear.x, w=cmd.angular.z, source_age=source_age,
                scan_age=scan_age, lidar_fresh=lidar_ok,
                scan_complete=getattr(self, 'lidar_rotation_observed', False),
                can_rotate=can_rotate, pivot_margin=pivot_margin)
            if sweep is None or sweep <= 0:
                self.halt_with_reason('bounded_sweep_unavailable' if sweep is None else 'bounded_sweep_blocked')
                return
        self.record_decision(cmd.linear.x, cmd.angular.z,
                             'allow' if (cmd.linear.x == self.last_cmd.linear.x and
                                         cmd.angular.z == self.last_cmd.angular.z) else 'motion_limited')
        cmd.linear.x = prepared.motor_linear
        self.pub.publish(cmd)

    def on_drive_ready(self, msg):
        self.drive_ready = bool(msg.data)

    def _translation_policy_evidence(self, now):
        """Freeze the current LiDAR footprint result for candidate re-checking."""
        if not self._sensor_only or not self.get_parameter('footprint_guard_enabled').value:
            return None
        row = self.observations.rows.get('lidar')
        travel = getattr(self, 'translation_clearance', None)
        mount = getattr(self, 'lidar_mount', None)
        ranges = (self.lidar_front, self.lidar_rear, self.lidar_left,
                  self.lidar_right, self.lidar_rear_left, self.lidar_rear_right)
        if row is None or row.received is None or not self.observations.fresh('lidar', now):
            return None
        if not translation_footprint_eligible(
                0., 0., enabled=True, lidar_fresh=True,
                scan_age=now - row.received, source_age=row.source_age,
                mount=mount, travel=travel, radius=self.robot_r,
                ranges=ranges):
            return None
        try:
            gains = self.calibration_lease.gains(now)
        except (TypeError, ValueError):
            return None
        return TranslationEvidence(
            scan_received_at=row.received,
            scan_source_at=row.received - row.source_age,
            enabled=True,
            lidar_fresh=True,
            mount=tuple(mount),
            travel=tuple(travel),
            radius=self.robot_r,
            ranges=tuple(ranges),
            radial_front=bool(self.blocked),
            radial_rear=bool(self.rear_blocked),
            previous_front=bool(getattr(self, '_policy_previous_front', False)),
            previous_rear=bool(getattr(self, '_policy_previous_rear', False)),
            linear_gains=tuple(gains),
        )

    def _tracking_policy_evidence(self, now):
        """Freeze camera/tracks/odom at one receive time for CORE."""
        if not self._sensor_only or not self.get_parameter('obstacle_tracking_enabled').value:
            return None
        tracks = self.obstacle_observation
        camera = self.camera_observation
        if (not isinstance(tracks, dict) or tracks.get('frame') != 'odom' or
                not isinstance(camera, dict)):
            return None
        try:
            ros_now = self.now().nanoseconds * 1e-9
            transform = self.lidar_tf.lookup_transform('odom', 'base_link', Time())
            stamp = transform.header.stamp.sec + transform.header.stamp.nanosec * 1e-9
            t, q = transform.transform.translation, transform.transform.rotation
            pose = planar_pose(t.x, t.y, (q.x, q.y, q.z, q.w))
            if pose is None or not math.isfinite(ros_now) or ros_now <= 0.:
                return None
            return TrackedEvidence.capture(
                tracks, camera, pose, stamp, source_now=ros_now,
                received_at=now, radius=self.robot_r,
                margin=float(self.get_parameter('obstacle_tracking_margin').value))
        except (AttributeError, KeyError, TypeError, ValueError, TransformException):
            return None

    def on_localization(self, msg):
        try:
            self.localization_status = json.loads(msg.data)
        except (ValueError, TypeError):
            self.localization_status = None
        if (self.get_parameter('localization_required').value and
                not lease_ready(self.localization_status, self.now().nanoseconds * 1e-9)):
            # Loss and recovery callbacks can both precede the next timer tick.
            self.last_cmd = Twist()
            self.last_cmd_time = None
            if not self._sensor_only:
                self._publish_zero()

    def bind_policy_handoff(self, policy, required, applied_revision=None):
        """Bind the sensor-only node to CORE's in-process policy consumer.

        Binding is explicit and requires the revision computed from the current
        ROS parameter readback. It never creates a command publisher.
        """
        if not self._sensor_only:
            raise ValueError('Policy handoff requires sensor_only mode')
        if applied_revision is None:
            self._refresh_distances()
            self.refresh_profile()
            applied_revision = self.profile.revision
        if applied_revision != self.profile.revision:
            raise ValueError('Applied revision does not match the sensor profile')
        self._policy_producer = ControlPolicyProducer(
            policy, self.observations, required, applied_revision)
        self.sensor_policy_published = False
        return applied_revision

    def corrected_drive_speed(self, speed):
        # Atomic lease binds both gains to the current geometry and expiry.
        if abs(speed) <= .014 and abs(self.last_cmd.angular.z) < 1e-4:
            gains = self.calibration_lease.gains(time.monotonic())
            return speed * gains[0 if speed >= 0 else 1]
        return speed

    def on_drive_scale(self, msg):
        values = list(msg.data)
        if len(values) == 2 and all(math.isfinite(v) and .75 <= v <= 1.25 for v in values):
            self.drive_scales = values
            self.drive_scale_time = time.monotonic()
        else:
            self.drive_scales = [1., 1.]
            self.drive_scale_time = 0.


def main():
    rclpy.init()
    node = SafetyNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop_motors()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
