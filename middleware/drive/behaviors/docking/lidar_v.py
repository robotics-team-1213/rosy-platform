"""core_features.docking.lidar_v — 후진 충전소의 LiDAR V 표지 검출 (D-972).

후진 USB 충전소(D-950)는 스캔면(125 mm)보다 낮아 LiDAR에 보이지 않는다. 그래서 멈춤면
뒤에 스캔면을 가로지르는 V자 날개 둘을 세운다(로봇 쪽으로 열림). 여기서는 base_link 점
(스캔 순서)에서 그 V를 찾아 멈춤면 가운데와 도크 안쪽 축을 낸다. 모양이 다르면 None —
잃은 것으로 읽히고, 추측하지 않는다. 움직임은 정하지 않는다.

CORE 는 스캔 표본을 이미 받는다(`core.bridge.observation`): 도킹이 도크를 찾는 동안에만
이 검출을 부르고 결과를 `dock/observation` 모양(source LIDAR_V, tag_id null)으로
`DockObservationFeed` 에 넣는다. 검출기 경계(`FeedDetector`) 뒤는 카메라 태그와 같다.

기하(도크 좌표, 연구 scad ``lidar_target``): 각 날개 앞면은 횡축에서 ``arm_angle_rad``
기울고, 두 앞면을 늘이면 멈춤면 뒤 ``apex_depth_m`` 에서 만난다. 안쪽 끝 사이에 케이블
틈이 있어 두 날개는 따로 떨어진 선분으로 잡힌다.

ROS 무의존.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from core_features.docking.feed import LIDAR_V as SOURCE


@dataclass(frozen=True)
class DockVSpec:
    apex_depth_m: float = 0.0666          # stop face -> apex of the fin front faces
    arm_angle_rad: float = math.radians(21.1)
    min_arm_m: float = 0.025              # shorter segments are not a fin (fin face 54.5 mm)
    max_apex_gap_m: float = 0.03          # inner fin end to apex (cable gap 11.8 mm)
    angle_tol_rad: float = math.radians(8.0)
    line_tol_m: float = 0.004             # split-and-merge residual
    # Neighbour gap that starts a new cluster: below the 23.6 mm cable gap between
    # the fins, above the C1's 0.72 deg spacing at 1 m (12.6 mm).
    break_m: float = 0.018
    min_range_m: float = 0.05
    max_range_m: float = 1.5
    min_points: int = 4                   # a fin at 0.8 m gives 4 - 5 returns


@dataclass(frozen=True)
class DockVObservation:
    x: float
    y: float
    yaw: float
    confidence: float

    @property
    def range_m(self) -> float:
        return math.hypot(self.x, self.y)


Point = tuple[float, float]


def _clusters(points: Sequence[Point], spec: DockVSpec) -> list[list[Point]]:
    groups: list[list[Point]] = []
    for p in points:
        if groups and math.dist(groups[-1][-1], p) <= spec.break_m:
            groups[-1].append(p)
        else:
            groups.append([p])
    # A full turn: the scan's seam may fall on a fin; its two ends are one cluster.
    if len(groups) >= 2 and math.dist(groups[-1][-1], groups[0][0]) <= spec.break_m:
        groups[0] = groups.pop() + groups[0]
    return [g for g in groups if len(g) >= spec.min_points]


def _deviation(points: Sequence[Point]) -> tuple[int, float]:
    (ax, ay), (bx, by) = points[0], points[-1]
    length = math.hypot(bx - ax, by - ay) or 1e-12
    worst, at = 0.0, 0
    for i, (px, py) in enumerate(points):
        d = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length
        if d > worst:
            worst, at = d, i
    return at, worst


def _split(points: Sequence[Point], spec: DockVSpec) -> list[Sequence[Point]]:
    if len(points) < spec.min_points:
        return []
    at, worst = _deviation(points)
    if worst <= spec.line_tol_m or at in (0, len(points) - 1):
        return [points]
    return _split(points[:at + 1], spec) + _split(points[at:], spec)


@dataclass(frozen=True)
class _Segment:
    cx: float
    cy: float
    dx: float          # unit direction
    dy: float
    ends: tuple[Point, Point]
    rms: float
    n: int

    @property
    def length(self) -> float:
        return math.dist(*self.ends)


def _fit(points: Sequence[Point]) -> _Segment:
    n = len(points)
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n
    sxx = sum((p[0] - cx) ** 2 for p in points)
    syy = sum((p[1] - cy) ** 2 for p in points)
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in points)
    theta = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    dx, dy = math.cos(theta), math.sin(theta)
    t = [(p[0] - cx) * dx + (p[1] - cy) * dy for p in points]
    ends = ((cx + min(t) * dx, cy + min(t) * dy), (cx + max(t) * dx, cy + max(t) * dy))
    rms = math.sqrt(sum(((p[0] - cx) * -dy + (p[1] - cy) * dx) ** 2 for p in points) / n)
    return _Segment(cx, cy, dx, dy, ends, rms, n)


def _intersection(a: _Segment, b: _Segment) -> Optional[Point]:
    det = a.dx * -b.dy + b.dx * a.dy
    if abs(det) < 1e-9:
        return None
    rx, ry = b.cx - a.cx, b.cy - a.cy
    s = (rx * -b.dy + b.dx * ry) / det
    return a.cx + s * a.dx, a.cy + s * a.dy


def _arm(seg: _Segment, apex: Point) -> tuple[float, Point]:
    """Distance from the apex to the segment's near end, and the unit
    direction from the apex out along the arm."""
    near, far = sorted(seg.ends, key=lambda e: math.dist(e, apex))
    length = math.dist(far, apex) or 1e-12
    return math.dist(near, apex), ((far[0] - apex[0]) / length, (far[1] - apex[1]) / length)


def detect_dock_v(points: Sequence[Point], spec: DockVSpec = DockVSpec()) -> Optional[DockVObservation]:
    """Base_link points in scan order -> the dock origin and inward axis, or
    None when no V of the declared shape is present (a lost dock reads as
    lost, never as a guess)."""
    usable = [(float(x), float(y)) for x, y in points
              if math.isfinite(x) and math.isfinite(y)
              and spec.min_range_m <= math.hypot(x, y) <= spec.max_range_m]
    segments = [_fit(part) for cluster in _clusters(usable, spec) for part in _split(cluster, spec)]
    segments = [s for s in segments if s.length >= spec.min_arm_m]
    target = 2.0 * spec.arm_angle_rad
    best = None
    for i, a in enumerate(segments):
        for b in segments[i + 1:]:
            between = math.acos(min(1.0, abs(a.dx * b.dx + a.dy * b.dy)))
            error = abs(between - target)
            if error > spec.angle_tol_rad:
                continue
            apex = _intersection(a, b)
            if apex is None:
                continue
            gap_a, out_a = _arm(a, apex)
            gap_b, out_b = _arm(b, apex)
            if max(gap_a, gap_b) > spec.max_apex_gap_m:
                continue
            ox, oy = out_a[0] + out_b[0], out_a[1] + out_b[1]
            norm = math.hypot(ox, oy)
            if norm < 1e-9:
                continue
            ox, oy = ox / norm, oy / norm            # the V's opening
            # The opening must face the robot: the apex is the far point.
            if ox * -apex[0] + oy * -apex[1] <= 0.0:
                continue
            # Both arms on opposite sides of the opening axis.
            if (out_a[0] * -oy + out_a[1] * ox) * (out_b[0] * -oy + out_b[1] * ox) >= 0.0:
                continue
            if best is None or error < best[0]:
                best = (error, apex, (-ox, -oy), a, b)
    if best is None:
        return None
    error, apex, (ax, ay), a, b = best
    origin = (apex[0] - ax * spec.apex_depth_m, apex[1] - ay * spec.apex_depth_m)
    fit = max(0.0, 1.0 - max(a.rms, b.rms) / spec.line_tol_m)
    shape = max(0.0, 1.0 - error / spec.angle_tol_rad)
    return DockVObservation(x=origin[0], y=origin[1], yaw=math.atan2(ay, ax),
                            confidence=round(min(1.0, 0.5 * fit + 0.5 * shape), 3))


def lidar_v_payload(stamp: float, observation: Optional[DockVObservation]) -> dict:
    """The ``dock/observation`` wire shape with source LIDAR_V."""
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) \
            or not math.isfinite(float(stamp)):
        raise ValueError("dock observation stamp must be finite")
    if observation is None:
        return {"source": SOURCE, "stamp": float(stamp), "visible": False,
                "tag_id": None, "x": None, "y": None, "yaw": None, "range_m": None,
                "confidence": 0.0, "revision": None}
    return {"source": SOURCE, "stamp": float(stamp), "visible": True, "tag_id": None,
            "x": float(observation.x), "y": float(observation.y),
            "yaw": float(observation.yaw), "range_m": float(observation.range_m),
            "confidence": float(observation.confidence), "revision": None}
