"""앞 공간(clearance) — LiDAR 한 장에서 로봇 앞 공간의 가장 가까운 거리 (D-344 §11).

ROS 를 모른다. `sample` 은 bridge 의 `translate.lidar_sample` 모양(`ranges`, `angle_min`,
`angle_max`, `range_min`, `range_max`)이다. LiDAR 는 로봇마다 다르게 장착된다 — 첫 실물 로봇
실물은 LiDAR 0° 가 로봇 뒤쪽이라 `forward_deg=180` 이다(2026-09-29 실측).

두 판정이 있다.
- `front_clearance`: 정면 ±half_angle 부채꼴의 최소 거리(sector).
- `scan_points` + `path_clearance`: 지금 조향으로 곧 지나갈 짧은 호 둘레의 띠(폭 ±half_width)
  안 점까지의 호 길이(path). L 모서리에서 돌아 나가는 쪽이 아닌 벽은 세지 않는다.
- D-422 `body_path_gap` / `rotation_gap`: URDF 몸 윤곽(사각형 ∩ 회전 원)이 의도 호를 따라 쓸고
  갈 때 첫 접촉까지의 거리, 제자리 회전은 회전 반경 밖 여유. 점은 base_footprint 기준이다.
"""

from __future__ import annotations

import math
from typing import Any, Iterator, Mapping, Optional, Sequence

from core_common.robot_body import inside_body as _inside_body
from core_common.robot_body import masked as _masked

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


def front_sector(sample: Mapping[str, Any], *, forward_deg: float = 0.0, half_angle_deg: float = 20.0,
                 self_mask: SelfMask = ()) -> tuple[Optional[float], int, int]:
    """(nearest valid range, valid beams, beams) in the front ±half_angle_deg sector.

    Unlike `front_clearance`, a beam that is inf, NaN or below `range_min` is counted as a
    beam without a valid range: something closer than the LiDAR can see looks exactly like
    that. Self-masked returns (the robot's own body) are not beams of the sector at all."""
    ranges = sample.get("ranges") or []
    count = len(ranges)
    if count < 2:
        return None, 0, 0
    angle_min, angle_max = float(sample["angle_min"]), float(sample["angle_max"])
    low = float(sample.get("range_min") or 0.0)
    high = float(sample.get("range_max") or math.inf)
    step, forward = (angle_max - angle_min) / (count - 1), math.radians(float(forward_deg))
    half = math.radians(float(half_angle_deg))
    best, valid, beams = None, 0, 0
    for index, value in enumerate(ranges):
        angle = angle_min + index * step - forward
        angle = math.atan2(math.sin(angle), math.cos(angle))
        if abs(angle) > half:
            continue
        try:
            distance = float(value)
        except (TypeError, ValueError):
            distance = math.nan
        ok = math.isfinite(distance) and low <= distance <= high
        if ok and self_mask and _masked(angle, distance, self_mask):
            continue
        beams += 1
        if ok:
            valid += 1
            best = distance if best is None or distance < best else best
    return best, valid, beams


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


def body_clearances(points: Sequence[Point], *, lidar_x_m: float, rear_x_m: float,
                    half_width_m: float,
                    rotation_radius_m: Optional[float] = None) -> dict[str, Optional[float]]:
    """D-407: 몸 기준 여유. points 는 `scan_points`(LiDAR 원점, self-mask 적용) 그대로다.

    - front_band_m: 앞 직진 띠(±half_width) 안 가장 가까운 점의 LiDAR 기준 x(obstacle_stop_m 과 같은 기준).
    - rear_m: 뒤 띠 안 가장 가까운 점과 몸 뒤끝(URDF base_footprint x = rear_x_m) 사이 거리.
    - turn_m: 제자리 회전 반경(rotation_radius_m) 밖 여유. 반경이 없으면 None.
    점이 없으면 각각 None(= 아무것도 안 보임). LiDAR range_min 안은 보이지 않는다.
    """
    front: Optional[float] = None
    rear: Optional[float] = None
    turn: Optional[float] = None
    for x, y in points:
        base_x = x + lidar_x_m
        if abs(y) <= half_width_m:
            if x > 0.0 and (front is None or x < front):
                front = x
            if base_x < rear_x_m and (rear is None or rear_x_m - base_x < rear):
                rear = rear_x_m - base_x
        if rotation_radius_m is not None:
            gap = math.hypot(base_x, y) - rotation_radius_m
            if turn is None or gap < turn:
                turn = gap
    return {"front_band_m": front, "rear_m": rear, "turn_m": turn}


