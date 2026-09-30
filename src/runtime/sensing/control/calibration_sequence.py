"""Subject: the calibration state machine — motion authorization, precision
holds, phase completion and persistence for the startup calibration node, plus
the calib_node floor/cliff/lidar pure helpers.

ROS-free mixin (D-171): trial commands and status publication go through the
node's ``drive_trial``/``zero``/``stop_wander``/``request_command``/``publish``
edges, so every decision here is visible to host pytest (C1 —
docs/plans/2026-09-22-control-package-split-design.md). Keep ``import time``
and ``time.monotonic()`` as written — the sim rig swaps this module's ``time``.
"""
import json
import math
import os
import socket
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from .control.calibration import (MOTION_LIMIT, MOTION_SECONDS, MOTION_SPEED,
                                  motion_evidence, motion_result)
from .control.calibration_certificate import make_certificate, validate_certificate
from .control.calibration_clearance import motion_clearance, preflight_clearance_wait
from .control.calibration_tf import map_motion_continuous
from .control.configured_operation import configured_status
from .control.navigation_calibration import environment_profile
from .control.round_trip import RoundTrip
from .control.sensor_tiers import partial_plan
from .control.sensing_only import partial_sensing_report


# --- calib_node pure helpers (floor/cliff IR, lidar yaw) --------------------


def yaw_from_quat(q) -> float:
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


def ir_valid(sample):
    return tuple(int(v) for v in sample if 50 < int(v) < 4000)


def looks_floor(sample) -> bool:
    v = ir_valid(sample)
    return bool(v) and len(v) >= 2 and min(v) >= 1500


def looks_cliff(sample, floor_m) -> bool:
    v = ir_valid(sample)
    if not v:
        return False
    return min(v) < min(1100.0, 0.40 * float(floor_m))


def _copy_scan(msg):
    return (
        float(msg.angle_min),
        float(msg.angle_increment),
        [float(r) for r in msg.ranges],
        float(msg.range_min),
        float(msg.range_max),
    )


def approach_heading(s0, s1):
    if s0 is None or s1 is None:
        return None
    amin, ainc, r0, rmin, rmax = s0
    _, _, r1, _, _ = s1
    n = min(len(r0), len(r1))
    sx = sy = wsum = 0.0
    hi = min(rmax, 6.0)
    for i in range(n):
        v0, v1 = r0[i], r1[i]
        if not (math.isfinite(v0) and math.isfinite(v1)):
            continue
        if not (rmin < v0 < hi and rmin < v1 < hi):
            continue
        dr = v1 - v0
        if dr >= -0.006:
            continue
        w = -dr
        ang = amin + i * ainc
        sx += w * math.cos(ang)
        sy += w * math.sin(ang)
        wsum += w
    if wsum < 0.012:
        return None
    return math.atan2(sy, sx)


def snap_lidar_yaw(ang: float) -> float:
    a = math.atan2(math.sin(ang), math.cos(ang))
    if abs(a) < math.radians(40.0):
        return 0.0
    if abs(abs(a) - math.pi) < math.radians(40.0):
        return math.pi
    return a


# --- startup calibration node mixin -----------------------------------------


