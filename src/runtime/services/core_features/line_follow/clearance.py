"""앞 공간(clearance) — LiDAR 한 장에서 로봇 정면 부채꼴의 가장 가까운 거리 (D-344 §11).

ROS 를 모른다. `sample` 은 bridge 의 `translate.lidar_sample` 모양(`ranges`, `angle_min`,
`angle_max`, `range_min`, `range_max`)이다. LiDAR 는 로봇마다 다르게 장착된다 — Pinky Pro
실물은 LiDAR 0° 가 로봇 뒤쪽이라 `forward_deg=180` 이다(2026-09-29 실측).
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional


def front_clearance(sample: Mapping[str, Any], *, forward_deg: float = 0.0,
                    half_angle_deg: float = 20.0) -> Optional[float]:
    """정면 ±half_angle_deg 안 유효 거리의 최솟값. 유효 표본이 없으면 None(= 아무것도 안 보임)."""
    ranges = sample.get("ranges") or []
    count = len(ranges)
    if count < 2:
        return None
    angle_min = float(sample["angle_min"])
    angle_max = float(sample["angle_max"])
    low = float(sample.get("range_min") or 0.0)
    high = float(sample.get("range_max") or math.inf)
    step = (angle_max - angle_min) / (count - 1)
    forward = math.radians(float(forward_deg))
    half = math.radians(float(half_angle_deg))
    best: Optional[float] = None
    for index, value in enumerate(ranges):
        try:
            distance = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(distance) or not low <= distance <= high:
            continue
        angle = angle_min + index * step - forward
        offset = math.atan2(math.sin(angle), math.cos(angle))
        if abs(offset) <= half and (best is None or distance < best):
            best = distance
    return best
