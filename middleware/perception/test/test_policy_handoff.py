"""The sensor producer passes real observation clocks into CORE's policy."""
import unittest
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from control.control.command_gate import CommandPolicy, GateInputs, GateSnapshot
from control.control.obstacle_risk import TrackedEvidence
from control.control.policy_handoff import ControlPolicyProducer
from control.sensing.observation import Observations


class ControlPolicyProducerTests(unittest.TestCase):
    def setUp(self):
        self.observations = Observations(max_age=.5)
        self.observations.add('lidar', 10.0, source=100.0, source_now=100.0)
        self.observations.add('imu', 10.0)
        self.policy = CommandPolicy('applied-profile-1')
        self.producer = ControlPolicyProducer(self.policy, self.observations,
                                              ('lidar', 'imu'), 'applied-profile-1')

    def test_publishes_gate_inputs_with_sensor_deadline_and_applied_revision(self):
        self.assertTrue(self.producer.publish(GateInputs(), now=10.01))
        result = self.policy.evaluate(.01, 0., 10.49)
        self.assertIsNotNone(result)
        snapshot, _ = result
        self.assertEqual(snapshot.sequence, 1)
        self.assertEqual(snapshot.observed_at, 10.0)
        self.assertEqual(snapshot.expires_at, 10.5)
        self.assertEqual(snapshot.calibration_revision, 'applied-profile-1')

    def test_required_stream_loss_invalidates_the_previous_snapshot(self):
        self.assertTrue(self.producer.publish(GateInputs(), now=10.01))
        self.observations.rows['imu'].valid = False
        self.assertFalse(self.producer.publish(GateInputs(), now=10.02))
        self.assertIsNone(self.policy.evaluate(.01, 0., 10.02))

    def test_replayed_or_wrong_applied_revision_cannot_publish(self):
        self.assertFalse(self.producer.publish(GateInputs(), now=10.01,
                                                applied_revision='requested-only'))
        self.assertIsNone(self.policy.evaluate(.01, 0., 10.02))
        self.assertEqual(self.producer.sequence, 1)

    def test_producer_does_not_refresh_receive_or_source_clocks(self):
        self.assertTrue(self.producer.publish(GateInputs(), now=10.01))
        self.assertFalse(self.producer.publish(GateInputs(), now=10.60))
        self.assertIsNone(self.policy.evaluate(.01, 0., 10.60))
        self.assertEqual(self.observations.generation('lidar'), 1)

    def test_producer_carries_candidate_tracking_evidence_into_snapshot(self):
        evidence = TrackedEvidence.capture(
            {'stamp': 100., 'frame': 'odom', 'tracks': []},
            {'stamp': 100., 'blocked': False},
            (0., 0., 0.), 100., source_now=100., received_at=10.,
            radius=.08, margin=.02)
        self.assertTrue(self.producer.publish(GateInputs(), now=10.01,
                                               tracking=evidence))
        result = self.policy.evaluate(.01, 0., 10.02)
        self.assertIsNotNone(result)
        self.assertIs(result[0].tracking, evidence)

    def test_live_linear_limit_is_snapshot_bound_and_preserves_curvature(self):
        self.assertTrue(self.producer.publish(GateInputs(), now=10.01,
                                              linear_limit=.005))
        snapshot, result = self.policy.evaluate(.01, .2, 10.02)
        self.assertEqual(snapshot.linear_limit, .005)
        self.assertAlmostEqual(result.linear, .005)
        self.assertAlmostEqual(result.angular, .1)
        self.assertEqual(result.reason, 'adaptive_speed_limit')

        # A limit is reducing-only; it cannot increase a smaller request.
        _, result = self.policy.evaluate(.003, .2, 10.03)
        self.assertEqual((result.linear, result.angular), (.003, .2))

    def test_malformed_linear_limit_invalidates_previous_authority(self):
        self.assertTrue(self.producer.publish(GateInputs(), now=10.01,
                                              linear_limit=.005))
        self.assertFalse(self.producer.publish(GateInputs(), now=10.02,
                                               linear_limit=float('nan')))
        self.assertIsNone(self.policy.evaluate(.01, 0., 10.03))


def _pair(evaluated):
    return evaluated[1].linear, evaluated[1].angular


class PolicyUnavailableDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.policy = CommandPolicy('applied')
        self.snapshot = GateSnapshot(self.policy.session, 1, 'applied', 10., 10.2, GateInputs())
        self.assertTrue(self.policy.update(self.snapshot))

    def test_none_reasons_capture_the_evaluated_window_without_refreshing_it(self):
        for now, reason in ((9.9, 'snapshot_future'), (10.21, 'snapshot_expired')):
            self.assertIsNone(self.policy.evaluate(.01, 0., now))
            detail = self.policy._take_unavailable_detail()
            self.assertEqual(detail, dict(reason=reason, now=now, session=self.snapshot.session,
                sequence=1, revision='applied', observed_at=10., expires_at=10.2,
                current_sequence=1))
            self.assertIsNone(self.policy._take_unavailable_detail())
        self.policy.invalidate()
        self.assertIsNone(self.policy.evaluate(.01, 0., 10.1))
        detail = self.policy._take_unavailable_detail()
        self.assertEqual(detail['reason'], 'snapshot_missing')
        self.assertEqual(detail['current_sequence'], 1)
        self.assertIsNone(detail['observed_at'])

    def test_evidence_just_after_the_callers_clock_read_is_judged_at_its_own_time(self):
        """Gazebo lap run56: the worker published 0.034 s after CORE read its clock, one refusal
        aborted the bend. Within one control tick the snapshot answers; beyond it stays future."""
        snapshot, result = self.policy.evaluate(.01, 0., 9.966)
        self.assertEqual((snapshot.sequence, result.reason, result.linear), (1, 'allow', .01))
        self.assertIsNone(self.policy._take_unavailable_detail())
        self.assertIsNone(self.policy.evaluate(.01, 0., 9.94))
        self.assertEqual(self.policy._take_unavailable_detail()['reason'], 'snapshot_future')
        self.policy.update(replace(self.snapshot, sequence=2, observed_at=9.99, expires_at=9.995))
        self.assertIsNone(self.policy.evaluate(.01, 0., 9.966))      # an invalid window stays refused


        from control.control.command_gate import evaluate_command
        sequences = iter(range(2, 9))
        def replace_during_evaluation(*args):
            self.assertTrue(self.policy.update(replace(self.snapshot, sequence=next(sequences))))
            return evaluate_command(*args)
        with patch('control.control.command_gate.evaluate_command', replace_during_evaluation):
            self.assertIsNone(self.policy.evaluate(.01, 0., 10.1))
        detail = self.policy._take_unavailable_detail()
        self.assertEqual((detail['reason'], detail['sequence'], detail['current_sequence']),
                         ('snapshot_changed', 2, 3))
        calls = []
        def replace_once(*args):
            if not calls:
                self.assertTrue(self.policy.update(replace(self.snapshot, sequence=9)))
            calls.append(1)
            return evaluate_command(*args)
        with patch('control.control.command_gate.evaluate_command', replace_once):
            snapshot, result = self.policy.evaluate(.01, 0., 10.1)
        self.assertEqual((snapshot.sequence, len(calls)), (9, 2))
        self.assertIsNone(self.policy._take_unavailable_detail())

    def test_diagnostics_are_thread_local_and_success_does_not_leave_a_failure(self):
        barrier = Barrier(2)
        def evaluate(now):
            self.assertIsNone(self.policy.evaluate(.01, 0., now))
            barrier.wait(timeout=5)
            return self.policy._take_unavailable_detail()
        with ThreadPoolExecutor(max_workers=2) as executor:
            future = executor.submit(evaluate, 9.9)
            expired = executor.submit(evaluate, 10.21)
            self.assertEqual(future.result()['reason'], 'snapshot_future')
            self.assertEqual(expired.result()['reason'], 'snapshot_expired')
        self.assertIsNone(self.policy.evaluate(.01, 0., 10.3))
        self.assertIsNotNone(self.policy.evaluate(.01, 0., 10.1))
        self.assertIsNone(self.policy._take_unavailable_detail())


class CameraEvidenceTests(unittest.TestCase):
    """D-424 J/K + review H2: camera evidence never stops a turn or a reverse; an unranged
    camera obstacle stops forward motion, an unusable camera only limits it."""

    def _policy(self, camera):
        observations = Observations(max_age=.5)
        observations.add('lidar', 10.0, source=100.0, source_now=100.0)
        policy = CommandPolicy('rev')
        producer = ControlPolicyProducer(policy, observations, ('lidar',), 'rev')
        evidence = TrackedEvidence.capture({'stamp': 100., 'frame': 'odom', 'tracks': []}, camera,
                                           (0., 0., 0.), 100., source_now=100., received_at=10.,
                                           radius=.08, margin=.02)
        self.assertTrue(producer.publish(GateInputs(), now=10.01, tracking=evidence))
        return policy

    def test_unranged_camera_obstacle_stops_forward_only(self):
        policy = self._policy({'stamp': 100., 'blocked': True})
        self.assertEqual(_pair(policy.evaluate(.01, .1, 10.02)), (0., .1))
        self.assertEqual(_pair(policy.evaluate(-.01, 0., 10.02)), (-.01, 0.))
        self.assertEqual(_pair(policy.evaluate(0., .2, 10.02)), (0., .2))

    def test_unusable_camera_limits_forward_and_never_stops_a_turn(self):
        policy = self._policy({'stamp': 100., 'blocked': False, 'quality': {'valid': False}})
        linear, angular = _pair(policy.evaluate(.01, .1, 10.02))
        self.assertAlmostEqual(linear, .005)
        self.assertEqual(angular, .1)
        self.assertEqual(_pair(policy.evaluate(0., .2, 10.02)), (0., .2))
