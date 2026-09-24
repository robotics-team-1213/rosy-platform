import unittest

from control.sensing.observation import Observations


class ObservationTest(unittest.TestCase):
    def test_policy_window_uses_oldest_source_corrected_measurement(self):
        samples = Observations(max_age=.5)
        samples.add('lidar', 10., source=100., source_now=100.2)
        samples.add('imu', 10.1)
        window = samples.policy_window(('lidar', 'imu'), 10.1)
        self.assertAlmostEqual(window[0], 9.8)
        self.assertAlmostEqual(window[1], 10.3)
        self.assertEqual(samples.policy_window(('lidar', 'imu'), 10.2), window)
        self.assertIsNone(samples.policy_window(('lidar', 'imu'), 10.31))

    def test_policy_window_requires_all_named_streams(self):
        samples = Observations()
        samples.add('lidar', 10.)
        self.assertIsNone(samples.policy_window(('lidar', 'imu'), 10.1))
        self.assertIsNone(samples.policy_window((), 10.1))
        samples.add('imu', 10.)
        samples.add('imu', 10.1, valid=False)
        self.assertIsNone(samples.policy_window(('lidar', 'imu'), 10.1))

    def test_real_observation_records_feed_control_policy_without_renewing_lease(self):
        from control.control.command_gate import CommandPolicy, GateInputs
        samples = Observations(max_age=.5)
        samples.add('lidar', 10.)
        samples.add('imu', 10.)
        policy = CommandPolicy('applied-1')
        self.assertTrue(policy.update_observations(samples, ('lidar', 'imu'), GateInputs(),
                                                  10.1, 1, 'applied-1'))
        self.assertTrue(policy.update_observations(samples, ('lidar', 'imu'), GateInputs(),
                                                  10.4, 2, 'applied-1'))
        self.assertIsNone(policy.evaluate(.1, 0., 10.51))
        samples.add('imu', 10.4, valid=False)
        self.assertFalse(policy.update_observations(samples, ('lidar', 'imu'), GateInputs(),
                                                   10.4, 3, 'applied-1'))
        self.assertIsNone(policy.evaluate(.1, 0., 10.4))

    def test_requested_revision_cannot_relabel_unapplied_sensor_state(self):
        from control.control.command_gate import CommandPolicy, GateInputs
        samples = Observations(max_age=.5)
        samples.add('lidar', 10.)
        policy = CommandPolicy('applied-1')
        self.assertTrue(policy.update_observations(samples, ('lidar',), GateInputs(), 10.1, 1, 'applied-1'))
        self.assertFalse(policy.update_observations(samples, ('lidar',), GateInputs(), 10.1, 2, 'old'))
        self.assertIsNone(policy.evaluate(.1, 0., 10.1))

    def test_replayed_packets_do_not_refresh_a_measurement(self):
        samples = Observations()
        self.assertTrue(samples.add('scan', 10., source=100., source_now=100.))
        self.assertFalse(samples.add('scan', 10.8, source=100., source_now=100.8))
        self.assertEqual(samples.generation('scan'), 1)
        self.assertFalse(samples.fresh('scan', 11.1))
        self.assertTrue(samples.add('scan', 11.2, source=101.2, source_now=101.2))
        self.assertTrue(samples.fresh('scan', 11.3))

    def test_source_age_and_receive_age_both_count(self):
        samples = Observations()
        self.assertFalse(samples.add('scan', 10., source=90., source_now=100.))
        self.assertFalse(samples.add('scan', 10., source=101., source_now=100.))
        self.assertTrue(samples.add('scan', 10., source=99.5, source_now=100.))
        self.assertTrue(samples.fresh('scan', 10.2))
        self.assertFalse(samples.fresh('scan', 10.6))

    def test_invalid_and_independent_camera_streams(self):
        samples = Observations()
        samples.add('camera_cliff', 10.)
        samples.add('camera_block', 12.)
        self.assertFalse(samples.fresh('camera_cliff', 12.))
        self.assertTrue(samples.fresh('camera_block', 12.))
        samples.add('ir', 12., valid=False)
        self.assertFalse(samples.fresh('ir', 12.))
        self.assertEqual(samples.report(12.)['ir']['status'], 'invalid')
        self.assertEqual(samples.report(12.)['camera_block']['clock'], 'receive_only')

    def test_nonfinite_and_backward_receive_clock_fail_closed(self):
        samples = Observations()
        self.assertFalse(samples.add('imu', float('nan')))
        samples.add('imu', 10.)
        self.assertFalse(samples.fresh('imu', 9.))
