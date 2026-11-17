"""core_features.docking.bay_zone — 칸 안에서 도킹을 켰을 때 어떻게 움직일지 판정한다
(D-1013 후속, 2026-11-18 사고와 패널).

칸 접근(`approach="line"`)은 원래 Nav2 로 칸 앞 스테이징까지 간 뒤 제자리 180° 회전한다. 로봇이
이미 칸 줄(칸 안이나 칸 입구와 스테이징 사이)에 있으면 그 Nav2 가 이웃 로봇 옆에서 제자리
회전·회복 동작을 할 수 있다(2026-11-18 옆 칸 접촉). 그래서 칸 줄 안에서는 Nav2 도 제자리 회전도
쓰지 않는다:

- out: 스테이징 근처나 밖 — 기존 흐름(Nav2 스테이징 → 회전).
- exit: 자기 칸 줄 안, 코가 밖을 보고(뒤가 칸 쪽) 분홍선이 보이고 곧게 서 있다 — 축을 따라
  곧게 전진해 스테이징 거리까지 나간 뒤, 이미 뒤가 칸을 보므로 회전 없이 선 포획부터.
- manual: 그 밖(맵 포즈 없음, 다른 칸 줄, 코가 칸 쪽, 선이 안 보임, 맵과 선이 어긋남, 곧은
  전진으로 줄을 벗어날 만큼 비뚤어짐) — 움직이지 않고 사람을 부른다.

맵 포즈는 "칸 줄 안인가"만 정하고(경계는 스테이징보다 margin 안쪽), 나갈 수 있는지는 선
관측으로 정한다 — 맵 등록 오차(수 cm)가 칸 반폭과 같은 크기라 맵만 믿지 않는다. ROS 무의존.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from core_features.docking.parking import wrap as _wrap
from core_features.docking.rear_phases import rear_errors


NO_LINE = "guide line not visible inside the bay"


@dataclass(frozen=True)
class ZoneVerdict:
    kind: str            # "out" | "exit" | "manual"
    reason: str
    exit_m: float = 0.0  # exit: 곧게 전진할 거리


def map_offsets(pose, dock) -> tuple[float, float, float]:
    """(칸 입구 밖으로의 거리, 칸 축에서의 횡, 코가 칸 밖을 보는 방향과의 각)."""
    x, y, yaw = pose
    c, s = math.cos(dock.yaw), math.sin(dock.yaw)       # dock.yaw = 칸 안쪽 축
    dx, dy = x - dock.x, y - dock.y
    return -(dx * c + dy * s), -dx * s + dy * c, _wrap(yaw - dock.yaw - math.pi)


def classify(pose, dock, staging_offset_m: float, observation, cfg) -> ZoneVerdict:
    if pose is None:
        return ZoneVerdict("manual", "map pose unavailable")
    along, lateral, heading = map_offsets(pose, dock)
    if along >= staging_offset_m - cfg.bay_zone_margin_m:
        return ZoneVerdict("out", "at or beyond the staging distance")
    if abs(lateral) > cfg.bay_lane_half_m:
        return ZoneVerdict("manual", "inside the bay row but not in this bay's lane")
    if abs(heading) > math.pi / 2:
        return ZoneVerdict("manual", "nose toward the bay: leaving needs a reverse without rear sight")
    if observation is None:
        return ZoneVerdict("manual", NO_LINE)
    _, o_lat, o_head = rear_errors(observation)
    if abs(o_lat - lateral) > cfg.bay_zone_agree_m or abs(_wrap(o_head - heading)) > cfg.bay_zone_agree_rad:
        return ZoneVerdict("manual", "map pose and guide line disagree")
    exit_m = staging_offset_m - along + cfg.bay_exit_extra_m
    limit = cfg.bay_exit_heading_max_rad
    if cfg.bay_exit_steer_head <= 0.0:       # no line steering on the way out: a straight drive must stay in
        limit = min(limit, math.atan(cfg.bay_exit_lateral_m / max(exit_m, 0.05)))
    if abs(o_lat) > cfg.bay_exit_lateral_m or abs(o_head) > limit:
        return ZoneVerdict("manual", "not straight enough to leave the lane")
    return ZoneVerdict("exit", "leave straight along the bay axis", exit_m)
