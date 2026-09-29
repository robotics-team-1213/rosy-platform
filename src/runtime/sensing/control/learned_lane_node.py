"""learned_lane_node — shadow inference of a learned lane model (D-356).

Subscribes camera/front (sensor_msgs/Image) and line/observation (rule-based
CAMERA_LINE error for comparison). Publishes perception/learned/shadow
(std_msgs/String JSON). No consumer in the control path reads it; this node
never publishes cmd_vel (D-2, D-209). The model comes from the pointer file
/var/lib/rosy/models/shadow (parameter `pointer`) and swaps without restart."""

import json

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from . import executor_choice
from .sensing.perception.image_frame import image_msg_to_frame
from .sensing.perception.learned.runner import ModelSlot
from .sensing.perception.learned.shadow import TOPIC, shadow_payload

RULE_MAX_AGE_S = 0.5  # older rule evidence is not compared


def _image_to_bgr(msg: Image) -> np.ndarray:
    frame = image_msg_to_frame(msg)
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    return np.ascontiguousarray(frame)


class LearnedLaneNode(Node):
    def __init__(self):
        super().__init__('learned_lane_node')
        pointer = self.declare_parameter('pointer', '/var/lib/rosy/models/shadow').value
        self._slot = ModelSlot(pointer)
        self._busy = False  # only matters under a MultiThreadedExecutor
        self._rule_error = None
        self._rule_stamp = None
        self._logged_error = None
        self._logged_revision = None
        self._pub = self.create_publisher(String, TOPIC, 10)
        self.create_subscription(Image, 'camera/front', self._on_camera, 1)
        self.create_subscription(String, 'line/observation', self._on_rule, 10)

    def _on_rule(self, msg: String) -> None:
        try:
            doc = json.loads(msg.data)
        except ValueError:
            return
        if not isinstance(doc, dict):
            return
        if doc.get('source') == 'CAMERA_LINE':
            self._rule_error = doc.get('error') if doc.get('visible') else None
            stamp = doc.get('stamp')
            ok = isinstance(stamp, (int, float)) and not isinstance(stamp, bool)
            self._rule_stamp = float(stamp) if ok else None

    def _on_camera(self, msg: Image) -> None:
        if self._busy:
            return  # drop frames while inferring
        try:
            model = self._slot.poll()
        except Exception as exc:
            self.get_logger().warn(f'shadow model poll failed: {exc}',
                                   throttle_duration_sec=5.0)
            return
        error = self._slot.last_error
        if error != self._logged_error:
            self._logged_error = error
            if error:
                self.get_logger().warn(f'shadow model not updated: {error}')
        if model is None:
            return
        if model.model_revision != self._logged_revision:
            self._logged_revision = model.model_revision
            self.get_logger().info(f'shadow model {model.model_revision}')
        self._busy = True
        try:
            bgr = _image_to_bgr(msg)
            result = model.infer(bgr)
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            rule_error = self._rule_error
            if (self._rule_stamp is None
                    or abs(stamp - self._rule_stamp) > RULE_MAX_AGE_S):
                rule_error = None
            payload = shadow_payload(result, stamp=stamp, rule_error=rule_error)
            self._pub.publish(String(data=json.dumps(payload, sort_keys=True)))
        except Exception as exc:
            self.get_logger().warn(f'shadow inference failed: {exc}',
                                   throttle_duration_sec=5.0)
        finally:
            self._busy = False


def main():
    rclpy.init()
    node = LearnedLaneNode()
    try:
        executor_choice.spin(node, rclpy)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
