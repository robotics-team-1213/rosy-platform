#!/usr/bin/env python3
"""Publish normalized white-line evidence from IR reflectance or camera frames.

This node owns no motion output. CORE chooses exactly one source and remains
the sole final ``cmd_vel`` publisher (D-143).
"""

import json
import math

import cv2
import numpy as np
import rclpy
import yaml
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from nav_msgs.msg import Odometry
from rcl_interfaces.msg import ParameterDescriptor
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String, UInt16MultiArray

from .sensing.camera_ground import simulation_ground_plane
from .sensing.lane import (
    IRLineCalibration,
    LaneCornerTracker,
    detect_ir_line,
    detect_lane_centre,
    detect_lane_error,
    line_observation_payload,
)
from .sensing.lane_bev import LaneEdgeFollower, pose_if_fresh
from .sensing.lane_boundaries import LaneBoundaryTracker
from .sensing.lane_debug import render_debug

#: Fixed at startup: the edge follower and the odom subscription are built
#: from these once, so a later change would silently run the wrong pipeline.
_READ_ONLY = ParameterDescriptor(read_only=True)


class LineObserverNode(Node):
    def __init__(self):
        super().__init__('line_observer_node')
        self.declare_parameter('ir_calibration_enabled', False)
        self.declare_parameter('ir_black', [0.0, 0.0, 0.0])
        self.declare_parameter('ir_white', [0.0, 0.0, 0.0])
        self.declare_parameter('ir_min_span', 100.0)
        self.declare_parameter('ir_min_white', 0.55)
        self.declare_parameter('ir_min_contrast', 0.15)
        self.declare_parameter('camera_bright_threshold', 180)
        self.declare_parameter('camera_roi_top_fraction', 0.4)
        self.declare_parameter('camera_washed_fraction', 0.4)
        self.declare_parameter('camera_min_pixels', 80)
        self.declare_parameter('require_camera_controls_stable', True)
        # 'line' follows one bright line; 'lane' keeps the centre between two
        # boundary lines; 'edge_left' holds the lane's left boundary a
        # half-width off in bird's-eye view (bends, arcs). Both lane modes need
        # a metric ground plane, edge_left also odometry (fail-closed without).
        # 'centre' follows the centre line between both boundaries (fallback ladder).
        self.declare_parameter('camera_lane_mode', 'line', _READ_ONLY)
        self.declare_parameter('lane_half_width_m', 0.0925)
        self.declare_parameter('camera_roi_bottom_fraction', 1.0)
        self.declare_parameter('camera_ground_source', 'PINKY')
        self.declare_parameter('allow_simulation_ground', False)
        self.declare_parameter('gazebo_camera_height_m', 0.0)
        self.declare_parameter('gazebo_camera_pitch_rad', 0.0)
        self.declare_parameter('gazebo_camera_hfov_rad', 0.0)
        self.declare_parameter('gazebo_camera_max_range_m', 0.6)
        # Lane mode only: odometry-bounded 90 deg corner turning. Off by
        # default; without odometry the tracker never leaves FOLLOW.
        self.declare_parameter('lane_corner_turning', False, _READ_ONLY)
        self.declare_parameter('camera_x_offset_m', 0.0)
        self.declare_parameter('debug_overlay', False, _READ_ONLY)
        self.declare_parameter('debug_overlay_max_hz', 5.0)
        self.declare_parameter('debug_lane_graph', '')

        self._ir_calibration = None
        self._camera_controls_stable = False
        self._simulation_ground_key = None
        self._simulation_ground = None
        self._odom_pose = None
        self._odom_stamp = None
        self._corner_tracker = LaneCornerTracker(
            camera_x_offset_m=float(self.get_parameter('camera_x_offset_m').value))
        self._edge_follower = LaneEdgeFollower(
            camera_x_offset_m=float(self.get_parameter('camera_x_offset_m').value),
            corner_handoff=bool(self.get_parameter('lane_corner_turning').value))
        self._centre_tracker = LaneBoundaryTracker(
            camera_x_offset_m=float(self.get_parameter('camera_x_offset_m').value))
        self._debug_pub = None
        self._debug_last_s = None
        self._debug_graph = None
        if bool(self.get_parameter('debug_overlay').value):
            self._debug_pub = self.create_publisher(
                CompressedImage, 'line/debug/compressed', 2)
            path = str(self.get_parameter('debug_lane_graph').value)
            if path:
                with open(path, encoding='utf-8') as handle:
                    self._debug_graph = yaml.safe_load(handle)
        if bool(self.get_parameter('ir_calibration_enabled').value):
            self._ir_calibration = IRLineCalibration(
                black=tuple(self.get_parameter('ir_black').value),
                white=tuple(self.get_parameter('ir_white').value),
                min_span=float(self.get_parameter('ir_min_span').value),
            )

        self.observation_pub = self.create_publisher(String, 'line/observation', 10)
        self.create_subscription(
            UInt16MultiArray, 'ir_sensor/range', self._on_ir, qos_profile_sensor_data)
        self.create_subscription(
            Image, 'camera/front', self._on_camera, qos_profile_sensor_data)
        controls_qos = QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(
            String, 'camera/controls', self._on_camera_controls, controls_qos)
        mode = str(self.get_parameter('camera_lane_mode').value)
        if mode in ('lane', 'edge_left', 'centre'):
            self.create_subscription(
                Odometry, 'odom', self._on_odom, qos_profile_sensor_data)
        if self._ir_calibration is None:
            self.get_logger().warning(
                'IR line calibration disabled; IR_LINE will remain fail-closed')

    def _ground(self, width: int, height: int):
        source = str(self.get_parameter('camera_ground_source').value)
        simulation_enabled = bool(
            self.get_parameter('allow_simulation_ground').value)
        use_sim_time = bool(self.get_parameter('use_sim_time').value)
        height_m = float(self.get_parameter('gazebo_camera_height_m').value)
        pitch_rad = float(self.get_parameter('gazebo_camera_pitch_rad').value)
        hfov_rad = float(self.get_parameter('gazebo_camera_hfov_rad').value)
        max_range_m = float(self.get_parameter(
            'gazebo_camera_max_range_m').value)
        key = (source, simulation_enabled, use_sim_time, int(width),
               int(height), height_m, pitch_rad, hfov_rad, max_range_m)
        if key != self._simulation_ground_key:
            self._simulation_ground = simulation_ground_plane(
                source=source,
                simulation_enabled=simulation_enabled,
                use_sim_time=use_sim_time,
                width_px=width,
                height_px=height,
                height_m=height_m,
                pitch_rad=pitch_rad,
                hfov_rad=hfov_rad,
                max_range_m=max_range_m,
            )
            self._simulation_ground_key = key
        return self._simulation_ground

    def _stamp(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _publish(self, source, observation, *, stamp=None) -> None:
        payload = line_observation_payload(
            source, self._stamp() if stamp is None else stamp, observation)
        self.observation_pub.publish(String(data=json.dumps(payload, sort_keys=True)))

    def _on_ir(self, msg: UInt16MultiArray) -> None:
        observation = None
        if self._ir_calibration is not None:
            try:
                observation = detect_ir_line(
                    list(msg.data), self._ir_calibration,
                    min_white=float(self.get_parameter('ir_min_white').value),
                    min_contrast=float(self.get_parameter('ir_min_contrast').value),
                )
            except ValueError as exc:
                self.get_logger().warning(f'invalid IR line sample: {exc}')
        self._publish('IR_LINE', observation)

    def _on_camera(self, msg: Image) -> None:
        observation = None
        frame = None
        if (bool(self.get_parameter(
                'require_camera_controls_stable').value)
                and not self._camera_controls_stable):
            self._publish('CAMERA_LINE', None, stamp=(
                float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9))
            return
        try:
            channels = 1 if msg.encoding == 'mono8' else 3
            if msg.encoding not in ('mono8', 'bgr8', 'rgb8'):
                raise ValueError(f'unsupported camera encoding {msg.encoding!r}')
            expected = int(msg.height) * int(msg.width) * channels
            pixels = np.frombuffer(msg.data, dtype=np.uint8)
            if pixels.size != expected:
                raise ValueError('camera payload size does not match dimensions')
            frame = pixels.reshape((int(msg.height), int(msg.width), channels))
            if channels == 1:
                frame = frame[:, :, 0]
            elif msg.encoding == 'rgb8':
                frame = frame[:, :, ::-1]
            mode = str(self.get_parameter('camera_lane_mode').value)
            if mode == 'line':
                observation = detect_lane_error(
                    frame,
                    bright_threshold=int(self.get_parameter('camera_bright_threshold').value),
                    roi_top_fraction=float(self.get_parameter('camera_roi_top_fraction').value),
                    washed_fraction=float(self.get_parameter('camera_washed_fraction').value),
                    min_pixels=int(self.get_parameter('camera_min_pixels').value),
                )
            elif mode in ('lane', 'edge_left', 'centre'):
                ground = self._ground(frame.shape[1], frame.shape[0])
                lane_kwargs = dict(
                    bright_threshold=int(self.get_parameter('camera_bright_threshold').value),
                    lane_half_width_m=float(self.get_parameter('lane_half_width_m').value),
                    roi_top_fraction=float(self.get_parameter('camera_roi_top_fraction').value),
                    roi_bottom_fraction=float(
                        self.get_parameter('camera_roi_bottom_fraction').value),
                    washed_fraction=float(self.get_parameter('camera_washed_fraction').value),
                )
                if mode == 'centre':
                    image_stamp = (float(msg.header.stamp.sec)
                                   + float(msg.header.stamp.nanosec) * 1e-9)
                    observation = self._centre_tracker.update(
                        image_stamp,
                        pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                        frame, ground, **lane_kwargs)
                elif mode == 'edge_left':
                    image_stamp = (float(msg.header.stamp.sec)
                                   + float(msg.header.stamp.nanosec) * 1e-9)
                    observation = self._edge_follower.update(
                        image_stamp,
                        pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                        frame, ground, **lane_kwargs)
                elif bool(self.get_parameter('lane_corner_turning').value):
                    image_stamp = (float(msg.header.stamp.sec)
                                   + float(msg.header.stamp.nanosec) * 1e-9)
                    observation = self._corner_tracker.update(
                        image_stamp,
                        pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                        frame, ground, **lane_kwargs)
                else:
                    observation = detect_lane_centre(frame, ground, **lane_kwargs)
            else:
                raise ValueError(f'unsupported camera_lane_mode {mode!r}')
        except ValueError as exc:
            self.get_logger().warning(f'invalid camera line frame: {exc}')
        source_stamp = (float(msg.header.stamp.sec)
                        + float(msg.header.stamp.nanosec) * 1e-9)
        self._publish('CAMERA_LINE', observation, stamp=source_stamp)
        self._publish_debug(msg, frame, observation)

    def _publish_debug(self, msg, frame, observation) -> None:
        """Observation only: a picture of the decision just published."""
        if self._debug_pub is None or frame is None:
            return
        stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
        period = 1.0 / max(0.1, float(self.get_parameter('debug_overlay_max_hz').value))
        if self._debug_last_s is not None and 0.0 <= stamp - self._debug_last_s < period:
            return
        self._debug_last_s = stamp
        mode = str(self.get_parameter('camera_lane_mode').value)
        follower = {'centre': self._centre_tracker, 'edge_left': self._edge_follower}.get(mode)
        if follower is None:
            return
        image = render_debug(
            frame, follower, observation, mode=mode,
            pose=pose_if_fresh(self._odom_pose, self._odom_stamp, stamp),
            graph=self._debug_graph,
            bright_threshold=int(self.get_parameter('camera_bright_threshold').value))
        ok, data = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return
        out = CompressedImage()
        out.header = msg.header
        out.format = 'jpeg; overlay=lane-debug-v1'
        out.data = data.tobytes()
        self._debug_pub.publish(out)

    def _on_odom(self, msg: Odometry) -> None:
        pose = msg.pose.pose
        q = pose.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                         1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        self._odom_pose = (float(pose.position.x), float(pose.position.y), yaw)
        # The header stamp, not arrival time: edge_left compares it with the
        # image stamp, so dead or delayed odometry is no pose.
        self._odom_stamp = (float(msg.header.stamp.sec)
                            + float(msg.header.stamp.nanosec) * 1e-9)

    def _on_camera_controls(self, msg: String) -> None:
        summary = str(msg.data)
        self._camera_controls_stable = (
            summary.startswith('exposure=') or summary.startswith('v4l2 exposure='))


def main():
    rclpy.init()
    node = LineObserverNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
