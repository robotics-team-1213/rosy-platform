"""D-536: where each robot is on the site map, what is wrong, and where it should go — pure.

One record per robot, built from what Fleet already holds: the arbitrated map pose (D-494), the
Rosy Cam tracking row (D-457), the robot's own state row, the active site graph and the traffic zones.
The console draws the record (body circle, heading, uncertainty ring, guide target) and lists the
findings in the exception queue. Nothing here commands a robot.

Findings carry map coordinates so the operator (or a later automatic step) can act at once:
``target`` is a map pose ``{x, y, yaw}`` to bring the robot to, ``action`` names an existing
console action (``relearn`` a camera background, ``identify`` by LED).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

#: tracking statuses that mean Rosy Cam did not find the robot this lease (tracking_match.py)
NOT_SEEN = frozenset({"NO_POSE"})
SEVERITY = ("crit", "warn", "info")


@dataclass(frozen=True)
class GuideConfig:
    #: pose uncertainty u = sighting floor + odom drift per bridged metre (D-517 3, trip_ports)
    sighting_floor_m: float = 0.12
    drift_per_m: float = 0.05
    #: two body circles closer than this gap are too close (rotation radius each, D-424)
    near_gap_m: float = 0.03
    #: a robot standing inside a zone this long blocks it (D-517 3, D-525 3)
    zone_stop_s: float = 10.0
    #: heading further than this from a one-way lane's direction is the wrong way
    wrong_way_deg: float = 100.0
    #: a lane is "the robot's lane" only within this many lane widths of its centre line
    lane_reach_widths: float = 1.5


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def uncertainty_m(dead_reckon_m: float, config: GuideConfig = GuideConfig()) -> float:
    return config.sighting_floor_m + config.drift_per_m * max(0.0, dead_reckon_m or 0.0)


def lane_context(graph, x: float, y: float, yaw: Optional[float], zone_of: Mapping[str, str],
                 config: GuideConfig = GuideConfig()) -> Optional[dict]:
    """The lane the robot is on: the nearest arc travelled its way (heading within 90°), else the
    nearest arc at all. ``lateral_m`` > 0 is left of the lane's direction. None: off every lane."""
    best = None
    for arc in graph.arcs.values():
        dist, s, tangent = arc.project(x, y)
        if dist > arc.width_m * config.lane_reach_widths:
            continue
        err = None if yaw is None else _wrap(yaw - tangent)
        rank = (0 if err is None or abs(err) <= math.pi / 2 else 1, dist)
        if best is None or rank < best[0]:
            best = (rank, arc, dist, s, tangent, err)
    if best is None:
        return None
    _rank, arc, dist, s, tangent, err = best
    px, py, _ = arc.point_at(s)
    left = math.cos(tangent) * (y - py) - math.sin(tangent) * (x - px)
    two_way = any(other.edge_id == arc.edge_id and other.forward != arc.forward for other in graph.arcs.values())
    return {"edge_id": arc.edge_id, "arc_id": arc.id, "s_m": round(s, 3), "length_m": round(arc.length_m, 3),
            "lateral_m": round(math.copysign(dist, left), 3), "width_m": arc.width_m,
            "heading_err_deg": None if err is None else round(math.degrees(err), 1), "one_way": not two_way,
            "zone": zone_of.get(arc.edge_id), "centre": {"x": round(px, 3), "y": round(py, 3), "yaw": round(tangent, 4)},
            "next_place": {"place_id": arc.end_place, "distance_m": round(arc.length_m - s, 3)}}


def _finding(code: str, severity: str, text: str, *, target: Optional[dict] = None,
             action: Optional[dict] = None) -> dict:
    row = {"code": code, "severity": severity, "text": text}
    if target is not None:
        row["target"] = target
    if action is not None:
        row["action"] = action
    return row


