"""core_features.docking.parking — 주차형 도크의 포즈 추정과 제어 법칙.

차선망 미션 3단계(docs/plans/2026-09-23-lane-network-parking-design.md). 주차점은
태그 앞 `tag_offset_m` 에 있고, 태그 관측(base_link 기준 태그 중심과 안쪽 축의
방위)만으로 도크 좌표계에서의 로봇 포즈를 세운다. 도크 좌표계: 원점이 주차점,
x 축이 태그를 향하는 도크 축, y 왼쪽. 로봇이 주차점에 태그를 정면으로 보고 서면
(0, 0, 0) 이다.

관측은 5 Hz 라 프레임 사이는 오도메트리 증분으로 전파한다. 관측은 촬영 시각의
오도메트리와 짝짓는다 — 처리 지연 동안 움직인 만큼을 한 번 더 세지 않기 위해서다.

ROS 무의존. 시계와 오도메트리는 호출자가 넣는다.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Optional


def wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def robot_in_dock_frame(x: float, y: float, yaw: float,
                        tag_offset_m: float) -> tuple[float, float, float]:
    """(ex, ey, eθ) from one tag observation in base_link.

    The tag sits at (tag_offset_m, 0) in the dock frame with its inward axis
    along +x; the robot sees it at (x, y) with that axis at `yaw`. So the
    robot's heading in the dock frame is -yaw and its position is the tag's
    minus the observation rotated into the dock frame."""
    heading = -yaw
    c, s = math.cos(heading), math.sin(heading)
    return (tag_offset_m - (c * x - s * y), -(s * x + c * y), wrap(heading))


def compose(pose, delta) -> tuple[float, float, float]:
    """pose (+) delta, both (x, y, yaw); delta in pose's own frame."""
    x, y, yaw = pose
    dx, dy, dyaw = delta
    c, s = math.cos(yaw), math.sin(yaw)
    return (x + c * dx - s * dy, y + s * dx + c * dy, wrap(yaw + dyaw))


def between(a, b) -> tuple[float, float, float]:
    """The increment from odometry pose a to b, in a's frame."""
    c, s = math.cos(a[2]), math.sin(a[2])
    wx, wy = b[0] - a[0], b[1] - a[1]
    return (c * wx + s * wy, -s * wx + c * wy, wrap(b[2] - a[2]))


class DockPoseTracker:
    """The robot's dock-frame pose: the last observation, carried forward
    by odometry. `record_odometry` every tick; `observe` each new
    observation (its `.at` on the same clock); `pose(odom)` now."""

    def __init__(self, tag_offset_m: float, history_s: float = 3.0,
                 max_pair_gap_s: float = 0.1) -> None:
        self._offset = float(tag_offset_m)
        self._history_s = float(history_s)
        # An observation pairs only with odometry recorded this close to its
        # capture time; farther, the pairing would put the latency back in.
        self._max_pair_gap_s = float(max_pair_gap_s)
        self._odometry: deque = deque()
        self._anchor: Optional[tuple] = None      # (dock pose, odom pose, at)

    def reset(self) -> None:
        self._anchor = None

    @property
    def anchored_at(self) -> Optional[float]:
        return None if self._anchor is None else self._anchor[2]

    def record_odometry(self, now: float, odom) -> None:
        if odom is None:
            return
        self._odometry.append((float(now), tuple(float(v) for v in odom)))
        while self._odometry and self._odometry[0][0] < now - self._history_s:
            self._odometry.popleft()

    def _odometry_at(self, at: float):
        """The recorded odometry pose nearest in time to `at`, if it is within
        `max_pair_gap_s` of it."""
        if not self._odometry:
            return None
        sample_t, odom = min(self._odometry, key=lambda sample: abs(sample[0] - at))
        return odom if abs(sample_t - at) <= self._max_pair_gap_s else None

    def observe(self, observation) -> bool:
        """Anchor on a new observation; False if it is not newer or no
        odometry was recorded near its capture time to pair it with."""
        at = float(observation.at)
        if self._anchor is not None and at <= self._anchor[2]:
            return False
        odom = self._odometry_at(at)
        if odom is None:
            return False
        dock = robot_in_dock_frame(observation.x, observation.y, observation.yaw,
                                   self._offset)
        self._anchor = (dock, odom, at)
        return True

    def pose(self, odom) -> Optional[tuple[float, float, float]]:
        if self._anchor is None or odom is None:
            return None
        dock, anchor_odom, _ = self._anchor
        return compose(dock, between(anchor_odom, tuple(float(v) for v in odom)))

    def carry(self, odom) -> None:
        """Re-anchor on the current propagated pose, keeping it without
        observations (backoff: the detector is off)."""
        pose = self.pose(odom)
        if pose is not None:
            self._anchor = (pose, tuple(float(v) for v in odom), self._anchor[2])


@dataclass(frozen=True)
class ParkingGains:
    speed_max: float = 0.05          # m/s, the last 0.1 m is a crawl
    speed_min: float = 0.015
    gain_range: float = 0.5          # 1/s on the remaining distance
    gain_lateral: float = 20.0       # rad/m: θ_ref = -atan(k·ey)
    heading_limit: float = 0.35      # rad, keeps the tag in view
    gain_heading: float = 2.5        # 1/s
    max_angular: float = 0.5
    arrive_m: float = 0.003
    creep_speed: float = 0.03
    turn_gain: float = 2.0
    turn_min_angular: float = 0.15
    turn_tolerance_rad: float = math.radians(1.0)
    reverse_speed: float = 0.05
    reverse_gain_lateral: float = 10.0


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def approach_twist(pose, gains: ParkingGains) -> tuple[float, float, bool]:
    """(linear, angular, arrived) toward the spot from dock-frame `pose`.

    A straight-line follower on the dock axis: the heading reference
    steers the lateral error out while the remaining distance shrinks the
    speed to a crawl. Arrived once the spot is within `arrive_m` (or
    passed): the caller stops and aligns the heading in place."""
    ex, ey, heading = pose
    remaining = -ex
    if remaining <= gains.arrive_m:
        return 0.0, 0.0, True
    reference = -_clamp(math.atan(gains.gain_lateral * ey), gains.heading_limit)
    angular = _clamp(gains.gain_heading * wrap(reference - heading), gains.max_angular)
    linear = max(gains.speed_min, min(gains.speed_max, gains.gain_range * remaining))
    return linear, angular, False


def reverse_twist(pose, gains: ParkingGains) -> tuple[float, float]:
    """Backing away from the tag, steered so the lateral error shrinks
    (moving backward, a heading toward the error reduces it)."""
    _, ey, heading = pose
    reference = _clamp(math.atan(gains.reverse_gain_lateral * ey), gains.heading_limit)
    angular = _clamp(gains.gain_heading * wrap(reference - heading), gains.max_angular)
    return -gains.reverse_speed, angular


def turn_twist(error: float, gains: ParkingGains) -> tuple[float, bool]:
    """In-place turn toward a heading `error` away: (angular, done)."""
    if abs(error) <= gains.turn_tolerance_rad:
        return 0.0, True
    angular = _clamp(gains.turn_gain * error, gains.max_angular)
    if abs(angular) < gains.turn_min_angular:
        angular = math.copysign(gains.turn_min_angular, error)
    return angular, False
