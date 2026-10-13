from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

rclpy = pytest.importorskip("rclpy", reason="requires the ROS 2 Jazzy runtime")

from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image

from omx_adapter.camera_contract import CameraFrameGate, CameraStreamConfig
from omx_adapter.ros_camera_runtime import RosCameraStreamRuntime


def test_camera_runtime_pairs_by_capture_stamp_and_keeps_only_latest_frame():
    rclpy.init()
    source = Node("omx_camera_test_source")
    receiver = Node("omx_camera_test_receiver")
    image_pub = source.create_publisher(Image, "/test/omx/image", 1)
    info_pub = source.create_publisher(CameraInfo, "/test/omx/camera_info", 1)
    info = CameraInfo()
    info.width, info.height = 2, 2
    info.distortion_model = "plumb_bob"
    info.d = [0.0] * 5
    info.k = [1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0]
    info.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    info.p = [1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    calibration_digest = CameraFrameGate.camera_info_fingerprint(info)
    runtime = RosCameraStreamRuntime(
        receiver,
        CameraStreamConfig("test-camera-serial", "overhead_optical", "test-cal-v1", calibration_digest),
        image_topic="/test/omx/image",
        camera_info_topic="/test/omx/camera_info",
    )
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(source)
    executor.add_node(receiver)
    spinner = ThreadPoolExecutor(max_workers=1)
    spinning = spinner.submit(executor.spin)
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and image_pub.get_subscription_count() == 0:
            time.sleep(0.02)
        image = Image()
        image.header.frame_id = "overhead_optical"
        image.width, image.height = 2, 2
        image.encoding, image.step, image.data = "mono8", 2, [0, 1, 2, 3]
        info.header.frame_id = "overhead_optical"

        image.header.stamp.sec = 7
        image.header.stamp.nanosec = 10
        info.header.stamp.sec = 7
        info.header.stamp.nanosec = 11
        image_pub.publish(image)
        info_pub.publish(info)
        time.sleep(0.1)
        assert runtime.latest_frame is None

        info.header.stamp.nanosec = 10
        image_pub.publish(image)
        info_pub.publish(info)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and runtime.latest_frame is None:
            time.sleep(0.01)
        assert runtime.latest_frame is not None
        first = runtime.latest_frame
        assert first[0].capture_time_ns == 7_000_000_010
        assert runtime.is_fresh()

        image.header.stamp.nanosec = 20
        info.header.stamp.nanosec = 20
        image_pub.publish(image)
        info_pub.publish(info)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and runtime.latest_frame[0].sequence == first[0].sequence:
            time.sleep(0.01)
        assert runtime.latest_frame[0].sequence == first[0].sequence + 1
    finally:
        executor.shutdown(timeout_sec=2.0)
        spinning.result(timeout=3.0)
        runtime.destroy()
        source.destroy_node()
        receiver.destroy_node()
        rclpy.shutdown()
