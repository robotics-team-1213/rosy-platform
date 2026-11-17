"""ROS-free helper mixin for SafetyNode motion limits and policy handoff."""

import json
import math
import os
import time

from ..control.command_gate import GateInputs
from ..control.escape_space import escape_space_plan
from ..control.floor_evidence import floor_observed
from ..control.footprint_sweep import footprint_translation_limits
from ..control.lidar_guard import (
    ForwardEvidence,
    TranslationEvidence,
    lidar_blocked,
    lidar_can_rotate,
    translation_footprint_eligible,
)
from ..control.motion_sweep import bounded_translation_limits
from ..control.obstacle_risk import TrackedEvidence
from ..control.policy_handoff import ControlPolicyProducer
from ..control.rotation_clearance import rotation_clearance_allowed
from ..control.rotation_envelope import (
    pivot_clearance,
    straight_translation_limits,
    suggest_rotation_translation,
)
from ..sensing.body import BODY, rotation_radius, use_radius
from ..sensing.localization import lease_ready
from ..sensing.pose import planar_pose


class SafetyNodeHelpersMixin:
    """Motion-limits calculation, runtime state setup, and sensor-only policy helpers."""

    def _init_runtime_state(self):
        self.last_cmd = self.zero_twist()
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
        self.cmd_linear_sign = 1.0 if self.cmd_linear_sign >= 0.0 else -1.0
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

    def _compute_motion_limits(self, lidar_ok, lidar_d, rear_d):
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
        footprint = footprint and not self._sensor_only
        if footprint:
            self.blocked = lidar_blocked(travel[0], travel[0], previous_front, 0., .010, True)
            self.rear_blocked = lidar_blocked(travel[1], travel[1], previous_rear, 0., .010, True)
            can_rev = not self.rear_blocked
        body_radius = rotation_radius(self.robot_r)
        flat = self.get_parameter('rotation_footprint_xy').value or []
        rotation_estimate = self.calibration_lease.rotation_envelope(
            time.monotonic(), body_radius, list(zip(flat[::2], flat[1::2])))
        swept_radius = rotation_estimate['required_radius_m'] if rotation_estimate else None
        if swept_radius is None:
            fallback = self.calibration_lease.fallback_rotation_radius()
            swept_radius = None if fallback is None else max(fallback, body_radius)
        can_rotate = lidar_can_rotate(
            (self.lidar_front, self.lidar_rear, self.lidar_left, self.lidar_right,
             self.lidar_rear_left, self.lidar_rear_right),
            body_radius,
            lidar_ok, getattr(self, 'lidar_rotation_clearance', None), sweep_radius=swept_radius)
        pivot_margin = None
        if rotation_estimate is not None:
            pivot_margin = pivot_clearance(
                getattr(self, 'lidar_rotation_points', None),
                rotation_estimate['center_m'], rotation_estimate['pivot_radius_m'])
            can_rotate = rotation_clearance_allowed(
                can_rotate, getattr(self, 'lidar_rotation_observed', False), lidar_ok,
                pivot_margin, (self.lidar_front, self.lidar_rear, self.lidar_left,
                               self.lidar_right, self.lidar_rear_left, self.lidar_rear_right))
        elif self.calibration_lease.rotation_estimate_required(time.monotonic()):
            can_rotate = False
        if getattr(self, 'lidar_rotation_reason', 'no scan') is not None:
            can_rotate = False
        rotation_trial = self.calibration_lease.rotation_trial_live(time.monotonic())
        translation_trial = self.calibration_lease.translation_trial_live(time.monotonic())
        bounded_motion = bool(
            not self._sensor_only
            and self.get_parameter('simulation_motion_sweep_enabled').value
            and self.get_parameter('use_sim_time').value
            and os.environ.get('ROS_DOMAIN_ID') == '227'
            and os.environ.get('GZ_PARTITION') == 'pinky_calmap227'
            and not rotation_trial
            and (rotation_estimate is not None
                 or self.calibration_lease.rotation_estimate_required(time.monotonic())))
        bounded_travel = None
        planning_escape_travel = None
        if bounded_motion:
            source_age = self.age(getattr(self, 'lidar_measurement_time', None))
            scan_age = max(self.age(self.last_scan_time), source_age)
            if (rotation_estimate is not None and lidar_ok
                    and getattr(self, 'lidar_rotation_observed', False) and 0 <= source_age <= .2):
                trusted_shape = rotation_estimate.get('footprint_xy')
                if trusted_shape:
                    bounded_travel = footprint_translation_limits(
                        self.lidar_rotation_points, trusted_shape,
                        rotation_estimate['center_m'], rotation_estimate['center_uncertainty_m'],
                        body_radius, scan_age)
                    planning_escape_travel = (
                        footprint_translation_limits(
                            self.lidar_rotation_points, trusted_shape,
                            rotation_estimate['center_m'], rotation_estimate['center_uncertainty_m'],
                            body_radius, .2, .12)
                        if 0 <= scan_age <= .2 else None)
                else:
                    bounded_travel = bounded_translation_limits(
                        self.lidar_rotation_points,
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
        forward_nominal = (
            rotation_estimate is None and swept_radius is None
            and body_radius == BODY.rotation_radius_m
            and not rotation_trial and not translation_trial
            and not self.calibration_lease.rotation_estimate_required(time.monotonic()))
        relocation = None
        relocation_limits = None
        if (rotation_estimate is not None and not rotation_trial and lidar_ok
                and getattr(self, 'lidar_rotation_observed', False)):
            relocation_limits = straight_translation_limits(self.lidar_rotation_points, body_radius)
        if (rotation_estimate is not None and not rotation_trial and lidar_ok
                and getattr(self, 'lidar_rotation_observed', False) and not can_rotate):
            relocation = suggest_rotation_translation(
                self.lidar_rotation_points,
                rotation_estimate['center_m'], rotation_estimate['pivot_radius_m'], body_radius)
        escape = self._compute_escape_space(
            footprint, rotation_estimate, rotation_trial, translation_trial, can_rotate, travel)
        payload = json.dumps({
            'execution_escape': escape,
            'can_rotate': can_rotate,
            'bounded_motion_enabled': bounded_motion,
            'bounded_translation_limits_m': bounded_travel,
            'planning_escape_limits_m': planning_escape_travel,
            'bounded_geometry': (
                ('trusted_footprint' if rotation_estimate and rotation_estimate.get('footprint_xy')
                 else 'body_circle') if bounded_motion else None),
            'geometry_revision': self.profile.revision if self.profile_valid else None,
            'front_stop_m': BODY.front_x_m - self.lidar_mount[0] + .010 if footprint else self.stop_d,
            'front_clear_m': BODY.front_x_m - self.lidar_mount[0] + .020 if footprint else self.clear_d,
            'rear_stop_m': -BODY.rear_x_m + self.lidar_mount[0] + .010 if footprint else self.rear_stop_d,
            'rear_clear_m': -BODY.rear_x_m + self.lidar_mount[0] + .020 if footprint else self.rear_clear_d,
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
            'footprint_half_width_m': BODY.half_width_m + BODY.sweep_pad_m if footprint else None,
            'forward_travel_m': travel[0] if footprint else None,
            'reverse_travel_m': travel[1] if footprint else None,
            'us_stop_m': self.us_stop,
            'front_m': self.lidar_distance() if lidar_ok and math.isfinite(self.lidar_distance()) else None,
            'rear_m': self.rear_distance() if lidar_ok and math.isfinite(self.rear_distance()) else None,
            'mount_source': self.lidar_yaw_source,
        }, allow_nan=False)
        return (can_rev, can_rotate, forward_nominal, bounded_motion,
                rotation_trial, translation_trial, rotation_estimate,
                body_radius, pivot_margin, payload)

    def _compute_escape_space(self, footprint, rotation_estimate, rotation_trial,
                              translation_trial, can_rotate, travel):
        source_age = self.age(getattr(self, 'lidar_measurement_time', None))
        scan_age = max(self.age(self.last_scan_time), source_age)
        if not (footprint and rotation_estimate is not None and not rotation_trial
                and not translation_trial and 0 <= source_age <= .2 and 0 <= scan_age <= .2):
            return None
        fully_observed = bool(getattr(self, 'lidar_rotation_observed', False))
        cache_key = (
            self.lidar_measurement_time.nanoseconds, self.profile.revision,
            rotation_estimate['required_radius_m'], rotation_estimate['pivot_radius_m'],
            tuple(rotation_estimate['center_m']), fully_observed, can_rotate, tuple(travel))
        cache = getattr(self, '_escape_space_cache', None)
        if cache is None or cache[0] != cache_key:
            prediction = escape_space_plan(
                getattr(self, 'lidar_rotation_points', None),
                rotation_radius=rotation_estimate['required_radius_m'],
                center=rotation_estimate['center_m'],
                pivot_radius=rotation_estimate['pivot_radius_m'],
                fully_observed=fully_observed, can_rotate=can_rotate,
                forward_room=travel[0], reverse_room=travel[1])
            self._escape_space_cache = (cache_key, prediction)
        escape = dict(self._escape_space_cache[1])
        scan_age = max(self.age(self.last_scan_time), self.age(self.lidar_measurement_time))
        if not 0 <= scan_age <= .2:
            return None
        escape.update(
            geometry_revision=self.profile.revision,
            issued_s=self.get_clock().now().nanoseconds * 1e-9,
            scan_age_s=scan_age)
        return escape

    def _update_us_blocked(self, us):
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

    def _evaluate_imu_hazards(self):
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
        return tilt, pickup

    def _tick_sensor_only(self, *, pickup, tilt, obstacle, can_rotate, forward_nominal):
        handoff_now = time.monotonic()
        translation_evidence = self._translation_policy_evidence(handoff_now)
        tracking_evidence = self._tracking_policy_evidence(handoff_now)
        forward_evidence = self._forward_policy_evidence(handoff_now) if forward_nominal else None
        failure = self.required_observation_failure()
        if ((self.get_parameter('obstacle_tracking_enabled').value and tracking_evidence is None)
                or self.get_parameter('simulation_motion_sweep_enabled').value
                or (self.get_parameter('footprint_guard_enabled').value
                    and translation_evidence is None)):
            failure = 'candidate_evidence_handoff_required'
        self.sensor_state = GateInputs(
            profile_valid=self.profile_valid, observation_failure=failure,
            localization_ready=(
                not self.get_parameter('localization_required').value
                or lease_ready(self.localization_status, self.now().nanoseconds * 1e-9)),
            pickup=pickup, tilt=tilt, rear_blocked=self.rear_blocked,
            obstacle=obstacle, cliff=self.cliff, can_rotate=can_rotate,
            floor_observed=floor_observed(
                self.ir_raw, fresh=self.observations.fresh('ir', handoff_now),
                enabled=self.get_parameter('cliff_enable').value,
                cliff=self.cliff, tilt=tilt, pickup=pickup))
        if self._policy_producer is not None:
            self.sensor_policy_published = self._policy_producer.publish(
                self.sensor_state, now=handoff_now, translation=translation_evidence,
                tracking=tracking_evidence, linear_limit=self.profile.max_linear,
                forward=forward_evidence)

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

    def _forward_policy_evidence(self, now):
        """Freeze the scan the turn decision used, for the forward-arc stopping sweep."""
        row = self.observations.rows.get('lidar')
        points = getattr(self, 'lidar_rotation_points', None)
        if (not self._sensor_only or points is None or row is None or row.received is None
                or not self.observations.fresh('lidar', now)):
            return None
        return ForwardEvidence(
            scan_received_at=row.received,
            scan_source_at=row.received - row.source_age,
            points=tuple(points),
            observed=getattr(self, 'lidar_rotation_observed', False) is True,
            body=BODY,
            limits=(self.profile.max_linear, self.profile.max_angular),
            front_blocked_other=bool(self.us_blocked),
        )

    def _tracking_policy_evidence(self, now):
        """Freeze camera/tracks/odom at one receive time for CORE."""
        if not self._sensor_only or not self.get_parameter('obstacle_tracking_enabled').value:
            return None
        tracks = self.obstacle_observation
        camera = self.camera_observation
        if (not isinstance(tracks, dict) or tracks.get('frame') != 'odom'
                or not isinstance(camera, dict)):
            return None
        try:
            ros_now = self.now().nanoseconds * 1e-9
            transform = self.lookup_odom_base()
            if transform is None:
                return None
            stamp = transform.header.stamp.sec + transform.header.stamp.nanosec * 1e-9
            t, q = transform.transform.translation, transform.transform.rotation
            pose = planar_pose(t.x, t.y, (q.x, q.y, q.z, q.w))
            if pose is None or not math.isfinite(ros_now) or ros_now <= 0.:
                return None
            return TrackedEvidence.capture(
                tracks, camera, pose, stamp, source_now=ros_now,
                received_at=now, radius=self.robot_r,
                margin=float(self.get_parameter('obstacle_tracking_margin').value))
        except (AttributeError, KeyError, TypeError, ValueError):
            return None

    def on_localization(self, msg):
        try:
            self.localization_status = json.loads(msg.data)
        except (ValueError, TypeError):
            self.localization_status = None
        if (self.get_parameter('localization_required').value
                and not lease_ready(self.localization_status, self.now().nanoseconds * 1e-9)):
            self.last_cmd = self.zero_twist()
            self.last_cmd_time = None
            if not self._sensor_only:
                self._publish_zero()

    def bind_policy_handoff(self, policy, required, applied_revision=None):
        """Bind the sensor-only node to CORE's in-process policy consumer."""
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
