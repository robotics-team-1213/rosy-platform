"""D-511 M0: lane-compliance monitor — observe and notify only, never a command to a robot.

Every tick (2 Hz, D-511 2) each roster robot is judged from `MapPoseService.arbitrated_pose`
against the active site graph. A robot whose odom moved within `max_odom_age_s` (beyond the `moving_min_m` / `moving_min_deg` jitter deadband) gets
`refresh(force_rest=True)` first, the trip loop's read; a still robot keeps its heartbeat odom.
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
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict
from typing import Callable, Iterable, Optional

from fastapi import HTTPException

from fleet.localization.lane_compliance import (OFF_MAP, ON_LANE, UNKNOWN, UNSEEN, LaneComplianceConfig,
                                                LaneComplianceTracker, ReturnTracker, map_bounds)
from fleet.localization.map_pose import DEGRADED, LOCALIZED, MAX_SIGHTING_FUTURE_S, MapPose

#: D-511 2: the monitor reads poses at 2 Hz or faster, like the trip loop (D-494 appendix).
PERIOD_S = 0.5
#: D-511 rev 1: a cue lives this long on CORE; the 2 Hz monitor renews it twice within.
CUE_TTL_S = 1.0
#: The near bar this close ahead of base_footprint counts as "at the crosswalk": body front
#: 0.06 m (URDF) + the IR row and the zone uncertainty, rounded up.
AT_CROSSWALK_M = 0.15
#: D-430 review 1: 404 (no route), 500 (route without wiring), 403 (not the site seat), 501: the
#: robot cannot take the cue; it is asked again after this long.
UNSUPPORTED = (403, 404, 500, 501)
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
        self._track_from: dict[str, tuple[float, float]] = {}   # last track point beyond the deadband
        self._track_yaw: dict[str, float] = {}                   # last motion heading of the track
        self._input: dict[str, tuple[str, str]] = {}            # (pose_source, heading_source), for logs
        self._trackers: dict[str, LaneComplianceTracker] = {}
        self._latest: dict[str, dict] = {}

    def knows(self, robot_id: str) -> bool:
        return robot_id in set(self._robot_ids())

    async def tick(self) -> None:
        roster = list(self._robot_ids())
        for gone in set(self._trackers) - set(roster):
            self._trackers.pop(gone, None)
            self._latest.pop(gone, None)
            self._track_from.pop(gone, None)
            self._track_yaw.pop(gone, None)
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
            result = tracker.judge(pose, graph)
            back = self._return(robot_id, pose, robot_id in movers, graph, crosswalks, bounds, now)
            if back is not None:
                cues.append((robot_id, back))
            self._latest[robot_id] = {**asdict(result), "pose_state": getattr(arbitrated, "state", UNKNOWN),
                                      "return": back,
                                      "pose_source": source, "heading_source": heading,
                                      "moving": robot_id in movers,
                                      "map_version": active[0] if active is not None else None,
                                      "at": self._wall()}

        if cues and self.config.return_cue and self._clients is not None:
            await asyncio.gather(*(self._send_cue(robot_id, back, now) for robot_id, back in cues),
                                 return_exceptions=True)

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
        state = back["state"]
        if back["raw"] == UNSEEN and state != OFF_MAP:
            return                     # not judged now: CORE's cue expires, the robot drives as today
        if back["pose_stamp"] is None and state != OFF_MAP:
            return                     # D-430 review 7: CORE measures a turn from the odom at pose_stamp
        if (state == ON_LANE and not back["moving"]
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
                                        "offset_m", "edge_id", "guide")}}
        # Crosswalk zones reach CORE only as the D-517 authority crosswalks[] (D-573), not here.
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
        """(pose to judge, pose_source, heading_source): the map pose, else a fresh LED track."""
        track = None
        if self._identity is not None and getattr(arbitrated, "state", None) != LOCALIZED:
            track = self._identity.confirmed_track_pose(robot_id)
        age = None if track is None else track.get("age_s")
        if (track is None or track.get("state") != "CONFIRMED" or age is None
                or not -MAX_SIGHTING_FUTURE_S <= age <= self._poses.config.sighting_lease_s
                or self._poses.active_map_id() not in (None, track.get("map_id"))):
            self._track_from.pop(robot_id, None)
            self._track_yaw.pop(robot_id, None)
            return arbitrated, "map_pose", "pose"
        x, y, yaw, heading = track["x"], track["y"], track.get("yaw"), "pose"
        if yaw is None:
            # The blob tracker has no heading. Odom says moving and the blob moved beyond the
            # camera-noise deadband: that direction is the heading, kept while the track is fresh
            # (a skipped frame repeats the position). Before the first one: no heading gate.
            last = self._track_from.get(robot_id)
            if last is None or math.hypot(x - last[0], y - last[1]) > self.config.track_heading_min_m:
                self._track_from[robot_id] = (x, y)
                if last is not None and moving:
                    self._track_yaw[robot_id] = math.atan2(y - last[1], x - last[0])
            yaw = self._track_yaw.get(robot_id)
            heading = "none" if yaw is None else "track_motion"
        return (MapPose(x, y, yaw, LOCALIZED, "led_track", 0.0, track["age_s"], map_id=track.get("map_id")),
                "led_track", heading)

    def view(self, robot_id: str) -> Optional[dict]:
        return self._latest.get(robot_id)


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
