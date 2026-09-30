"""Stationary camera-extrinsic fit (sensing/perception/camera_extrinsic.py) and
its startup-calibration step (calibration_camera.py), on synthetic walls.

The scene is rendered from a known camera and a LiDAR scan is ray-cast from a
known mount, so the fit must return the camera it was drawn with. Walls are
0.155 m tall (the track), bright over a darker carpet and a dark room.
"""
import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

import cv2
import numpy as np
import yaml

from control import calibration_camera as step
from control.calibration_camera import CalibrationCamera
from control.sensing.perception import camera_extrinsic as ce
from control.sensing.perception.camera_ground import nominal_ground_plane

PROFILE_PATH = (Path(__file__).resolve().parents[3] / 'products' / 'pinky_pro' / 'profile'
                / 'config' / 'camera_nominal.yaml')
PROFILE = yaml.safe_load(PROFILE_PATH.read_text(encoding='utf-8'))
TRUE_PITCH_DEG, TRUE_ROLL_DEG = 11.0, 1.5
TRUE_HEIGHT_M = PROFILE['height_m']
# A wall across the view 1.2 m ahead and two nearer walls angled in from the
# sides: the spread of distances is what separates lens height from pitch.
WALLS = [((1.20, 0.90), (1.20, -0.90)), ((0.40, -0.12), (0.95, -0.45)), ((0.45, 0.14), (1.00, 0.40))]


def true_camera(height_m=TRUE_HEIGHT_M):
    return ce.CameraPose.from_profile(PROFILE).replace(
        pitch_rad=math.radians(TRUE_PITCH_DEG), roll_rad=math.radians(TRUE_ROLL_DEG),
        height_m=height_m)


def render(cam, walls=WALLS):
    """Dark room, carpet below the horizon, bright walls (far wall painted first)."""
    img = np.full((cam.height, cam.width), 35, np.uint8)
    horizon = int(round(cam.cy - cam.fx * math.tan(cam.pitch_rad)))
    img[max(horizon, 0):] = 80
    for a, b in sorted(walls, key=lambda w: -min(w[0][0], w[1][0])):
        t = np.linspace(0.0, 1.0, 400)[:, None]
        xy = np.asarray(a) + t * (np.asarray(b) - np.asarray(a))
        ub, vb, db = cam.project(np.column_stack([xy, np.zeros(len(xy))]))
        ut, vt, dt = cam.project(np.column_stack([xy, np.full(len(xy), ce.WALL_HEIGHT_M)]))
        keep = (db > 0.02) & (dt > 0.02)
        poly = np.concatenate([np.column_stack([ub[keep], vb[keep]]),
                               np.column_stack([ut[keep], vt[keep]])[::-1]])
        cv2.fillPoly(img, [np.round(poly).astype(np.int32).reshape(-1, 1, 2)], 210)
    return img


def cast_scan(yaw_offset_deg, walls=WALLS, n=720, x_offset=ce.LIDAR_X_OFFSET_M):
    """(ranges, angle_min, angle_increment, range_min, range_max) of a C1-like scan."""
    inc = 2 * math.pi / n
    ranges = np.full(n, np.inf)
    for i in range(n):
        a = i * inc - math.radians(yaw_offset_deg)
        d = np.array([math.cos(a), math.sin(a)])
        for p, q in walls:
            p, q = np.asarray(p) - [x_offset, 0.0], np.asarray(q) - [x_offset, 0.0]
            e = q - p
            den = d[0] * -e[1] + d[1] * e[0]
            if abs(den) < 1e-12:
                continue
            r = (p[0] * -e[1] + p[1] * e[0]) / den
            s = (d[0] * p[1] - d[1] * p[0]) / den
            if r > 0 and 0 <= s <= 1:
                ranges[i] = min(ranges[i], r)
    return ranges, 0.0, inc, 0.05, 12.0


def samples_for(yaw_deg, fitted_yaw_deg=None, cam=None):
    cam = cam or true_camera()
    grad = ce.vertical_gradient(render(cam))
    scan = cast_scan(yaw_deg)
    yaw = math.radians(yaw_deg if fitted_yaw_deg is None else fitted_yaw_deg)
    return ce.wall_samples([(scan, grad)], yaw), scan, grad


