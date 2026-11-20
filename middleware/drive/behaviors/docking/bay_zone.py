"""core_features.docking.bay_zone — 칸 안에서 도킹을 켰을 때 어떻게 움직일지 판정한다
(D-1013 후속, 2026-11-18 사고와 패널).

칸 접근(`approach="line"`)은 원래 Nav2 로 칸 앞 스테이징까지 간 뒤 제자리 180° 회전한다. 로봇이
이미 칸 줄(칸 안이나 칸 입구와 스테이징 사이)에 있으면 그 Nav2 가 이웃 로봇 옆에서 제자리
회전·회복 동작을 할 수 있다(2026-11-18 옆 칸 접촉). 그래서 칸 줄 안에서는 Nav2 도 제자리 회전도
쓰지 않는다:

- out: 스테이징 근처나 밖 — 기존 흐름(Nav2 스테이징 → 회전).
- acquire: 칸 줄 안에서 이미 곧게 서 있다(횡·방위가 후진 정렬 허용 안) — 나가지 않고 그 자리에서 선 포획부터.
  선이 스테이징 거리 앞에서 끝나는 현장(2026-11-20 y8xs)에서 나가기는 선을 잃는다.
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
DISAGREE = "map pose and guide line disagree"


@dataclass(frozen=True)
class ZoneVerdict:
    kind: str            # "out" | "acquire" | "exit" | "manual"
    reason: str
    exit_m: float = 0.0  # exit: 곧게 전진할 거리


def lane_edge(cfg, dock=None) -> float:
    """Half the bay lane width: the map owns it (dock metadata "lane_width_m", 0.10-0.24: edge <= 0.12 so a wrong value cannot admit the neighbour lane), bay_lane_width_m is the default."""
    width = getattr(dock, "metadata", {}).get("lane_width_m") if dock is not None else None
    if not isinstance(width, (int, float)) or isinstance(width, bool) or not 0.10 <= width <= 0.24:
        width = cfg.bay_lane_width_m
    return width / 2.0


def lane_extent(cfg, lateral: float, heading: float) -> float:
    """The farthest the body (corners incl. the tray) reaches sideways from the lane axis: the lane keeping check is a FOOTPRINT check, not a centre limit
    (panel B 2026-11-21: tray corner radius 0.144, so the allowed centre offset shrinks with heading: +-0.048 at 0 deg, +-0.026..0.032 at 10 deg)."""
    s, c = math.sin(heading), math.cos(heading)
    corners = [(fx, hy) for fx in (cfg.bay_body_front_m, -cfg.bay_turn_rear_overhang_m) for hy in (cfg.bay_body_half_width_m, -cfg.bay_body_half_width_m)]
    # bay frame: y to the left of the seated robot, heading ccw+ (the spin test: w>0 = ccw = LiDAR +), lateral = -y. A corner at robot-frame (fx, hy) is at
    # y + fx*sin(h) + hy*cos(h), i.e. lateral - fx*sin(h) - hy*cos(h): a ccw heading swings the tray (fx<0) toward -y = +lateral (right).
    return max(abs(lateral - fx * s - hy * c) for fx, hy in corners)


def scan_fit_pose(match, cfg):
    """(along, lateral, heading) of a LiDAR bay pose that passes only the FIT gates (inliers, margin, heading), no lane or staging-distance
    gate: for a dock already being docked (the entry check at the staging point, x beyond the row). None when the fit is not good."""
    if match is None or not all(math.isfinite(v) for v in (match.x, match.y, match.heading, match.inliers, match.margin)):
        return None
    if match.inliers < cfg.bay_scan_inlier_min or match.margin < cfg.bay_scan_margin_min or abs(match.heading) > cfg.bay_scan_heading_max_rad:
        return None
    return match.x, -match.y, match.heading


def scan_geometry(match, staging_offset_m: float, cfg):
    """(along, lateral, heading) of the zone check from a LiDAR bay-pose match, or None when it is not good enough.

    Bay frame -> dock frame: along = x (out of the bay), lateral = -y (the dock's +x points into the bay, so its left
    is the seated robot's right), heading is the same. Wrong-bay protection stays: a good fit (inliers, margin to the
    next different pose), inside this bay's lane, inside the row, a plausible heading. Anything else: None -> map path."""
    if match is None or not all(math.isfinite(v) for v in (match.x, match.y, match.heading, match.inliers, match.margin)):
        return None
    if match.inliers < cfg.bay_scan_inlier_min or match.margin < cfg.bay_scan_margin_min:
        return None
    if abs(match.y) > cfg.bay_lane_half_m or abs(match.heading) > cfg.bay_scan_heading_max_rad:
        return None
    if match.x >= staging_offset_m - cfg.bay_zone_margin_m:
        return None                          # at or past staging the reference scan no longer sees the bay
    return match.x, -match.y, match.heading


