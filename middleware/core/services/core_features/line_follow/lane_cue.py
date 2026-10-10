"""D-511 rev 1/2: Fleet's lane cue in the CAMERA_LINE keep (``fleet_lane_cue_enabled``, D-430 review).

Fleet (Rosy Cam + site map, 2 Hz, ttl <= 2 s) says where the robot is against the lanes. The cue is a
hint: it never lifts a stop. ``_lane_cue_plan`` runs on a CAMERA_LINE tick after the IR guard is read
and before the obstacle check, so the D-422 body stop measures the twist the cue will produce (a pivot
is ``(0, w)``: the rotation circle). A pivot is returned only after the LOST latch, the D-364 NOMINAL
ground rule and the camera freshness rule (lane_recovery_rule FOLLOW) all passed; the D-573 gate and
the D-517 authority cap it afterwards like any decision. Per state:

- ON_LINE / OFF_LANE: when the IR guard sees no line (clear, or off) and Fleet's lateral offset is at
  least ``SIDE_MIN_OFFSET_M`` on the same side twice in a row, the side takes the IR edge branch
  toward the lane centre (``cue_left``/``cue_right``, no back-creep). An IR reading wins. Bringing a
  robot that is outside the lane back across the paint is D-468's job, not this cue's.
- WRONG_WAY (``turn_deg``) and OFF_LANE with the re-entry point more than ``PIVOT_BEARING_DEG`` off the
  nose: after two cues of the same sign at least ``DEBOUNCE_S`` apart, turn in place to an odom yaw
  target = odom yaw at the cue's ``pose_stamp`` + the angle. The pivot is bounded on CORE: turned
  angle <= |angle| + ``BUDGET_PAD_DEG`` and time <= |angle| / rate + ``TIME_PAD_S``, else a latched
  HOLD ``fleet_turn_unconfirmed``. No pivot starts while a junction instruction, an arc or a crosswalk
  zone is live.
- OFF_MAP, a pivot whose cue expired, and an unconfirmed pivot: a latched HOLD. It is released only by a
  fresh ON_LANE / ON_LINE cue of the same Fleet epoch, a D-407 stuck decision (STUCK_DECIDE) or a mode
  change.
- ``guide`` (D-511 rev 2): kept in ``lane_cue`` for the keep (line_observer) as a prior; not steered on.

``(fleet_epoch, seq)`` is kept across expiry: an older seq is always stale; another epoch is taken only
when no cue is fresh and no pivot or latch is open. A cue whose ``pose_stamp`` is more than
``MAX_POSE_AGE_S`` older than CORE's newest odom (or newer) is refused, like the D-517 authority,
except OFF_MAP: a HOLD needs no odom alignment, and OFF_MAP is sent exactly when Fleet has lost the
robot (re-review 1). A pivot's sign is locked at its start and its progress is the signed odom turn
since then, so a turn near 180 deg ends on progress, not on a wrapped angle (re-review 3). A junction
left ``aborted`` keeps pivots off until the mode changes. Enabling needs ``obstacle_mode: path``.
While a D-407 stuck record is open the cue stands down (no pivot, no side steering; a latch still
holds): the stuck answer is the one channel then.
"""
from __future__ import annotations

import math
from typing import Optional

from core_common.protocol.line_authority import STAMP_TOL_S
from core_features.line_follow.model import LineFollowDecision

#: OFF_LANE: re-entry point further than this off the nose -> turn in place first (deg).
PIVOT_BEARING_DEG = 45.0
#: A WRONG_WAY smaller than this is left to the keep; a pivot ends within it (deg).
PIVOT_DONE_DEG = 30.0
#: A pivot may turn |angle| + this before it is unconfirmed (deg); and take |angle|/rate + this (s).
BUDGET_PAD_DEG = 30.0
TIME_PAD_S = 2.0
#: Two same-sign pivot cues this far apart before a pivot starts (s).
DEBOUNCE_S = 0.5
#: Side cues act only beyond this lateral offset (m): Rosy Cam +-2-4 cm plus ~6 cm of latency travel.
SIDE_MIN_OFFSET_M = 0.05
#: A cue's pose_stamp may be at most this much older than CORE's newest odom (s).
MAX_POSE_AGE_S = 1.5
#: A pivot cue this close to 180 deg keeps the streak's sign (Fleet's sign there is noise) (deg).
SIGN_FREE_DEG = 150.0
#: A gap longer than this between two cues restarts the debounce (s).
STREAK_GAP_S = 1.0
#: Normal states that release a latch.
NORMAL = ("ON_LANE", "ON_LINE")


