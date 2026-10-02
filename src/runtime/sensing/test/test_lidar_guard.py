import math
import unittest
from types import SimpleNamespace

from control.control.lidar_guard import lidar_limits, lidar_blocked, lidar_can_rotate, scan_body_clearance
from control.sensing.lidar import NOSE_YAW, sector_range


class LidarGuardTest(unittest.TestCase):
    def test_candidate_bumpers_use_directional_gain_and_preserve_hysteresis(self):
        from dataclasses import replace
        from control.control.lidar_guard import TranslationEvidence, command_translation_bumpers
        evidence = TranslationEvidence(10., 10., True, True, (-.017, 0.), (.02, .02), .076,
                                       (.2,) * 6, True, True, True, True, (1.25, .75))
        self.assertEqual(command_translation_bumpers(evidence, .014, 0., 10.01), (True, True))
        self.assertEqual(command_translation_bumpers(evidence, -.014, 0., 10.01), (False, False))
        near = replace(evidence, travel=(.005, .02))
        self.assertEqual(command_translation_bumpers(near, .005, 0., 10.01), (True, False))
        self.assertEqual(command_translation_bumpers(replace(near, previous_front=False), .005, 0., 10.01),
                         (False, False))
        with self.assertRaises(ValueError):
            command_translation_bumpers(replace(evidence, radial_front=False, radial_rear=False), .1, 0., 10.51)
        for changes in ({'linear_gains': (0., 1.)}, {'ranges': [.2] * 6}, {'radial_front': 0},
                        {'scan_received_at': float('nan')}, {'travel': (float('nan'), .2)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                command_translation_bumpers(replace(evidence, **changes), .01, 0., 10.01)

    def test_footprint_permission_is_specific_to_the_selected_motion(self):
        from control.control.lidar_guard import translation_footprint_eligible
        geometry = dict(enabled=True, lidar_fresh=True, scan_age=.1, source_age=.1,
                        mount=(-.017, 0.), travel=(.02, .03), radius=.076, ranges=(.2,) * 6)
        self.assertTrue(translation_footprint_eligible(.014, 0., **geometry))
        self.assertTrue(translation_footprint_eligible(-.014, 0., **geometry))
        self.assertFalse(translation_footprint_eligible(.0141, 0., **geometry))
        self.assertFalse(translation_footprint_eligible(.01, .001, **geometry))
        for changes in ({'scan_age': .21}, {'source_age': .21}, {'source_age': -.06},
                        {'scan_age': -.1}, {'mount': None}, {'travel': None},
                        {'ranges': (.2, float('inf'))}, {'radius': .084}, {'lidar_fresh': False}):
            with self.subTest(changes=changes):
                self.assertFalse(translation_footprint_eligible(.01, 0., **(geometry | changes)))

    def test_measured_swept_radius_expands_without_legacy_radius_clamping(self):
        self.assertFalse(lidar_can_rotate([.3]*6, .076, True, .2, sweep_radius=.21))
        self.assertTrue(lidar_can_rotate([.3]*6, .076, True, .23, sweep_radius=.21))
        self.assertFalse(lidar_can_rotate([.3]*6, .076, True, .08, sweep_radius=.02))
        self.assertFalse(lidar_can_rotate([.3]*6, .076, True, .3, sweep_radius=math.nan))

    def test_rotation_uses_tf_body_distance_instead_of_symmetric_mount_penalty(self):
        rear=scan_body_clearance([.09],math.pi,.01,-.017,0,0,.05,12)
        front=scan_body_clearance([.09],0,.01,-.017,0,0,.05,12)
        self.assertAlmostEqual(rear,.107)
        self.assertAlmostEqual(front,.073)
        self.assertTrue(lidar_can_rotate([.2,.09,.2,.2,.2,.2],.076,True,rear))
        self.assertFalse(lidar_can_rotate([.09,.2,.2,.2,.2,.2],.076,True,front))
        self.assertFalse(lidar_can_rotate([.2]*6,.076,False,rear))
        # D-424: an empty sector is unknown space, not a reason to refuse a turn.
        self.assertTrue(lidar_can_rotate([.2,math.inf],.076,True,rear))
        self.assertFalse(lidar_can_rotate([math.inf]*6,.076,True,math.inf))   # no return at all

    def test_legacy_unreachable_threshold_is_raised_to_the_body_gap(self):
        """D-424: LiDAR-to-front 0.059 + g(0.014) 0.0223 = 0.081; clear + 0.03."""
        stop, clear = lidar_limits(.018, .028, .076)
        self.assertAlmostEqual(stop, .0813, places=3)
        self.assertGreater(clear, stop)
        for distance in (.059, .070, .080):
            self.assertTrue(lidar_blocked(distance, .3, False, stop, clear, True))

    def test_closer_raw_hit_stops_before_filter_settles(self):
        self.assertTrue(lidar_blocked(.10, .50, False, .12, .14, True))
        self.assertTrue(lidar_blocked(.16, .10, True, .12, .14, True))
        self.assertFalse(lidar_blocked(.16, .16, True, .12, .14, True))

    def test_unknown_and_stale_never_authorize_translation(self):
        for raw in (math.nan, 0.0, -.1):
            self.assertTrue(lidar_blocked(raw, .5, False, .12, .14, True))
        self.assertTrue(lidar_blocked(.5, .5, False, .12, .14, False))
        self.assertTrue(lidar_blocked(math.inf, .5, False, .12, .14, False))
        # D-424: inf is an empty strip (strip_ranges reports an unknown band as a near range).
        self.assertFalse(lidar_blocked(math.inf, math.inf, True, .12, .14, True))

    def test_rear_uses_same_fail_closed_latch_and_hysteresis(self):
        self.assertTrue(lidar_blocked(.13, .13, True, .12, .14, True))
        self.assertFalse(lidar_blocked(.13, .13, False, .12, .14, True))

    def test_spin_requires_fresh_clear_envelope_in_every_seen_sector(self):
        self.assertTrue(lidar_can_rotate([.2] * 6, .076, True))
        self.assertFalse(lidar_can_rotate([.2] * 6, .076, False))
        self.assertFalse(lidar_can_rotate([.2, .2, .09, .2], .076, True))
        self.assertTrue(lidar_can_rotate([.2, .2, math.inf, .2], .076, True))

    def test_malformed_configuration_cannot_disable_bumper(self):
        stop, clear = lidar_limits(math.nan, -.1, math.nan)
        self.assertAlmostEqual(stop, .0813, places=3)
        self.assertGreater(clear, stop)

    # --- D-424 ---------------------------------------------------------------------------

    def test_object_10cm_ahead_is_not_blocked_at_the_gate_speed(self):
        """LiDAR 0.10 = body gap 0.041 > g(0.014) 0.022; the old 0.111 floor froze it."""
        stop, clear = lidar_limits(math.nan, math.nan, .076)
        self.assertAlmostEqual(clear, .1113, places=3)
        self.assertFalse(lidar_blocked(.10, .10, False, stop, clear, True))

    def test_one_empty_sector_does_not_block_a_turn_when_base_points_clear(self):
        """Base-frame nearest 0.10 > rho 0.0826 + 0.010 = 0.0926."""
        self.assertTrue(lidar_can_rotate([.2, .2, math.inf, .2, .2, .2], .076, True, .10))
        self.assertFalse(lidar_can_rotate([.2] * 6, .076, True, .09))

    def test_rotation_never_uses_less_than_the_urdf_rotation_radius(self):
        """Worker default robot_radius 0.076 < rho 0.0826: the turn check uses rho."""
        self.assertFalse(lidar_can_rotate([.3] * 6, .076, True, .09))       # 0.076+0.010 would allow
        self.assertTrue(lidar_can_rotate([.3] * 6, .076, True, .093))

    def test_strip_ranges_ignore_side_points_and_report_unknown_as_the_edge(self):
        from control.control.lidar_guard import strip_ranges
        front, rear = strip_ranges([(0.0, .07), (.20, 0.0)], mount=(-.017, 0.))
        self.assertAlmostEqual(front, .217, places=6)           # 0.20 - (-0.017)
        self.assertEqual(rear, math.inf)
        unknown = [(.133, 0.0)]                                   # a no-return beam to range_min 0.15
        self.assertAlmostEqual(strip_ranges([], unknown)[0], .05905, places=6)
        self.assertEqual(strip_ranges([], unknown, ultrasonic_m=.5)[0], math.inf)
        self.assertAlmostEqual(strip_ranges([], unknown, ultrasonic_m=None)[0], .05905, places=6)
        # A corner contact 40 deg off the nose at 0.09 is in the strip (gap 0.010).
        corner = (-.017 + .09 * math.cos(math.radians(40)), .09 * math.sin(math.radians(40)))
        stop, clear = lidar_limits(math.nan, math.nan, .076)
        self.assertTrue(lidar_blocked(strip_ranges([corner])[0], .5, False, stop, clear, True))

    def test_single_corner_beam_is_not_discarded_by_percentile_or_narrow_cone(self):
        ranges = [.5] * 720
        # 180-degree nose (URDF nominal) plus a 40-degree corner contact.
        ranges[440] = .09
        scan = SimpleNamespace(ranges=ranges, angle_min=0.0,
                               angle_increment=math.pi / 360, range_max=40.0)
        raw = sector_range(scan, NOSE_YAW, math.pi / 4, pctl=0.0)
        self.assertAlmostEqual(raw, .09)
        self.assertTrue(lidar_blocked(raw, .5, False, .12, .14, True))


class ReviewFixesTest(unittest.TestCase):
    """D-424 review M3/M4/M1/L3: pure scan geometry as the bumper feeds it."""

    @staticmethod
    def scan(values, default=2.0, range_min=.15):
        """720 beams, scan angle 0 = robot rear (nose 180 deg), {scan deg: range}."""
        ranges = [default] * 720
        for deg, value in values.items():
            ranges[int(deg * 2) % 720] = value
        return dict(ranges=ranges, angle_min=0., increment=math.pi / 360, range_min=range_min,
                    range_max=12.)

    def geometry(self, values, default=2.0, range_min=.15, ultrasonic_m=None):
        from control.control.lidar_guard import scan_geometry
        scan = self.scan(values, default, range_min)
        return scan_geometry(scan['ranges'], scan['angle_min'], scan['increment'], scan['range_min'],
                             scan['range_max'], mount=(-.017, 0.), rotation=-math.pi, ignore_m=.04,
                             ultrasonic_m=ultrasonic_m)

    def test_stop_gap_uses_the_actual_top_speed(self):
        """M3: g(0.1) = 0.02 + 0.015 + 0.01 = 0.045 -> 0.104 from the LiDAR."""
        stop, clear = lidar_limits(math.nan, math.nan, .076, speed=.1)
        self.assertAlmostEqual(stop, .05905 + .045, places=6)
        self.assertAlmostEqual(clear, stop + .03, places=6)
        self.assertTrue(lidar_blocked(.10, .10, False, stop, clear, True))

    def test_stale_reading_is_nan_and_blocks(self):
        from control.control.lidar_guard import stale_or_nan
        self.assertTrue(math.isnan(stale_or_nan(math.inf, False)))
        self.assertTrue(lidar_blocked(stale_or_nan(math.inf, False), math.inf, False, .08, .11, True))
        self.assertFalse(lidar_blocked(stale_or_nan(math.inf, True), math.inf, True, .08, .11, True))

    def test_near_return_below_range_min_blocks_forward(self):
        g = self.geometry({180: .07})
        stop, clear = lidar_limits(math.nan, math.nan, .076)
        self.assertAlmostEqual(g['front'], .07, places=6)
        self.assertTrue(lidar_blocked(g['front'], .5, False, stop, clear, True))
        self.assertGreater(g['rear'], 1.)                       # the far wall behind

    def test_no_return_beam_ahead_is_the_body_edge_unless_a_real_echo_clears_it(self):
        g = self.geometry({180: math.inf})
        self.assertAlmostEqual(g['front'], .05905, places=6)                  # gap 0 -> blocked
        self.assertGreater(self.geometry({180: math.inf}, ultrasonic_m=.5)['front'], 1.)   # far wall
        self.assertAlmostEqual(self.geometry({180: math.inf}, ultrasonic_m=.05)['front'], .05905, places=6)
        self.assertIsNotNone(g['rotation_reason'])                            # front band, no echo
        self.assertIsNotNone(self.geometry({0: math.inf}, ultrasonic_m=.5)['rotation_reason'])  # rear

    def test_self_return_inside_the_outline_is_dropped_outside_it_counts(self):
        inside = self.geometry({270: .045})        # beside the LiDAR: base (-0.017, -0.045) inside
        self.assertEqual(len(inside['points']), 719)
        outside = self.geometry({270: .075})       # base y 0.075 > half width: an obstacle
        self.assertEqual(len(outside['points']), 720)
        self.assertGreater(outside['front'], 1.)                     # outside the strip
        self.assertIsNotNone(outside['rotation_reason'])             # 0.077 < rho + 0.010

    def test_one_finite_beam_is_not_a_clear_turn(self):
        g = self.geometry({90: 2.0}, default=math.inf, range_min=.05)
        self.assertIn('sectors', g['rotation_reason'])
        self.assertIsNone(self.geometry({}, range_min=.05)['rotation_reason'])