def pose_gate(match, cfg, staging_offset_m=None) -> Optional[str]:
    """The first gate a LiDAR bay pose fails, as text (None = it passes): what status.last_event names when a pose is dropped."""
    if match is None:
        return "no fit"
    if not all(math.isfinite(v) for v in (match.x, match.y, match.heading, match.inliers, match.margin)):
        return "non-finite pose"
    if match.inliers < cfg.bay_scan_inlier_min:
        return "inliers %.2f < %.2f" % (match.inliers, cfg.bay_scan_inlier_min)
    if match.margin < cfg.bay_scan_margin_min:
        return "margin %.2f < %.2f" % (match.margin, cfg.bay_scan_margin_min)
    if abs(match.heading) > cfg.bay_scan_heading_max_rad:
        return "heading %.0f deg" % math.degrees(match.heading)
    if abs(match.y) > cfg.bay_lane_half_m:
        return "|y| %.3f m outside the lane" % abs(match.y)
    if staging_offset_m is not None and match.x >= staging_offset_m - cfg.bay_zone_margin_m:
        return "x %.3f m at or beyond staging" % match.x
    return None


def scan_diagnosis(asked: bool, match, error, scan, cfg) -> str:
    """Why the LiDAR bay pose was or was not used, for the refusal text (CORE's Python logging does not reach the journal)."""
    if scan is not None:
        return "[scan pose used]"
    if not asked:
        return "[scan pose: never requested]"
    if match is None:
        return "[scan pose: no answer in %.1f s]" % cfg.bay_scan_pose_wait_s
    m = match[0]
    if m is None:
        return "[scan pose: no fit%s]" % (" (%s)" % error if error else "")
    return ("[scan pose rejected: inliers %.2f (min %.2f) margin %.2f (min %.2f) x %.3f y %.3f heading %.1f deg]"
            % (m.inliers, cfg.bay_scan_inlier_min, m.margin, cfg.bay_scan_margin_min, m.x, m.y, math.degrees(m.heading)))


def map_offsets(pose, dock) -> tuple[float, float, float]:
    """(칸 입구 밖으로의 거리, 칸 축에서의 횡, 코가 칸 밖을 보는 방향과의 각)."""
    x, y, yaw = pose
    c, s = math.cos(dock.yaw), math.sin(dock.yaw)       # dock.yaw = 칸 안쪽 축
    dx, dy = x - dock.x, y - dock.y
    return -(dx * c + dy * s), -dx * s + dy * c, _wrap(yaw - dock.yaw - math.pi)


