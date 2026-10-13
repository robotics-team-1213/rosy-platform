"""Optional ROS 2 Jazzy receiver for one selected local workcell camera."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image

from .camera_contract import CameraFrameGate, CameraFrameMetadata, CameraStreamConfig


class RosCameraStreamRuntime:
    """Pair Image and CameraInfo by exact capture stamp with bounded buffering.

    This node adapter does not select a camera driver or device path. The
    operator-supplied persistent identity must be resolved by deployment before
    construction. Only one accepted image/info pair is retained for consumers.
    """

    def __init__(
        self,
        node: Any,
        config: CameraStreamConfig,
        *,
        image_topic: str,
        camera_info_topic: str,
        pending_pairs: int = 4,
    ) -> None:
        if not image_topic.strip() or not camera_info_topic.strip():
            raise ValueError("camera image and CameraInfo topics must be explicit")
        if type(pending_pairs) is not int or pending_pairs < 1:
            raise ValueError("pending_pairs must be a positive integer")
        self.gate = CameraFrameGate(config)
        self.latest_frame: tuple[CameraFrameMetadata, Image, CameraInfo] | None = None
        self.last_error: str | None = None
        self._pending_limit = pending_pairs
        self._images: OrderedDict[int, Image] = OrderedDict()
        self._infos: OrderedDict[int, CameraInfo] = OrderedDict()
        self._image_sub = node.create_subscription(
            Image, image_topic, self._on_image, qos_profile_sensor_data
        )
        self._info_sub = node.create_subscription(
            CameraInfo, camera_info_topic, self._on_info, qos_profile_sensor_data
        )
        self._node = node

    @staticmethod
    def _key(message: Any) -> int:
        stamp = message.header.stamp
        return stamp.sec * 1_000_000_000 + stamp.nanosec

    def _trim(self, pending: OrderedDict[int, Any]) -> None:
        while len(pending) > self._pending_limit:
            pending.popitem(last=False)

    def _on_image(self, message: Image) -> None:
        self._images[self._key(message)] = message
        self._images.move_to_end(self._key(message))
        self._trim(self._images)
        self._try_pair(self._key(message))

    def _on_info(self, message: CameraInfo) -> None:
        self._infos[self._key(message)] = message
        self._infos.move_to_end(self._key(message))
        self._trim(self._infos)
        self._try_pair(self._key(message))

    def _try_pair(self, stamp_ns: int) -> None:
        image = self._images.get(stamp_ns)
        info = self._infos.get(stamp_ns)
        if image is None or info is None:
            return
        try:
            metadata = self.gate.accept(image, info, received_at=time.monotonic())
        except (TypeError, ValueError) as exc:
            self.last_error = str(exc)
        else:
            self.latest_frame = (metadata, image, info)
            self.last_error = None
        finally:
            self._images.pop(stamp_ns, None)
            self._infos.pop(stamp_ns, None)

    def is_fresh(self) -> bool:
        return self.gate.is_fresh(now=time.monotonic())

    def destroy(self) -> None:
        self._node.destroy_subscription(self._image_sub)
        self._node.destroy_subscription(self._info_sub)
