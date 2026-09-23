#!/usr/bin/env python3
"""Watch node interruptions. Publishes /robot/ok and /robot/health."""
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String

from .watch import graph_tables, inspect


class WatchNode(Node):
    def __init__(self):
        super().__init__('watch_node')
        self.declare_parameter('hz', 1.0)
        self.declare_parameter('once', False)
        self.declare_parameter('graph_mode', 'standalone')
        self._mode = str(self.get_parameter('graph_mode').value)
        graph_tables(self._mode)
        self.ok_pub = self.create_publisher(Bool, 'robot/ok', 10)
        self.health_pub = self.create_publisher(String, 'robot/health', 10)
        self.int_pub = self.create_publisher(String, 'robot/interrupt', 10)
        self._last = None
        self._ready = False
        hz = max(0.2, float(self.get_parameter('hz').value))
        self.create_timer(1.0 / hz, self.tick)
        self.get_logger().info('watch_node ready | /robot/ok /robot/health /robot/interrupt')

    def _snapshot(self):
        names = [namespace.rstrip('/') + '/' + name
                 for name, namespace in self.get_node_names_and_namespaces()]
        pubs = {}
        _, _, exclusive, _ = graph_tables(self._mode)
        for topic in exclusive:
            resolved = self.resolve_topic_name(topic.lstrip('/'))
            info = self.get_publishers_info_by_topic(resolved)
            pubs[topic] = [p.node_namespace.rstrip('/') + '/' + p.node_name for p in info]
        return names, pubs

    def tick(self):
        names, pubs = self._snapshot()
        report = inspect(names, pubs, namespace=self.get_namespace(), mode=self._mode)
        line = report.line()
        self.ok_pub.publish(Bool(data=report.ok))
        self.health_pub.publish(String(data=line))
        self.int_pub.publish(String(data='' if report.ok else line))
        if line != self._last:
            self._last = line
            if report.ok:
                self.get_logger().info('graph ok')
            else:
                self.get_logger().error(f'interrupt: {line}')
        if bool(self.get_parameter('once').value):
            if not self._ready:
                self._ready = True
                return
            raise SystemExit(0 if report.ok else 2)


def main():
    rclpy.init()
    node = WatchNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit) as exc:
        code = getattr(exc, 'code', 0) or 0
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        raise SystemExit(code)
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()


if __name__ == '__main__':
    main()
