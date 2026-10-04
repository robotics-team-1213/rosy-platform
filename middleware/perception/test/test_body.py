#!/usr/bin/env python3
import unittest

from control.sensing.body import (
    ROTATION_RADIUS,
    URDF_RADIUS,
    footprint_bounds,
    rotation_radius,
    ignore_m,
    turn_clear_m,
    urdf_radius,
    use_radius,
)


class BodyTest(unittest.TestCase):
    def test_urdf_is_rear_caster(self):
        r = urdf_radius()
        self.assertAlmostEqual(r, URDF_RADIUS)
        self.assertGreater(r, 0.068)
        self.assertLess(r, 0.090)
        self.assertAlmostEqual(r, 0.076, places=3)

    def test_rotation_radius_is_the_urdf_mesh_radius(self):
        """D-424: the wheel/caster circumradius 0.076 under-reads the mesh rotation radius."""
        self.assertAlmostEqual(ROTATION_RADIUS, 0.08257)

    def test_worker_rotation_radius_never_below_rho(self):
        """D-424: the old robot.yaml 0.076 must not shrink the in-place turn check."""
        self.assertGreaterEqual(rotation_radius(0.076), 0.0825)
        self.assertGreaterEqual(rotation_radius(None), 0.0825)
        self.assertAlmostEqual(rotation_radius(0.12), 0.12)

    def test_footprint_box_is_the_urdf_body(self):
        rear, front, half_width = footprint_bounds()
        self.assertAlmostEqual((rear, front, half_width), (0.076, 0.04205, 0.05655))

    def test_calib_param_wins(self):
        self.assertAlmostEqual(use_radius(0.080), 0.080)
        self.assertAlmostEqual(use_radius(0.076), 0.076)

    def test_bad_calib_falls_back(self):
        self.assertAlmostEqual(use_radius(None), URDF_RADIUS)
        self.assertAlmostEqual(use_radius(0.0), URDF_RADIUS)
        self.assertAlmostEqual(use_radius(1.5), URDF_RADIUS)
        self.assertAlmostEqual(use_radius(float('nan')), URDF_RADIUS)

    def test_turn_clear_bigger_than_body(self):
        c = turn_clear_m(0.076)
        self.assertGreater(c, 0.076)
        self.assertAlmostEqual(c, 0.086, places=3)

    def test_ignore_near_four_cm(self):
        lo = ignore_m(0.076)
        self.assertGreaterEqual(lo, 0.035)
        self.assertLessEqual(lo, 0.055)


if __name__ == '__main__':
    unittest.main()
