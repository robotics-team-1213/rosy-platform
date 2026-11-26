"""D-546 pose-request handling and S1 anchor provenance helpers for LocalizationService."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Mapping, Optional

import yaml

from core_common.protocol.localization import LocState
from fleet.localization import cues, pose_request, service_logic, trust
from fleet.swarm import transport

logger = logging.getLogger("fleet.localization")

MapFrame = tuple[str, str]


def load_lane_rules(path: Optional[Path]) -> dict:
    """`lane_rules.yaml` as a dict; {} (no squares, no slots) when absent or unreadable."""
    if path is None:
        return {}
    try:
        rules = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        logger.warning("localization: lane rules %s unreadable (%s); no squares or slots", path, exc)
        return {}
    return rules if isinstance(rules, dict) else {}


def default_lane_rules() -> Optional[Path]:
    """map_v2_fleet's lane_rules.yaml when Fleet runs from a source checkout, else None."""
    path = ((Path(__file__).resolve().parents[5] / "middleware") / "perception" / "map" / "map_v2_fleet"
            / "lane_rules.yaml")
    return path if path.is_file() else None


def map_frame(state: Mapping) -> MapFrame | None:
    """Map name and content identity used for comparing independent robot observations."""
    map_id = state.get("map_id")
    if not isinstance(map_id, str) or not map_id:
        return None
    grid = state.get("map_grid_id")
    return (map_id, grid) if isinstance(grid, str) and grid else None


async def handle_pose_request(svc, rid: str, client: transport.RobotClient, state: Mapping, now: float) -> None:
    """D-546 6: answer the robot's open pose request: overhead, arbiter, model, then a human."""
    reason = str(((state.get("line_follow") or {}).get("reason")) or "")
    if not reason.startswith("lane_return_") or reason == "lane_return_corridor_verified":
        svc._pose_req.pop(rid, None)
        svc._pose_tries.pop(rid, None)
        return
    try:
        request = await svc._bounded(client.localization_request())
    except Exception as exc:
        logger.debug("localization: %s pose request unreadable: %s", rid, exc)
        return
    if request is None:
        asked = svc._pose_req.get(rid)
        if asked is None or not asked.get("failed"):
            svc._pose_req.pop(rid, None)
        return
    if not pose_request.is_live(request):
        return
    asked = svc._pose_req.get(rid)
    if asked is not None:
        if asked["state"] == "needs_human" and asked.get("failed"):
            return
        if asked["request_id"] == request.get("request_id"):
            if asked["state"] == "needs_human" or now - asked["at"] < pose_request.RETRY_S:
                return
    tries = svc._pose_tries.get(rid, 0)
    if tries >= pose_request.MAX_ANSWERS:
        logger.warning("localization: %s pose request still open after %d answers: needs_human", rid, tries)
        svc._pose_req[rid] = {"request_id": request.get("request_id"), "at": now, "by": None,
                              "state": "needs_human", "tries": tries, "failed": True}
        return
    pose = svc._overhead_pose(rid) if svc._overhead_pose is not None and svc.pose_request_overhead else None
    robot_map = state.get("map_id") if isinstance(state, Mapping) else None
    decision = pose_request.overhead_decision(request, pose, robot_map_id=robot_map)
    if decision is not None:
        by = "overhead"
    else:
        status = trust.status_of(state)
        if (status is not None and status.state is LocState.CANDIDATES
                and svc._arbiter.pending(rid, status.request_id)):
            by = "arbiter"
        else:
            decision = pose_request.resolve_pose_with_model(request, state)
            by = None if decision is None else "model"
    if decision is not None:
        await svc._post_decision(rid, client, decision,
                                 (decision.pose.x, decision.pose.y, decision.pose.yaw), now, map_frame(state))
    if by is not None:
        tries += 1
        svc._pose_tries[rid] = tries
    record = {"request_id": request.get("request_id"), "at": now, "by": by,
              "state": "answered" if by else "needs_human", "tries": tries}
    if by is None and (asked is None or asked["state"] != "needs_human"):
        logger.warning("localization: %s pose request %s (%s) has no Fleet answer: needs_human",
                       rid, request.get("request_id"), request.get("reason"))
    svc._pose_req[rid] = record