def situation(robot_id: str, *, online: bool, pose, tracking_row: Optional[Mapping],
              camera_ok: Optional[str], graph, zone_of: Mapping[str, str], body_radius_m: float,
              body_half_width_m: float, stopped_s: float = 0.0, anonymous_seen: bool = False,
              config: GuideConfig = GuideConfig()) -> dict:
    """One robot's record. ``pose`` is a ``MapPose`` (or None); ``camera_ok`` the id of a Rosy Cam
    source reporting OK, or None; ``stopped_s`` how long it has not moved (the service keeps it);
    ``anonymous_seen`` whether Rosy Cam shows a blob no robot is matched to (D-596: then the LED
    identify names it, standing or not; without one the robot is likely learned into the background)."""
    placed = pose is not None and pose.state in ("LOCALIZED", "DEGRADED") and pose.x is not None
    record = {"robot_id": robot_id, "online": online, "body_radius_m": body_radius_m,
              "pose": None, "lane": None, "findings": []}
    findings = record["findings"]
    if placed:
        record["pose"] = {"x": round(pose.x, 3), "y": round(pose.y, 3),
                          "yaw": None if pose.yaw is None else round(pose.yaw, 4), "state": pose.state,
                          "source": pose.source, "u_m": round(uncertainty_m(pose.dead_reckon_m, config), 3),
                          "age_s": pose.age_s,
                          # D-593: who set the anchor and how old it is ("운영자 핀 · 4 s")
                          "anchor_source": getattr(pose, "anchor_source", None),
                          "anchor_age_s": getattr(pose, "anchor_age_s", None)}
    if not online:
        return record          # the roster already says "연결 끊김"; a stale pose stays drawn faded
    status = (tracking_row or {}).get("status")
    if camera_ok and status in NOT_SEEN and anonymous_seen:
        findings.append(_finding(
            "CAMERA_NOT_SEEING", "warn",
            f"Rosy Cam이 {robot_id}를 찾지 못합니다 · 이름 없는 로봇이 보입니다. "
            "LED로 찾기(멈춘 채로 됩니다)",
            action={"kind": "identify", "robot_id": robot_id}))
    elif camera_ok and status in NOT_SEEN:
        findings.append(_finding(
            "CAMERA_NOT_SEEING", "warn",
            f"Rosy Cam이 {robot_id}를 찾지 못합니다 · 로봇이 매트 위에 있을 때 배경을 배웠다면 로봇이 배경이 됩니다. "
            "로봇을 매트 밖으로 옮긴 뒤 배경 다시 학습",
            action={"kind": "relearn", "source_id": camera_ok}))
    if pose is not None and pose.odom_refused_reason == "future":
        findings.append(_finding(
            "ODOM_CLOCK_AHEAD", "warn",
            f"{robot_id}의 odom 시각이 관제 PC보다 앞서 버려집니다({pose.odom_refused}건) · 로봇 시간 동기(NTP)를 확인하세요"))
    if not placed:
        if not findings:
            findings.append(_finding("POSE_UNKNOWN", "info", f"{robot_id}의 지도 위치를 모릅니다 · Rosy Cam 관측을 기다립니다"))
        return record
    lane = lane_context(graph, pose.x, pose.y, pose.yaw, zone_of, config) if graph is not None else None
    record["lane"] = lane
    if lane is None:
        findings.append(_finding("OFF_MAP", "warn", f"{robot_id}가 어느 차로에도 없습니다 · 차로 위로 옮기세요"))
        return record
    centre = lane["centre"]
    margin = lane["width_m"] / 2 - (abs(lane["lateral_m"]) + body_half_width_m)
    if margin < 0:
        side = "왼쪽" if lane["lateral_m"] > 0 else "오른쪽"
        findings.append(_finding(
            "OFF_LANE", "warn",
            f"{robot_id}가 {lane['edge_id']} 차로 {side}로 {abs(margin) * 100:.0f} cm 벗어났습니다 · 표시한 차로 중심으로",
            target=centre))
    if lane["one_way"] and lane["heading_err_deg"] is not None and abs(lane["heading_err_deg"]) > config.wrong_way_deg:
        findings.append(_finding(
            "WRONG_WAY", "warn",
            f"{robot_id}가 일방 차로 {lane['edge_id']}에서 거꾸로 섰습니다({lane['heading_err_deg']:+.0f}°) · 표시한 방향으로 돌리세요",
            target=centre))
    if lane["zone"] and stopped_s >= config.zone_stop_s:
        findings.append(_finding(
            "STOPPED_IN_ZONE", "crit",
            f"{robot_id}가 구역 {lane['zone']} 안에 {stopped_s:.0f}초 서 있습니다 · 다른 로봇이 들어가지 못합니다. "
            f"{lane['next_place']['place_id']}까지 {lane['next_place']['distance_m']:.2f} m",
            target=centre))
    return record


def near_pairs(records: Iterable[dict], config: GuideConfig = GuideConfig()) -> list[tuple[str, str, float]]:
    """Pairs of placed online robots whose body circles come within ``near_gap_m``: (a, b, gap m)."""
    placed = [r for r in records if r["pose"] is not None and r["online"]]
    out = []
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            centre = math.hypot(a["pose"]["x"] - b["pose"]["x"], a["pose"]["y"] - b["pose"]["y"])
            gap = centre - a["body_radius_m"] - b["body_radius_m"]
            if gap < config.near_gap_m:
                out.append((a["robot_id"], b["robot_id"], round(gap, 3)))
    return out


def add_near(records: list[dict], config: GuideConfig = GuideConfig()) -> None:
    for a, b, gap in near_pairs(records, config):
        for me, other in ((a, b), (b, a)):
            row = next(r for r in records if r["robot_id"] == me)
            row["findings"].append(_finding(
                "TOO_CLOSE", "crit",
                f"{me}와 {other}의 몸체 사이가 {gap * 100:.0f} cm입니다 · 한 대를 멈추고 떼어 놓으세요"))


def worst(record: dict) -> Optional[str]:
    levels = [f["severity"] for f in record["findings"]]
    return next((s for s in SEVERITY if s in levels), None)
