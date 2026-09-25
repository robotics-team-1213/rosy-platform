"""Real TF-buffer lookup across two robot trees without drivers or motion."""
import unittest

try:
    import rclpy
except ImportError:
    rclpy = None

if rclpy is not None:
    from rclpy.node import Node
    from rclpy.time import Time
    from rclpy.parameter import Parameter
    from tf2_ros import TransformException
    from geometry_msgs.msg import TransformStamped
    from control.tf_buffer import RobotTransformBuffer


@unittest.skipIf(rclpy is None, 'Requires isolated ROS Jazzy graph')
class TransformGraphTests(unittest.TestCase):
    def test_root_and_explicit_prefix_are_preserved(self):
        rclpy.init()
        nodes = []
        try:
            for namespace, override, expected in (
                    ('', None, 'base_link'),
                    ('rosy_01', 'device_a/', 'device_a/base_link'),
                    ('rosy_01', '', 'base_link')):
                overrides = [] if override is None else [Parameter('frame_prefix', value=override)]
                node = Node('frame_probe_' + str(len(nodes)), namespace=namespace, parameter_overrides=overrides)
                nodes.append(node)
                buffer = RobotTransformBuffer(node)
                self.assertEqual(buffer.robot_frame('base_link'), expected)
                self.assertEqual(buffer.robot_frame('sensor/front'), 'sensor/front')
                with self.assertRaises(TransformException):
                    buffer.lookup_transform('map', 'base_link', Time())
        finally:
            for node in nodes:
                node.destroy_node()
            rclpy.shutdown()

    def test_each_robot_resolves_its_own_base_in_shared_map(self):
        rclpy.init()
        nodes = []
        try:
            for namespace, expected in (('rosy_01', 1.), ('rosy_02', 2.)):
                node = Node('frame_probe', namespace=namespace)
                nodes.append(node)
                buffer = RobotTransformBuffer(node)
                for owner, x in (('rosy_01', 1.), ('rosy_02', 2.)):
                    for parent, child, offset in (
                            ('map', owner + '/odom', x),
                            (owner + '/odom', owner + '/base_footprint', 0.),
                            (owner + '/base_footprint', owner + '/base_link', .1)):
                        tf = TransformStamped()
                        tf.header.frame_id, tf.child_frame_id = parent, child
                        tf.transform.translation.x = offset
                        tf.transform.rotation.w = 1.
                        buffer.set_transform_static(tf, 'test')
                actual = buffer.lookup_transform('map', 'base_link', Time())
                self.assertAlmostEqual(actual.transform.translation.x, expected + .1)
                self.assertEqual(actual.child_frame_id, namespace + '/base_link')
                self.assertEqual(buffer.robot_frame('map'), 'map')
                self.assertEqual(buffer.robot_frame(namespace + '/base_link'), namespace + '/base_link')
        finally:
            for node in nodes:
                node.destroy_node()
            rclpy.shutdown()


if __name__ == '__main__':
    unittest.main()
