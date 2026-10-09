"""learned_lane_node — shadow inference of a learned lane model (D-356).

Subscribes camera/front (sensor_msgs/Image) and line/observation (rule-based
CAMERA_LINE error for comparison). Publishes perception/learned/shadow
(std_msgs/String JSON) and, at 1 Hz, perception/learned/status (model,
last error, frame counters, latency p50; D-373, D-62). No consumer in the control path reads it; this node
never publishes cmd_vel (D-2, D-209). The model comes from the pointer file
/var/lib/rosy/models/shadow (parameter `pointer`) and swaps without restart.
`visible` is latched per stream (VisibleHysteresis, on 0.35 / off below 0.25;
2026-10-02 audit); a swapped model starts a fresh latch."""

import dataclasses
import json
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import String

from . import executor_choice
from .sensing.perception.image_frame import image_msg_to_frame
from .sensing.perception.learned.lane_mask import VisibleHysteresis
from .sensing.perception.learned.runner import LaneSegModel, ModelSlot
from .sensing.perception.learned.shadow import TOPIC, RuleRing, shadow_payload
from .sensing.perception.learned.signature import TRUSTED_KEYS, SignatureCheck
from .sensing.perception.learned.status import STATUS_TOPIC, LearnedStatus, rate_limited


def _image_to_bgr(msg: Image) -> np.ndarray:
    frame = image_msg_to_frame(msg)
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    return np.ascontiguousarray(frame)


class LearnedLaneNode(Node):
    def __init__(self):
        super().__init__('learned_lane_node')
        pointer = self.declare_parameter('pointer', '/var/lib/rosy/models/shadow').value
        # D-373 CPU budget: ~175 % of a Pi 5 at the full 8 fps (2026-10-01), too
        # heavy for an always-on shadow. Infer at most max_rate_hz; 0 = no limit.
        self._max_rate_hz = float(self.declare_parameter('max_rate_hz', 3.0).value)
        threads = int(self.declare_parameter('threads', 2).value)
        # D-423 (2026-10-03): lane_seg signatures are warn-only until the field's 0930
        # model is signed; the status reports signed and an unsigned model is logged.
        self._signature = SignatureCheck(lambda folder: LaneSegModel.open(folder, threads=threads),
                                         enforce=False, keys_dir=TRUSTED_KEYS)
        self._slot = ModelSlot(pointer, opener=self._signature)
        self._last_infer: float | None = None
        self._busy = False  # only matters under a MultiThreadedExecutor
        # Rule answers keyed by image stamp: compared per frame, not newest-wins.
        self._rules = RuleRing()
        self._visible = VisibleHysteresis()
        self._logged_error = None
        self._logged_revision = None
        self._pub = self.create_publisher(String, TOPIC, 10)
        fps = float(self.declare_parameter('camera_fps', 8.0).value)  # camera.yaml fps
        self._status = LearnedStatus(period_s=1.0 / max(fps, 0.1))
        # Latched: a subscriber that joins late (dashboard, an echo on a loaded
        # host) gets the current status instead of waiting for the next tick.
        self._status_pub = self.create_publisher(String, STATUS_TOPIC, QoSProfile(
            depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE))
        self.create_timer(1.0, self._publish_status)
        # camera_detect_node publishes best effort (sensor data); a reliable
        # subscriber is QoS-incompatible and never receives a frame (seen in the
        # D-373 WSL run). Depth 1: only the newest frame is worth inferring (D-185).
        self.create_subscription(Image, 'camera/front', self._on_camera,
                                 QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_subscription(String, 'line/observation', self._on_rule, 10)
        self._publish_status()

    def _on_rule(self, msg: String) -> None:
        try:
            doc = json.loads(msg.data)
        except ValueError:
            return
        if not isinstance(doc, dict):
            return
        if doc.get('source') == 'CAMERA_LINE':
            stamp = doc.get('stamp')
            if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
                self._rules.add(float(stamp), doc.get('visible') is True, doc.get('error'))

    def _publish_status(self) -> None:
        try:
            self._slot.poll()  # report a missing/broken model even with no camera frames
        except Exception as exc:
            self.get_logger().warn(f'shadow model poll failed: {exc}',
                                   throttle_duration_sec=5.0)
        model = self._slot.current
        payload = self._status.payload(
            model_revision=model.model_revision if model is not None else None,
            last_error=self._slot.last_error,
            signed=self._signature.signed if model is not None else None)
        self._status_pub.publish(String(data=json.dumps(payload, sort_keys=True)))

    def _on_camera(self, msg: Image) -> None:
        self._status.frame_in(msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9)
        if self._busy:
            self._status.frame_skipped()  # still inferring the previous frame
            return
        now = time.monotonic()
        if rate_limited(now, self._last_infer, self._max_rate_hz):
            self._status.frame_rate_limited()
            return
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
            self._visible = VisibleHysteresis()
            version = getattr(getattr(model, 'manifest', None), 'model_version', None)  # D-558
            self.get_logger().info(f'shadow model {model.model_revision}'
                                   + (f' ({version})' if version else ''))
            if self._signature.signed is False:
                self.get_logger().warn(f'shadow model {model.model_revision} is not release-signed '
                                       f'({self._signature.reason}); warn-only for lane_seg (D-423)')
        self._busy = True
        self._last_infer = now
        try:
            bgr = _image_to_bgr(msg)
            result = model.infer(bgr)
            self._status.frame_inferred(result.latency_ms)
            result = dataclasses.replace(result, evidence=self._visible.update(result.evidence))
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            rule_visible, rule_error = self._rules.match(stamp)
            payload = shadow_payload(result, stamp=stamp, rule_error=rule_error,
                                     rule_visible=rule_visible)
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
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
