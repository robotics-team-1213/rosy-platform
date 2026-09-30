"""Wheel odometry against LiDAR registration (sensing/odometry_fit.py).

A room with an off-centre box is ray-cast from a LiDAR mounted 17 mm behind
base at a 182-degree yaw, the way the Pinky Pro's C1 sits. The robot pivots
and drives straight; the LiDAR motion must come back exact and the wheel
model must return the radius and separation the wheel angles were made with.
"""
import math
import unittest

import numpy as np

from control.sensing import odometry_fit as of

ROOM = [((-0.6, -0.5), (0.9, -0.5)), ((0.9, -0.5), (0.9, 0.6)), ((0.9, 0.6), (-0.6, 0.6)),
        ((-0.6, 0.6), (-0.6, -0.5)),
        ((0.30, 0.20), (0.45, 0.20)), ((0.45, 0.20), (0.45, 0.32)), ((0.45, 0.32), (0.30, 0.32)),
        ((0.30, 0.32), (0.30, 0.20))]
YAW = math.radians(182.0)
LIDAR_X = -0.017
MOUNT = (LIDAR_X, 0.0, -YAW)


def cast(base_pose, n=720):
    """Scan tuple seen from a base pose (x, y, yaw) in the room."""
    lx, ly, lyaw = of.compose(base_pose, MOUNT)
    inc = 2 * math.pi / n
    ranges = np.full(n, np.inf)
    for i in range(n):
        a = lyaw + i * inc
        d = (math.cos(a), math.sin(a))
        for p, q in ROOM:
            ex, ey = q[0] - p[0], q[1] - p[1]
            den = d[0] * -ey + d[1] * ex
            if abs(den) < 1e-12:
                continue
            px, py = p[0] - lx, p[1] - ly
            r = (px * -ey + py * ex) / den
            s = (d[0] * py - d[1] * px) / den
            if r > 0.05 and 0 <= s <= 1:
                ranges[i] = min(ranges[i], r)
    return ranges, 0.0, inc, 0.05, 12.0


class Se2Test(unittest.TestCase):
    def test_between_undoes_compose(self):
        a, b = (0.1, -0.2, 0.7), (0.05, 0.02, -0.3)
        c = of.between(a, of.compose(a, b))
        np.testing.assert_allclose(c, b, atol=1e-12)


class IcpTest(unittest.TestCase):
    def test_icp_recovers_a_small_motion(self):
        s0 = of.scan_points(*cast((0.0, 0.0, 0.0)))
        s1 = of.scan_points(*cast((0.03, 0.01, math.radians(4.0))))
        est, info = of.icp(s1, s0, init=(0.0, 0.0, 0.0))
        truth = of.compose(of.compose(of.inverse(MOUNT), (0.03, 0.01, math.radians(4.0))), MOUNT)
        np.testing.assert_allclose(est[:2], truth[:2], atol=1e-3)
        self.assertAlmostEqual(est[2], truth[2], delta=math.radians(0.1))
        self.assertGreater(info['inliers'], 0.7)


class MotionTest(unittest.TestCase):
    def test_full_pivot_unwraps_and_stays_in_place(self):
        angles = np.radians(np.arange(0.0, 361.0, 15.0))
        poses = [(0.0, 0.0, float(a)) for a in angles]
        guess = [(0.0, 0.0, float(a) * 1.05) for a in angles]    # odometry 5 % high
        m = of.lidar_motion([cast(p) for p in poses], guess, YAW, LIDAR_X)
        self.assertAlmostEqual(m['dth'], math.radians(360.0), delta=math.radians(0.3))
        self.assertLess(math.hypot(m['dx'], m['dy']), 0.002)

    def test_pivot_without_odometry_seed_is_independent_of_a_mirrored_odom(self):
        angles = np.radians(np.arange(0.0, 361.0, 5.0))
        m = of.lidar_motion([cast((0.0, 0.0, float(a))) for a in angles], None, YAW, LIDAR_X)
        self.assertAlmostEqual(m['dth'], math.radians(360.0), delta=math.radians(0.3))

    def test_straight_run_measures_length_and_the_mount_yaw(self):
        poses = [(x, 0.0, 0.0) for x in np.arange(0.0, 0.181, 0.02)]
        m = of.lidar_motion([cast(p) for p in poses], poses, YAW, LIDAR_X)
        self.assertAlmostEqual(m['dx'], 0.18, delta=0.001)
        rec = of.segment_record('straight', (0.0, 0.0), (1.0, 1.0), m)
        self.assertAlmostEqual(rec['lidar_nose_deg'], 182.0, delta=0.5)

    def test_a_wrong_mount_yaw_does_not_shorten_the_travel(self):
        poses = [(x, 0.0, 0.0) for x in np.arange(0.0, 0.181, 0.02)]
        m = of.lidar_motion([cast(p) for p in poses], poses, math.radians(190.0), LIDAR_X)
        rec = of.segment_record('straight', (0.0, 0.0), (1.0, 1.0), m)
        self.assertAlmostEqual(rec['ds'], 0.18, delta=0.001)       # |t|, not t.x * cos(8 deg)
        self.assertAlmostEqual(rec['lidar_nose_deg'], 182.0, delta=0.5)


