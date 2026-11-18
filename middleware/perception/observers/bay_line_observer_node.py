#!/usr/bin/env python3
"""Publish the charge-bay pink guide line (``dock/observation``, D-1013).

This node owns no motion output. It reports the guide line as the virtual
dock in base_link; CORE's docking manager decides the motion and remains the
sole final ``cmd_vel`` publisher (D-2, D-143 pattern). Camera geometry is
declared, not calibrated: the Gazebo camera (``camera_geometry_source``
GAZEBO under ``use_sim_time``) may project. On a robot, NOMINAL with
``allow_nominal_ground`` projects through camera_nominal.yaml and labels each
payload ``ground: NOMINAL``; CORE docks on it from one button press (user decision
2026-11-18, D-1042 6). Anything else fails closed like the dock tag observer —
every frame publishes not visible, never a guess.
"""

import json

import yaml

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String

from . import executor_choice
from .sensing.bay_line_observer import BayLineObserver, nominal_geometry
from .sensing.dock_tag import CameraMount


class BayLineObserverNode(Node):
    def __init__(self):
        super().__init__('bay_line_observer_node')
        self.declare_parameter('camera_geometry_source', 'PINKY')
        self.declare_parameter('camera_height_m', 0.0)
        self.declare_parameter('camera_pitch_rad', 0.0)
        self.declare_parameter('camera_hfov_rad', 0.0)
        self.declare_parameter('camera_x_offset_m', 0.0)
        self.declare_parameter('allow_nominal_ground', False)
        self.declare_parameter('nominal_camera_profile_path', '')
        # Stop face -> line's corridor-side end (site constant, unmeasured).
        self.declare_parameter('line_total_m', 0.65)
        self.declare_parameter('far_field_m', 0.45)
        self.declare_parameter('frame_width', 320)
        self.declare_parameter('frame_height', 180)

        self._ground = None
        self._observer = self._build_observer()
        self.observation_pub = self.create_publisher(String, 'dock/observation', 10)
        self.create_subscription(Image, 'camera/front', self._on_camera,
                                 qos_profile_sensor_data)

    def _build_observer(self):
        source = str(self.get_parameter('camera_geometry_source').value).strip().upper()
        use_sim_time = bool(self.get_parameter('use_sim_time').value)
        if source == 'NOMINAL' and bool(self.get_parameter('allow_nominal_ground').value):
            return self._build_nominal()
        if source != 'GAZEBO' or not use_sim_time:
            self.get_logger().warning(
                'bay line needs declared GAZEBO camera geometry under use_sim_time; '
                'no observer built, dock/observation stays not visible')
            return None
        try:
            return BayLineObserver(
                mount=CameraMount(
                    height_m=float(self.get_parameter('camera_height_m').value),
                    pitch_rad=float(self.get_parameter('camera_pitch_rad').value),
                    x_offset_m=float(self.get_parameter('camera_x_offset_m').value)),
                hfov_rad=float(self.get_parameter('camera_hfov_rad').value),
                width=int(self.get_parameter('frame_width').value),
                height=int(self.get_parameter('frame_height').value),
                line_total_m=float(self.get_parameter('line_total_m').value),
                far_field_m=float(self.get_parameter('far_field_m').value))
        except ValueError as exc:
            self.get_logger().warning(
                f'invalid bay line camera geometry ({exc}); no observer built, '
                'dock/observation stays not visible')
            return None

    def _build_nominal(self):
        path = str(self.get_parameter('nominal_camera_profile_path').value)
        try:
            with open(path, encoding='utf-8') as handle:
                mount, hfov, width, height = nominal_geometry(yaml.safe_load(handle) or {})
            observer = BayLineObserver(
                mount=CameraMount(**mount), hfov_rad=hfov, width=width, height=height,
                line_total_m=float(self.get_parameter('line_total_m').value),
                far_field_m=float(self.get_parameter('far_field_m').value))
        except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
            self.get_logger().warning(
                f'nominal bay line geometry unusable ({exc}); dock/observation stays not visible')
            return None
        self._ground = 'NOMINAL'
        return observer

    def _on_camera(self, msg: Image) -> None:
        stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
        payload = {"source": "CAMERA_LINE", "visible": False, "stamp": stamp,
                   "tag_id": None}
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
                if self._ground:
                    payload['ground'] = self._ground
            except ValueError as exc:
                self.get_logger().warning(f'invalid camera frame for bay line: {exc}',
                                          throttle_duration_sec=5.0)
        self.observation_pub.publish(String(data=json.dumps(payload, sort_keys=True)))


def main():
    rclpy.init()
    node = BayLineObserverNode()
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