class ProjectionTest(unittest.TestCase):
    def test_roll_zero_matches_the_d379_pinhole(self):
        cam = ce.CameraPose.from_profile(PROFILE)
        u, v, d = cam.project([[1.0, 0.0, 0.0]])
        expect_v = cam.cy + cam.fx * math.tan(math.atan2(cam.height_m, 1.0 - cam.x_offset_m) - cam.pitch_rad)
        self.assertAlmostEqual(float(u[0]), cam.cx, places=6)
        self.assertAlmostEqual(float(v[0]), expect_v, places=3)

    def test_positive_roll_turns_the_horizon_clockwise(self):
        cam = ce.CameraPose.from_profile(PROFILE).replace(roll_rad=math.radians(3.0))
        u, v, _ = cam.project([[3.0, 1.0, cam.height_m], [3.0, -1.0, cam.height_m]])
        self.assertLess(u[0], u[1])      # left point is left in the image
        self.assertLess(v[0], v[1])      # and higher: the right side dips

    def test_scan_offset_rotates_returns_into_the_base_frame(self):
        ranges = np.full(360, np.inf)
        ranges[180] = 1.0                # scan angle pi = the nose for a 180-deg mount
        xy = ce.scan_to_base(ranges, 0.0, math.radians(1.0), 0.05, 12.0, yaw_offset_rad=math.pi,
                             x_offset_m=0.0)
        np.testing.assert_allclose(xy, [[1.0, 0.0]], atol=1e-9)


class FitTest(unittest.TestCase):
    def test_fit_recovers_pitch_and_roll(self):
        samples, _scan, _grad = samples_for(182.0)
        base = ce.CameraPose.from_profile(PROFILE)
        fit = ce.fit_camera_extrinsic(base, samples)
        self.assertAlmostEqual(math.degrees(fit['pitch_rad']), TRUE_PITCH_DEG, delta=0.3)
        self.assertAlmostEqual(math.degrees(fit['roll_rad']), TRUE_ROLL_DEG, delta=0.5)
        self.assertAlmostEqual(fit['height_m'], TRUE_HEIGHT_M, delta=0.005)
        self.assertTrue(fit['recommended'])
        self.assertGreater(fit['score'], fit['score_at_base'] + ce.SCORE_MARGIN)

    def test_one_view_cannot_pin_a_wrong_lens_height_so_pitch_absorbs_it(self):
        # Height and pitch move both wall rows the same way; only the spread
        # of 1/distance separates them, a pixel or two at 320x240. The fit
        # must say so (height kept from the base) instead of inventing one,
        # and the pitch it returns stays within a degree of the truth.
        cam = true_camera(height_m=0.055)
        grad = ce.vertical_gradient(render(cam))
        samples = ce.wall_samples([(cast_scan(182.0), grad)], math.radians(182.0))
        fit = ce.fit_camera_extrinsic(ce.CameraPose.from_profile(PROFILE), samples)
        if fit['height_source'] == 'base':
            self.assertEqual(fit['height_m'], PROFILE['height_m'])
            self.assertGreater(fit['uncertainty']['height_m'], ce.HEIGHT_OBSERVABLE_SPAN_M / 2)
        else:
            self.assertAlmostEqual(fit['height_m'], 0.055, delta=0.005)
        self.assertAlmostEqual(math.degrees(fit['pitch_rad']), TRUE_PITCH_DEG, delta=1.0)

    def test_fit_with_height_held_keeps_the_base_height(self):
        samples, _scan, _grad = samples_for(180.0)
        base = ce.CameraPose.from_profile(PROFILE)
        fit = ce.fit_camera_extrinsic(base, samples, fit_height=False)
        self.assertEqual(fit['height_source'], 'base')
        self.assertEqual(fit['height_m'], base.height_m)

    def test_no_wall_in_view_is_an_error_not_a_candidate(self):
        grad = ce.vertical_gradient(np.full((240, 320), 80, np.uint8))
        scan = (np.full(720, np.inf), 0.0, 2 * math.pi / 720, 0.05, 12.0)
        fit = ce.fit_camera_extrinsic(ce.CameraPose.from_profile(PROFILE),
                                      ce.wall_samples([(scan, grad)], math.pi))
        self.assertIn('error', fit)

    def test_yaw_check_flags_a_mount_the_camera_does_not_support(self):
        # Scene cast with a 182-deg mount; the configured offset says 190.
        _samples, scan, grad = samples_for(182.0, fitted_yaw_deg=190.0)
        yaw = ce.yaw_check(true_camera(), [(scan, grad)], math.radians(190.0))
        self.assertTrue(yaw['disagrees'])
        self.assertAlmostEqual(yaw['best_deg'], 182.0, delta=1.0)
        agree = ce.yaw_check(true_camera(), [(scan, grad)], math.radians(182.0))
        self.assertFalse(agree['disagrees'])

    def test_candidate_keeps_profile_keys_and_feeds_the_nominal_ground_model(self):
        samples, _scan, _grad = samples_for(182.0)
        fit = ce.fit_camera_extrinsic(ce.CameraPose.from_profile(PROFILE), samples, fit_height=False)
        cand = ce.candidate_profile(PROFILE, fit, revision='r1', source='test')
        for key in PROFILE:
            self.assertIn(key, cand)
        for key in ('revision', 'source', 'score', 'uncertainty', 'roll_rad'):
            self.assertIn(key, cand)
        self.assertEqual(cand['fx'], PROFILE['fx'])
        plane = nominal_ground_plane(source='NOMINAL', allowed=True, width_px=320, height_px=240,
                                     profile=cand)
        self.assertIsNotNone(plane)
        json.dumps(cand, allow_nan=False)


