import sys

import rclpy
from control.line_observer_node import LineObserverNode


rclpy.init(args=['--ros-args', '--params-file', sys.argv[1]])
node = LineObserverNode()
print('route_follower=' + type(node._route_follower).__name__, flush=True)
node.destroy_node()
rclpy.shutdown()