def track_anchor_provenance(svc, states: Mapping[str, dict], localized: Mapping[str, cues.Pose],
                            now: float) -> None:
    """Anchors (S1 finding 3): LOCALIZED at the pose of a Fleet decision that a world
    cue, `source: human` or anchored peers carried."""
    operator_anchors = svc._search_window.operator_anchors
    for rid in operator_anchors.keys() - localized.keys():
        operator_anchors.pop(rid)
    for rid in states:
        pose = localized.get(rid)
        previous = svc._localized_at.get(rid)
        if pose is None:
            svc._anchors.discard(rid)
            svc._localized_at.pop(rid, None)
            continue
        frame = map_frame(states[rid])
        svc._localized_at[rid] = (pose, now, frame)
        if previous is None or previous[2] != frame:
            svc._anchors.discard(rid)
            operator_anchors.pop(rid, None)
            decided = svc._pending.pop(rid, None)
            unconfirmed = svc._unconfirmed.pop(rid, None)
            operator = svc._operator_pending.pop(rid, None)
            if operator is not None and operator[0] == frame and svc._reached(operator[1], pose, now):
                svc._anchors.add(rid)
                operator_anchors[rid] = (frame, states[rid].get("map_generation"))
                logger.info("localization: %s LOCALIZED at the operator-confirmed pose: anchor", rid)
            elif decided is not None and decided[0] == frame and not service_logic.disagrees(decided[1], pose):
                svc._anchors.add(rid)
                logger.info("localization: %s LOCALIZED by a Fleet decision: anchor", rid)
            elif unconfirmed is not None and unconfirmed[0] == frame and svc._reached(unconfirmed[1], pose, now):
                svc._anchors.add(rid)
                logger.info("localization: %s LOCALIZED at timed-out decision %s: confirmed, anchor",
                            rid, unconfirmed[1][0])
            else:
                logger.info("localization: %s LOCALIZED without a Fleet-known decision: "
                            "not an anchor, not a peer", rid)
        elif rid in svc._anchors and service_logic.jumped(previous[0], pose, now - previous[1]):
            svc._anchors.discard(rid)
            operator_anchors.pop(rid, None)
            logger.warning("localization: %s pose jumped while LOCALIZED: no longer an anchor", rid)


def check_reached_unconfirmed(unconfirmed: tuple, pose: cues.Pose, now: float, *,
                              unconfirmed_s: float, unconfirmed_m: float, unconfirmed_yaw_rad: float) -> bool:
    """A timed-out decision is confirmed by the robot's first LOCALIZED pose (S1 run 3 T2)."""
    _, decided, anchoring, sent = unconfirmed
    return (now - sent <= unconfirmed_s
            and math.dist(decided[:2], pose[:2]) <= unconfirmed_m
            and abs(cues.wrap(pose[2] - decided[2])) <= unconfirmed_yaw_rad
            and anchoring)


def known_obstacle_points(svc, observer_id: str, observer_pose: cues.Pose, observer_state: Optional[Mapping],
                          exclude_ids: set[str]) -> list[tuple[float, float]]:
    """Project measured non-target obstacle/parked poses onto the observer's robot-map frame."""
    provider = getattr(svc, "_site_obstacle_pose", None)
    if provider is None:
        return []
    site_map_id = None
    fit = svc._binding_fit_for_state(observer_id, observer_state) if isinstance(observer_state, Mapping) else None
    if fit is not None and svc._site_maps is not None and (active := svc._site_maps.active()) is not None:
        site_map_id = active[1].map_id

        def site_to_robot(sx: float, sy: float) -> tuple[float, float]:
            return fit.inverse((sx, sy))
    else:
        obs_site = provider(observer_id)
        if obs_site is None:
            return []
        site_map_id, osx, osy, osyaw = obs_site
        dyaw = observer_pose[2] - osyaw
        c, s = math.cos(dyaw), math.sin(dyaw)

        def site_to_robot(sx: float, sy: float) -> tuple[float, float]:
            return (
                observer_pose[0] + c * (sx - osx) - s * (sy - osy),
                observer_pose[1] + s * (sx - osx) + c * (sy - osy),
            )
    out: list[tuple[float, float]] = []
    for other_id in svc._clients():
        if other_id == observer_id or other_id in exclude_ids:
            continue
        other_site = provider(other_id)
        if other_site is None or other_site[0] != site_map_id:
            continue
        rx, ry = site_to_robot(other_site[1], other_site[2])
        out.append((rx, ry))
    return out