class CalibrationSequence:
    def snapshot(self):
        return {name: self.baseline.latest(name) for name in ('odom', 'lidar', 'us', 'map_tf')}

    def runtime_health(self, now):
        """Current availability, never stationary motion/variance criteria."""
        result = {}
        for name, rows in self.baseline.samples.items():
            fresh = bool(rows) and 0 <= now-rows[-1][0] <= (5. if name == 'map' else 1.)
            valid = bool(rows) and rows[-1][2]
            advisory_echo = name == 'us' and not self.get_parameter('calibration_require_us_agreement').value
            eligible = name == 'camera' or (fresh and (valid or (advisory_echo and self.us_source_valid)))
            detail = 'Live sensor data valid; stationary limits do not apply during driving'
            if not fresh:
                detail = 'Waiting for fresh sensor data; saved calibration retained'
            elif not valid:
                detail = ('Ultrasonic source timestamp invalid; saved calibration retained'
                          if advisory_echo and not self.us_source_valid else
                          'Ultrasonic echo unavailable; LiDAR clearance remains authoritative'
                          if advisory_echo else 'Invalid sensor data; saved calibration retained')
            result[name] = dict(ok=fresh and valid, eligible=eligible,
                status='ok' if fresh and valid else 'advisory' if eligible else 'stale' if not fresh else 'invalid',
                samples=len(rows), detail=detail)
            if name == 'map_tf':
                result[name]['transform'] = self.map_tf_diagnostic
        return result

    def stationary_report(self, now):
        result = self.baseline.report(now)
        result['camera']['eligible'] = True  # RGB quality is advisory; safety owns hazard inputs.
        if not self.get_parameter('calibration_require_us_agreement').value:
            result['us'] = self.runtime_health(now)['us']
        return result

    def sensor_failure(self, now):
        failures = []
        for name, rows in self.baseline.samples.items():
            if not rows or not rows[-1][2] or not 0 <= now-rows[-1][0] <= (5. if name == 'map' else 1.):
                detail = 'no sample' if not rows else f'valid={rows[-1][2]}, age={now-rows[-1][0]:.3f}s'
                if name == 'lidar':
                    detail += ', wall=' + str(self.wall_tracker.diagnostic)
                if name == 'map_tf':
                    detail += ', transform=' + str(self.map_tf_diagnostic)
                failures.append(name + ': ' + detail)
        return 'Sensor data became stale or invalid: ' + '; '.join(failures)

    def precision_sensors_fresh(self, now):
        return all(item['eligible'] for item in self.runtime_health(now).values())

    def safe_motion(self, now):
        reason = self.trial_gate_reason(now)
        if reason:
            return reason
        stamp, limits = self.safety_limits
        if not 0 <= now-stamp <= .75:
            self.motion_clearance = {'reason': 'Missing fresh safety motion limits', 'target_m': None}
            return self.motion_clearance['reason']
        limits = dict(limits)
        lidar_raw = self.raw_ranges.get('lidar', (0., 0., False))
        if isinstance(limits.get('front_m'), (int, float)) and lidar_raw[2]:
            limits['front_m'] = min(limits['front_m'], lidar_raw[1])
        if (limits.get('translation_mode') is True and lidar_raw[2] and
                isinstance(limits.get('front_stop_m'), (int, float)) and
                lidar_raw[1] <= limits['front_stop_m']):
            self.motion_clearance = {'reason': 'Raw nose range inside chassis stop clearance', 'target_m': None}
            return self.motion_clearance['reason']
        us_raw = self.raw_ranges.get('us', (0., 0., False))
        optional_us = not self.get_parameter('calibration_require_us_agreement').value
        limits['us_optional'] = optional_us
        limits['us_m'] = us_raw[1] if us_raw[2] else None
        forward = 0.
        if self.motion_start is not None:
            current = self.snapshot()
            if not self.precision_sensors_fresh(now) or any(value is None for key, value in current.items() if key != 'us' or not optional_us):
                return self.sensor_failure(now)
            forward = motion_evidence(self.motion_start[1], current)['lidar_delta_m']
        round_trip = bool(self.get_parameter('calibration_round_trip').value)
        requested = float(self.get_parameter('calibration_distance_m').value) if round_trip else MOTION_LIMIT
        target = self.selected_target
        preflight = self.phase == 'validating_motion' and self.motion_start is None and target is not None
        if preflight:
            # Footprint eligibility may change while waiting for wander's stop.
            # Refit only downward before the origin; never resize a moving trial.
            requested = min(requested, target)
            target = None
        self.motion_clearance = motion_clearance(limits, requested,
            target=target, forward=forward, round_trip=round_trip,
            selection_margin_m=.003)
        if self.estop is not False:
            return 'Emergency stop must be explicitly released'
        if self.get_parameter('calibration_round_trip').value:
            stamp, clear = self.rear_clear
            if not clear or now - stamp > .75:
                return 'Round-trip requires fresh rear clearance for safe return'
        if not self.precision_sensors_fresh(now):
            return self.sensor_failure(now)
        for name in ('lidar', 'us'):
            stamp, distance, valid = self.raw_ranges.get(name, (0., 0., False))
            if name == 'us' and optional_us and self.us_source_valid and 0 <= now-stamp <= 1.:
                continue
            if not valid or not 0 <= now - stamp <= 1. or distance <= 0.:
                return 'Raw range unsafe or stale; filtered values cannot authorize motion'
        required = ('/safety/blocked', '/safety/cliff', '/safety/tilt', '/safety/pickup')
        if any(key not in self.hazards or now - self.hazards[key][0] > .75
               or self.hazards[key][1] for key in required):
            return 'Safety hazard or missing fresh safety state'
        if self.motion_clearance['reason']:
            return self.motion_clearance['reason']
        if preflight:
            self.selected_target = self.motion_clearance['target_m']
        return None

    def pause_precision(self, now):
        # Transport gaps are not permission to coast or reuse an old pose.
        # Hold zero with the same trial origin and bounded overall deadline.
        if self.estop is not False or self.motion_start is None or self.round_trip is None:
            return False
        health = self.runtime_health(now)
        waiting_map = (not health['map_tf']['eligible'] and self.map_tf_diagnostic.get('reason') in
                       ('stale','ExtrapolationException','LookupException','ConnectivityException'))
        waiting_wall = (not health['lidar']['eligible'] and self.wall_tracker.diagnostic.get('reason') in
                        ('Tracked wall missing or ambiguous', 'Waiting for three associated scans'))
        waiting_odom = (not health['lidar']['eligible'] and
                        self.wall_tracker.diagnostic.get('reason') == 'Waiting for fresh odometry')
        waiting = (({'map_tf'} if waiting_map else set()) | ({'lidar'} if waiting_wall else set()) |
                   ({'lidar', 'odom'} if waiting_odom else set()))
        if not waiting:
            return False
        for name, item in health.items():
            if name not in waiting and not item['eligible']:
                return False
        odom_rows = self.baseline.samples['odom']
        if (not odom_rows or not odom_rows[-1][2] or now < odom_rows[-1][0] or
                (not waiting_odom and now-odom_rows[-1][0] > .2)):
            return False
        stamp, limits = self.safety_limits
        if not 0 <= now-stamp <= .75:
            return False
        for name, stop_key in (('lidar', 'front_stop_m'), ('us', 'us_stop_m')):
            stamp, distance, valid = self.raw_ranges.get(name, (0., 0., False))
            if (name == 'us' and not valid and self.us_source_valid and 0 <= now-stamp <= .2
                    and not self.get_parameter('calibration_require_us_agreement').value):
                continue
            stop = limits.get(stop_key)
            if not valid or not 0 <= now-stamp <= .2 or not isinstance(stop, (float, int)) or distance <= stop:
                return False
        if any(key not in self.hazards or not 0 <= now-self.hazards[key][0] <= .75 or self.hazards[key][1]
               for key in ('/safety/blocked', '/safety/cliff', '/safety/tilt', '/safety/pickup')):
            return False
        if self.precision_pause_started is None:
            self.precision_pause_started = now
        elapsed = now-self.precision_pause_started
        if elapsed > 1.:
            return False
        self.precision_pause_map |= waiting_map
        self.zero()
        self.round_trip.pause(now)
        if self.round_trip.error:
            return False
        self.sensors = health
        self.message = ('Precision LiDAR paused at zero speed; waiting for fresh odometry (maximum 1s)'
                        if waiting_odom else
                        'Map TF paused at zero speed; waiting for fresh consistent pose (maximum 1s)'
                        if waiting_map else
                        'Precision LiDAR paused at zero speed; reacquiring the same wall (maximum 1s)')
        self.publish()
        return True

    def precision_timeout_message(self, elapsed):
        channel = 'Map TF' if self.precision_pause_map else 'Precision LiDAR'
        return (channel + ' reacquisition time exceeded: '
                f'episode={elapsed:.2f}/1.00s, paused_total={self.precision_pause_total+elapsed:.2f}s; '
                'overall motion remains limited to 35s')

    def tick_collecting(self, now):
        """The collecting/waiting_motion branch of the node tick.

        Returns True when the original branch returned early (skipping the
        tick-trailing report publish); falls through otherwise.
        """
        self.sensors = self.stationary_report(now)
        # Display current clearance even while sensor qualification waits.
        # This only calculates evidence; it does not authorize movement.
        self.safe_motion(now)
        for name in ('lidar', 'us'):
            stamp, distance, valid_range = self.raw_ranges.get(name, (0., math.inf, False))
            shown = f'{distance:.3f}m' if math.isfinite(distance) else 'no return'
            self.sensors[name]['detail'] += f'; raw={shown} valid={valid_range} age={max(0., now-stamp):.2f}s'
            if name == 'lidar':
                self.sensors[name]['detail'] += '; wall=' + str(self.wall_tracker.diagnostic)
        valid = all(sensor.get('eligible', sensor['ok']) for sensor in self.sensors.values())
        self.phase = 'waiting_motion' if valid else 'collecting'
        if valid:
            self.baseline_values = self.baseline.statistics(now)
            if self.environment_map is not None:
                self.navigation_profile = environment_profile(
                    float(self.get_parameter('robot_radius').value), self.environment_map.res,
                    [row for stamp,row in self.environment_samples if now-stamp <= 5.])
        self.message = 'Keep stationary; waiting for healthy stable sensors'
        if valid:
            if self.get_parameter('calibration_auto_motion').value:
                reason = self.safe_motion(now)
                self.message = reason or 'Stationary checks passed; starting automatic motion validation'
                if reason is None:
                    self.request_command('validate_motion')
                elif 'clearance' in reason.lower() and self.begin_relocation(now, before_translation=True):
                    return True
            else:
                self.message = 'Stationary baseline passed; manual motion validation selected'
        return None

    def tick_motion(self, now):
        """The validating_motion branch of the node tick.

        Returns True when the original branch returned early (skipping the
        tick-trailing report publish); falls through otherwise.
        """
        reason = self.safe_motion(now)
        if reason:
            if preflight_clearance_wait(self.phase, self.motion_start, reason, now, self.requested):
                self.zero()
                self.message = 'Waiting for stable preflight clearance: ' + reason
                self.publish()
                return True
            if reason.startswith('Sensor data became stale or invalid') and self.pause_precision(now):
                return True
            if self.precision_pause_started is not None:
                elapsed = now-self.precision_pause_started
                if elapsed > 1.:
                    reason = self.precision_timeout_message(elapsed)
            self.finish(False, reason)
            return True
        if self.precision_pause_started is not None:
            elapsed = now-self.precision_pause_started
            if elapsed > 1.:
                self.finish(False, self.precision_timeout_message(elapsed))
                return True
            if self.precision_pause_map and not map_motion_continuous(
                    motion_evidence(self.motion_start[1], self.snapshot())):
                self.finish(False, 'Map TF changed relative to odometry during reacquisition')
                return True
            self.precision_pause_total += elapsed
            self.precision_pause_started = None
            self.precision_pause_map = False
            if self.round_trip is not None:
                self.round_trip.pause(now)
        state, seen = self.wander_state
        if not state.startswith('stop') or seen < self.requested or now - seen > .75:
            self.zero()
            if now - self.requested > 2.:
                self.finish(False, 'Wander did not confirm stopped')
            return True
        if self.motion_start is None:
            self.zero()
            if now - self.requested < .5:
                return True
            self.motion_start = (now, self.snapshot())
            if self.get_parameter('calibration_round_trip').value:
                self.round_trip = RoundTrip(now, self.snapshot(),
                    self.selected_target)
        if self.round_trip is not None:
            speed = self.round_trip.update(now, self.snapshot())
            self.motion = self.round_trip.report()
            self.message = f"Round trip {self.round_trip.cycle + 1}/2: {self.round_trip.stage}"
            if self.round_trip.error:
                self.finish(False, self.round_trip.error)
                return True
            if self.round_trip.done:
                self.complete_translation(True, 'Round-trip correction verified and saved')
                return True
            self.drive_trial(linear=speed)
            if now - self.last_report >= .5:
                self.publish()
            return True
        evidence = motion_evidence(self.motion_start[1], self.snapshot())
        self.motion = evidence
        if (evidence['forward_m'] < -.005 or abs(evidence['lateral_m']) > .02 or
                abs(evidence['yaw_drift_rad']) > .15):
            self.finish(False, 'Unexpected motion direction or yaw drift')
            return True
        if now - self.motion_start[0] >= MOTION_SECONDS or evidence['distance_m'] >= self.selected_target:
            passed, checks = motion_result(evidence,
                require_us=bool(self.get_parameter('calibration_require_us_agreement').value))
            self.motion['checks'] = checks
            self.complete_translation(passed, 'Motion sensors agree' if passed else 'Motion validation failed; inspect sensor agreement')
            return True
        self.drive_trial(linear=MOTION_SPEED)
        return None

    def report(self):
        imu = self.baseline_values.get('imu', {}).get('mean', [])
        lidar = self.baseline_values.get('lidar', {}).get('mean', [])
        us = self.baseline_values.get('us', {}).get('mean', [])
        return {'phase': self.phase,
                'calibration_complete': self.phase == 'ready',
                'recalibration_required': bool(getattr(self, 'recalibration_required', False)),
                'runtime_state': ('recalibration_required' if getattr(self, 'recalibration_required', False)
                    else 'ready' if self.runtime_ready else 'sensor_hold') if self.phase == 'ready' else 'not_ready',
                'runtime_waiting_reasons': list(getattr(self, 'runtime_waiting', [])),
                'ready': self.phase == 'ready' and self.runtime_ready and self.settings_applied(),
                'rotation': self.rotation_report(),
                'relocation': self.relocation.report() if self.relocation else None,
                'calibration_origin': self.calibration_origin,
                'after_relocation': self.after_relocation,
                'return_motion': self.return_motion.report() if self.return_motion else None,
                'rotation_verified': bool(self.rotation_report() and self.rotation_report().get('done')),
                'rotation_required_for_new_trial': bool(self.get_parameter('calibration_rotation').value),
                'profile_revision': self.profile_revision,
                'calibration_verified': self.phase == 'ready', 'message': self.message,
                'auto_motion': bool(self.get_parameter('calibration_auto_motion').value),
                'us_precision_required': bool(self.get_parameter('calibration_require_us_agreement').value),
                'elapsed_s': round(time.monotonic() - self.started, 2),
                'sensors': self.sensors, 'motion': self.motion, 'baseline': self.baseline_values,
                'map_tf': self.map_tf_diagnostic,
                'precision_pause_total_s': self.precision_pause_total,
                'navigation_profile': self.navigation_profile,
                'motion_clearance': self.motion_clearance,
                'estimates': {'imu_gyro_bias_rad_s': imu[3:6], 'imu_gravity_mean_mps2': imu[6:9],
                              'imu_roll_pitch_baseline_rad': imu[9:11],
                              'lidar_us_range_difference_m': lidar[0] - us[0] if lidar and us else None},
                'recorded_unix_s': time.time(),
                'limits': {'motion_speed_mps': MOTION_SPEED,
                           'motion_seconds': 35. if self.get_parameter('calibration_round_trip').value else MOTION_SECONDS,
                           'motion_distance_m': MOTION_LIMIT,
                           'round_trip_target_m': float(self.get_parameter('calibration_distance_m').value)},
                'settings_applied': self.phase in ('ready', 'existing_settings', 'limited_sensors') and self.settings_applied(),
                'partial_option': {key: (list(value) if isinstance(value, tuple) else value)
                                   for key, value in partial_plan(
                                       self.sensors,
                                       bool(self.get_parameter('localization_required').value)).items()},
                'calibration_scope': getattr(self, 'calibration_scope', 'full'),
                # Stationary camera step (calibration_camera.py): a candidate, never applied here.
                'camera_extrinsic': getattr(self, 'camera_extrinsic', None),
                **(configured_status(self.phase in ('existing_settings', 'limited_sensors') and self.runtime_ready and self.settings_applied(),
                    self.configured_waiting + ([] if self.settings_applied() else ['settings_acknowledgement']),
                    limited_sensors=self.limited_sensors)
                   if self.existing_settings else {}),
                **(partial_sensing_report(self.sensors) if self.sensing_only else {})}

    def finish(self, passed, message, phase=None):
        if self.sensing_only or self.existing_settings:
            passed = False
        self.zero()
        self.phase = phase or ('ready' if passed else 'failed')
        self.runtime_ready = bool(passed)
        self.runtime_healthy_since = None
        self.message = message
        self.motion_start = None
        try:
            if passed and self.round_trip is not None and self.round_trip.done:
                certificate = make_certificate(self.certificate_configuration(), self.motion, self.rotation_report(), self.trial_geometry_revision)
                self.write_json(self.certificate_path(), certificate)
            self.persist()
        except (OSError, ValueError) as exc:
            self.phase, self.message = 'failed', f'Cannot persist calibration result: {exc}'
        self.publish()

    def certificate_path(self):
        return Path(str(self.get_parameter('result_path').value)).expanduser().with_suffix('.certificate.json')

    def certificate_configuration(self):
        keys = ('robot_radius', 'rotation_footprint_xy', 'lidar_yaw_offset', 'imu_angular_velocity_unit',
                'calibration_round_trip', 'calibration_distance_m', 'calibration_us_max_range',
                'calibration_require_us_agreement')
        try:
            machine_id = Path('/etc/machine-id').read_text().strip()
        except OSError:
            machine_id = socket.gethostname()
        return {'robot_host': socket.gethostname(), 'machine_id': machine_id,
                **{key: self.get_parameter(key).value for key in keys}}

    def restore_certificate(self):
        try:
            saved = json.loads(self.certificate_path().read_text())
            motion = validate_certificate(saved, self.certificate_configuration())
        except (OSError, ValueError, TypeError):
            return
        if motion is None:
            return
        self.motion = motion
        self.saved_rotation = saved.get('rotation') if saved.get('schema') == 2 else None
        self.trial_geometry_revision = saved.get('safety_geometry_revision')
        self.round_trip = SimpleNamespace(done=True, scales=[motion['forward_scale'], motion['reverse_scale']])
        self.phase = 'ready'
        self.runtime_ready = False
        self.runtime_healthy_since = None
        self.message = 'Saved calibration restored; checking current sensors without motion'
        self.publish()
        return True

    def persist(self):
        path = Path(str(self.get_parameter('result_path').value)).expanduser()
        self.write_json(path, self.report())

    @staticmethod
    def write_json(path, value):
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as stream:
                temporary = stream.name
                json.dump(value, stream, allow_nan=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)
