"""Subject: the stationary camera-extrinsic step of startup calibration.

Command ``camera_extrinsic`` on ``calibration/cmd``. The robot must stand still
facing track walls that both the LiDAR and the camera see. The step never
moves the robot: it holds zero, collects scans and frames for a few seconds,
fits camera pitch, roll and (if observable) lens height against the LiDAR
walls with the calibrated ``lidar_yaw_offset`` (sensing/perception/
camera_extrinsic.py), and writes a CameraProfile candidate beside the
calibration result. It changes no runtime parameter; applying the candidate
is an operator decision (D-47 addendum, D-364, D-379).

ROS-free mixin (D-171): the node feeds ``camera_capture_scan``/``_frame`` and
supplies ``zero``/``stop_wander``/``publish``/``write_json``/``get_parameter``.
Keep ``import time`` and ``time.monotonic()`` as written — the sim rig swaps
this module's ``time``.
"""
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .sensing.perception import camera_extrinsic as extrinsic

CAPTURE_SECONDS = 3.0
CAPTURE_TIMEOUT_S = 10.0
MIN_SCANS = 10
MIN_FRAMES = 5
MAX_SCANS = 40
MAX_FRAMES = 15
# Stationary: odometry may drift this much over the capture, no more.
MAX_DRIFT_M = 0.005
MAX_DRIFT_RAD = math.radians(1.0)
MAX_SPEED_MPS = 0.005
MOTION_PHASES = ('validating_motion', 'validating_rotation', 'relocating_calibration',
                 'returning_calibration')


class CalibrationCamera:
    def camera_candidate_path(self):
        return Path(str(self.get_parameter('result_path').value)).expanduser().with_suffix(
            '.camera_candidate.json')

    def start_camera_extrinsic(self, now, odom):
        """Begin a capture, or refuse with a reason (the report says which)."""
        reason = None
        if self.phase in MOTION_PHASES:
            reason = 'Calibration motion in progress; camera step needs a stationary robot'
        elif getattr(self, 'camera_capture', None) is not None:
            reason = 'Camera step already running'
        elif odom is None:
            reason = 'No fresh odometry; cannot prove the robot is stationary'
        elif abs(odom[3]) > MAX_SPEED_MPS:
            reason = 'Robot is moving; stop it before the camera step'
        if reason:
            self.camera_extrinsic = {'state': 'refused', 'message': reason}
            self.publish()
            return False
        self.zero()
        self.stop_wander()
        self.camera_capture = {'started': now, 'odom': tuple(odom[:3]), 'scans': [], 'frames': []}
        self.camera_extrinsic = {'state': 'capturing',
                                 'message': 'Hold still: capturing LiDAR walls and camera frames'}
        self.publish()
        return True

    def camera_capture_scan(self, scan):
        """scan = (ranges, angle_min, angle_increment, range_min, range_max)."""
        capture = getattr(self, 'camera_capture', None)
        if capture is not None and capture.get('thread') is None and len(capture['scans']) < MAX_SCANS:
            if capture['scans'] and len(capture['scans'][0][0]) != len(scan[0]):
                return
            capture['scans'].append(scan)

    def camera_capture_frame(self, gray):
        capture = getattr(self, 'camera_capture', None)
        if capture is not None and capture.get('thread') is None and len(capture['frames']) < MAX_FRAMES:
            if capture['frames'] and capture['frames'][0].shape != gray.shape:
                return
            capture['frames'].append(gray)

    def tick_camera_extrinsic(self, now, odom):
        capture = getattr(self, 'camera_capture', None)
        if capture is None:
            return
        if capture.get('thread') is not None:
            if not capture['thread'].is_alive():
                self.camera_capture = None
                self.finish_camera_extrinsic(capture['result'])
            return
        self.zero()
        moved = odom is None or abs(odom[3]) > MAX_SPEED_MPS or math.hypot(
            odom[0] - capture['odom'][0], odom[1] - capture['odom'][1]) > MAX_DRIFT_M or abs(
            math.atan2(math.sin(odom[2] - capture['odom'][2]),
                       math.cos(odom[2] - capture['odom'][2]))) > MAX_DRIFT_RAD
        if moved:
            self.camera_capture = None
            self.camera_extrinsic = {'state': 'failed',
                                     'message': 'Robot moved or odometry went stale during the camera step'}
            self.publish()
            return
        elapsed = now - capture['started']
        enough = len(capture['scans']) >= MIN_SCANS and len(capture['frames']) >= MIN_FRAMES
        if elapsed < CAPTURE_SECONDS or not enough:
            if elapsed > CAPTURE_TIMEOUT_S:
                self.camera_capture = None
                self.camera_extrinsic = {
                    'state': 'failed',
                    'message': f"Too few samples: scans={len(capture['scans'])}, frames={len(capture['frames'])}"}
                self.publish()
            return
        inputs = self.camera_extrinsic_inputs(capture)
        # The fit takes seconds on the Pi; the node keeps ticking (and holding zero).
        capture['result'] = {}
        capture['thread'] = threading.Thread(
            target=lambda: capture['result'].update(run_camera_extrinsic(**inputs)), daemon=True)
        self.camera_extrinsic = {'state': 'fitting', 'message': 'Fitting camera pitch/roll/height'}
        self.publish()
        capture['thread'].start()

    def camera_extrinsic_inputs(self, capture):
        mount = getattr(self, 'rotation_mount', None)
        return {'scans': list(capture['scans']), 'frames': list(capture['frames']),
                'yaw_offset_rad': float(self.get_parameter('lidar_yaw_offset').value),
                'lidar_x_m': float(mount[0]) if mount else extrinsic.LIDAR_X_OFFSET_M,
                'tf_nose_rad': getattr(self, 'lidar_nose', None),
                'profile_path': str(self.get_parameter('camera_extrinsic_profile_path').value)}

    def finish_camera_extrinsic(self, result):
        if 'error' in result:
            self.camera_extrinsic = {'state': 'failed', 'message': result['error']}
        else:
            try:
                path = self.camera_candidate_path()
                self.write_json(path, result['candidate'])
                self.camera_extrinsic = {
                    'state': 'candidate', 'path': str(path),
                    'message': ('Candidate written; review before applying' if result['candidate']['recommended']
                                else 'Candidate written but not recommended: ' + result['candidate']['why']),
                    'candidate': result['candidate']}
            except (OSError, ValueError) as exc:
                self.camera_extrinsic = {'state': 'failed', 'message': f'Cannot persist camera candidate: {exc}'}
        self.publish()


