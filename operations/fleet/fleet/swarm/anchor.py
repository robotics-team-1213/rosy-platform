"""fleet.swarm.anchor — D-581 ceiling-camera anchored trail reference.

On the motor-mode site no robot has a map pose: the leader's /ws/swarm/pose sample is its odom
pose (`frame: odom`) and a D-559 trail follower would hold. Fleet knows where both robots are
on the site map (D-494 3 map pose: Rosy Cam sightings paired with odom at capture time), so for
a TRAIL formation it re-expresses every leader sample in each follower's own odom frame:

    leader in follower odom = T_f^-1 * T_L * leader odom,   T_r = map <- odom of robot r

and sends it with `anchor: fleet`, `for_robot_id`. The follower then replays the trail in its own
odom. The leader's stream (>= 10 Hz) is the clock; between sightings each T is constant and odom
bridges. A leader frame that says "map" (or nothing) is relayed byte for byte (D-31).

T must not jump under the trail. Each robot keeps a smoothed T that moves toward the tracker's
by a first-order filter, capped per second, measured at the robot (a 1 deg yaw correction turned
about an odom origin 5 m away would move the robot 9 cm). A disagreement beyond JUMP_M /
JUMP_DEG is a relocalisation, not drift: that robot's samples stop (the follower holds on its
stream timeout) until the relay resumes after a reform.

While an anchor is missing the follower gets an explicit hold sample (`anchor_hold: <reason>`)
on every leader frame instead of silence, so a withheld anchor is not read as a dead leader.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Optional

from fleet.localization.map_pose import LOCALIZED, UNKNOWN, Pose, compose, relative
from fleet.swarm.relay import Relay

log = logging.getLogger(__name__)


def formation_relay_kwargs(relay_factory, poses, enabled: Callable[[], bool]) -> dict:
    """FormationSession kwargs: a given (test) factory wins; else the anchored relay when there is
    a map pose service; else the session default."""
    if relay_factory is not None:
        return {"relay_factory": relay_factory}
    return {} if poses is None else {"relay_factory": anchored_relay_factory(poses, enabled)}


def anchor_status(relay) -> Optional[dict]:
    """Formation status `anchor` block: None when the relay does not anchor."""
    anchor = getattr(relay, "anchor", None)
    return None if anchor is None else anchor.status()


def anchored_relay_factory(poses, enabled: Callable[[], bool]):
    """FormationSession `relay_factory`: a Relay with a TrailAnchor over `poses` (MapPoseService),
    refreshing both robots' odom from REST while it anchors."""
    def build(leader, followers):
        anchor = TrailAnchor(poses, leader.robot_id, [f.robot_id for f in followers], enabled=enabled,
                             refresh=lambda rid: poses.refresh(rid, force_rest=True))
        return Relay(leader, followers, anchor=anchor)
    return build

#: A camera anchor older than this stops the samples. At 0.15 m/s that is 0.75 m on odom alone,
#: about 1-2 cm of wheel-odom drift; a missing marker (9dfk's small sticker) shows up here.
ANCHOR_MAX_AGE_S = 5.0
#: DEGRADED (a sighting disagreed, or a first anchor not yet confirmed) freezes the smoothed T
#: for at most this long since its last LOCALIZED update: two consistent 5 Hz sightings recover in
#: 0.4 s, and 2 s of odom bridging adds well under 1 cm. Longer, or DEGRADED from the start, stops.
DEGRADED_HOLD_S = 2.0
#: Smoothing time constant of T toward the tracker's newest anchor (s). Sighting noise is
#: ~1-2 cm / 1-2 deg per fix; odom drift is millimetres per second.
FILTER_TAU_S = 1.0
#: Correction caps, at the robot. Odom drift needs far less (~3 mm/s, ~1 deg/s while turning).
MAX_CORRECTION_MPS = 0.05
MAX_CORRECTION_DPS = 5.0
#: A smoothed-vs-anchored disagreement beyond this is a relocalisation: stop, never teleport.
#: Below D-559's 0.30 m trail_lost bound, above sighting noise plus a few seconds of drift.
JUMP_M = 0.20
JUMP_DEG = 15.0
#: Odom refresh per robot while anchoring (the trip loop's 2 Hz, D-494 appendix).
REFRESH_S = 0.5
#: One correction step covers at most this much time (a long gap is not a licence to snap).
MAX_STEP_S = 0.2
#: The leader's streamed odom must sit within this speed x (age of the tracker's newest odom) +
#: margin of that odom: farther, the stream and the tracker are not in one odom frame (a CORE or
#: driver restart the 2 Hz tracker has not seen yet). Above any 차체 최고 속도.
LEADER_ODOM_MPS = 0.5
LEADER_ODOM_MARGIN_M = 0.10
#: An odom refresh (robot REST read) gives up after this (s).
REFRESH_TIMEOUT_S = 2.0


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


