"""object_detector_node -- advisory object detection (D-423 §2).

Subscribes camera/front (best effort, depth 1) and, with region_lidar_range,
scan. Publishes vision/detections (std_msgs/String JSON: DetectionEvidence
fields plus an additive `ranges` list) and, at 1 Hz, latched
perception/learned/object_det/status. The model comes from the pointer file
/var/lib/rosy/models/object_det/active (parameter `pointer`) and swaps without
restart. Off unless camera_preview.launch.py object_det:=true (ROSY_OBJECT_DET).

Advisory only (D-137): CORE does not read vision/detections, and this node never
publishes cmd_vel. The ROS-free logic lives in object_detector.py."""

import json
import math

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import Image, LaserScan
from std_msgs.msg import String

from . import executor_choice
from .calibrated_values import finite_overrides, lidar_nose_rad, nominal_camera_profile
from .object_detector import STATUS_TOPIC, TOPIC, BoxRanger, ObjectDetectorCore
from .sensing.body import LIDAR_X
from .sensing.lidar import enable_simulation_scans, is_robot_scan
from .sensing.perception.camera_ground import nominal_ground_plane
from .sensing.perception.image_frame import image_msg_to_frame
from .sensing.perception.learned.detector import CONFIDENCE, IOU, ObjectDetModel
from .sensing.perception.learned.runner import ModelSlot
from .sensing.perception.learned.signature import TRUSTED_KEYS, checked_opener
from .sensing.perception.learned.slots import slot_pointer


class ObjectDetectorNode(Node):
    def __init__(self):
        super().__init__('object_detector_node')
        p = lambda name, default: self.declare_parameter(name, default).value  # noqa: E731
        pointer = p('pointer', slot_pointer('object_det', 'active'))
        threads, conf, iou = int(p('threads', 2)), float(p('confidence', CONFIDENCE)), float(p('iou', IOU))
        # D-423 §3.4: only release-signed bundles; allow_unsigned_models is a dev-only override.
        opener = checked_opener(lambda folder: ObjectDetModel.open(folder, threads=threads, conf=conf, iou=iou),
                                allow_unsigned=bool(p('allow_unsigned_models', False)),
                                keys_dir=str(p('trusted_keys_dir', TRUSTED_KEYS)))
        self._slot = ModelSlot(pointer, opener=opener)
        self._core = ObjectDetectorCore(self._slot, max_rate_hz=float(p('max_rate_hz', 2.0)),
                                        camera_fps=float(p('camera_fps', 8.0)), ranger=self._ranger(p))
        self._busy, self._logged_error = False, None
        self._pub = self.create_publisher(String, TOPIC, 10)
        self._status_pub = self.create_publisher(String, STATUS_TOPIC, QoSProfile(
            depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE))
        self.create_timer(1.0, self._publish_status)
        self.create_subscription(Image, 'camera/front', self._on_camera,
                                 QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
        self._publish_status()

    def _ranger(self, p):
        """BoxRanger from the NOMINAL plane (as camera_detect_node mode 'nominal'), or None."""
        path, allow = str(p('nominal_camera_profile_path', '')), bool(p('allow_nominal_ground', False))
        size = (int(p('width', 320)), int(p('height', 240)))
        overrides = {k: p(f'camera_{k}_override', math.nan) for k in ('pitch_rad', 'height_m')}
        yaw_override = p('lidar_yaw_offset_override', math.nan)
        lidar, sim = bool(p('region_lidar_range', False)), bool(p('accept_simulation_scans', False))
        tolerance = (float(p('region_lidar_max_age_s', 0.3)), float(p('region_lidar_tolerance_m', 0.05)),
                     float(p('region_lidar_tolerance_ratio', 0.2)))
        if not path:
            return None
        profile, source = nominal_camera_profile(path, override=finite_overrides(overrides))
        self.get_logger().info(f'camera profile from {source}')
        plane = nominal_ground_plane(source='NOMINAL', allowed=allow, width_px=size[0],
                                     height_px=size[1], profile=profile)
        if plane is None:
            self.get_logger().warn('NOMINAL ground refused; detections stay unranged')
            return None
        nose = None
        if lidar and profile.get('x_offset_m') is not None:
            if sim:
                enable_simulation_scans(True)  # process-wide: every is_robot_scan caller here
            nose, nose_source = lidar_nose_rad(override=finite_overrides({'lidar_yaw_offset': yaw_override}))
            self.get_logger().info(f'detection LiDAR range on; lidar forward from {nose_source}')
            self.create_subscription(LaserScan, 'scan', self._on_scan, qos_profile_sensor_data)
        return BoxRanger(plane, frame_size=size, camera_x_m=profile.get('x_offset_m'), nose_rad=nose,
                         lidar_x_m=LIDAR_X, max_age_s=tolerance[0], tolerance_m=tolerance[1],
                         tolerance_ratio=tolerance[2])

    def _on_scan(self, msg):
        if is_robot_scan(msg):
            self._core.ranger.set_scan(msg.ranges, msg.angle_min, msg.angle_increment, msg.range_min,
                                       msg.range_max, stamp=msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9)

    def _publish_status(self):
        try:
            self._slot.poll()  # report a missing or broken model even with no camera frames
        except Exception as exc:
            self.get_logger().warn(f'object_det model poll failed: {exc}', throttle_duration_sec=5.0)
        payload = self._core.status_payload()
        if payload['last_error'] != self._logged_error:
            self._logged_error = payload['last_error']
            if self._logged_error:
                self.get_logger().warn(f'object_det: {self._logged_error}')
        self._status_pub.publish(String(data=json.dumps(payload, sort_keys=True)))

    def _on_camera(self, msg):
        if self._busy:
            return
        self._busy = True
        try:
            frame = image_msg_to_frame(msg)
            bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR) if frame.ndim == 2 else np.ascontiguousarray(frame)
            packet = self._core.on_frame(bgr, stamp=msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9)
            if packet is not None:
                self._pub.publish(String(data=json.dumps(packet, sort_keys=True)))
        except Exception as exc:
            self.get_logger().warn(f'object detection failed: {exc}', throttle_duration_sec=5.0)
        finally:
            self._busy = False


def main():
    rclpy.init()
    node = ObjectDetectorNode()
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
