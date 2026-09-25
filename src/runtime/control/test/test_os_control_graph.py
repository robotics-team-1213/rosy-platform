"""Full processing-node constructors in isolated ROS; no drivers or timer spin."""
import unittest

try:
    import rclpy
except ImportError:
    rclpy = None

if rclpy is not None:
    from control.safety.node import SafetyNode
    from control.wander.node import WanderNode
    from control.goal_node import GoalNode
    from control.control_node import ControlNode
    from control.calib_node import CalibNode
    from control.startup_calibration_node import StartupCalibrationNode
    from control.localization_node import LocalizationNode
    from control.obstacle_observer_node import ObstacleObserver


@unittest.skipIf(rclpy is None, 'Requires isolated ROS Jazzy graph')
class ProcessingGraphTests(unittest.TestCase):
    def test_all_processing_endpoints_follow_namespace(self):
        for namespace in ('rosy_01', 'rosy_02'):
            rclpy.init(args=['--ros-args', '-r', '__ns:=/' + namespace,
                            '-r', '/tf:=tf', '-r', '/tf_static:=tf_static'])
            nodes = []
            try:
                for constructor in (SafetyNode, WanderNode, GoalNode, ControlNode,
                                    CalibNode, StartupCalibrationNode,
                                    LocalizationNode, ObstacleObserver):
                    node = constructor()
                    nodes.append(node)
                    for attribute in ('tf', 'lidar_tf', 'navigation_tf'):
                        buffer = getattr(node, attribute, None)
                        if buffer is not None:
                            self.assertEqual(buffer.frame_prefix, namespace + '/')
                    topics = {p.topic_name for p in node.publishers}
                    topics.update(s.topic_name for s in node.subscriptions)
                    topics -= {'/rosout', '/parameter_events'}
                    self.assertTrue(all(t.startswith('/' + namespace + '/') for t in topics),
                                    (constructor.__name__, sorted(topics)))
                    clients = {node.resolve_service_name(client.srv_name)
                               for client in node.clients}
                    self.assertTrue(all(s.startswith('/' + namespace + '/') for s in clients),
                                    (constructor.__name__, clients))
                final_publishers = [node.get_name() for node in nodes
                                    if any(p.topic_name == '/' + namespace + '/cmd_vel'
                                           for p in node.publishers)]
                # This is the legacy comparison graph, not the target CORE graph.
                self.assertEqual(final_publishers, ['safety_node'])
            finally:
                for node in reversed(nodes):
                    node.destroy_node()
                rclpy.shutdown()


if __name__ == '__main__':
    unittest.main()