def load_profile(path):
    import yaml
    with open(path, encoding='utf-8') as stream:
        profile = yaml.safe_load(stream) or {}
    missing = [key for key in extrinsic.PROFILE_KEYS if key not in profile]
    if missing:
        raise ValueError('camera profile lacks ' + ', '.join(missing))
    return profile


def run_camera_extrinsic(*, scans, frames, yaw_offset_rad, lidar_x_m, tf_nose_rad, profile_path):
    """The whole fit, off the ROS thread. Returns {'candidate': ...} or {'error': ...}."""
    try:
        profile = load_profile(profile_path)
        height, width = frames[0].shape[:2]
        base = extrinsic.CameraPose.from_profile(profile, width, height)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'error': f'Camera base profile unusable ({profile_path or "unset"}): {exc}'}
    _ranges, angle_min, angle_increment, range_min, range_max = scans[0]
    scan = (extrinsic.median_ranges([s[0] for s in scans]), angle_min, angle_increment, range_min, range_max)
    gray = sum(frame.astype('float32') for frame in frames) / len(frames)
    grad = extrinsic.vertical_gradient(gray)
    samples = extrinsic.wall_samples([(scan, grad)], yaw_offset_rad, lidar_x_m)
    fit = extrinsic.fit_camera_extrinsic(base, samples)
    if 'error' in fit:
        return {'error': fit['error'] + '; face the robot at track walls within 1.6 m'}
    fitted = base.replace(pitch_rad=fit['pitch_rad'], roll_rad=fit['roll_rad'], height_m=fit['height_m'])
    yaw = extrinsic.yaw_check(fitted, [(scan, grad)], yaw_offset_rad, x_offset_m=lidar_x_m)
    if tf_nose_rad is not None:
        yaw['tf_nose_deg'] = round(math.degrees(tf_nose_rad), 2)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    candidate = extrinsic.candidate_profile(
        profile, fit, revision=f'camera-extrinsic-{stamp}',
        source=(f'startup_calibration camera_extrinsic; lidar_yaw_offset='
                f'{math.degrees(yaw_offset_rad):.2f}deg; scans={len(scans)} frames={len(frames)}; '
                f'base={profile_path}'), yaw=yaw)
    candidate['recorded_unix_s'] = time.time()
    return {'candidate': candidate}
