"""Translate robot-local TF aliases at the ROS boundary (OS ADR D-4).

The legacy policies use local odom/base aliases. Message frames already fully
qualified by a sensor remain unchanged, and map stays the shared map frame.
"""
from tf2_ros import Buffer


class RobotTransformBuffer(Buffer):
    def __init__(self, node):
        if not node.has_parameter('frame_prefix'):
            node.declare_parameter('frame_prefix', node.get_namespace().strip('/'))
        prefix = node.get_parameter('frame_prefix').value
        if not isinstance(prefix, str) or prefix.startswith('/') or '//' in prefix:
            raise ValueError('frame_prefix must be a relative TF prefix')
        self.frame_prefix = prefix.rstrip('/') + '/' if prefix else ''
        super().__init__()

    def robot_frame(self, frame):
        if frame in ('odom', 'base_link', 'base_footprint'):
            return self.frame_prefix + frame
        return frame

    def lookup_transform(self, target_frame, source_frame, time, *args, **kwargs):
        return super().lookup_transform(self.robot_frame(target_frame),
                                        self.robot_frame(source_frame), time, *args, **kwargs)
