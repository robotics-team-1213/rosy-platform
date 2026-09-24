#!/usr/bin/env python3
"""Publish dock tag evidence (``dock/observation``) from camera frames.

This node owns no motion output. It reports where the parking tag is in
base_link; CORE's docking manager decides the motion and remains the sole
final ``cmd_vel`` publisher (D-2, D-143 pattern).

Camera geometry is declared, not calibrated: only the Gazebo camera
(``camera_geometry_source`` GAZEBO under ``use_sim_time``) may use the
declared height / pitch / hfov / offset. Anything else fails closed: no
observer is built, a warning is logged once, and every frame publishes a
not-visible observation, so CORE reads a lost tag, never a guessed one.
"""

import json

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String

from . import executor_choice
from .sensing.dock_observer import DockTagObserver, dock_observation_payload
from .sensing.dock_tag import CameraMount


class DockObserverNode(Node):
    def __init__(self):
        super().__init__('dock_observer_node')
        self.declare_parameter('tag_id', 7)
        self.declare_parameter('tag_size_m', 0.05)
        self.declare_parameter('camera_geometry_source', 'PINKY')
        self.declare_parameter('camera_height_m', 0.0)
        self.declare_parameter('camera_pitch_rad', 0.0)
        self.declare_parameter('camera_hfov_rad', 0.0)
        self.declare_parameter('camera_x_offset_m', 0.0)

        self._observer = self._build_observer()
        self.observation_pub = self.create_publisher(String, 'dock/observation', 10)
        self.create_subscription(Image, 'camera/front', self._on_camera,
                                 qos_profile_sensor_data)

    def _build_observer(self):
        source = str(self.get_parameter('camera_geometry_source').value).strip().upper()
        use_sim_time = bool(self.get_parameter('use_sim_time').value)
        if source != 'GAZEBO' or not use_sim_time:
            self.get_logger().warning(
                'dock tag needs declared GAZEBO camera geometry under use_sim_time; '
                'no observer built, dock/observation stays not visible')
            return None
        try:
            return DockTagObserver(
                tag_id=int(self.get_parameter('tag_id').value),
                tag_size_m=float(self.get_parameter('tag_size_m').value),
                mount=CameraMount(
                    height_m=float(self.get_parameter('camera_height_m').value),
                    pitch_rad=float(self.get_parameter('camera_pitch_rad').value),
                    x_offset_m=float(self.get_parameter('camera_x_offset_m').value)),
                hfov_rad=float(self.get_parameter('camera_hfov_rad').value))
        except ValueError as exc:
            self.get_logger().warning(
                f'invalid dock tag or camera geometry ({exc}); no observer built, '
                'dock/observation stays not visible')
            return None

    def _on_camera(self, msg: Image) -> None:
        stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
        payload = dock_observation_payload(stamp, None)
        if self._observer is not None:
            try:
                channels = 1 if msg.encoding == 'mono8' else 3
                if msg.encoding not in ('mono8', 'bgr8', 'rgb8'):
                    raise ValueError(f'unsupported camera encoding {msg.encoding!r}')
                pixels = np.frombuffer(msg.data, dtype=np.uint8)
                if pixels.size != int(msg.height) * int(msg.width) * channels:
                    raise ValueError('camera payload size does not match dimensions')
                frame = pixels.reshape((int(msg.height), int(msg.width), channels))
                frame = np.ascontiguousarray(frame[:, :, 0] if channels == 1 else (
                    frame[:, :, ::-1] if msg.encoding == 'rgb8' else frame))
                payload = self._observer.observe(frame, stamp)
            except ValueError as exc:
                self.get_logger().warning(f'invalid camera frame for dock tag: {exc}',
                                          throttle_duration_sec=5.0)
        self.observation_pub.publish(String(data=json.dumps(payload, sort_keys=True)))


def main():
    rclpy.init()
    node = DockObserverNode()
    try:
        executor_choice.spin(node, rclpy)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