def classify(pose, dock, staging_offset_m: float, observation, cfg, scan=None) -> ZoneVerdict:
    """`scan`: (along, lateral, heading) from scan_geometry, measured by LiDAR; it replaces the map pose."""
    src = "scan" if scan is not None else "map"
    if scan is not None:
        along, lateral, heading = scan
    elif pose is None:
        return ZoneVerdict("manual", "map pose unavailable")
    else:
        along, lateral, heading = map_offsets(pose, dock)
    if along >= staging_offset_m - cfg.bay_zone_margin_m:
        # One-way corridor: Nav2 would drive against the flow into a robot leaving the bay row.
        if (cfg.bay_downstream_sign and abs(along - staging_offset_m) <= cfg.bay_corridor_band_m
                and lateral * cfg.bay_downstream_sign > cfg.bay_lane_half_m + cfg.bay_downstream_map_error_m):
            return ZoneVerdict("manual", "downstream of this bay on the one-way corridor: re-enter from the upstream side")
        return ZoneVerdict("out", "at or beyond the staging distance")
    if abs(lateral) > cfg.bay_lane_half_m:
        return ZoneVerdict("manual", "inside the bay row but not in this bay's lane")
    seen = None if observation is None else rear_errors(observation)
    if seen is not None and scan is None:
        heading = seen[2]        # the camera sees the line: its heading decides, the SLAM yaw may be 17-30 deg off (a LiDAR pose is checked against it instead)
    if abs(heading) > math.pi / 2:
        return ZoneVerdict("manual", "nose toward the bay: leaving needs a reverse without rear sight")
    if seen is None:
        return ZoneVerdict("manual", NO_LINE)
    _, o_lat, o_head = seen
    # A lateral CORE filled from its own estimate or the map says nothing: never compare the map with itself (2026-11-20).
    # Only a measured line lateral is evidence; a corridor-only frame gives the heading, and the steering checks below
    # then use the pose source's lateral.
    measured = getattr(observation, "lateral_measured", True)
    if not measured:
        if scan is None:
            # A corridor-only frame gives a heading; a lateral from the map alone is not evidence (2026-11-20 review L2).
            return ZoneVerdict("manual", "no measured lateral: corridor line only and no LiDAR scan pose (centre it, or store a reference scan)")
        o_lat = lateral
    if (measured and abs(o_lat - lateral) > cfg.bay_zone_agree_m) or abs(_wrap(o_head - heading)) > cfg.bay_zone_agree_rad:
        # The numbers tell a stale map (odom slip near the bay) from a wrong bay at a glance; the verdict itself is unchanged.
        return ZoneVerdict("manual", DISAGREE + " (lateral %s %.3f line %.3f m, heading %s %.1f line %.1f deg)"
                           % (src, lateral, o_lat, src, math.degrees(heading), math.degrees(o_head)))
    if scan is not None:
        # The LiDAR pose is authoritative for lateral and heading (the camera line heading is 6-25 deg off at this site and passes the agreement gate
        # above): the camera only had to agree. b8xy C2 x 0.214: LiDAR straight (y -1 mm, 0.1 deg, extent 0.057), camera -9 deg / -15 mm -> the
        # camera-driven footprint check refused a robot that was inside its lane. The disagreement gates above are unchanged.
        o_lat, o_head = lateral, heading
    # Straight enough that the reverse run (along) cannot leave the lane: the rear already faces the bay, so there is
    # no turn and no runway to find, only the line to hold.
    if abs(o_lat) <= cfg.bay_exit_lateral_m and lane_extent(cfg, o_lat, o_head) <= lane_edge(cfg, dock) and abs(o_head) <= min(
            cfg.bay_acquire_heading_max_rad, math.atan(cfg.bay_exit_lateral_m / max(along, 0.05))):
        return ZoneVerdict("acquire", "straight in the lane: acquire where it stands")
    if lane_extent(cfg, o_lat, o_head) > lane_edge(cfg, dock):      # measured values (the line's, or the LiDAR's when it was used): a footprint check, not a centre limit
        return ZoneVerdict("manual", "inside the bay row but the body (with the tray) overlaps a neighbour lane: not moving in the row")
    exit_m = staging_offset_m - along + cfg.bay_exit_extra_m
    limit = cfg.bay_exit_heading_max_rad
    if cfg.bay_exit_steer_head <= 0.0:       # no line steering on the way out: a straight drive must stay in
        limit = min(limit, math.atan(cfg.bay_exit_lateral_m / max(exit_m, 0.05)))
    if abs(o_lat) > cfg.bay_exit_lateral_m or abs(o_head) > limit:
        return ZoneVerdict("manual", "not straight enough to leave the lane")
    return ZoneVerdict("exit", "leave straight along the bay axis", exit_m)