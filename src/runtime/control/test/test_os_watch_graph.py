"""Real DDS endpoint identity checks; no sensor drivers or commands run."""
import time
import unittest

try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    from control.watch_node import WatchNode
except ImportError:
    rclpy = None

from control.watch import STANDALONE_EXCLUSIVE, STANDALONE_REQUIRED, inspect


@unittest.skipIf(rclpy is None, 'Requires isolated ROS Jazzy graph')
class ScopedWatchGraphTests(unittest.TestCase):
    def test_namespaced_owners_and_cross_namespace_injection(self):
        rclpy.init(args=['--ros-args', '-r', '__ns:=/rosy_01'])
        nodes = []
        try:
            watch = WatchNode()
            nodes.append(watch)
            owners = {}
            for namespace in ('/rosy_01', '/rosy_02'):
                for name in STANDALONE_REQUIRED:
                    node = Node(name, namespace=namespace, use_global_arguments=False)
                    nodes.append(node)
                    owners[namespace, name] = node
                for topic, allowed in STANDALONE_EXCLUSIVE.items():
                    owner = next(iter(allowed))
                    owners[namespace, owner].create_publisher(String, topic.lstrip('/'), 10)

            def wait_for(predicate):
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    names, pubs = watch._snapshot()
                    if predicate(names, pubs):
                        return names, pubs
                    rclpy.spin_once(watch, timeout_sec=0.05)
                self.fail('DDS graph did not reach the expected state')

            names, pubs = wait_for(lambda n, p: all('/rosy_02/' + x in n for x in STANDALONE_REQUIRED)
                                  and inspect(n, p, namespace='/rosy_01', mode='standalone').ok)
            self.assertTrue(inspect(names, pubs, namespace='/rosy_01', mode='standalone').ok)
            for topic, allowed in STANDALONE_EXCLUSIVE.items():
                owner = next(iter(allowed))
                self.assertEqual(pubs[topic], ['/rosy_01/' + owner])

            # A differently scoped process deliberately registers a publisher
            # on our command topic. No messages are sent.
            owners['/rosy_02', 'safety_node'].create_publisher(String, '/rosy_01/cmd_vel', 10)
            names, pubs = wait_for(lambda n, p: '/rosy_02/safety_node' in p['/cmd_vel'])
            report = inspect(names, pubs, namespace='/rosy_01', mode='standalone')
            self.assertFalse(report.ok)
            self.assertTrue(any(i.kind == 'foreign_namespace' for i in report.issues))
        finally:
            for node in reversed(nodes):
                node.destroy_node()
            rclpy.shutdown()


if __name__ == '__main__':
    unittest.main()
