"""D-511 M0: lane-compliance monitor — observe and notify only, never a command to a robot.

Every tick (2 Hz, D-511 2) each roster robot is judged from `MapPoseService.arbitrated_pose`
against the active site graph. A robot whose odom moved within `max_odom_age_s` (beyond the `moving_min_m` / `moving_min_deg` jitter deadband) gets
`refresh(force_rest=True)` first, the shared REST read no older than 0.45 s (D-760 8); a still robot keeps its heartbeat odom.
The console raises WARN/ACT only for `moving` robots (D-511 2: the watch is on moving robots).
When the map pose is not LOCALIZED (a site without corner or robot markers) and an
`identity` service is wired, the robot's D-472 LED-confirmed track is judged instead (addendum 3:
lane compliance only; the track never reaches MapPoseService, trips, initialpose or commands). The
track counts only when CONFIRMED, its age within [-MAX_SIGHTING_FUTURE_S, `sighting_lease_s`] like a
map pose sighting, and on the active site map id. Its blob has no heading: while odom says moving
and the track moved more than `track_heading_min_m`, the direction of that move is the heading and
is kept while the track stays fresh (a skipped camera frame repeats the position); before the
first such heading the arc is chosen without the heading gate (`heading_source` `pose` |
`track_motion` | `none`, logged on every change). A change of `pose_source` restarts the
WARN/ACT counts. `pose_source` says
which input produced the sample (`map_pose` | `led_track`); `pose_state` stays the map pose state.
The latest result per robot is read by `GET /api/fleet/state` rows (`lane_compliance`) and
`GET /api/fleet/robots/{id}/lane-compliance`.

D-511 rev 1 (return loop, user 2026-10-10): the same input pose (LOCALIZED or DEGRADED) also feeds
a `ReturnTracker`; `return` is ON_LANE | ON_LINE | OFF_LANE | OFF_MAP | WRONG_WAY (debounced) with
the side and bearing back to the lane, the lane direction and a D-573 `crosswalk_ahead` hint. With
`return_cue` on, every tick a robot is not ON_LANE or has a crosswalk ahead (and once on the tick
it is back) Fleet sends it `POST /api/v1/line-follow/lane-cue` (`ttl_s` 1.0). The cue moves
nothing by itself: CORE reads it only while its own CAMERA_LINE keep drives, and its IR, body stop
and crosswalk gate still win. A CORE without the route answers 404 and is asked again after
`CUE_RETRY_S`.

D-1084 (amends D-511, user 2026-11-28): a still robot, and one on a parking or bay edge, in DOCKING or in a
parking handoff, is not judged: no WARN/ACT (its counts freeze), `exempt` says why, `return.state` is
PARKING there, and its cue only says ON_LANE (a docking verdict still goes) - unless the last cue sent was
not ON_LANE: then the tracked state goes on as before, so no CORE latch is released off the lane. A moving
robot is past the edge (ACT, OFF_LANE) only when the camera pose and its approved-binding SLAM pose both
are; a camera-only OFF_LANE is POSE_MISMATCH (no correction), any one-sided margin is `pose_mismatch`.
Side and direction use the SLAM yaw first.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict, replace
from typing import Callable, Iterable, Optional

from fastapi import HTTPException

from fleet.localization.lane_compliance import (OFF_LANE, OFF_MAP, ON_LANE, PARKING, POSE_MISMATCH, UNKNOWN, UNSEEN,
                                                LaneComplianceConfig, LaneComplianceTracker, ReturnTracker, classify,
                                                evaluate_bay_dock, map_bounds, parking_edge, sample)
from fleet.localization.lap_context import build_lap, context as lap_context
from fleet.localization.track_heading import TrackHeading
from rosy.world.state.projections.map_pose import DEGRADED, LOCALIZED, MAX_SIGHTING_FUTURE_S, MapPose

#: D-511 2: the monitor reads poses at 2 Hz or faster, like the trip loop (D-494 appendix).
PERIOD_S = 0.5
#: D-511 rev 1: a cue lives this long on CORE; the 2 Hz monitor renews it twice within.
CUE_TTL_S = 1.0
#: The near bar this close ahead of base_footprint counts as "at the crosswalk": body front
#: 0.06 m (URDF) + the IR row and the zone uncertainty, rounded up.
AT_CROSSWALK_M = 0.15
#: D-430 review 1: 404 (no route), 500 (route without wiring), 403 (not the site seat), 501: the
#: robot cannot take the cue; it is asked again after this long.
UNSUPPORTED = (400, 403, 404, 422, 500, 501)   # 400/422: an older strict lane-cue schema
#: A robot whose CORE cannot take the cue is asked again after this long.
CUE_RETRY_S = 60.0

logger = logging.getLogger("fleet.lane_compliance")


class LaneComplianceMonitor:
    def __init__(self, robot_ids: Callable[[], Iterable[str]], *, poses, site_maps,
                 config: LaneComplianceConfig = LaneComplianceConfig(), identity=None,
                 wall: Callable[[], float] = time.time, clients: Optional[Callable] = None,
                 stuck_open: Optional[Callable[[str], bool]] = None) -> None:
        self.config = config
        self._clients = clients          # () -> {robot_id: HttpRobotClient}; None = observe only
        #: robot -> an open CORE stuck (D-407): its answer owns the robot, the cue stands down.
        self._stuck_open = stuck_open or (lambda robot_id: False)
        self._returns: dict[str, ReturnTracker] = {}
        self._lap: tuple = (None, None)          # (map version, Lap) for the rev 6 context
        self._cue_seq = 0
        self._cue_sent: dict[str, str] = {}      # last state sent per robot
        self._cue_mute: dict[str, float] = {}    # robot -> wall time an unsupported CORE is asked again
        self._cue_refused: dict[str, Optional[str]] = {}   # robot -> last refusal reason (log once)
        self._last_stamp: dict[str, float] = {}  # robot -> last odom stamp sent (an OFF_MAP cue reuses it)
        self._epoch = f"{int(wall() * 1000):x}"
        self._robot_ids = robot_ids
        self._poses = poses              # MapPoseService: moved / refresh / arbitrated_pose
        self._site_maps = site_maps      # SiteMapStore: active() -> (version, map, graph, painted)
        self._identity = identity        # D-472 IdentityService: confirmed_track_pose only
        self._wall = wall
        self._track_heading: dict[str, TrackHeading] = {}        # motion heading of each robot's blob track
        self._input: dict[str, tuple[str, str]] = {}            # (pose_source, heading_source), for logs
        self._trackers: dict[str, LaneComplianceTracker] = {}
        self._latest: dict[str, dict] = {}
        self._heading_samples: dict[str, MapPose] = {}
        #: D-1084: robot -> an open trip in a parking handoff (role_builders wires the trip runner).
        self.parking_handoff: Callable[[str], bool] = lambda robot_id: False

    def knows(self, robot_id: str) -> bool:
        return robot_id in set(self._robot_ids())

    async def tick(self) -> None:
        roster = list(self._robot_ids())
        for gone in set(self._trackers) - set(roster):
            self._trackers.pop(gone, None)
            self._latest.pop(gone, None)
            self._heading_samples.pop(gone, None)
            self._track_heading.pop(gone, None)
            self._input.pop(gone, None)
            self._returns.pop(gone, None)
        cfg = self.config
        movers = [r for r in roster if self._poses.moved(r, cfg.moving_min_m, cfg.moving_min_deg)]
        # A failed or slow read (cut at one period) leaves the last odom, which goes UNKNOWN
        # after max_odom_age_s; one slow robot never holds up the others' judgement.
        await asyncio.gather(*(asyncio.wait_for(self._poses.refresh(r, force_rest=True), PERIOD_S)
                               for r in movers), return_exceptions=True)
        active = self._site_maps.active()
        graph = active[2] if active is not None else None
        crosswalks = ([(c.id, [tuple(p) for p in c.polygon]) for c in getattr(active[1], "crosswalks", ())]
                      if active is not None else [])
        bounds = map_bounds(graph, cfg.off_map_pad_m)
        version = active[0] if active is not None else None
        if cfg.guide_context and self._lap[0] != version:
            self._lap = (version, build_lap(graph, cfg.lap_arcs, crosswalks, cfg.turn_spots))
        now = self._wall()
        cues = []
        for robot_id in roster:
            arbitrated = self._poses.arbitrated_pose(robot_id)
            pose, source, heading = self._input_pose(robot_id, arbitrated, robot_id in movers)
            previous = self._input.get(robot_id)
            if previous is None or previous[0] != source:   # another input: counts start over
                self._trackers[robot_id] = LaneComplianceTracker(self.config)
            tracker = self._trackers[robot_id]
            if previous != (source, heading):
                self._input[robot_id] = (source, heading)
                logger.info("lane compliance %s: judged from %s, heading %s%s", robot_id, source, heading,
                            " (LED track without a motion heading yet: nearest arc, no heading gate)"
                            if heading == "none" else "")
            state = self._cached_state(robot_id)
            try:
                body, body_reason = (self._body_pose(robot_id, state, active) if robot_id in movers
                                     else (None, "not_moving"))
            except Exception:  # noqa: BLE001 - an odd binding record never stops the watch: camera alone
                logger.debug("lane compliance %s: SLAM pose not read", robot_id, exc_info=True)
                body, body_reason = None, "error"
            # D-1084: side and direction from the robot's own yaw; the ceiling yaw is off +4-8 deg in the north bays.
            judged = pose if body is None or getattr(pose, "x", None) is None else replace(pose, yaw=body.yaw)
            back = self._return(robot_id, judged, robot_id in movers, graph, crosswalks, bounds, now)
            result, judgement = self._judge(robot_id, tracker, judged, body, back, state, robot_id in movers,
                                            graph, crosswalks, bounds, camera=pose)
            if back is not None:
                cues.append((robot_id, back))
            pose_state = (getattr(pose, "state", UNKNOWN) if getattr(pose, "source", None) == "approved_slam"
                          else getattr(arbitrated, "state", UNKNOWN))
            self._latest[robot_id] = {**asdict(result), "pose_state": pose_state,
                                      "return": back,
                                      "pose_source": source, "heading_source": heading,
                                      "moving": robot_id in movers,
                                      "map_version": active[0] if active is not None else None,
                                      "at": self._wall()}
            self._latest[robot_id].update(judgement, body_pose_reason=body_reason,
                                          yaw_source="body" if judged is not pose else "camera")
            self._heading_samples[robot_id] = pose

        if cues and self.config.return_cue and self._clients is not None:
            await asyncio.gather(*(self._send_cue(robot_id, back, now) for robot_id, back in cues),
                                 return_exceptions=True)

    def _judge(self, robot_id: str, tracker, judged, body, back, state, moving: bool, graph, crosswalks, bounds,
               camera=None):
        """D-1084: (level result, extra view fields). A still robot, or one on a parking or bay edge, in
        DOCKING or a parking handoff, is not judged (counts frozen). A moving one is past the edge (ACT,
        OFF_LANE) only when the camera pose and the bound SLAM pose both are; one alone is POSE_MISMATCH.
        Without a SLAM pose the camera alone judges, as before. ``back`` is settled in place."""
        cfg = self.config
        lane = sample(judged, graph, tracker.body_half_width_m, cfg)
        exempt = ("parking" if (parking_edge(graph, lane.edge_id) or parking_edge(graph, (back or {}).get("edge_id"))
                                or (state or {}).get("mode") == "DOCKING" or self.parking_handoff(robot_id))
                  else None if moving else "still")
        mismatch = gap = None
        if body is not None and getattr(judged, "x", None) is not None:
            gap = round(math.hypot(judged.x - body.x, judged.y - body.y), 3)
        if exempt is None and gap is not None:
            mine = sample(body, graph, tracker.body_half_width_m, cfg)
            if lane.margin_m is not None and mine.margin_m is not None:
                if (lane.margin_m < 0) != (mine.margin_m < 0):
                    mismatch = {"gap_m": gap, "camera_margin_m": round(lane.margin_m, 4),
                                "body_margin_m": round(mine.margin_m, 4)}
                lane = replace(lane, margin_m=max(lane.margin_m, mine.margin_m))   # both past the edge to count
        result = tracker.hold(lane) if exempt else tracker.update(lane)
        if back is not None:
            if judged is not camera and back.get("docking") is not None:   # the bay verdict keeps its own input
                back["docking"] = evaluate_bay_dock(camera.x, camera.y, camera.yaw, self._returns[robot_id].travel, graph)
            back["exempt"] = exempt
            if exempt == "parking" and back["state"] != OFF_MAP:
                back["state"] = PARKING
            elif exempt is None and gap is not None and back["state"] == OFF_LANE:
                # Only the camera's departure is doubted; a camera ON_LINE keeps its correction as before.
                if classify(body.x, body.y, body.yaw, None, graph, crosswalks, cfg,
                            tracker.body_half_width_m, bounds).state != OFF_LANE:
                    back["state"], back["pose_gap_m"] = POSE_MISMATCH, gap
        return result, {"exempt": exempt, "pose_mismatch": mismatch, "pose_gap_m": gap,
                        "body_pose": None if body is None else {
                            "x": round(body.x, 4), "y": round(body.y, 4), "yaw": round(body.yaw, 4),
                            "source": body.source}}

    def _cached_state(self, robot_id: str):
        """The robot's last REST state (this tick's for a mover), never a new read; None when unread."""
        cached = getattr(self._poses, "cached_motion_sample", None)
        got = cached(robot_id) if callable(cached) else None
        return got[0] if got is not None else None

    def _body_pose(self, robot_id: str, state, active) -> tuple:
        """D-1084: (fresh native SLAM through the robot's approved map binding as a site-frame MapPose, None)
        or (None, why not); the same reading as the bound Nav2 trip (``read_precision_pose_status``)."""
        from fleet.localization.map_binding import bound_pose
        from fleet.server.trips.named_stop_map_pose import fresh_native_slam

        bindings = getattr(self._site_maps, "map_bindings", None)
        if active is None or bindings is None or bindings.active(robot_id) is None:
            return None, "no_binding"
        if not isinstance(state, dict):
            return None, "state_unread"
        native = fresh_native_slam(state, self._wall())
        if native is None:
            return None, "slam_stale"
        fit, reason = bindings.matching_fit(robot_id, state, (active[1].map_id, active[0]))
        if fit is None:
            return None, reason or "binding_mismatch"
        x, y, yaw = bound_pose(fit, native[0])
        return MapPose(x, y, yaw, LOCALIZED, "approved_slam", 0.0, native[1], anchor_age_s=native[1],
                       map_id=active[1].map_id, odom_stamp=native[2]), None

    def _return(self, robot_id: str, pose, moving: bool, graph, crosswalks, bounds, now: float):
        """D-511 rev 1: the robot's debounced return state, or None before the first judgement."""
        tracker = self._returns.setdefault(robot_id, ReturnTracker(self.config))
        state = getattr(pose, "state", None)
        anchor = getattr(pose, "anchor_age_s", None)
        # D-511 rev 2: guide only from a fresh LOCALIZED pose (an LED track has no anchor age). A
        # DEGRADED or stale pose is "not judged now", never OFF_MAP; only no pose at all is unseen.
        placed = (state == LOCALIZED and pose.x is not None and pose.y is not None and graph is not None
                  and (anchor is None or anchor <= self.config.guide_anchor_max_s))
        raw = tracker.update(now, pose.x if placed else None, pose.y if placed else None,
                             pose.yaw if placed else None, graph, crosswalks, moving, bounds,
                             unseen_counts=state not in (LOCALIZED, DEGRADED))
        if tracker.state == UNSEEN:
            return None
        current = tracker.state == raw.state   # detail fields belong to the reported state only
        detail = ("edge_id", "offset_m", "side", "bearing_deg", "lane_heading_deg", "turn_deg")
        return {"state": tracker.state, "since": tracker.since, "raw": raw.state, "moving": moving,
                "pose_stamp": getattr(pose, "odom_stamp", None) if placed else None,
                "guide": raw.guide if current else None,
                "turn_spot": raw.turn_spot if current else False,
                "context": (lap_context(self._lap[1], raw.arc_id, raw.s_m, raw.offset_m,
                                        getattr(pose, "age_s", None), getattr(pose, "anchor_age_s", None))
                            if current and self.config.guide_context else None),
                "docking": raw.docking if current else None,
                **{k: getattr(raw, k) if current else None for k in detail},
                "entry": list(raw.entry) if current and raw.entry else None,
                "crosswalk": raw.crosswalk,
                # D-491/D-573: the zone's odom anchor is the robot pose this old (CORE back-dates it)
                "crosswalk_ahead": None if raw.crosswalk_ahead is None else {
                    **raw.crosswalk_ahead, "pose_age_s": round(max(0.0, getattr(pose, "age_s", 0.0) or 0.0), 3)}}

    def at_crosswalk(self, robot_id: str) -> bool:
        """D-573 개정: the robot's body is on a mapped crosswalk or its front at the near bar."""
        back = (self._latest.get(robot_id) or {}).get("return") or {}
        ahead = back.get("crosswalk_ahead") or {}
        return back.get("crosswalk") is not None or (
            ahead.get("near_m") is not None and ahead["near_m"] <= AT_CROSSWALK_M)

    async def _send_cue(self, robot_id: str, back: dict, now: float) -> None:
        if back["state"] in (PARKING, POSE_MISMATCH) or (back.get("exempt") and back["state"] != OFF_MAP):
            if self._cue_sent.get(robot_id, ON_LANE) != ON_LANE:
                # D-430 review: an ON_LANE would release a CORE latch (fleet_wrong_way, a turn) on a robot that
                # stopped off the lane, so after a non-normal cue the tracked state goes as before until it is back.
                back = {**back, "state": self._returns[robot_id].state}
            else:
                # D-1084: not a departure, so no correction; the docking verdict still goes.
                back = {**back, "state": ON_LANE, "side": None, "bearing_deg": None, "turn_deg": None,
                        "offset_m": None, "turn_spot": False}
        state = back["state"]
        if back["raw"] == UNSEEN and state != OFF_MAP:
            return                     # not judged now: CORE's cue expires, the robot drives as today
        if back["pose_stamp"] is None and state != OFF_MAP:
            return                     # D-430 review 7: CORE measures a turn from the odom at pose_stamp
        if (state == ON_LANE and not back["moving"] and back.get("docking") is None
                and self._cue_sent.get(robot_id, ON_LANE) == ON_LANE):
            return                     # still on the lane: nothing to guide, nothing to clear
        if self._cue_mute.get(robot_id, 0.0) > now:
            return
        if state != OFF_MAP and self._stuck_open(robot_id):
            return                     # D-577 REALIGN / a human answers the stuck; one channel at a time
        send = getattr((self._clients() or {}).get(robot_id), "line_follow_lane_cue", None)
        if send is None:
            return
        self._cue_seq += 1
        body = {"cue_id": f"{robot_id}-{self._epoch}-{self._cue_seq}", "fleet_epoch": self._epoch,
                "seq": self._cue_seq, "ttl_s": CUE_TTL_S,
                # OFF_MAP: CORE holds without odom alignment (re-review 1), any positive stamp will do.
                "pose_stamp": back["pose_stamp"] or self._last_stamp.get(robot_id) or now,
                **{k: back[k] for k in ("state", "side", "bearing_deg", "turn_deg", "lane_heading_deg",
                                        "offset_m", "edge_id", "guide")},
                # rev 4: only when true, so a CORE without the field (strict schema) never sees it.
                **({"turn_spot": True} if back["turn_spot"] else {}),
                # rev 6: only with guide_context on, so a CORE without the field never sees it.
                **({"context": back["context"]} if back["context"] is not None else {}),
                **({"docking": back["docking"]} if back.get("docking") is not None else {})}
        # Crosswalk zones never go from Fleet: CORE's own camera finds them (D-491/D-573, no crosswalks[]).
        try:
            reply = await asyncio.wait_for(send(body), PERIOD_S)
        except Exception as exc:  # noqa: BLE001 - one robot's failure never stops the watch
            status = getattr(exc, "status", None)
            if status in UNSUPPORTED:
                self._cue_mute[robot_id] = now + CUE_RETRY_S
                logger.info("lane cue %s: CORE answered %s (no lane cue, wiring or seat); again in %.0f s",
                            robot_id, status, CUE_RETRY_S)
            else:
                logger.debug("lane cue %s failed: %s", robot_id, exc)
            return
        if isinstance(reply, dict) and reply.get("accepted") is False:
            # D-430 re-review 1: a refused cue did not take effect; say why and try again next tick
            # ("disabled": that robot's CORE does not read cues, asked again after CUE_RETRY_S).
            reason = reply.get("reason")
            if reason == "disabled":
                self._cue_mute[robot_id] = now + CUE_RETRY_S
            if self._cue_refused.get(robot_id) != reason:
                logger.warning("lane cue %s: %s refused (%s)", robot_id, state, reason)
            self._cue_refused[robot_id] = reason
            return
        self._cue_refused.pop(robot_id, None)
        if back["pose_stamp"] is not None:
            self._last_stamp[robot_id] = back["pose_stamp"]
        if self._cue_sent.get(robot_id) != state:
            logger.info("lane cue %s: %s side=%s turn=%s", robot_id, state, back["side"], back["turn_deg"])
        self._cue_sent[robot_id] = state

    def _input_pose(self, robot_id: str, arbitrated, moving: bool) -> tuple:
        """(pose to judge, pose_source, heading_source): approved SLAM, else camera map pose, else LED track."""
        latest_fn = getattr(self._poses, "latest_state", None)
        if callable(latest_fn):
            from fleet.server.named_stop_map_pose import approved_slam_site_pose
            bound = approved_slam_site_pose(self._site_maps, robot_id, latest_fn(robot_id), self._wall())
            if bound is not None:
                self._track_heading.pop(robot_id, None)
                return bound[0], "map_pose", "pose"
        track = None
        if self._identity is not None and getattr(arbitrated, "state", None) != LOCALIZED:
            track = self._identity.confirmed_track_pose(robot_id)
        age = None if track is None else track.get("age_s")
        if (track is None or track.get("state") != "CONFIRMED" or age is None
                or not -MAX_SIGHTING_FUTURE_S <= age <= self._poses.config.sighting_lease_s
                or self._poses.active_map_id() not in (None, track.get("map_id"))):
            self._track_heading.pop(robot_id, None)
            return arbitrated, "map_pose", "pose"
        x, y, yaw, heading = track["x"], track["y"], track.get("yaw"), "pose"
        if yaw is None:
            # The blob tracker has no heading. Odom says moving and the blob moved beyond the
            # camera-noise deadband: that direction is the heading, kept while the track is fresh
            # (a skipped frame repeats the position). Before the first one: no heading gate.
            yaw = self._track_heading.setdefault(robot_id, TrackHeading(self.config.track_heading_min_m)).update(x, y, moving)
            heading = "none" if yaw is None else "track_motion"
        return (MapPose(x, y, yaw, LOCALIZED, "led_track", 0.0, track["age_s"], map_id=track.get("map_id")),
                "led_track", heading)

    def view(self, robot_id: str) -> Optional[dict]:
        return self._latest.get(robot_id)

    def realign_evidence(self, robot_id: str) -> dict:
        """D-622 coherent map evidence; default-off selector still proves the full map sweep."""
        review = self.stuck_heading(robot_id)
        if review["status"] != "heading_compared":
            return review
        pose = self._heading_samples[robot_id]
        back = (self.view(robot_id) or {}).get("return") or {}
        travel = getattr(pose, "dead_reckon_m", None)
        if (not isinstance(travel, (int, float)) or isinstance(travel, bool)
                or not math.isfinite(travel) or travel < 0):
            return {"status":"pose_untrusted"}
        return {**review, "map_id":pose.map_id, "x":pose.x, "y":pose.y, "yaw":pose.yaw,
                "pose_age_s":pose.age_s, "offset_m":back.get("offset_m"),
                "u_m":.018+.05*travel}

    def stuck_heading(self, robot_id: str) -> dict:
        """D-607: reassess direction from coherent map evidence without issuing a manoeuvre."""
        from fleet.localization.stuck_heading import reassess

        active = self._site_maps.active()
        pose = self._poses.arbitrated_pose(robot_id)
        review = reassess(pose, self.view(robot_id), now=self._wall(),
                          map_id=active[1].map_id if active is not None else None,
                          map_version=active[0] if active is not None else None)
        sample = self._heading_samples.get(robot_id)
        # A camera anchor or operator pin can change the map pose without a new odom stamp.
        if review["status"] == "heading_compared" and (sample is None or any(
                getattr(sample, key) != getattr(pose, key) for key in ("x", "y", "yaw", "map_id", "odom_stamp"))):
            return {"status": "lane_sample_untrusted"}
        return review


def install_lane_compliance_routes(app, *, monitor: LaneComplianceMonitor, read_guard) -> None:
    @app.get("/api/fleet/robots/{robot_id}/lane-compliance", dependencies=read_guard, tags=["fleet"])
    async def robot_lane_compliance(robot_id: str) -> dict:
        if not monitor.knows(robot_id):
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_ROBOT",
                                                         "message": "robot is not on the roster"})
        latest = monitor.view(robot_id)
        if latest is None:          # before the first tick
            latest = {"level": UNKNOWN, "pose_state": None, "at": None}
        return {"robot_id": robot_id, **latest}
