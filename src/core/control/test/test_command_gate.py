"""Semantic gate boundaries, independent of ROS and physical drive calibration."""
import unittest

from control.control.command_gate import GateInputs, evaluate_command


class CommandGateTest(unittest.TestCase):
    def evaluate(self, v=.1, w=0., **state):
        return evaluate_command(v, w, GateInputs(**state))

    def test_forward_obstacle_still_allows_explicit_reverse_or_spin(self):
        self.assertEqual(self.evaluate(obstacle=True).linear, 0.)
        self.assertEqual(self.evaluate(-.1, obstacle=True).linear, -.1)
        self.assertEqual(self.evaluate(0., .2, obstacle=True).angular, .2)

    def test_component_removal_cannot_change_an_arc_into_a_new_path(self):
        for state in ({'cliff': True}, {'can_rotate': False}, {'rear_blocked': True}):
            with self.subTest(state=state):
                v = -.1 if 'rear_blocked' in state else .1
                result = self.evaluate(v, .2, **state)
                self.assertEqual((result.linear, result.angular, result.reason),
                                 (0., 0., 'trajectory_changed'))

    def test_stop_precedence_and_candidate_invalidation(self):
        cases = [({'estop': True, 'pickup': True}, 'estop', True),
                 ({'observation_failure': 'imu_unavailable', 'pickup': True}, 'imu_unavailable', True),
                 ({'profile_valid': False}, 'invalid_geometry', True),
                 ({'localization_ready': False}, 'localization_unavailable', True),
                 ({'pickup': True}, 'pickup', False),
                 ({'obstacle_hold': 'obstacle_replan'}, 'obstacle_replan', False),
                 ({'command_age': .501}, 'command_stale', False)]
        for state, reason, discard in cases:
            with self.subTest(state=state):
                result = self.evaluate(**state)
                self.assertEqual((result.linear, result.angular, result.reason, result.discard),
                                 (0., 0., reason, discard))

    def test_trial_domains_include_boundary_and_reject_wrong_axis(self):
        self.assertEqual(self.evaluate(0., .06, rotation_trial=True).angular, .06)
        self.assertEqual(self.evaluate(0., .061, rotation_trial=True).reason, 'rotation_trial_domain')
        self.assertEqual(self.evaluate(.001, 0., rotation_trial=True).reason, 'rotation_trial_domain')
        self.assertEqual(self.evaluate(.014, translation_trial=True).linear, .014)
        self.assertEqual(self.evaluate(.0141, translation_trial=True).reason, 'translation_trial_domain')
        self.assertEqual(self.evaluate(0., .001, translation_trial=True).reason, 'translation_trial_domain')

    def test_legacy_tilt_recovery_is_an_explicit_option(self):
        result = self.evaluate(tilt=True, command_age=2., legacy_tilt_recovery=True)
        self.assertEqual(result.linear, -.003)
        self.assertEqual(self.evaluate(tilt=True, legacy_tilt_recovery=True,
                                       rear_blocked=True).linear, 0.)
        # CORE consumes limits only; a forward candidate must not become reverse.
        result = self.evaluate(tilt=True)
        self.assertEqual((result.linear, result.angular), (0., 0.))

    def test_bounded_motion_defers_rotation_to_the_swept_footprint_guard(self):
        self.assertEqual(self.evaluate(0., .1, can_rotate=False).angular, 0.)
        self.assertEqual(self.evaluate(0., .1, can_rotate=False, bounded_motion=True).angular, .1)

    def test_invalid_command_or_clock_is_rejected(self):
        for value in (float('nan'), float('inf'), True):
            with self.subTest(value=value):
                self.assertEqual(self.evaluate(value).reason, 'invalid_command')
        for age in (-.1, float('nan'), float('inf')):
            with self.subTest(age=age):
                self.assertEqual(self.evaluate(command_age=age).reason, 'command_stale')

    def test_unrestricted_candidate_is_preserved(self):
        result = self.evaluate(.08, -.15, command_age=.5)
        self.assertEqual((result.linear, result.angular, result.reason, result.discard),
                         (.08, -.15, 'allow', False))
