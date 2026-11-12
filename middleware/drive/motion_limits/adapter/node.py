#!/usr/bin/env python3
"""Safety ROS node. Subjects: bumper, hazard, gate."""
import json  # noqa: F401 — re-exported
import math
import os  # noqa: F401 — re-exported
import time

import rclpy
from geometry_msgs.msg import Twist
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time  # noqa: F401 — re-exported
from sensor_msgs.msg import Imu, LaserScan, Range
from std_msgs.msg import Bool, Float32, Float32MultiArray, String, UInt16MultiArray
from tf2_ros import TransformException, TransformListener  # noqa: F401 — re-exported

from .. import executor_choice
from ..control.actuation import prepare_command
from ..control.command_gate import GateInputs, evaluate_command
from ..control.escape_space import escape_space_plan  # noqa: F401 — re-exported
from ..control.floor_evidence import floor_observed  # noqa: F401 — re-exported
from ..control.footprint_sweep import footprint_translation_limits  # noqa: F401 — re-exported
from ..control.lidar_guard import (  # noqa: F401 — re-exported
    ForwardEvidence,
    TranslationEvidence,
    lidar_blocked,
    lidar_can_rotate,
    translation_footprint_eligible,
)
from ..control.motion_sweep import (  # noqa: F401 — re-exported
    bounded_translation_limits,
    command_sweep_clearance,
)
from ..control.obstacle_risk import TrackedEvidence  # noqa: F401 — re-exported
from ..control.policy_handoff import ControlPolicyProducer  # noqa: F401 — re-exported
from ..control.rotation_clearance import rotation_clearance_allowed  # noqa: F401 — re-exported
from ..control.rotation_envelope import (  # noqa: F401 — re-exported
    pivot_clearance,
    straight_translation_limits,
    suggest_rotation_translation,
)
from ..sensing.body import BODY, URDF_RADIUS, rotation_radius, use_radius  # noqa: F401 — re-exported
from ..sensing.filt import IrMedian, MedianLp
from ..sensing.lidar import NOSE_YAW, enable_simulation_scans
from ..sensing.localization import lease_ready
from ..sensing.pose import planar_pose  # noqa: F401 — re-exported
from ..tf_buffer import RobotTransformBuffer
from .bumper import Bumper
from .evidence import Evidence
from .gate import Gate
from .hazard import Hazard
from .node_helpers import SafetyNodeHelpersMixin
from .obstacles import Obstacles
from .ros_edges import RosEdges
from .scale import Scale


class SafetyNode(SafetyNodeHelpersMixin, RosEdges, Node, Bumper, Hazard, Gate, Scale, Evidence, Obstacles):

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
        super().__init__('safety_node', cli_args=['--ros-args', '-r', '__node:=safety_node'] if sensor_only and namespace is not None else None, **node_kwargs)
        self.declare_parameter('cmd_in', 'cmd_vel_raw')
        self.declare_parameter('cmd_out', 'cmd_vel')
        self.declare_parameter('start_estopped', True)
        self.declare_parameter('localization_required', False)
        self.localization_status = None
        self.create_subscription(String, 'localization/status', self.on_localization, 10)
        self.declare_parameter('footprint_guard_enabled', False)
        self.declare_parameter('simulation_motion_sweep_enabled', False)
        self.declare_parameter('accept_simulation_scans', False)
        if self.get_parameter('accept_simulation_scans').value is True:
            if self.get_parameter('use_sim_time').value is not True:
                raise ValueError('accept_simulation_scans needs use_sim_time')
            enable_simulation_scans(True)
        self.init_obstacles()
        self.create_subscription(String, 'obstacles/tracks', self.on_obstacle_tracks, 10)  # D-171: node edge
        self.create_subscription(String, 'camera/observation', self.on_camera_observation, 10)
        self.declare_parameter('scan_topic', 'scan')
        self.declare_parameter('us_topic', 'us_sensor/range')
        self.declare_parameter('ir_topic', 'ir_sensor/range')
        self.declare_parameter('stop_distance', 0.0)
        self.declare_parameter('clear_distance', 0.0)
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
            for k in ('front', 'rear', 'us', 'left', 'right', 'rear_left', 'rear_right')
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
        self._init_runtime_state()
        if sensor_only:
            self.get_logger().info('sensor-only mode: no command or legacy calibration authority')
        elif self.estop:
            self.engage_estop('startup')
        else:
            self.estop_pub.publish(Bool(data=False))

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
        lidar_d = self._filt('front', self.lidar_distance())
        us = self._filt('us', self.us_distance())
        left = self._filt('left', self.lidar_left)
        right = self._filt('right', self.lidar_right)
        self._scale_update(left, right)
        rleft = self._filt('rear_left', self.lidar_rear_left)
        rright = self._filt('rear_right', self.lidar_rear_right)
        self.range_pub.publish(Float32(data=float(lidar_d if math.isfinite(lidar_d) else -1.0)))
        self.us_pub.publish(Float32(data=float(us if math.isfinite(us) else -1.0)))
        def _m(v):
            return float(v if math.isfinite(v) else -1.0)
        self.publish_heard(self.left_pub, Float32(data=_m(left)))
        self.publish_heard(self.right_pub, Float32(data=_m(right)))
        self.publish_heard(self.rear_left_pub, Float32(data=_m(rleft)))
        self.publish_heard(self.rear_right_pub, Float32(data=_m(rright)))
        self.publish_heard(self.open_pub, Float32(data=_m(self.open_range)))
        self.publish_heard(self.open_yaw_pub, Float32(data=float(self.open_yaw)))
        self.publish_heard(self.frontier_yaw_pub, Float32(data=float(self.frontier_yaw)))
        self.publish_heard(self.frontier_pub, Float32(data=_m(self.frontier_range)))
        self.publish_heard(self.route_yaw_pub, Float32(data=float(self.route_yaw)))
        self.publish_heard(self.route_pub, Float32(data=_m(self.route_range)))
        self.publish_heard(self.exit_yaw_pub, Float32(data=float(self.exit_yaw)))
        self.publish_heard(self.exit_pub, Float32(data=_m(self.exit_range)))
        self.publish_heard(self.radius_pub, Float32(data=float(self.robot_r)))

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
        (can_rev, can_rotate, forward_nominal, bounded_motion,
         rotation_trial, translation_trial, rotation_estimate,
         body_radius, pivot_margin, motion_limits_json) = self._compute_motion_limits(
            lidar_ok, lidar_d, rear_d)
        self.motion_limits_pub.publish(String(data=motion_limits_json))
        self.rear_clear_pub.publish(Bool(data=can_rev))
        self.can_rev_pub.publish(Bool(data=can_rev))

        self._update_us_blocked(us)
        tilt, pickup = self._evaluate_imu_hazards()
        self.tilt_pub.publish(Bool(data=tilt))
        self.pickup_pub.publish(Bool(data=pickup))

        obstacle = self.blocked or self.us_blocked
        self.block_pub.publish(Bool(data=obstacle))

        if self._sensor_only:
            self._tick_sensor_only(
                pickup=pickup, tilt=tilt, obstacle=obstacle,
                can_rotate=can_rotate, forward_nominal=forward_nominal)
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


def main():
    rclpy.init()
    node = SafetyNode()
    try:
        executor_choice.spin(node, rclpy)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop_motors()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
