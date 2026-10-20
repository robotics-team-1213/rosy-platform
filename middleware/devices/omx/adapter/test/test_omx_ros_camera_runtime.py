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


def test_sim_joint_capture_is_not_blocked_by_default_camera_callback_group():
    import threading
    from types import SimpleNamespace
    from sensor_msgs.msg import JointState
    from rclpy.qos import qos_profile_sensor_data
    from omx_adapter.pilot_sim.camera import PilotSimCamera
    from omx_adapter.ros_owner_executor import OwnerMultiThreadedExecutor
    rclpy.init()
    source, receiver = Node('capture_group_source'), Node('capture_group_receiver')
    entered, release, received = threading.Event(), threading.Event(), threading.Event()
    capture = SimpleNamespace(camera=None, tick=lambda: None,
        observe_joint_state=lambda _: received.set(), interrupt=lambda *_: None)
    camera = PilotSimCamera(receiver,capture,'a'*64)
    publisher = source.create_publisher(JointState,'/joint_states',qos_profile_sensor_data)
    def occupy_camera_group():
        entered.set()
        release.wait(3)
    timer = receiver.create_timer(.01,occupy_camera_group)
    executor = OwnerMultiThreadedExecutor(num_threads=4)
    executor.add_node(receiver)
    spinner = threading.Thread(target=executor.spin)
    spinner.start()
    try:
        deadline = time.monotonic()+3
        while publisher.get_subscription_count() == 0 and time.monotonic() < deadline:
            time.sleep(.01)
        assert publisher.get_subscription_count() > 0
        assert entered.wait(2)
        publisher.publish(JointState())
        assert received.wait(.5), 'joint capture waits behind the camera callback group'
    finally:
        release.set()
        receiver.destroy_timer(timer)
        executor.shutdown(timeout_sec=3)
        spinner.join(timeout=3)
        camera.destroy()
        source.destroy_node()
        receiver.destroy_node()
        rclpy.shutdown()


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
    accepted = []
    runtime = RosCameraStreamRuntime(
        receiver,
        CameraStreamConfig("test-camera-serial", "overhead_optical", "test-cal-v1", calibration_digest),
        image_topic="/test/omx/image",
        camera_info_topic="/test/omx/camera_info",
        on_frame=accepted.append,
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
        assert accepted == []

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
        deadline = time.monotonic()+1
        while len(accepted) < 2 and time.monotonic() < deadline:
            time.sleep(.01)
        assert [frame[0].capture_time_ns for frame in accepted] == [7_000_000_010, 7_000_000_020]
    finally:
        executor.shutdown(timeout_sec=2.0)
        spinning.result(timeout=3.0)
        runtime.destroy()
        source.destroy_node()
        receiver.destroy_node()
        rclpy.shutdown()