def observe_pose_from_anchors(svc, states: Mapping[str, dict], localized: Mapping[str, cues.Pose],
                              anchors: Mapping[str, cues.Pose], observations: dict, now: float) -> None:
    """D-395 rev. 4 §5 follow-up (S1 R1): a LOCALIZED anchor's status carries what its lidar sees."""
    for rid, pose in anchors.items():
        if svc._overhead_pose is not None and not service_logic.observer_pose_trustworthy(svc._overhead_pose(rid)):
            svc._objects_seen.pop(rid, None)
            continue
        frame = map_frame(states[rid])
        if frame is None:
            continue
        status = trust.status_of(states.get(rid))
        if status is None or status.objects_stamp is None:
            svc._objects_seen.pop(rid, None)
            continue
        seen = svc._objects_seen.get(rid)
        if seen is None or seen[0] != status.objects_stamp:
            seen = svc._objects_seen[rid] = (status.objects_stamp, now)
        if now - seen[1] > service_logic.REPORT_FRESH_S:
            continue
        targets = {o: p for o, p in localized.items() if o != rid and map_frame(states[o]) == frame}
        if not targets:
            continue
        known = known_obstacle_points(svc, rid, pose, states.get(rid), set(targets))
        for target, observed in service_logic.peer_observations(
                status.unmapped_objects, pose, targets, known_points=known).items():
            observations.setdefault(target, []).append((("objects", rid, status.objects_stamp), observed))


def fresh_overhead_sighting(
    svc, rid: str, now: float, force: bool = False, expected_map_id: Optional[str] = None,
) -> Optional[cues.Sighting]:
    """A fresh (<= 300 ms) overhead sighting, only while the D-257 flag is on (`force`: the SLAM fallback tie-break, 2026-11-18)."""
    if not (force or svc.overhead_cue) or svc._sightings is None:
        return None
    for row in svc._sightings.snapshot().get("sightings", ()):
        if row.get("robot_id") != rid:
            continue
        if expected_map_id is not None and row.get("map_id") != expected_map_id:
            continue
        try:
            age = svc._wall() - float(row["captured_at"])
            x, y, yaw = float(row["x"]), float(row["y"]), float(row["yaw"])
        except (KeyError, TypeError, ValueError):
            return None
        max_age = 1.0 if force else cues.OVERHEAD_FRESH_S
        if not 0.0 <= age <= max_age:
            return None
        return cues.Sighting(x, y, yaw, captured_at=now - age)
    return None


def sighting_in_robot_frame(svc, rid: str, state: Optional[Mapping], now: float) -> Optional[cues.Sighting]:
    """Compare the scene camera cue only in the robot map's coordinates."""
    if not svc.overhead_cue or state is None or map_frame(state) is None:
        return None
    site_map = svc._current_active_map_id()
    if site_map is None:
        return None
    sighting = fresh_overhead_sighting(svc, rid, now, expected_map_id=site_map)
    if sighting is None:
        return None
    if (fit := svc._binding_fit_for_state(rid, state, expected_site_map=site_map)) is not None:
        x, y = fit.inverse((sighting.x, sighting.y))
        return cues.Sighting(x, y, cues.wrap(sighting.yaw - fit.yaw), sighting.captured_at)
    return sighting if loaded_wall_proven(svc, state, site_map) else None


def loaded_wall_proven(svc, state, active_map) -> bool:
    prove = getattr(svc._wall_sync, "proves_loaded", None)
    return bool(active_map and callable(prove) and prove(state, active_map))


def forget_removed_robots(svc, current: set) -> None:
    for rid in svc._known - current:
        svc._monitor.forget(rid)
        svc._ladder.forget(rid)
        svc._last_good.pop(rid, None)
        svc._last_decision.pop(rid, None)
        svc._last_mission.pop(rid, None)
        svc._last_report.pop(rid, None)
        svc._search_window.forget(rid)
        svc._busy_rung.pop(rid, None)
        svc._unsupported.pop(rid, None)
        svc._report_seen.pop(rid, None)
        svc._objects_seen.pop(rid, None)
        svc._mission_running.discard(rid)
        svc._quiet_until.pop(rid, None)
        svc._anchors.discard(rid)
        svc._search_window.operator_anchors.pop(rid, None)
        svc._pending.pop(rid, None)
        svc._operator_pending.pop(rid, None)
        svc._unconfirmed.pop(rid, None)
        svc._localized_at.pop(rid, None)
        svc._pose_req.pop(rid, None)
        svc._pose_tries.pop(rid, None)
    svc._known = current
