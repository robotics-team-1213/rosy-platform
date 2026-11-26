import unittest
from control.control.rotation_clearance import rotation_clearance_allowed


class RotationClearanceTest(unittest.TestCase):
    def test_partial_scan_retains_conservative_swept_body_check(self):
        self.assertTrue(rotation_clearance_allowed(True, False, True, None, (.2,)*6))
        self.assertFalse(rotation_clearance_allowed(False, False, True, .1, (.2,)*6))
        self.assertFalse(rotation_clearance_allowed(True, False, False, .1, (.2,)*6))

    def test_full_scan_pivot_optimization_requires_actual_margin(self):
        self.assertTrue(rotation_clearance_allowed(False, True, True, .02, (.2,)*6))
        for margin in (None, .005, float('nan')):
            self.assertFalse(rotation_clearance_allowed(True, True, True, margin, (.2,)*6))
        self.assertTrue(rotation_clearance_allowed(True, True, True, .02, (.2,float('inf'))))   # D-424

    def test_clearance_vectorized_scan_points_and_front_clearance_match_reference(self):
        import math
        from core_features.line_follow import clearance

        sample = {
            "ranges": [float("nan"), 0.05, 0.25, 1.5, float("inf"), 2.0, 0.12, 3.0],
            "angle_min": -math.pi,
            "angle_max": math.pi,
            "range_min": 0.10,
            "range_max": 2.5,
        }
        self_mask = ((-180.0, -90.0, 0.30),)
        expected_pts = tuple(
            (d * math.cos(a), d * math.sin(a))
            for a, d in clearance._returns(sample, 180.0, self_mask)
            if d <= 2.2
        )
        got_pts = clearance.scan_points(sample, forward_deg=180.0, max_range=2.2, self_mask=self_mask)
        self.assertEqual(len(got_pts), len(expected_pts))
        for (gx, gy), (ex, ey) in zip(got_pts, expected_pts):
            self.assertAlmostEqual(gx, ex, places=12)
            self.assertAlmostEqual(gy, ey, places=12)
        self.assertEqual(clearance.front_clearance(sample, forward_deg=180.0, half_angle_deg=90.0, self_mask=self_mask),
                         min((d for a, d in clearance._returns(sample, 180.0, self_mask) if abs(a) <= math.pi / 2), default=None))
