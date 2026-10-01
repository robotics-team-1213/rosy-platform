"""앞 공간(clearance) — LiDAR 한 장에서 로봇 앞 공간의 가장 가까운 거리 (D-344 §11).

ROS 를 모른다. `sample` 은 bridge 의 `translate.lidar_sample` 모양(`ranges`, `angle_min`,
`angle_max`, `range_min`, `range_max`)이다. LiDAR 는 로봇마다 다르게 장착된다 — 첫 실물 로봇
실물은 LiDAR 0° 가 로봇 뒤쪽이라 `forward_deg=180` 이다(2026-09-29 실측).

두 판정이 있다.
- `front_clearance`: 정면 ±half_angle 부채꼴의 최소 거리(sector).
- `scan_points` + `path_clearance`: 지금 조향으로 곧 지나갈 짧은 호 둘레의 띠(폭 ±half_width)
  안 점까지의 호 길이(path). L 모서리에서 돌아 나가는 쪽이 아닌 벽은 세지 않는다.
"""

from __future__ import annotations

import math
from typing import Any, Iterator, Mapping, Optional, Sequence

Point = tuple[float, float]
#: (from_deg, to_deg, max_range_m) in the robot frame (0 = forward, + = left): returns of the
#: robot's own body. A mask only reaches SELF_MASK_MAX_RANGE_M, so it never hides a real
#: obstacle further out (8kcn: a fixed part at -52..-66 deg, 0.11-0.165 m, 2026-10-01).
SelfMask = tuple[tuple[float, float, float], ...]
SELF_MASK_MAX_RANGE_M = 0.30


def self_mask_from_config(raw) -> SelfMask:
    """`line_follow.lidar_self_mask`: a list of {from_deg, to_deg, max_range_m}; [] or None = none."""
    if raw in (None, []):
        return ()
    if not isinstance(raw, list):
        raise ValueError("line_follow.lidar_self_mask must be a list")
    out = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"from_deg", "to_deg", "max_range_m"}:
            raise ValueError("lidar_self_mask entries need exactly from_deg, to_deg, max_range_m")
        lo, hi, reach = (float(item[k]) for k in ("from_deg", "to_deg", "max_range_m"))
        if not (-180.0 <= lo < hi <= 180.0) or not 0.0 < reach <= SELF_MASK_MAX_RANGE_M:
            raise ValueError(f"lidar_self_mask entry out of range: {item!r}")
        out.append((lo, hi, reach))
    return tuple(out)


def _masked(angle: float, distance: float, mask: SelfMask) -> bool:
    deg = math.degrees(angle)
    return any(lo <= deg <= hi and distance <= reach for lo, hi, reach in mask)


def _returns(sample: Mapping[str, Any], forward_deg: float,
             self_mask: SelfMask = ()) -> Iterator[tuple[float, float]]:
    """(로봇 정면 기준 각 rad, 거리) — 유효 표본만, 자기 몸 반사(self_mask)는 뺀다."""
    ranges = sample.get("ranges") or []
    count = len(ranges)
    if count < 2:
        return
    angle_min = float(sample["angle_min"])
    angle_max = float(sample["angle_max"])
    low = float(sample.get("range_min") or 0.0)
    high = float(sample.get("range_max") or math.inf)
    step = (angle_max - angle_min) / (count - 1)
    forward = math.radians(float(forward_deg))
    for index, value in enumerate(ranges):
        try:
            distance = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(distance) or not low <= distance <= high:
            continue
        angle = angle_min + index * step - forward
        angle = math.atan2(math.sin(angle), math.cos(angle))
        if self_mask and _masked(angle, distance, self_mask):
            continue
        yield angle, distance


def front_clearance(sample: Mapping[str, Any], *, forward_deg: float = 0.0,
                    half_angle_deg: float = 20.0, self_mask: SelfMask = ()) -> Optional[float]:
    """정면 ±half_angle_deg 안 유효 거리의 최솟값. 유효 표본이 없으면 None(= 아무것도 안 보임)."""
    half = math.radians(float(half_angle_deg))
    best: Optional[float] = None
    for offset, distance in _returns(sample, forward_deg, self_mask):
        if abs(offset) <= half and (best is None or distance < best):
            best = distance
    return best


def scan_points(sample: Mapping[str, Any], *, forward_deg: float = 0.0,
                max_range: float = math.inf, self_mask: SelfMask = ()) -> tuple[Point, ...]:
    """유효 표본을 로봇 좌표(x 앞, y 왼쪽, REP-103) 점으로. max_range 밖은 버린다."""
    return tuple((distance * math.cos(offset), distance * math.sin(offset))
                 for offset, distance in _returns(sample, forward_deg, self_mask)
                 if distance <= max_range)


def path_clearance(points: Sequence[Point], *, linear: float, angular: float,
                   half_width_m: float, horizon_m: float,
                   window_m: float = 0.0, near_m: float = 0.0) -> Optional[float]:
    """지금 (linear, angular) 로 갈 호 둘레 ±half_width_m 띠 안 가장 가까운 점까지의 거리.

    호 길이로 잰다. 호는 horizon_m 까지이되, 회전각 창은 max(90°, window_m/R) 이고 180° 를
    넘지 않는다 — 급회전(작은 R)에서 90° 호는 정지 거리보다 짧아 앞 물체를 못 본다.
    near-field: 창 밖이어도 0..180° 띠 안이고 LiDAR 에서 near_m 안인 점은 그 직선 거리로 센다.
    linear 가 0 이면 제자리 회전이라 max(half_width_m, near_m) 안 점이 곧 0 거리다.

    LiDAR `range_min`(Pinky C1 약 0.15 m) 안은 아무것도 보이지 않는다. half_width_m 가 그보다
    작으면 제자리 회전 판정은 near_m 없이는 늘 비어 있다 — near_m 를 정지 거리로 준다.
    띠 안에 점이 없으면 None.
    """
    speed = max(0.0, float(linear))
    turn = float(angular)
    best: Optional[float] = None
    if abs(turn) < 1e-6 or speed / abs(turn) > 1e3:
        for x, y in points:
            if 0.0 < x <= horizon_m and abs(y) <= half_width_m and (best is None or x < best):
                best = x
        return best
    radius = speed / abs(turn)
    if radius < 1e-9:
        reach = max(half_width_m, near_m)
        for x, y in points:
            if math.hypot(x, y) <= reach:
                return 0.0
        return None
    side = 1.0 if turn > 0 else -1.0                 # 왼쪽(+) 회전이면 중심이 +y 에 있다
    centre_y = side * radius
    start = math.atan2(-centre_y, 0.0)               # 중심에서 본 로봇 위치의 각
    window = min(math.pi, max(math.pi / 2, window_m / radius))
    limit = min(horizon_m / radius, window)
    for x, y in points:
        dy = y - centre_y
        if abs(math.hypot(x, dy) - radius) > half_width_m:
            continue
        travel = side * (math.atan2(dy, x) - start)
        travel = math.atan2(math.sin(travel), math.cos(travel))
        if travel <= 0.0:
            continue
        if travel <= limit:
            candidate = radius * travel
        elif math.hypot(x, y) <= near_m:
            candidate = math.hypot(x, y)
        else:
            continue
        if best is None or candidate < best:
            best = candidate
    return best
