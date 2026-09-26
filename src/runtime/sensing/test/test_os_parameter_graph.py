"""Verify shipped parameter selectors with real ROS name resolution."""
from pathlib import Path
import unittest
import tempfile
import time

try:
    import rclpy
except ImportError:
    rclpy = None

if rclpy is not None:
    from rclpy.node import Node
    import yaml
    from control.calibration_storage import merge_calibration


@unittest.skipIf(rclpy is None, 'Requires isolated ROS Jazzy graph')
class ParameterGraphTests(unittest.TestCase):
    def test_sensor_only_handoff_carries_translation_evidence_to_core(self):
        from control.control.command_gate import CommandPolicy
        from control.safety.node import SafetyNode
        from rclpy.parameter import Parameter
        rclpy.init(args=['--ros-args', '-r', '__ns:=/rosy_01'])
        node = None
        try:
            node = SafetyNode(sensor_only=True, parameter_overrides=[
                Parameter('footprint_guard_enabled', value=True)])
            node._refresh_distances()
            node.lidar_mount = (-.017, 0.)
            node.translation_clearance = (.02, .02)
            node.lidar_front = node.lidar_rear = .2
            node.lidar_left = node.lidar_right = node.lidar_rear_left = node.lidar_rear_right = .2
            node.refresh_profile()
            policy = CommandPolicy(node.profile.revision)
            node.bind_policy_handoff(policy, ('lidar',), node.profile.revision)
            received = time.monotonic()
            node.observations.add('lidar', received)
            node.tick()
            self.assertTrue(node.sensor_policy_published)
            result = policy.evaluate(.01, 0., time.monotonic())
            self.assertIsNotNone(result)
            self.assertIsNotNone(result[0].translation)
        finally:
            if node is not None:
                node.destroy_node()
            rclpy.shutdown()

    def test_sensor_only_builds_tracking_evidence_from_camera_tracks_and_odom(self):
        from control.safety.node import SafetyNode
        from rclpy.parameter import Parameter
        from geometry_msgs.msg import TransformStamped
        from unittest.mock import patch
        rclpy.init(args=['--ros-args', '-r', '__ns:=/rosy_01'])
        node = None
        try:
            node = SafetyNode(sensor_only=True, parameter_overrides=[
                Parameter('obstacle_tracking_enabled', value=True)])
            ros_now = node.get_clock().now().nanoseconds * 1e-9
            node.camera_observation = {'stamp': ros_now, 'blocked': False,
                                       'quality': {'valid': True}}
            node.obstacle_observation = {
                'stamp': ros_now, 'frame': 'odom', 'tracks': []}
            transform = TransformStamped()
            transform.header.stamp = node.get_clock().now().to_msg()
            transform.transform.rotation.w = 1.0
            with patch.object(node.lidar_tf, 'lookup_transform', return_value=transform):
                evidence = node._tracking_policy_evidence(time.monotonic())
            self.assertIsNotNone(evidence)
            self.assertEqual(evidence.pose, (0.0, 0.0, 0.0))
        finally:
            if node is not None:
                node.destroy_node()
            rclpy.shutdown()

    def test_sensor_only_builds_translation_evidence_from_current_lidar_sample(self):
        from control.safety.node import SafetyNode
        from control.control.lidar_guard import TranslationEvidence
        from rclpy.parameter import Parameter
        rclpy.init(args=['--ros-args', '-r', '__ns:=/rosy_01'])
        node = None
        try:
            node = SafetyNode(sensor_only=True, parameter_overrides=[
                Parameter('footprint_guard_enabled', value=True)])
            node._refresh_distances()
            received = time.monotonic()
            node.observations.add('lidar', received)
            node.lidar_mount = (-.017, 0.)
            node.translation_clearance = (.02, .02)
            node.lidar_front = node.lidar_rear = .2
            node.lidar_left = node.lidar_right = node.lidar_rear_left = node.lidar_rear_right = .2
            evidence = node._translation_policy_evidence(received + .01)
            self.assertIsInstance(evidence, TranslationEvidence)
            self.assertEqual(evidence.travel, (.02, .02))
            self.assertEqual(evidence.ranges, (.2,) * 6)
        finally:
            if node is not None:
                node.destroy_node()
            rclpy.shutdown()

    def test_sensor_only_handoff_consumes_real_observation_window(self):
        from control.control.command_gate import CommandPolicy
        from control.safety.node import SafetyNode
        rclpy.init(args=['--ros-args', '-r', '__ns:=/rosy_01'])
        node = None
        try:
            node = SafetyNode(sensor_only=True)
            node.refresh_profile()
            policy = CommandPolicy(node.profile.revision)
            self.assertEqual(node.bind_policy_handoff(policy, ('lidar', 'imu')),
                             node.profile.revision)
            received = time.monotonic()
            node.observations.add('lidar', received)
            node.observations.add('imu', received)
            node.tick()
            self.assertTrue(node.sensor_policy_published)
            self.assertIsNotNone(policy.evaluate(.01, 0., time.monotonic()))
            node.observations.rows['imu'].valid = False
            node.tick()
            self.assertFalse(node.sensor_policy_published)
            self.assertIsNone(policy.evaluate(.01, 0., time.monotonic()))
        finally:
            if node is not None:
                node.destroy_node()
            rclpy.shutdown()

    def test_sensor_only_node_has_no_command_or_legacy_ack_endpoints(self):
        from control.safety.node import SafetyNode
        rclpy.init(args=['--ros-args', '-r', '__ns:=/rosy_01'])
        node = None
        try:
            node = SafetyNode(sensor_only=True)
            forbidden = {'/rosy_01/cmd_vel', '/rosy_01/cmd_vel_raw', '/rosy_01/wander/cmd',
                         '/rosy_01/calib/step', '/rosy_01/estop/state', '/rosy_01/calibration/applied',
                         '/rosy_01/safety/decision'}
            publishers = {name for name, _ in node.get_publisher_names_and_types_by_node(
                node.get_name(), node.get_namespace())}
            self.assertFalse(publishers & forbidden)
            subscriptions = {name for name, _ in node.get_subscriber_names_and_types_by_node(
                node.get_name(), node.get_namespace())}
            self.assertFalse(subscriptions & {'/rosy_01/cmd_vel_raw', '/rosy_01/estop',
                                             '/rosy_01/estop/cmd', '/rosy_01/calibration/profile'})
            self.assertIn('/rosy_01/scan', subscriptions)
            node.tick()
            self.assertIsNotNone(node.sensor_state)
            self.assertIsNotNone(node.sensor_state.observation_failure)
            self.assertTrue(node.sensor_state.legacy_tilt_recovery is False)
            node.set_parameters([rclpy.parameter.Parameter('localization_required', value=True)])
            from std_msgs.msg import String
            node.on_localization(String(data='{}'))
            node.tick()
            self.assertFalse(node.sensor_state.localization_ready)
            publishers = {name for name, _ in node.get_publisher_names_and_types_by_node(
                node.get_name(), node.get_namespace())}
            self.assertFalse(publishers & forbidden)
        finally:
            if node is not None:
                node.destroy_node()
            rclpy.shutdown()

    def test_verified_record_reaches_actual_stopped_safety_consumer(self):
        from control.calibration_record import encode_record
        from control.calibration_snapshot import load_calibration_snapshot
        from control.safety.node import SafetyNode
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'calibration/rosy_01/calibration.yaml'
            path.parent.mkdir(parents=True)
            context = dict(robot_id='rosy_01', hardware_model='pinky_pro',
                           geometry_revision='g1', sensor_revision='s1', data_generation='d1')
            values = {'imu_roll0': 0.25, 'imu_pitch0': 0.5, 'cliff_raw_max': 321}
            path.write_text(encode_record({'/**/safety_node': {'ros__parameters': values}},
                                         context, 'test'), encoding='utf-8')
            snapshot = load_calibration_snapshot(str(path), context, 'd1', str(root))
            rclpy.init(args=['--ros-args', '-r', '__ns:=/rosy_01'])
            node = None
            try:
                node = SafetyNode.from_calibration(snapshot)
                self.assertEqual(node.get_namespace(), '/rosy_01')
                self.assertTrue(node.get_parameter('start_estopped').value)
                for name, value in values.items():
                    self.assertEqual(node.get_parameter(name).value, value)
                self.assertEqual(node.calibration_parameter_digest, snapshot.digest)
                node.set_parameters([rclpy.parameter.Parameter('imu_roll0', value=0.75)])
                with self.assertRaises(ValueError):
                    snapshot.verify_parameters(node)
                for name, value in (('start_estopped', False), ('cmd_out', 'other'),
                                    ('unknown_parameter', 1)):
                    path.write_text(encode_record({'/**/safety_node': {'ros__parameters': {name: value}}},
                                                 context, 'test'), encoding='utf-8')
                    rejected = load_calibration_snapshot(str(path), context, 'd1', str(root))
                    with self.subTest(name=name), self.assertRaises(ValueError):
                        SafetyNode.from_calibration(rejected)
            finally:
                if node is not None:
                    node.destroy_node()
                rclpy.shutdown()

    def test_saved_legacy_calibration_is_consumed_by_namespaced_owner_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calibration.yaml'
            path.write_text('safety_node:\n  ros__parameters:\n    imu_roll0: 0.25\n')
            merge_calibration(str(path), 'safety_node:\n  ros__parameters:\n    imu_pitch0: 0.5\n')
            rclpy.init(args=['--ros-args', '--params-file', str(path)])
            nodes = []
            try:
                for name in ('safety_node', 'unrelated_node'):
                    node = Node(name, namespace='rosy_01',
                                automatically_declare_parameters_from_overrides=True)
                    nodes.append(node)
                self.assertEqual(nodes[0].get_parameter('imu_roll0').value, 0.25)
                self.assertEqual(nodes[0].get_parameter('imu_pitch0').value, 0.5)
                self.assertFalse(nodes[1].has_parameter('imu_roll0'))
                self.assertFalse(nodes[1].has_parameter('imu_pitch0'))
            finally:
                for node in nodes:
                    node.destroy_node()
                rclpy.shutdown()

    def test_per_node_files_apply_under_root_and_robot_namespaces(self):
        config = Path(__file__).parents[1] / 'config'
        for path in sorted(config.glob('*.yaml')):
            document = yaml.safe_load(path.read_text(encoding='utf-8'))
            for selector, settings in document.items():
                if selector == '/**':
                    continue
                name = selector.rsplit('/', 1)[-1]
                for namespace in ('', 'rosy_01', 'rosy_02'):
                    rclpy.init(args=['--ros-args', '--params-file', str(path)])
                    node = None
                    try:
                        node = Node(name, namespace=namespace,
                                    automatically_declare_parameters_from_overrides=True)
                        for key, expected in settings['ros__parameters'].items():
                            self.assertTrue(node.has_parameter(key),
                                            (path.name, namespace, key))
                            actual = node.get_parameter(key).value
                            if isinstance(expected, list):
                                actual = list(actual)
                            self.assertEqual(actual, expected, (path.name, namespace, key))
                    finally:
                        if node is not None:
                            node.destroy_node()
                        rclpy.shutdown()


if __name__ == '__main__':
    unittest.main()
