#!/usr/bin/env python3
"""Pilot 시뮬 카메라 릴레이(D-323 T7 시뮬 도구): gz raw Image → jpeg-first
CompressedImage. CORE 가 요구하는 계약(parse_preview_format: jpeg 우선) 그대로.

원본 1280x720 bgr 은 프레임당 약 2.7MB 다. best-effort 로 받으면 부하가 걸린 호스트에서
DDS 조각 하나만 잃어도 프레임 전체가 사라져, 릴레이가 살아 있는데 영상이 멈춘다.
그래서 reliable·depth 1(최신 한 장)로 받고, 조종 미리보기에 충분한 폭으로 줄여 보낸다."""
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CompressedImage, Image
import cv2
import numpy as np


def bgr_frame(msg):
    layouts = {
        "bgr8": (3, None), "rgb8": (3, cv2.COLOR_RGB2BGR),
        "mono8": (1, cv2.COLOR_GRAY2BGR), "bgra8": (4, cv2.COLOR_BGRA2BGR),
        "rgba8": (4, cv2.COLOR_RGBA2BGR),
    }
    if msg.encoding not in layouts:
        raise ValueError(f"unsupported Gazebo image encoding {msg.encoding!r}")
    channels, conversion = layouts[msg.encoding]
    packed = msg.width * channels
    pixels = np.frombuffer(msg.data, dtype=np.uint8)
    if msg.width <= 0 or msg.height <= 0 or msg.step < packed or pixels.size != msg.height * msg.step:
        raise ValueError("invalid Gazebo image dimensions or stride")
    frame = pixels.reshape(msg.height, msg.step)[:, :packed].reshape(msg.height, msg.width, channels)
    return frame if conversion is None else cv2.cvtColor(frame, conversion)


class SimJpegRelay(Node):
    def __init__(self):
        super().__init__("pilot_sim_jpeg_relay")
        self.pub = self.create_publisher(CompressedImage, "camera/preview/compressed", 10)
        latest = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                            reliability=ReliabilityPolicy.RELIABLE)
        self.sub = self.create_subscription(Image, "camera/image_raw", self.on_image, latest)
        self.declare_parameter("max_width", 640)
        self.count = 0

    def on_image(self, msg):
        try:
            frame = bgr_frame(msg)
            max_width = int(self.get_parameter("max_width").value)
            if frame.shape[1] > max_width:
                scale = max_width / frame.shape[1]
                frame = cv2.resize(frame, (max_width, round(frame.shape[0] * scale)),
                                   interpolation=cv2.INTER_AREA)
            height, width = frame.shape[:2]
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if not ok:
                return
            out = CompressedImage()
            out.header = msg.header
            out.format = f"jpeg; width={width}; height={height}; source=gz"
            out.data = buf.tobytes()
            self.pub.publish(out)
            self.count += 1
            if self.count % 20 == 1:
                self.get_logger().info(f"relayed {self.count} frames ({width}x{height})")
        except Exception as error:
            self.get_logger().warning(f"relay error: {error}")


def main():
    rclpy.init()
    rclpy.spin(SimJpegRelay())


if __name__ == "__main__":
    main()