def self_mask_rear_blind_m(mask: SelfMask, *, lidar_x_m: float, rear_x_m: float,
                           half_width_m: float) -> float:
    """D-407 review M1: how deep behind the body rear a self-mask window hides the rear band.

    A masked return is dropped as "the robot itself", so a real obstacle inside a window that
    reaches past the body rear would read as clear. That depth is blind like range_min.
    Sampled every 0.5 deg across each window; 0 when no window reaches the rear band.
    """
    behind = lidar_x_m - rear_x_m              # LiDAR to body rear, metres (> 0)
    worst = 0.0
    for lo, hi, reach in mask:
        steps = max(1, int(math.ceil((hi - lo) / 0.5)))
        for index in range(steps + 1):
            angle = math.radians(lo + (hi - lo) * index / steps)
            back, side = -math.cos(angle), abs(math.sin(angle))
            if back <= 0.0:
                continue
            far = reach if side < 1e-9 else min(reach, half_width_m / side)
            worst = max(worst, far * back - behind)
    return worst


def body_path_gap(points: Sequence[Point], *, linear: float, angular: float, front_x_m: float,
                  rear_x_m: float, half_width_m: float, rotation_radius_m: float,
                  horizon_m: float, step_m: float = 0.005) -> Optional[float]:
    """D-422: how far the robot drives along (linear, angular) before its body touches a point.

    points are in base_footprint (x forward, y left), not the LiDAR origin. The body is
    `_inside_body` swept along the arc; the gap is the base origin's travel (arc length) at
    first contact, refined by bisection. 0 = a point is already inside the outline. The arc
    ends at horizon_m or half a turn, whichever is first; None = nothing touched by then.
    linear must be positive: in-place rotation is `rotation_gap`.
    """
    speed = float(linear)
    if not speed > 0.0:
        raise ValueError("body_path_gap needs a forward speed; use rotation_gap in place")
    curvature = float(angular) / speed
    reach = horizon_m + rotation_radius_m
    near = [(x, y) for x, y in points if x * x + y * y <= reach * reach]
    if not near:
        return None
    body = (front_x_m, rear_x_m, half_width_m, rotation_radius_m)

    def touches(travel: float) -> bool:
        heading = curvature * travel
        if abs(curvature) < 1e-9:
            px, py = travel, 0.0
        else:
            px, py = math.sin(heading) / curvature, (1.0 - math.cos(heading)) / curvature
        c, s = math.cos(heading), math.sin(heading)
        for x, y in near:
            dx, dy = x - px, y - py
            if _inside_body(c * dx + s * dy, -s * dx + c * dy, *body):
                return True
        return False

    if touches(0.0):
        return 0.0
    limit = horizon_m if abs(curvature) < 1e-9 else min(horizon_m, math.pi / abs(curvature))
    # The body's farthest point moves (1 + |k|·R) times the base travel: keep its step ~step_m.
    step = step_m / (1.0 + abs(curvature) * rotation_radius_m)
    low, travel = 0.0, 0.0
    while travel < limit:
        travel = min(travel + step, limit)
        if touches(travel):
            high = travel
            for _ in range(10):
                mid = 0.5 * (low + high)
                low, high = (low, mid) if touches(mid) else (mid, high)
            return high
        low = travel
    return None


def rotation_gap(points: Sequence[Point], *, rotation_radius_m: float,
                 reach_m: float) -> Optional[float]:
    """D-422 in-place rotation: the smallest gap outside the URDF rotation radius (base_footprint
    points). Points farther than rotation_radius_m + reach_m are ignored; None = none nearer."""
    best: Optional[float] = None
    for x, y in points:
        gap = max(0.0, math.hypot(x, y) - rotation_radius_m)
        if gap <= reach_m and (best is None or gap < best):
            best = gap
    return best


def ultrasonic_points(range_m: float, *, sensor_x_m: float, half_angle_deg: float,
                      step_deg: float = 2.5) -> tuple[Point, ...]:
    """D-422: a forward ultrasonic echo at range_m as base_footprint points across its cone.

    The sensor reports only that something is somewhere on that arc, so every point of it
    counts (fail-safe: an echo can only make the gap smaller)."""
    count = max(1, int(math.ceil(2.0 * half_angle_deg / step_deg)))
    out = []
    for index in range(count + 1):
        angle = math.radians(-half_angle_deg + 2.0 * half_angle_deg * index / count)
        out.append((sensor_x_m + range_m * math.cos(angle), range_m * math.sin(angle)))
    return tuple(out)


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
