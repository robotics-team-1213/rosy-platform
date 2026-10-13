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
        # D-424: an obstacle/rear-blocked arc with a clear turn becomes a turn in place
        # (test_an_arc_with_forward_blocked_turns_in_place_when_rotation_is_clear).
        for state in ({'cliff': True}, {'can_rotate': False}):
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


def test_an_arc_with_forward_blocked_turns_in_place_when_rotation_is_clear():
    """D-424 (F): a clipped v used to stop the whole command (trajectory_changed)."""
    from control.control.command_gate import GateInputs, evaluate_command
    result = evaluate_command(.01, .05, GateInputs(obstacle=True, can_rotate=True))
    assert (result.linear, result.angular) == (0., .05)
    assert result.reason == 'motion_limited'
    blocked = evaluate_command(.01, .05, GateInputs(obstacle=True, can_rotate=False))
    assert (blocked.linear, blocked.angular) == (0., 0.)
    rear = evaluate_command(-.01, .05, GateInputs(rear_blocked=True, can_rotate=True))
    assert (rear.linear, rear.angular) == (0., .05)
    cliff = evaluate_command(.01, .05, GateInputs(cliff=True, can_rotate=True))
    assert (cliff.linear, cliff.angular, cliff.reason) == (0., 0., 'trajectory_changed')


# Forward-arc stopping sweep: a wall 96 mm beside the base centre fails the pivot circle
# (can_rotate False) although a moving arc beside it can be clear.
WALL = tuple((x/200., .096) for x in range(-60, 61))
_DEFAULT = object()


def forward_arc(v, w, *, state=None, now=10.01, evidence=_DEFAULT, policy=None, **changes):
    from core_common.robot_body import NOMINAL_BODY
    from control.control.command_gate import CommandPolicy, GateSnapshot
    from control.control.lidar_guard import ForwardEvidence
    if policy is None:
        if evidence is _DEFAULT:
            evidence = ForwardEvidence(**(dict(scan_received_at=10., scan_source_at=10., points=WALL,
                observed=True, body=NOMINAL_BODY, limits=(.06, .5)) | changes))
        policy = CommandPolicy('applied')
        inputs = GateInputs(**({'can_rotate': False} | (state or {})))
        assert policy.update(GateSnapshot(policy.session, 1, 'applied', 10., 10.4, inputs,
                                          forward=evidence))
    snapshot, result = policy.evaluate(v, w, now)
    # The candidate decision never rewrites the shared snapshot.
    assert snapshot.inputs.can_rotate is (state or {}).get('can_rotate', False)
    return (result.linear, result.angular, result.reason), policy


REFUSED = (0., 0., 'trajectory_changed')


def test_forward_arc_beside_a_wall_is_admitted_unchanged_when_its_stop_sweep_is_clear():
    assert forward_arc(.05, -.05)[0] == (.05, -.05, 'allow')


def test_forward_arc_into_the_wall_is_refused_and_no_permission_is_cached():
    result, policy = forward_arc(.05, -.05)
    assert result == (.05, -.05, 'allow')
    assert forward_arc(.03, .5, policy=policy)[0] == REFUSED
    assert forward_arc(.05, -.05, policy=policy)[0] == (.05, -.05, 'allow')


def test_pivot_and_reverse_arc_keep_the_pivot_circle_rule():
    assert forward_arc(0., .3)[0] == (0., 0., 'motion_limited')
    assert forward_arc(-.05, -.05)[0] == REFUSED
    assert forward_arc(-.05, .05)[0] == REFUSED


def test_forward_arc_without_usable_evidence_keeps_the_old_refusal():
    import math
    from core_common.robot_body import NOMINAL_BODY
    assert forward_arc(.05, -.05, evidence=None)[0] == REFUSED
    assert forward_arc(.05, -.05, evidence='clear')[0] == REFUSED
    cases = [dict(observed=False), dict(observed=1), dict(points=list(WALL)), dict(points=()),
             dict(points=((0., math.nan),)*3), dict(body=None), dict(limits=[.06, .5]),
             dict(limits=(.04, .5)), dict(limits=(.06, .04)),
             # Stale: beyond the sweep's own 0.2 s and beyond the 0.5 s hard limit.
             dict(scan_received_at=9.76), dict(scan_source_at=9.76),
             dict(scan_received_at=9.5, scan_source_at=9.5),
             # A scan from the future is a clock fault.
             dict(scan_received_at=10.02), dict(scan_source_at=10.02),
             dict(scan_received_at=math.nan), dict(scan_source_at=True),
             dict(body=NOMINAL_BODY.__class__)]
    for changes in cases:
        assert forward_arc(.05, -.05, **changes)[0] == REFUSED, changes


def test_stops_keep_priority_over_an_admissible_forward_arc():
    # A blocked front must not become a turn in place the pivot circle refuses.
    for state in ({'obstacle': True}, {'cliff': True}, {'tilt': True}):
        assert forward_arc(.05, -.05, state=state)[0] == REFUSED, state
    for state, reason in (({'pickup': True}, 'pickup'), ({'estop': True}, 'estop'),
                          ({'observation_failure': 'lidar_unavailable'}, 'lidar_unavailable'),
                          ({'rotation_trial': True}, 'rotation_trial_domain'),
                          ({'translation_trial': True}, 'translation_trial_domain')):
        assert forward_arc(.05, -.05, state=state)[0] == (0., 0., reason), state


def test_lidar_front_strip_yields_to_a_clear_arc_sweep_but_another_front_block_does_not():
    # D-740 rev 1: the straight front strip is not the arc's path; ultrasonic (or unknown) still blocks.
    for can_rotate in (False, True):
        state = {'obstacle': True, 'can_rotate': can_rotate}
        assert forward_arc(.05, -.05, state=state, front_blocked_other=False)[0] == (.05, -.05, 'allow')
        assert forward_arc(.05, -.05, state=state, front_blocked_other=True)[0] != (.05, -.05, 'allow')
        assert forward_arc(.05, -.05, state=state)[0] != (.05, -.05, 'allow')
        assert forward_arc(.03, .5, state=state, front_blocked_other=False)[0] != (.03, .5, 'allow')


def test_clear_pivot_circle_never_consults_the_forward_arc_evidence():
    for evidence in (_DEFAULT, None):
        assert forward_arc(.03, .5, state={'can_rotate': True},
                           evidence=evidence)[0] == (.03, .5, 'allow')
    assert forward_arc(0., .3, state={'can_rotate': True})[0] == (0., .3, 'allow')
