"""Exercise the production constructor with real ROS name resolution, without I/O."""
import ast
import json
import os
from control.calibration_record import validate_context
import unittest
from pathlib import Path

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import Imu, LaserScan, Range
    from std_msgs.msg import String, UInt16MultiArray
except ImportError:
    rclpy = None


@unittest.skipIf(rclpy is None, 'Requires ROS Jazzy; run in the ROS container')
class CalibrationGraphTests(unittest.TestCase):
    def test_two_namespaces_have_disjoint_calibration_endpoints(self):
        # Compile the actual constructor; unused sensing/driver imports and
        # callbacks are omitted so this test cannot command a physical robot.
        path = Path(__file__).parents[1] / 'control/calib_node.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CalibNode')
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__']
        callbacks = ('on_ir', 'on_step', 'on_odom', 'on_scan', 'on_us', 'on_imu', '_heartbeat', '_tick')
        for namespace in ('rosy_01', 'rosy_02'):
            class NamespacedNode(Node):
                def __init__(self, name):
                    super().__init__(name, namespace=namespace)

            bindings = dict(globals(), Node=NamespacedNode, URDF_RADIUS=0.08)
            exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), 'exec'), bindings)
            constructor = bindings['CalibNode']
            for callback in callbacks:
                setattr(constructor, callback, lambda *args: None)
            rclpy.init()
            node = None
            try:
                node = constructor()
                topics = {p.topic_name for p in node.publishers}
                topics.update(s.topic_name for s in node.subscriptions)
                # rosout and parameter_events are ROS global infrastructure.
                topics -= {'/rosout', '/parameter_events'}
                self.assertTrue(topics)
                self.assertTrue(all(t.startswith('/' + namespace + '/') for t in topics), topics)
                self.assertNotIn('/' + namespace + '/cmd_vel', topics)
                self.assertIn('/' + namespace + '/cmd_vel_raw', topics)
                self.assertEqual(node.get_parameter('save_path').value, '')
                self.assertEqual(node.get_parameter('sign_path').value, '')
            finally:
                if node is not None:
                    node.destroy_node()
                rclpy.shutdown()


if __name__ == '__main__':
    unittest.main()