@dataclass
class _Held:
    """One robot's smoothed map <- odom."""
    T: Pose
    at: float
    anchor_age_s: Optional[float]
    map_id: Optional[str]
    anchor_at: float          # the tracker anchor (captured_at) T last came from
    epoch: int                # the tracker's odom epoch T belongs to
    residual_m: float = 0.0
    residual_deg: float = 0.0


class TrailAnchor:
    """`route(frame)` per leader frame. `poses` is the D-494 3 MapPoseService (or a fake)."""

    def __init__(self, poses, leader_id: str, follower_ids: Iterable[str], *,
                 enabled: Callable[[], bool] = lambda: True,
                 refresh: Optional[Callable[[str], Awaitable[None]]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self._poses = poses
        self._leader = leader_id
        self._followers = list(follower_ids)
        self._enabled = enabled
        self._refresh = refresh
        self._clock = clock
        self._wall = wall           # odom stamps are UTC epoch seconds
        self._refreshed: dict[str, float] = {}
        self._tasks: set[asyncio.Future] = set()
        self._frames: dict[str, _Held] = {}
        self._jumped: set[str] = set()
        #: follower -> why its samples stop ("<robot>:<reason>"), None while sending.
        self._reasons: dict[str, Optional[str]] = {}
        self.jumps = 0

    def reset(self) -> None:
        """Relay resume (after a reform): every robot starts over from its tracker anchor."""
        self._frames.clear()
        self._jumped.clear()
        self._reasons.clear()

    def route(self, frame: str) -> Optional[dict[str, Optional[str]]]:
        """None: relay `frame` unchanged. Else follower -> its own frame text, None = withhold."""
        if not self._enabled():
            return None
        try:
            envelope = json.loads(frame)
            payload = envelope["payload"]
            if payload.get("frame") != "odom":
                return None                     # the leader's own map pose (or none): D-31
            odom = (float(payload["pose"]["x"]), float(payload["pose"]["y"]),
                    float(payload["pose"]["yaw"]))
        except (TypeError, ValueError, KeyError, AttributeError):
            return None                         # not ours to judge; CORE drops malformed frames
        if not all(math.isfinite(v) for v in odom):
            return {robot_id: None for robot_id in self._followers}
        self._schedule_refresh()
        now = self._clock()
        leader, why = self._frame(self._leader, now, streamed=odom)
        routed: dict[str, Optional[str]] = {}
        for robot_id in self._followers:
            follower, why_f = self._frame(robot_id, now) if leader is not None else (None, None)
            reason = (f"{self._leader}:{why}" if leader is None
                      else f"{robot_id}:{why_f}" if follower is None
                      else f"{robot_id}:map_id_differs" if follower.map_id != leader.map_id
                      else None)
            if reason != self._reasons.get(robot_id, "") and reason is not None:
                log.warning("trail anchor: samples to %s stop: %s", robot_id, reason)
            self._reasons[robot_id] = reason
            if reason is not None:
                # An explicit hold, not silence: silence past stream_timeout_ms reads as a dead
                # leader on the robot (D-20 succession). The pose is the leader's own odom and
                # the follower never puts it in the trail; a dead leader still goes silent.
                routed[robot_id] = json.dumps({**envelope, "payload": {
                    **payload, "frame": "odom", "anchor": "fleet", "for_robot_id": robot_id,
                    "anchor_hold": reason}})
                continue
            x, y, yaw = relative(follower.T, compose(leader.T, odom))
            ages = [a for a in (leader.anchor_age_s, follower.anchor_age_s) if a is not None]
            routed[robot_id] = json.dumps({**envelope, "payload": {
                **payload, "pose": {"x": x, "y": y, "yaw": yaw}, "frame": "odom",
                "anchor": "fleet", "for_robot_id": robot_id, "map_id": leader.map_id,
                "anchor_age_s": round(max(ages), 3) if ages else None}})
        return routed

    def status(self) -> dict:
        """Formation status `anchor` block: why each follower is not sent, and each frame."""
        return {
            "followers": dict(self._reasons),
            "robots": {robot_id: {"anchor_age_s": held.anchor_age_s,
                                  "residual_m": round(held.residual_m, 3),
                                  "residual_deg": round(held.residual_deg, 2),
                                  "jumped": robot_id in self._jumped}
                       for robot_id, held in self._frames.items()},
            "jumps": self.jumps,
        }

    def _frame(self, robot_id: str, now: float,
               streamed: Optional[Pose] = None) -> tuple[Optional[_Held], Optional[str]]:
        if robot_id in self._jumped:
            return None, "anchor_jump"
        pose = self._poses.arbitrated_pose(robot_id)
        raw = self._poses.odom_to_map(robot_id)
        if pose is None or raw is None or pose.state == UNKNOWN:
            self._frames.pop(robot_id, None)    # the tracker reset: its odom frame is gone
            return None, "no_map_pose"
        target, odom, anchor_at, epoch = raw
        held = self._frames.get(robot_id)
        if held is not None and held.epoch != epoch:
            del self._frames[robot_id]          # odom reset since: never reuse T on new odom
            held = None
        if streamed is not None and pose.odom_stamp is not None:
            # The stream's odom and the tracker's newest odom must be one odom frame.
            slack = LEADER_ODOM_MPS * max(0.0, self._wall() - pose.odom_stamp) + LEADER_ODOM_MARGIN_M
            if math.dist(streamed[:2], odom[:2]) > slack:
                self._frames.pop(robot_id, None)
                return None, "leader_odom_mismatch"
        if pose.anchor_age_s is None or pose.anchor_age_s > ANCHOR_MAX_AGE_S:
            return None, "anchor_stale"
        if pose.state != LOCALIZED:
            # Frozen: odom bridges a short DEGRADED, but only on the anchor T came from.
            if held is None or now - held.at > DEGRADED_HOLD_S or held.anchor_at != anchor_at:
                return None, "map_pose_degraded"
            return held, None
        if held is None:
            held = self._frames[robot_id] = _Held(target, now, pose.anchor_age_s, pose.map_id,
                                                  anchor_at, epoch)
            return held, None
        here, there = compose(held.T, odom), compose(target, odom)
        ex, ey, eyaw = there[0] - here[0], there[1] - here[1], _wrap(there[2] - here[2])
        error = math.hypot(ex, ey)
        held.residual_m, held.residual_deg = error, math.degrees(eyaw)
        if error > JUMP_M or abs(eyaw) > math.radians(JUMP_DEG):
            self._jumped.add(robot_id)
            self.jumps += 1
            log.warning("trail anchor: %s anchor moved %.3f m / %.1f deg at the robot; stopping "
                        "its samples (no teleported trail)", robot_id, error, math.degrees(eyaw))
            return None, "anchor_jump"
        dt = min(max(now - held.at, 0.0), MAX_STEP_S)
        k = 1.0 - math.exp(-dt / FILTER_TAU_S)
        step = min(k * error, MAX_CORRECTION_MPS * dt)
        cap = math.radians(MAX_CORRECTION_DPS) * dt
        turn = min(max(k * eyaw, -cap), cap)
        scale = step / error if error > 0.0 else 0.0
        moved = (here[0] + ex * scale, here[1] + ey * scale, _wrap(here[2] + turn))
        held.T = compose(moved, relative(odom, (0.0, 0.0, 0.0)))
        held.at, held.anchor_age_s, held.map_id, held.anchor_at = now, pose.anchor_age_s, pose.map_id, anchor_at
        if step > 0.002 or abs(turn) > math.radians(0.2):
            log.debug("trail anchor: %s corrected %.4f m %.3f deg (residual %.3f m %.2f deg)",
                      robot_id, step, math.degrees(turn), error, math.degrees(eyaw))
        return held, None

    def _schedule_refresh(self) -> None:
        """Keep both robots' odom >= 2 Hz in the trackers (the hub heartbeat alone is 1 Hz)."""
        if self._refresh is None:
            return
        now = self._clock()
        for robot_id in (self._leader, *self._followers):
            if now - self._refreshed.get(robot_id, -math.inf) < REFRESH_S:
                continue
            self._refreshed[robot_id] = now
            task = asyncio.ensure_future(self._refresh_one(robot_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _refresh_one(self, robot_id: str) -> None:
        try:
            await asyncio.wait_for(self._refresh(robot_id), REFRESH_TIMEOUT_S)
        except Exception as exc:                # an unreachable robot goes stale, then stops
            log.debug("trail anchor: odom refresh of %s failed: %r", robot_id, exc)
