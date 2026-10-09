"""core_features.swarm.trail — D-559 리더 자취 재생(path replay). ROS 무의존.

리더가 실제로 지나간 점(자취)을 쌓고, 팔로워는 그 위를 경로 거리 `gap` 만큼 뒤에서
pure pursuit 로 따라간다. 리더의 지금 pose 에 오프셋을 둔 목표를 쫓는 D-20 방식은
모서리를 가로지른다 — 자취 재생은 리더가 돈 곳에서 돈다.

좌표는 전부 map 프레임이다. 두 로봇이 같은 맵에서 서로 맞는 자기 위치를 갖고 있다는
것이 전제이고, 그 확인은 이 모듈 밖(SwarmManager 의 map_id·frame 검사)에 있다.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from typing import Optional

#: 자취 점 사이 최소 간격 (m). 정지한 리더의 자세 떨림이 점을 쌓지 않게 한다.
CRUMB_M = 0.03
#: 팔로워 진행 위치보다 이만큼 뒤의 점은 버린다 (m).
PRUNE_BEHIND_M = 1.0
#: 점 개수 상한. 3 cm 간격이면 60 m 다 — 팔로워가 그만큼 뒤처졌으면 이미 끊긴 대형이다.
MAX_CRUMBS = 2000
#: 시작할 때 팔로워–리더 직선 거리 상한, 그리고 표본 사이 건너뜀의 절대 상한 (m).
#: 그 사이는 직선으로 이을 수밖에 없는데, 실제 경로를 모르는 직선을 길게 그으면 벽을 지난다.
#: 표본 사이 상한은 호출자가 시간으로 준다(`add(max_jump=...)`): 10 Hz 스트림에서 0.3 m 넘게
#: 튄 표본은 재지역화이지 주행이 아니다.
JOIN_MAX_M = 1.5
#: 자취에서 이만큼 벗어나면 따라가지 않는다 (m). 위치가 튀었거나 밀렸다.
LOST_M = 0.30
#: 팔로워 진행 위치는 지금 위치에서 이 경로 거리 앞까지만 찾는다 (m). 자취가 스스로
#: 겹치는 곳(고리)에서 뒤쪽 통과 지점으로 건너뛰지 않게 한다.
SEARCH_AHEAD_M = 0.5
#: pure pursuit 의 앞보기 경로 거리 (m).
LOOKAHEAD_M = 0.20
#: 남은 거리(경로 거리 − gap) → 속도 이득 (1/s). 정상 주행에서 gap 을 v/K 만큼 넘겨 따라간다.
K_GAP = 2.0
#: 가속 상한 (m/s²). 감속은 막지 않는다.
ACCEL_MPS2 = 0.5
#: 이보다 느린 명령은 0 이다. gap 에 지수로 다가가는 꼬리가 바퀴 데드밴드 안에서 끝없이 남지 않게.
MIN_LINEAR = 0.01


class TrailError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Trail:
    """리더 자취와 그 위의 팔로워 진행 위치. 경로 거리 `s` 는 시작부터의 누적 길이다."""

    def __init__(self, start: tuple[float, float], leader: tuple[float, float]) -> None:
        """첫 점은 팔로워 자신, 다음은 리더다. 대열에서 그 직선은 리더가 막 지나온 길이다."""
        join = math.hypot(leader[0] - start[0], leader[1] - start[1])
        if join > JOIN_MAX_M:
            raise TrailError("TRAIL_JOIN_TOO_FAR",
                             f"leader is {join:.2f} m away; trail follow joins within {JOIN_MAX_M} m")
        self._x = [float(start[0])]
        self._y = [float(start[1])]
        self._s = [0.0]
        #: 팔로워 진행 위치 s_F. 줄지 않는다.
        self.progress = 0.0
        if join >= CRUMB_M:
            self._append(leader[0], leader[1])

    @property
    def leader_s(self) -> float:
        return self._s[-1]

    def add(self, x: float, y: float, yaw: float, max_jump: float = JOIN_MAX_M) -> bool:
        """리더 표본 하나. False 면 리더가 max_jump(≤ JOIN_MAX_M) 넘게 건너뛰었다(자취를 이을 수 없다).

        뒤로 가는 리더(이동이 리더 heading 반대쪽)는 점을 쌓지 않는다 — 진행 거리가
        줄지 않으니 남은 간격만 줄어 팔로워는 선다. 리더가 마지막 점을 다시 지나면 이어 쌓는다.
        """
        dx, dy = x - self._x[-1], y - self._y[-1]
        distance = math.hypot(dx, dy)
        if distance < CRUMB_M:
            return True
        if dx * math.cos(yaw) + dy * math.sin(yaw) < 0.0:
            return True
        if distance > min(max_jump, JOIN_MAX_M):
            return False
        self._append(x, y)
        return True

    def _append(self, x: float, y: float) -> None:
        self._s.append(self._s[-1] + math.hypot(x - self._x[-1], y - self._y[-1]))
        self._x.append(float(x))
        self._y.append(float(y))
        drop = bisect_right(self._s, self.progress - PRUNE_BEHIND_M) - 1
        drop = max(drop, len(self._s) - MAX_CRUMBS)
        if drop > 0:
            del self._x[:drop], self._y[:drop], self._s[:drop]

    def _segment(self, s: float) -> int:
        """s 를 담은 구간의 시작 점 번호."""
        return min(max(bisect_right(self._s, s) - 1, 0), len(self._s) - 2)

    def point_at(self, s: float) -> tuple[float, float]:
        if len(self._s) == 1:
            return self._x[0], self._y[0]
        i = self._segment(s)
        length = self._s[i + 1] - self._s[i]
        t = 0.0 if length <= 0.0 else min(max((s - self._s[i]) / length, 0.0), 1.0)
        return (self._x[i] + t * (self._x[i + 1] - self._x[i]),
                self._y[i] + t * (self._y[i + 1] - self._y[i]))

    def locate(self, x: float, y: float) -> tuple[float, float]:
        """(진행 위치, 자취까지 거리). 지금 진행 위치부터 SEARCH_AHEAD_M 앞까지만 본다."""
        if len(self._s) == 1:
            return self.progress, math.hypot(x - self._x[0], y - self._y[0])
        best_s, best_d = self.progress, math.inf
        i = self._segment(self.progress)
        limit = self.progress + SEARCH_AHEAD_M
        while i < len(self._s) - 1 and self._s[i] <= limit:
            ax, ay = self._x[i], self._y[i]
            vx, vy = self._x[i + 1] - ax, self._y[i + 1] - ay
            length2 = vx * vx + vy * vy
            t = 0.0 if length2 <= 0.0 else min(max(((x - ax) * vx + (y - ay) * vy) / length2, 0.0), 1.0)
            d = math.hypot(x - ax - t * vx, y - ay - t * vy)
            if d < best_d:
                best_d, best_s = d, self._s[i] + t * (self._s[i + 1] - self._s[i])
            i += 1
        self.progress = max(self.progress, best_s)
        return self.progress, best_d


def trail_twist(trail: Trail, x: float, y: float, yaw: float, *, gap: float, max_speed: float,
                max_angular: float, prev_linear: float, dt: float,
                lookahead: float = LOOKAHEAD_M) -> tuple[float, float, Optional[str]]:
    """(linear, angular, hold 사유). 사유가 None 이면 달리거나 gap 에 닿아 서 있는 것이다."""
    s, off = trail.locate(x, y)
    if off > LOST_M:
        return 0.0, 0.0, "trail_lost"
    linear = min(max_speed, K_GAP * (trail.leader_s - s - gap),
                 max(0.0, prev_linear) + ACCEL_MPS2 * max(0.0, dt))
    if linear < MIN_LINEAR:
        return 0.0, 0.0, None
    gx, gy = trail.point_at(min(s + lookahead, trail.leader_s))
    dx, dy = gx - x, gy - y
    reach = math.hypot(dx, dy)
    if reach < 1e-6:
        return 0.0, 0.0, None
    alpha = math.atan2(dy, dx) - yaw
    alpha = math.atan2(math.sin(alpha), math.cos(alpha))
    if abs(alpha) > math.pi / 2:
        # 자취가 등 뒤에 있다(시작 자세가 틀어졌다). 제자리에서 돌아 세운다.
        return 0.0, math.copysign(max_angular, alpha), None
    angular = 2.0 * linear * math.sin(alpha) / reach
    if abs(angular) > max_angular:
        # 곡률을 지킨다: 회전을 자르면 바깥으로 밀리니 속도를 같이 줄인다.
        linear *= max_angular / abs(angular)
        angular = math.copysign(max_angular, angular)
    return linear, angular, None
