"""ROS-free /sensors mirror for imu, odometry, wheels, motor and dock observation.

Load rule: a ROS callback only keeps the latest raw message (one clock read, one assignment,
and at most one per `min_period_s`). Conversion to the JSON dict runs on the API thread when
`GET /api/v1/sensors/{type}` asks, via `StateManager.set_sensor_lazy`.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any, Callable

from core.bridge.translate import yaw_from_quat


def _stamp_ns(msg: Any) -> int:
    stamp = msg.header.stamp
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def _xyz(v: Any) -> dict[str, float]:
    return {"x": float(v.x), "y": float(v.y), "z": float(v.z)}


def imu_fields(msg: Any) -> dict[str, Any]:
    q, a = msg.orientation, msg.linear_acceleration
    roll = math.atan2(2.0 * (q.w * q.x + q.y * q.z), 1.0 - 2.0 * (q.x ** 2 + q.y ** 2))
    pitch = math.asin(max(-1.0, min(1.0, 2.0 * (q.w * q.y - q.z * q.x))))
    return {
        "frame_id": msg.header.frame_id,
        "source_stamp_ns": _stamp_ns(msg),
        "orientation": {"x": float(q.x), "y": float(q.y), "z": float(q.z), "w": float(q.w)},
        "angular_velocity": _xyz(msg.angular_velocity),
        "linear_acceleration": _xyz(a),
        "roll_rad": roll, "pitch_rad": pitch,
        # kept for readers of the first imu sample (translate.imu_sample)
        "orientation_yaw": yaw_from_quat(q), "angular_velocity_z": float(msg.angular_velocity.z),
        "linear_accel_x": float(a.x),
        # Gravity-only attitude: still valid when the IMU leaves orientation at zero.
        "roll_accel_rad": math.atan2(float(a.y), float(a.z)),
        "pitch_accel_rad": math.atan2(-float(a.x), math.hypot(float(a.y), float(a.z))),
    }


def odometry_fields(msg: Any) -> dict[str, Any]:
    pose, twist = msg.pose.pose, msg.twist.twist
    return {
        "frame_id": msg.header.frame_id, "child_frame_id": msg.child_frame_id,
        "source_stamp_ns": _stamp_ns(msg),
        "pose": {"x": float(pose.position.x), "y": float(pose.position.y),
                 "z": float(pose.position.z), "yaw": yaw_from_quat(pose.orientation)},
        "twist": {"linear": _xyz(twist.linear), "angular": _xyz(twist.angular)},
    }


def _is_wheel(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]  # a namespace prefix may precede it; caster_wheel_joint must not match
    return base in ("l_wheel_joint", "r_wheel_joint") or base.endswith(("_l_wheel_joint", "_r_wheel_joint"))


def wheels_fields(msg: Any) -> dict[str, Any]:
    """Drive-wheel joints only: /joint_states carries bringup's and joint_state_publisher's lists."""
    keep = [i for i, n in enumerate(msg.name) if _is_wheel(n)]

    def pick(values: Any) -> list[float]:
        return [float(values[i]) for i in keep if i < len(values)]

    return {"source_stamp_ns": _stamp_ns(msg), "names": [msg.name[i] for i in keep],
            "position": pick(msg.position), "velocity": pick(msg.velocity), "effort": pick(msg.effort)}


class SensorMirror:
    KEYS = ("imu", "odometry", "wheels", "motor", "dock_observation")
    _CONVERT = {"imu": imu_fields, "odometry": odometry_fields, "wheels": wheels_fields}

    def __init__(self, *, min_period_s: float = 0.1,
                 monotonic: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self._period, self._mono, self._wall = min_period_s, monotonic, wall
        self._last: dict[str, float] = {}
        self._raw: dict[str, tuple[Any, float]] = {}   # key -> (raw message, wall time)
        self._motor_ready: bool | None = None

    def install(self, state: Any) -> None:
        for key in self.KEYS:
            state.set_sensor_lazy(key, lambda key=key: self.sample(key))

    def _keep(self, key: str, raw: Any) -> None:
        now = self._mono()
        if now - self._last.get(key, -math.inf) >= self._period:
            self._last[key] = now
            self._raw[key] = (raw, self._wall())

    def imu(self, msg: Any) -> None:
        self._keep("imu", msg)

    def odometry(self, msg: Any) -> None:
        self._keep("odometry", msg)

    def wheels(self, msg: Any) -> None:
        # Other joint lists must not take the slot of the wheel message (name scan only, no conversion).
        if any(_is_wheel(n) for n in msg.name):
            self._keep("wheels", msg)

    def dock_observation(self, payload: Any) -> None:
        self._keep("dock_observation", payload)

    def motor_health(self, text: Any) -> None:
        self._keep("motor", text)

    def motor_ready(self, ready: bool) -> None:
        self._motor_ready = bool(ready)  # latched and rare
        self._raw.setdefault("motor", (None, self._wall()))

    def sample(self, key: str) -> dict[str, Any] | None:
        """The last sample as a dict, or None. Runs on the API thread."""
        held = self._raw.get(key)
        if held is None:
            return None
        raw, at = held
        if key in self._CONVERT:
            return {**self._CONVERT[key](raw), "received_at": at}
        if key == "dock_observation":
            return {**raw, "received_at": at} if isinstance(raw, dict) else None
        try:
            health = json.loads(raw) if raw is not None else None
        except (TypeError, ValueError):
            health = None
        return {"health": health, "ready": self._motor_ready, "received_at": at}