class Node(CalibrationCamera):
    """The node edges the mixin needs, recorded."""

    def __init__(self, tmp, yaw_deg=182.0, phase='ready'):
        self.phase = phase
        self.camera_capture = self.camera_extrinsic = None
        self.params = {'result_path': str(Path(tmp) / 'calibration.json'),
                       'lidar_yaw_offset': math.radians(yaw_deg),
                       'camera_extrinsic_profile_path': str(PROFILE_PATH)}
        self.zeros = self.stops = self.published = 0

    def get_parameter(self, name):
        return NS(value=self.params[name])

    def zero(self):
        self.zeros += 1

    def stop_wander(self):
        self.stops += 1

    def publish(self):
        self.published += 1

    @staticmethod
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, allow_nan=False))


class StepTest(unittest.TestCase):
    ODOM = (1.0, 2.0, 0.3, 0.0)

    def feed(self, node, n_scans=12, n_frames=6):
        scan = cast_scan(182.0)
        gray = render(true_camera()).astype(np.float32)
        for _ in range(n_scans):
            node.camera_capture_scan(scan)
        for _ in range(n_frames):
            node.camera_capture_frame(gray)

    def run_to_end(self, node, t0):
        now = t0 + step.CAPTURE_SECONDS + 0.1
        node.tick_camera_extrinsic(now, self.ODOM)
        deadline = time.monotonic() + 120.0
        while node.camera_capture is not None and time.monotonic() < deadline:
            time.sleep(0.05)
            node.tick_camera_extrinsic(now, self.ODOM)

    def test_stationary_capture_writes_a_candidate_and_applies_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = Node(tmp)
            self.assertTrue(node.start_camera_extrinsic(10.0, self.ODOM))
            self.assertEqual((node.zeros, node.stops), (1, 1))
            self.feed(node)
            self.run_to_end(node, 10.0)
            report = node.camera_extrinsic
            self.assertEqual(report['state'], 'candidate', report)
            saved = json.loads(Path(report['path']).read_text())
            self.assertTrue(report['path'].endswith('calibration.camera_candidate.json'))
            self.assertAlmostEqual(math.degrees(saved['pitch_rad']), TRUE_PITCH_DEG, delta=0.3)
            self.assertIn('lidar_yaw_offset=182.00deg', saved['source'])
            self.assertFalse(saved['lidar_yaw_check']['disagrees'])
            # Only the candidate file: the calibration result itself is untouched.
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['calibration.camera_candidate.json'])

    def test_refuses_while_moving_or_during_calibration_motion(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = Node(tmp)
            self.assertFalse(node.start_camera_extrinsic(0.0, (0.0, 0.0, 0.0, 0.05)))
            self.assertEqual(node.camera_extrinsic['state'], 'refused')
            self.assertFalse(node.start_camera_extrinsic(0.0, None))
            node = Node(tmp, phase='validating_rotation')
            self.assertFalse(node.start_camera_extrinsic(0.0, self.ODOM))
            self.assertEqual(node.zeros, 0)

    def test_motion_during_capture_fails_the_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = Node(tmp)
            node.start_camera_extrinsic(0.0, self.ODOM)
            self.feed(node)
            node.tick_camera_extrinsic(1.0, (1.01, 2.0, 0.3, 0.0))
            self.assertIsNone(node.camera_capture)
            self.assertEqual(node.camera_extrinsic['state'], 'failed')
            self.assertFalse(any(Path(tmp).iterdir()))

    def test_too_few_samples_times_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = Node(tmp)
            node.start_camera_extrinsic(0.0, self.ODOM)
            self.feed(node, n_scans=2, n_frames=1)
            node.tick_camera_extrinsic(step.CAPTURE_TIMEOUT_S + 1.0, self.ODOM)
            self.assertEqual(node.camera_extrinsic['state'], 'failed')
            self.assertIn('Too few samples', node.camera_extrinsic['message'])


if __name__ == '__main__':
    unittest.main()
