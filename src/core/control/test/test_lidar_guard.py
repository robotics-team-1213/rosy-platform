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
        self.assertFalse(lidar_can_rotate([.2,math.inf],.076,True,rear))

    def test_legacy_unreachable_threshold_is_raised_above_body_and_blind_zone(self):
        stop, clear = lidar_limits(.018, .028, .076)
        self.assertAlmostEqual(stop, .111)
        self.assertGreater(clear, stop)
        for distance in (.076, .080, .090):
            self.assertTrue(lidar_blocked(distance, .3, False, stop, clear, True))

    def test_closer_raw_hit_stops_before_filter_settles(self):
        self.assertTrue(lidar_blocked(.10, .50, False, .12, .14, True))
        self.assertTrue(lidar_blocked(.16, .10, True, .12, .14, True))
        self.assertFalse(lidar_blocked(.16, .16, True, .12, .14, True))

    def test_unknown_and_stale_never_authorize_translation(self):
        for raw in (math.inf, math.nan, 0.0, -.1):
            self.assertTrue(lidar_blocked(raw, .5, False, .12, .14, True))
        self.assertTrue(lidar_blocked(.5, .5, False, .12, .14, False))

    def test_rear_uses_same_fail_closed_latch_and_hysteresis(self):
        self.assertTrue(lidar_blocked(.13, .13, True, .12, .14, True))
        self.assertFalse(lidar_blocked(.13, .13, False, .12, .14, True))

    def test_spin_requires_fresh_clear_envelope_in_every_sector(self):
        self.assertTrue(lidar_can_rotate([.2] * 6, .076, True))
        self.assertFalse(lidar_can_rotate([.2] * 6, .076, False))
        for unsafe in (.09, math.inf, math.nan):
            self.assertFalse(lidar_can_rotate([.2, .2, unsafe, .2], .076, True))

    def test_malformed_configuration_cannot_disable_bumper(self):
        stop, clear = lidar_limits(math.nan, -.1, math.nan)
        self.assertAlmostEqual(stop, .111)
        self.assertGreater(clear, stop)

    def test_single_corner_beam_is_not_discarded_by_percentile_or_narrow_cone(self):
        ranges = [.5] * 720
        # 190-degree nose plus a 30-degree corner contact.
        ranges[440] = .09
        scan = SimpleNamespace(ranges=ranges, angle_min=0.0,
                               angle_increment=math.pi / 360, range_max=40.0)
        raw = sector_range(scan, NOSE_YAW, math.pi / 4, pctl=0.0)
        self.assertAlmostEqual(raw, .09)
        self.assertTrue(lidar_blocked(raw, .5, False, .12, .14, True))
