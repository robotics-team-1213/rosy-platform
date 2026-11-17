"""D-546 pose-request handling and S1 anchor provenance helpers for LocalizationService."""

from __future__ import annotations

import logging
import math
from typing import Mapping, Optional

from core_common.protocol.localization import LocState
from fleet.localization import cues, pose_request, service_logic, trust
from fleet.swarm import transport

logger = logging.getLogger("fleet.localization")


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
                                 (decision.pose.x, decision.pose.y, decision.pose.yaw), now)
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
    for rid in states:
        pose = localized.get(rid)
        previous = svc._localized_at.get(rid)
        if pose is None:
            svc._anchors.discard(rid)
            svc._localized_at.pop(rid, None)
            continue
        svc._localized_at[rid] = (pose, now)
        if previous is None:
            decided = svc._pending.pop(rid, None)
            unconfirmed = svc._unconfirmed.pop(rid, None)
            if decided is not None and not service_logic.disagrees(decided, pose):
                svc._anchors.add(rid)
                logger.info("localization: %s LOCALIZED by a Fleet decision: anchor", rid)
            elif unconfirmed is not None and svc._reached(unconfirmed, pose, now):
                svc._anchors.add(rid)
                logger.info("localization: %s LOCALIZED at timed-out decision %s: confirmed, anchor",
                            rid, unconfirmed[0])
            else:
                logger.info("localization: %s LOCALIZED without a Fleet-known decision: "
                            "not an anchor, not a peer", rid)
        elif rid in svc._anchors and service_logic.jumped(previous[0], pose, now - previous[1]):
            svc._anchors.discard(rid)
            logger.warning("localization: %s pose jumped while LOCALIZED: no longer an anchor", rid)


def check_reached_unconfirmed(unconfirmed: tuple, pose: cues.Pose, now: float, *,
                              unconfirmed_s: float, unconfirmed_m: float, unconfirmed_yaw_rad: float) -> bool:
    """A timed-out decision is confirmed by the robot's first LOCALIZED pose (S1 run 3 T2)."""
    _, decided, anchoring, sent = unconfirmed
    return (now - sent <= unconfirmed_s
            and math.dist(decided[:2], pose[:2]) <= unconfirmed_m
            and abs(cues.wrap(pose[2] - decided[2])) <= unconfirmed_yaw_rad
            and anchoring)


def observe_pose_from_anchors(svc, states: Mapping[str, dict], localized: Mapping[str, cues.Pose],
                              anchors: Mapping[str, cues.Pose], observations: dict, now: float) -> None:
    """D-395 rev. 4 §5 follow-up (S1 R1): a LOCALIZED anchor's status carries what its lidar sees."""
    for rid, pose in anchors.items():
        status = trust.status_of(states.get(rid))
        if status is None or status.objects_stamp is None:
            svc._objects_seen.pop(rid, None)
            continue
        seen = svc._objects_seen.get(rid)
        if seen is None or seen[0] != status.objects_stamp:
            seen = svc._objects_seen[rid] = (status.objects_stamp, now)
        if now - seen[1] > service_logic.REPORT_FRESH_S:
            continue
        targets = {o: p for o, p in localized.items() if o != rid}
        for target, observed in service_logic.peer_observations(
                status.unmapped_objects, pose, targets).items():
            observations.setdefault(target, []).append((("objects", rid, status.objects_stamp), observed))


def fresh_overhead_sighting(svc, rid: str, now: float) -> Optional[cues.Sighting]:
    """A fresh (<= 300 ms) overhead sighting, only while the D-257 flag is on."""
    if not svc.overhead_cue or svc._sightings is None:
        return None
    for row in svc._sightings.snapshot().get("sightings", ()):
        if row.get("robot_id") != rid:
            continue
        try:
            age = svc._wall() - float(row["captured_at"])
            x, y, yaw = float(row["x"]), float(row["y"]), float(row["yaw"])
        except (KeyError, TypeError, ValueError):
            return None
        if not 0.0 <= age <= cues.OVERHEAD_FRESH_S:
            return None
        return cues.Sighting(x, y, yaw, captured_at=now - age)
    return None


def forget_removed_robots(svc, current: set) -> None:
    for rid in svc._known - current:
        svc._monitor.forget(rid)
        svc._ladder.forget(rid)
        svc._last_good.pop(rid, None)
        svc._last_decision.pop(rid, None)
        svc._last_mission.pop(rid, None)
        svc._last_report.pop(rid, None)
        svc._busy_rung.pop(rid, None)
        svc._unsupported.pop(rid, None)
        svc._report_seen.pop(rid, None)
        svc._objects_seen.pop(rid, None)
        svc._mission_running.discard(rid)
        svc._quiet_until.pop(rid, None)
        svc._anchors.discard(rid)
        svc._pending.pop(rid, None)
        svc._unconfirmed.pop(rid, None)
        svc._localized_at.pop(rid, None)
        svc._pose_req.pop(rid, None)
        svc._pose_tries.pop(rid, None)
    svc._known = current
