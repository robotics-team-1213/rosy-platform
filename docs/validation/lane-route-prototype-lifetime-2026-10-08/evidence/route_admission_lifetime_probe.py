import sys

import numpy as np
import rclpy
from rclpy.parameter import Parameter
from sensor_msgs.msg import Image

from control.line_observer_node import LineObserverNode


rclpy.init(args=['--ros-args', '--params-file', sys.argv[1]])
node = LineObserverNode()
node._camera_controls_stable = True
print('before=' + type(node._route_follower).__name__, flush=True)

frame = Image()
frame.height, frame.width = 240, 320
frame.encoding = 'bgr8'
frame.data = np.full((240, 320, 3), 100, np.uint8).tobytes()
frame.header.stamp.sec = 1

changed = node.set_parameters([Parameter('camera_ground_source', value='PINKY')])[0]
print('physical_parameter_change=' + str(changed.successful), flush=True)
node._on_camera(frame)
print('after_physical_frame=' + type(node._route_follower).__name__, flush=True)

restored = node.set_parameters([Parameter('camera_ground_source', value='GAZEBO')])[0]
print('simulation_parameter_restore=' + str(restored.successful), flush=True)
node._on_camera(frame)
print('after_restored_frame=' + type(node._route_follower).__name__, flush=True)
node.destroy_node()
rclpy.shutdown()
