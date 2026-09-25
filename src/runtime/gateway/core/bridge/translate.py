"""core.bridge.translate — ROS 메시지를 도메인 dict 로 옮기는 순수 변환.

`ros_bridge` 는 rclpy 없이는 import 조차 되지 않는다. 그래서 브리지 안에 있던
변환 코드는 Windows·CI 어디서도 실행되지 못했고, 검증은 "소스에 이 문자열이
있는가"를 확인하는 수준에 머물렀다 — 값이 틀려도 통과하는 테스트다.

이 모듈은 ROS 타입을 import 하지 않는다. 필요한 속성만 읽는 duck typing 이라
평범한 객체로 호출할 수 있고, 그래서 실제로 테스트된다. 여기 있는 함수는
전부 부작용이 없다: 상태를 만지는 일은 브리지가 한다.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from core_features.traffic_policy import RoadEvidence


def yaw_from_quat(q: Any) -> float:
    """쿼터니언의 z 축 회전. 브리지 세 곳에 같은 식이 흩어져 있던 것을 모았다."""
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y ** 2 + q.z ** 2))


def _origin(pose: Any) -> dict[str, float]:
    return {
        "x": float(pose.position.x),
        "y": float(pose.position.y),
        "yaw": yaw_from_quat(pose.orientation),
    }


def grid_from_occupancy(msg: Any) -> dict[str, Any]:
    """`nav_msgs/OccupancyGrid` → MAP-003 스냅샷 격자."""
    info = msg.info
    return {
        "width": int(info.width),
        "height": int(info.height),
        "resolution": float(info.resolution),
        "origin": _origin(info.origin),
        "data": list(msg.data),
    }


def grid_from_costmap(msg: Any) -> dict[str, Any]:
    """`nav2_msgs/Costmap` → 같은 격자 형태. 메타데이터 필드 이름만 다르다."""
    meta = msg.metadata
    return {
        "width": int(meta.size_x),
        "height": int(meta.size_y),
        "resolution": float(meta.resolution),
        "origin": _origin(meta.origin),
        "data": list(msg.data),
    }


def path_points(msg: Any) -> list[dict[str, float]]:
    """`nav_msgs/Path` → x/y 목록. 고도와 자세는 스냅샷이 쓰지 않는다."""
    return [
        {"x": float(ps.pose.position.x), "y": float(ps.pose.position.y)}
        for ps in msg.poses
    ]


def odom_sample(msg: Any) -> dict[str, float]:
    """`nav_msgs/Odometry` → 포즈와 속도."""
    pose = msg.pose.pose
    twist = msg.twist.twist
    return {
        "x": float(pose.position.x),
        "y": float(pose.position.y),
        "yaw": yaw_from_quat(pose.orientation),
        "linear_x": float(twist.linear.x),
        "angular_z": float(twist.angular.z),
    }


def lidar_sample(msg: Any, received_at: float) -> dict[str, Any]:
    return {
        "frame_id": msg.header.frame_id,
        "range_min": msg.range_min,
        "range_max": msg.range_max,
        "angle_min": msg.angle_min,
        "angle_max": msg.angle_max,
        "num_ranges": len(msg.ranges),
        "ranges": list(msg.ranges),
        "received_at": received_at,
    }


def imu_sample(msg: Any, received_at: float) -> dict[str, Any]:
    return {
        "orientation_yaw": yaw_from_quat(msg.orientation),
        "angular_velocity_z": msg.angular_velocity.z,
        "linear_accel_x": msg.linear_acceleration.x,
        "received_at": received_at,
    }


def ultrasonic_sample(msg: Any, received_at: float) -> dict[str, Any]:
    return {
        "frame_id": msg.header.frame_id,
        "range": float(msg.range),
        "min_range": msg.min_range,
        "max_range": msg.max_range,
        "field_of_view": msg.field_of_view,
        "received_at": received_at,
    }


def usable_range(sample: dict[str, Any]) -> Optional[float]:
    """센서가 스스로 보고한 유효 구간 안의 표본만 정책에 넣는다 (PWR-002).

    구간 밖 값은 "가까운 물체 없음"을 뜻하는 포화값이거나 노이즈다. 그것을
    거리로 읽으면 아무도 없는 복도에서 로봇이 깨어난다.
    """
    value = sample["range"]
    if not math.isfinite(value):
        return None
    if not (sample["min_range"] <= value <= sample["max_range"]):
        return None
    return value


def battery_sample(msg: Any, received_at: float) -> dict[str, Any]:
    return {
        "voltage": float(msg.voltage),
        "percentage": float(msg.percentage),
        "power_supply_status": int(msg.power_supply_status),
        "location": msg.location,
        "received_at": received_at,
    }


def _wire_mapping(value: Any, name: str) -> dict:
    if type(value) is not dict:
        raise TypeError(f"{name} must be an object")
    return value


def _wire_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")
    return value


def _wire_number(value: Any, name: str, *, optional: bool = False):
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    return float(value)


def road_evidence(data: Any) -> RoadEvidence:
    """Decode one strict semantic-road JSON object into policy evidence."""
    root = _wire_mapping(data, "road observation")
    lane = _wire_mapping(root["lane"], "lane")
    stop = _wire_mapping(root["stop_line"], "stop_line")
    crosswalk = _wire_mapping(root["crosswalk"], "crosswalk")
    signal = _wire_mapping(root["signal"], "signal")

    lane_visible = _wire_bool(lane["visible"], "lane.visible")
    lane_error = _wire_number(
        lane["error"], "lane.error", optional=not lane_visible)
    if lane_visible and lane_error is None:
        raise ValueError("visible lane requires error")
    if not lane_visible and lane_error is not None:
        raise ValueError("invisible lane cannot carry error")
    _wire_number(lane["confidence"], "lane.confidence")

    stop_visible = _wire_bool(stop["visible"], "stop_line.visible")
    _wire_number(stop["image_row"], "stop_line.image_row", optional=True)
    stop_distance = _wire_number(
        stop["distance_m"], "stop_line.distance_m", optional=True)
    stop_confidence = _wire_number(
        stop["confidence"], "stop_line.confidence")

    crosswalk_visible = _wire_bool(
        crosswalk["visible"], "crosswalk.visible")
    _wire_number(
        crosswalk["image_row"], "crosswalk.image_row", optional=True)
    _wire_number(
        crosswalk["distance_m"], "crosswalk.distance_m", optional=True)
    _wire_number(crosswalk["confidence"], "crosswalk.confidence")

    signal_visible = _wire_bool(signal["visible"], "signal.visible")
    signal_conflict = _wire_bool(signal["conflict"], "signal.conflict")
    signal_colour = signal["colour"]
    if signal_visible and signal_colour is None:
        raise ValueError("visible signal requires colour")
    if not signal_visible and signal_colour is not None:
        raise ValueError("invisible signal cannot carry colour")
    signal_confidence = _wire_number(
        signal["confidence"], "signal.confidence")

    # Scene context (D-162) is optional additive observability. A present
    # key must decode strictly; absence decodes to all-None fields.
    context_id = None
    context_confidence = None
    context_profile_revision = None
    if "context" in root:
        context = _wire_mapping(root["context"], "context")
        context_id = context["id"]
        if not isinstance(context_id, str) or not context_id.strip():
            raise TypeError("context.id must be a non-empty string")
        context_confidence = _wire_number(
            context["confidence"], "context.confidence")
        if not 0.0 <= context_confidence <= 1.0:
            raise ValueError("context.confidence must be in [0, 1]")
        context_profile_revision = context["profile_revision"]
        if (not isinstance(context_profile_revision, str)
                or not context_profile_revision.strip()):
            raise TypeError(
                "context.profile_revision must be a non-empty string")

    return RoadEvidence(
        source=root["source"],
        stamp=_wire_number(root["stamp"], "stamp"),
        map_id=root["map_id"],
        scene_revision=root["scene_revision"],
        stop_line_visible=stop_visible,
        stop_line_distance_m=stop_distance,
        stop_line_confidence=stop_confidence,
        crosswalk_visible=crosswalk_visible,
        signal_colour=signal_colour,
        signal_confidence=signal_confidence,
        signal_conflict=signal_conflict,
        context_id=context_id,
        context_confidence=context_confidence,
        context_profile_revision=context_profile_revision,
    )