def _wrap(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


class LaneCueMixin:
    """LineFollowManager glue (manager lock throughout)."""

    def _init_lane_cue(self) -> None:
        self._cue: Optional[dict] = None
        self._cue_until = 0.0
        self._cue_last: Optional[tuple] = None     # (epoch, seq), kept across expiry
        self._cue_yaw0: Optional[float] = None     # odom yaw at the cue's pose_stamp
        self._cue_streak: dict = {}                # pivot: (sign, first_at, count); side: (side, count)
        self._pivot: Optional[dict] = None
        self._cue_latch: Optional[str] = None

    # ---- input --------------------------------------------------------------------------------

    def set_lane_cue(self, cue: dict, now: Optional[float] = None,
                     principal_ref: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """Keep the newest cue (``LaneCueRequest.model_dump()``). (accepted, reason)."""
        now = self._clock() if now is None else float(now)
        with self._lock:
            if not self._config.fleet_lane_cue_enabled:
                return False, "disabled"
            epoch, seq = cue["fleet_epoch"], cue["seq"]
            last = self._cue_last
            if last is not None and last[0] == epoch and seq <= last[1]:
                return False, "stale"
            if (last is not None and last[0] != epoch
                    and (now < self._cue_until or self._pivot is not None or self._cue_latch is not None)):
                return False, "epoch_busy"
            yaw0, refusal = (None, None) if cue["state"] == "OFF_MAP" else self._cue_pose_yaw(cue["pose_stamp"])
            if refusal is not None:
                return False, refusal
            previous = None if self._cue is None or now >= self._cue_until else self._cue["state"]
            self._cue, self._cue_until, self._cue_last, self._cue_yaw0 = (
                dict(cue), now + float(cue["ttl_s"]), (epoch, seq), yaw0)
            self._cue_count(cue, now)
            if self._cue_latch is not None and cue["state"] in NORMAL:
                self._cue_event("unlatched", cue, principal_ref, latch=self._cue_latch)
                self._cue_latch, self._cue_streak = None, {}
            if cue["state"] != previous:
                self._cue_event("state", cue, principal_ref)
            return True, None

    def _cue_pose_yaw(self, pose_stamp: float) -> tuple[Optional[tuple], Optional[str]]:
        """((odom key, yaw) at ``pose_stamp`` (CORE wall clock, the authority's odom log), or a refusal."""
        log, trail = self._odom_log, self._return_evidence.trail.samples
        if not log or not trail:
            return None, "odom_stale"
        if pose_stamp > log[-1][0] + STAMP_TOL_S:
            return None, "pose_future"
        if pose_stamp < log[-1][0] - MAX_POSE_AGE_S:
            return None, "pose_stale"
        base = next((e for e in reversed(log) if e[0] <= pose_stamp), None)
        sample = None if base is None else next((p for p in reversed(trail) if p.stamp_ns == base[2]), None)
        if sample is None:
            return None, "pose_stale"
        return (base[1], sample.yaw), None

    def _cue_count(self, cue: dict, now: float) -> None:
        """Debounce: consecutive same-sign pivot cues and same-side side cues."""
        angle = self._cue_angle(cue)
        sign = None if angle is None else (1 if angle > 0 else -1)
        old = self._cue_streak.get("pivot")
        if old and now - old[3] > STREAK_GAP_S:
            old = None                                      # a gap restarts the debounce
        if old and sign is not None and abs(angle) >= SIGN_FREE_DEG:
            sign = old[0]                                   # near 180 deg the sign is noise: keep it
        self._cue_streak["pivot"] = (None if sign is None else
                                     (sign, old[1], old[2] + 1, now) if old and old[0] == sign else (sign, now, 1, now))
        side = cue.get("side") if (cue["state"] in ("ON_LINE", "OFF_LANE") and cue.get("offset_m") is not None
                                   and abs(cue["offset_m"]) >= SIDE_MIN_OFFSET_M) else None
        old = self._cue_streak.get("side")
        self._cue_streak["side"] = (None if side is None else
                                    (side, old[1] + 1) if old and old[0] == side else (side, 1))

    @staticmethod
    def _cue_angle(cue: dict) -> Optional[float]:
        if cue["state"] == "WRONG_WAY" and cue.get("turn_deg") is not None and abs(cue["turn_deg"]) > PIVOT_DONE_DEG:
            return cue["turn_deg"]
        if (cue["state"] == "OFF_LANE" and cue.get("bearing_deg") is not None
                and abs(cue["bearing_deg"]) > PIVOT_BEARING_DEG):
            return cue["bearing_deg"]
        return None

    def release_lane_cue_latch(self, principal_ref: Optional[str] = None) -> None:
        """A D-407 stuck decision (STUCK_DECIDE) releases a latched cue HOLD."""
        with self._lock:
            if self._cue_latch is not None:
                self._cue_event("unlatched", self._cue or {}, principal_ref, latch=self._cue_latch)
            self._cue_latch, self._pivot, self._cue_streak = None, None, {}

    def _cue_event(self, action: str, cue: dict, principal_ref: Optional[str], latch: Optional[str] = None,
                   angle_deg: Optional[float] = None) -> None:
        """D-430 review 6: every state change, latch, release and pivot start, with who sent it."""
        self._events.publish("nav.lane_cue", source="line_follow_manager", data={
            "action": action, "state": cue.get("state"), "fleet_epoch": cue.get("fleet_epoch"),
            "seq": cue.get("seq"), "principal_ref": principal_ref, "latch": latch, "angle_deg": angle_deg})

    # ---- status -------------------------------------------------------------------------------

    def _fresh_cue(self, now: float) -> Optional[dict]:
        return self._cue if self._cue is not None and now < self._cue_until else None

    def _lane_cue_view(self, now: float) -> Optional[dict]:
        cue = self._fresh_cue(now)
        if cue is None and self._cue_latch is None and self._pivot is None:
            return None
        return {**(cue or {}), "expires_in_s": None if cue is None else round(self._cue_until - now, 3),
                "latch": self._cue_latch, "pivot": None if self._pivot is None else {
                    "turned_deg": round(math.degrees(self._pivot["turned"]), 1),
                    "remaining_deg": round(math.degrees(self._pivot["remaining"]), 1)}}

    def lane_cue_status(self, now: Optional[float] = None) -> Optional[dict]:
        now = self._clock() if now is None else float(now)
        with self._lock:
            return self._lane_cue_view(now)

    # ---- the tick -----------------------------------------------------------------------------

    def _latch(self, reason: str, now: float) -> tuple:
        if self._cue_latch is None:
            self._cue_latch = reason
            self._cue_event("latched", self._cue or {}, None, latch=reason)
        self._pivot = None
        return ("hold", reason)

    def _lane_cue_busy(self, now: float) -> bool:
        """A junction instruction, an arc or a crosswalk zone owns the robot's heading now."""
        arc = self._arc_status()
        return (self._junction_status().state != "idle" or (arc is not None and arc.state == "running")
                or self._xwalk.zone is not None)

    def _lane_cue_plan(self, now: float, cap: float):
        """None (the keep drives), ("hold", reason), ("turn", angular, reason) or ("side", side)."""
        if self._cue_latch is not None:
            return ("hold", self._cue_latch)
        if self._recovery.status(now) is not None:
            # An open D-407 stuck: its answer (Fleet's REALIGN, a human) owns the robot. No pivot or
            # side steering until it closes; a running pivot is dropped, not latched.
            self._pivot, self._cue_streak = None, {}
            return None
        cue = self._fresh_cue(now)
        if self._pivot is not None:
            if self._lane_cue_busy(now):
                return self._latch("fleet_turn_interrupted", now)   # a junction/arc/zone took over
            return self._pivot_step(now, cue, cap)
        if cue is None:
            return None
        if cue["state"] == "OFF_MAP":
            return self._latch("fleet_off_map", now)
        angle = self._cue_angle(cue)
        streak = self._cue_streak.get("pivot")
        if angle is not None:
            if cue["state"] == "WRONG_WAY" and cue.get("turn_deg") is None:
                return ("hold", "fleet_wrong_way")
            if (streak and streak[2] >= 2 and now - streak[1] >= DEBOUNCE_S and self._cue_yaw0 is not None
                    and not self._lane_cue_busy(now)):
                return self._pivot_start(now, streak[0] * abs(angle), cap)
            return None
        side = self._cue_streak.get("side")
        if side and side[1] >= 2:
            return ("side", side[0])
        return None

    def _pivot_start(self, now: float, angle_deg: float, cap: float):
        pose = self._fresh_pose(now)
        rate = min(self._config.ir_guard_turn, self._config.max_angular, cap)
        key = None if pose is None else (self._return_evidence.epoch, pose.frame)
        if pose is None or rate <= 0.0 or self._cue_yaw0[0] != key:
            return None                                     # the cue's odom run is not this one
        angle = math.radians(angle_deg)
        sign = 1.0 if angle > 0 else -1.0
        # Signed progress since the start; the cue's pose already turned _wrap(now - then) of it.
        done = sign * _wrap(pose.yaw - self._cue_yaw0[1])
        self._pivot = dict(key=key, sign=sign, last=pose.yaw, turned=0.0, total=abs(angle),
                           progress=done, remaining=abs(angle) - done,
                           budget=abs(angle) + math.radians(BUDGET_PAD_DEG),
                           deadline=now + abs(angle) / rate + TIME_PAD_S,
                           reason="fleet_wrong_way_turn" if self._cue["state"] == "WRONG_WAY" else "fleet_off_lane_turn")
        self._cue_event("pivot", self._cue, None, angle_deg=round(angle_deg, 1))
        return self._pivot_step(now, self._cue, cap)

    def _pivot_step(self, now: float, cue: Optional[dict], cap: float):
        p, pose = self._pivot, self._fresh_pose(now)
        if cue is None:
            return self._latch("fleet_cue_lost", now)                    # Fleet vanished mid-pivot
        if pose is None or (self._return_evidence.epoch, pose.frame) != p["key"]:
            return self._latch("fleet_turn_unconfirmed", now)            # odom gone: cannot measure
        step = _wrap(pose.yaw - p["last"])                              # one tick: never near 180
        p["turned"] += abs(step)
        p["progress"] += p["sign"] * step
        p["last"] = pose.yaw
        p["remaining"] = p["total"] - p["progress"]
        if p["remaining"] <= math.radians(PIVOT_DONE_DEG) / 3:            # within 10 deg: done
            self._pivot = None
            self._cue_streak["pivot"] = None
            return None
        if p["turned"] > p["budget"] or now > p["deadline"]:
            return self._latch("fleet_turn_unconfirmed", now)
        rate = min(self._config.ir_guard_turn, self._config.max_angular, cap)
        if rate <= 0.0:
            return ("hold", "angular_limit_zero")
        return ("turn", p["sign"] * rate, p["reason"])

    def _lane_cue_turn(self, plan) -> LineFollowDecision:
        """The pivot decision, after every earlier gate of the tick passed."""
        _, angular, reason = plan
        self._status = self._status.model_copy(update={
            "mode": self._mode.value, "state": "TRACKING", "linear": 0.0, "angular": angular,
            "reason": reason, "clearance_m": self._clearance, **self._gap_status})
        return LineFollowDecision(linear=0.0, angular=angular, generation=self._generation,
                                  evidence_revision=self._evidence_revision, mode=self._mode)
