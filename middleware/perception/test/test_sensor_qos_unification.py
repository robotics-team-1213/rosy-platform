"""센서 토픽 소비자 QoS는 SENSOR(QoS_PROFILE_SENSOR_DATA)로 통일한다.

통신·프로토콜 보고서(2026-09-22 §3.2) 잠복 리스크: BEST_EFFORT 구독은
RELIABLE·BEST_EFFORT 발행자 모두와 매칭되지만, RELIABLE(depth) 구독은
sensor-data(BEST_EFFORT) 발행자와 **영원히 매칭되지 않는다**. 소비자 정책이
섞여 있으면 발행자를 D-119로 통일하는 순간 일부 구독자만 조용히 죽는다.
"""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "control"


def _source(rel) -> str:
    return (PKG / rel).read_text(encoding="utf-8")


def test_startup_calibration_reads_sensors_with_sensor_qos():
    src = _source("startup_calibration_node.py")
    for topic in ("imu_raw", "us_sensor/range", "ir_sensor/range"):
        pattern = (rf"create_subscription\([^)]*'{re.escape(topic)}'"
                   rf"[^)]*qos_profile_sensor_data")
        assert re.search(pattern, src, re.S), (
            f"startup_calibration '{topic}' subscription is not sensor-data QoS")


def _subscription_chunk(src: str, needle: str, msg_type: str) -> str:
    """"create_subscription" 호출 조각( '(' 로 시작) 중 타입과 needle 을
    모두 담은 것을 반환 — 선언부 조각은 제외한다."""
    for part in src.split("create_subscription")[1:]:
        head = part.lstrip()
        if head.startswith("(") and msg_type in part and needle in part:
            return part
    return ""


def test_safety_reads_us_and_ir_with_sensor_qos():
    src = _source(Path("safety") / "node.py")
    for needle, msg_type in (("us_topic", "Range"), ("ir_topic", "UInt16MultiArray")):
        chunk = _subscription_chunk(src, needle, msg_type)
        assert chunk, (
            f"safety has no {msg_type} subscription referencing {needle}")
        assert "qos_profile_sensor_data" in chunk, (
            f"safety '{needle}' subscription is not sensor-data QoS")


def test_estop_operator_publish_needs_transient_local_note():
    """/estop(Bool) 구독은 latched — 운영자 가이드에 QoS 지정 예시가 있어야 한다."""
    steps = (Path(__file__).resolve().parents[1] / "STEPS.txt").read_text(encoding="utf-8")
    assert "transient_local" in steps, (
        "STEPS.txt must tell operators that publishing /estop needs "
        "transient_local — a default-QoS ros2 topic pub never matches")
