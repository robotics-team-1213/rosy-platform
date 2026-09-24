"""D-137 T4 transport injection — 와이어가 자문 좌석에 닿는지의 ROS 그래프 시험.

rclpy 필요(ROS 없는 호스트는 모듈째 건너뛴다). RosBridge의 `detection_evidence`
구독이 실제 DDS 왕복으로 `PersonAdvisoryFeed`에 닿는지, 깨진 패킷이 자문을
해제하는지, e-stop이 이 경로로 흔들리지 않는지를 확인한다. Gazebo 불필요 —
주입은 시험 발행자가 증거 패킷으로 한다(노드 기동은 T5까지 금지).
"""
import json
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("rclpy")

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _build_services(tmp_path):
    import yaml
    from core.services import CoreServices
    from core_common.profile import RobotProfile, robot_config_dir

    def read(name):
        return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))

    return CoreServices.build(read("rosy_default.yaml"),
                              RobotProfile.load(robot_config_dir("pinky_pro") / "profile.yaml"),
                              yaml.safe_load((robot_config_dir("pinky_pro") / "capabilities.yaml").read_text(encoding="utf-8")), tmp_path / "wp.json")


def test_wire_packets_drive_and_clear_the_advisory(tmp_path):
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from std_msgs.msg import String

    from core.bridge.ros_bridge import RosBridge

    rclpy.init()
    executor = None
    node = None
    try:
        node = rclpy.create_node("advisory_feed_injection")
        services = _build_services(tmp_path)
        RosBridge(node, services)
        executor = SingleThreadedExecutor()
        executor.add_node(node)
        threading.Thread(target=executor.spin, daemon=True).start()

        pub = node.create_publisher(String, "detection_evidence", 10)

        def packet(**overrides):
            body = {
                "model_revision": "yolo11n-r1",
                "observed_at": node.get_clock().now().nanoseconds / 1e9,
                "seq": 41, "input_width": 640, "input_height": 640,
                "input_fps": 10.0, "inference_ms": 12.0,
                "detections": [{"label": "person", "x": 0.4, "y": 0.3,
                                "w": 0.2, "h": 0.4, "confidence": 0.8,
                                "track_id": 3}],
            }
            body.update(overrides)
            return String(data=json.dumps(body))

        def publish_until(make_msg, predicate, timeout_s=8.0):
            """DDS 매칭 전 발행은 유실된다 — 매치되기 전까지 계속 발행한다."""
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if pub.get_subscription_count() > 0:
                    pub.publish(make_msg())
                if predicate():
                    return True
                time.sleep(0.1)
            return predicate()

        def clipped():
            return services.safety.clip(0.20, 0.50)[0]

        # 신선한 person 패킷 → 자문 좌석이 살고 선속도는 캡(0.05)으로.
        assert publish_until(packet, lambda: clipped() <= 0.05 + 1e-9)

        # 깨진 패킷 → 자문 해제, 프로필 복귀. "못 본 것"으로 상한을 유지하지
        # 않는 것이 자문의 방향이다(D-136 §5).
        def broken():
            body = json.loads(packet().data)
            body["detections"] = [{"label": "person", "x": 0.4, "y": 0.3,
                                   "w": 0.2, "h": 0.4, "confidence": 2.0}]
            return String(data=json.dumps(body))

        assert publish_until(broken, lambda: clipped() >= 0.20 - 1e-9)

        # e-stop은 이 경로로 흔들리지 않는다 — metric과 operator만이 만진다.
        services.safety.trigger_estop("lidar")
        pub.publish(packet())
        time.sleep(0.5)
        assert services.safety.estop is True
    finally:
        if executor is not None:
            executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