class WheelFitTest(unittest.TestCase):
    R, B = 0.0271, 0.0968

    def segments(self, noise=0.0, seed=1):
        rng = np.random.default_rng(seed)
        out = []
        for ds in (0.18, -0.18, 0.18, -0.18):
            phi = ds / self.R
            out.append({'kind': 'straight', 'phi_l': phi, 'phi_r': phi,
                        'ds': ds * (1 + noise * rng.standard_normal()), 'dth': 0.0})
        for dth in (2 * math.pi, -2 * math.pi):
            phi = dth * self.B / 2 / self.R
            out.append({'kind': 'pivot', 'phi_l': -phi, 'phi_r': phi, 'ds': 0.0,
                        'dth': dth * (1 + noise * rng.standard_normal())})
        return out

    def test_exact_segments_give_the_true_wheels(self):
        fit = of.fit_wheels(self.segments(), 0.027, 0.0961)
        self.assertAlmostEqual(fit['wheel_radius'], self.R, places=6)
        self.assertAlmostEqual(fit['wheel_separation'], self.B, places=6)
        self.assertAlmostEqual(fit['right_to_left_ratio'], 1.0, places=6)

    def test_noise_shows_up_as_standard_error(self):
        fit = of.fit_wheels(self.segments(noise=0.003), 0.027, 0.0961)
        self.assertLess(abs(fit['wheel_radius'] - self.R), 4 * fit['wheel_radius_se'] + 1e-9)
        self.assertGreater(fit['wheel_radius_se'], 0.0)
        self.assertGreater(fit['wheel_separation_se'], 0.0)

    def test_no_straights_keeps_the_nominal_radius(self):
        fit = of.fit_wheels([s for s in self.segments() if s['kind'] == 'pivot'], 0.027, 0.0961)
        self.assertEqual(fit['wheel_radius'], 0.027)
        self.assertIn('nominal', fit['wheel_radius_source'])

    def test_pinky_right_encoder_counts_backwards(self):
        m = {'dx': 0.18, 'dy': 0.0, 'dth': 0.0, 'lidar_dx': -0.18, 'lidar_dy': 0.0, 'rmse': 0.0,
             'min_inliers': 1.0}
        rec = of.segment_record('straight', (0.0, 0.0), (6.6, -6.6), m, wheel_signs=(1.0, -1.0))
        self.assertEqual((rec['phi_l'], rec['phi_r']), (6.6, 6.6))


class CommandSegmentTest(unittest.TestCase):
    def test_runs_split_on_stop_and_on_direction(self):
        cmds = [(t * 0.1, 0.03 if t < 20 else -0.03 if t < 40 else 0.0, 0.0) for t in range(60)]
        cmds += [(6.0 + t * 0.1, 0.0, 0.1) for t in range(20)]
        segs = of.command_segments(cmds)
        self.assertEqual([(round(s['linear'], 3), s['angular']) for s in segs],
                         [(0.03, 0.0), (-0.03, 0.0), (0.0, 0.1)])


if __name__ == '__main__':
    unittest.main()
