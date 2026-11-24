"""Translate robot-local TF aliases at the ROS boundary (OS ADR D-4).

The legacy policies use local odom/base aliases. Message frames already fully
qualified by a sensor remain unchanged, and map stays the shared map frame.
"""
from tf2_ros import Buffer


_LOCAL_FRAMES = ('odom', 'base_link', 'base_footprint')


def _frame_prefix(node):
    if not node.has_parameter('frame_prefix'):
        node.declare_parameter('frame_prefix', node.get_namespace().strip('/'))
    prefix = node.get_parameter('frame_prefix').value
    if not isinstance(prefix, str) or prefix.startswith('/') or '//' in prefix:
        raise ValueError('frame_prefix must be a relative TF prefix')
    return prefix.rstrip('/') + '/' if prefix else ''


class _RobotFrameMixin:
    def robot_frame(self, frame):
        if frame in _LOCAL_FRAMES:
            return self.frame_prefix + frame
        return frame


class RobotTransformBuffer(_RobotFrameMixin, Buffer):
    def __init__(self, node):
        self.frame_prefix = _frame_prefix(node)
        super().__init__()

    def lookup_transform(self, target_frame, source_frame, time, *args, **kwargs):
        return super().lookup_transform(self.robot_frame(target_frame),
                                        self.robot_frame(source_frame), time, *args, **kwargs)

    def lookup_transform_full(self, target_frame, target_time, source_frame, source_time, fixed_frame,
                              *args, **kwargs):
        return super().lookup_transform_full(self.robot_frame(target_frame), target_time,
                                             self.robot_frame(source_frame), source_time,
                                             self.robot_frame(fixed_frame), *args, **kwargs)


class SharedRobotTransformBuffer(_RobotFrameMixin):
    """Share an existing tf2_ros.Buffer with robot-local frame translation."""

    def __init__(self, node, buffer):
        self.frame_prefix = _frame_prefix(node)
        self._buffer = buffer

    def lookup_transform(self, target_frame, source_frame, time, *args, **kwargs):
        return self._buffer.lookup_transform(self.robot_frame(target_frame),
                                               self.robot_frame(source_frame), time, *args, **kwargs)

    def lookup_transform_full(self, target_frame, target_time, source_frame, source_time, fixed_frame,
                              *args, **kwargs):
        return self._buffer.lookup_transform_full(self.robot_frame(target_frame), target_time,
                                                    self.robot_frame(source_frame), source_time,
                                                    self.robot_frame(fixed_frame), *args, **kwargs)
