"""D-511 rev 1: Fleet's lane return cue in the CAMERA_LINE keep (``fleet_lane_cue_enabled``).

Fleet (Rosy Cam + site map, 2 Hz, ttl <= 2 s) says where the robot is against the lanes. The cue
never starts motion and is read only on a CAMERA_LINE tick that already passed the obstacle stop,
the stale-IR stop and the IR centre departure; the D-573 gate and the D-517 authority still cap
the result afterwards. Per state:

- ON_LINE / OFF_LANE: when the IR guard sees no line (clear, or off) the cue's ``side`` takes the
  IR edge branch (D-511 4: the same bounded ``ir_guard_turn`` toward the lane centre). An IR
  ``left``/``right`` reading wins. OFF_LANE with the re-entry point more than
  ``PIVOT_BEARING_DEG`` off the nose turns in place toward it first.
- WRONG_WAY: turn in place toward the lane's direction (``turn_deg``) until within
  ``PIVOT_DONE_DEG``; the lane is 0.185 m and the Pinky sweep radius 0.088 m, so the pivot fits
  (URDF). Without ``turn_deg`` (Fleet has no heading): HOLD.
- OFF_MAP: HOLD ``fleet_off_map`` until Fleet says otherwise (Fleet raises it to the operator).
- ``crosswalk_ahead``: one D-573 zone anchored at the odom pose when the cue arrived, so the gate
  stops, looks and crosses even when the camera zone is unstable.
"""
from __future__ import annotations

import math
from typing import Optional

from core_features.line_follow.crosswalk_gate import Zone
from core_features.line_follow.model import LineFollowDecision

#: OFF_LANE: re-entry point further than this off the nose -> turn in place first (deg).
PIVOT_BEARING_DEG = 45.0
#: WRONG_WAY pivot ends when the lane direction is within this of the nose (deg).
PIVOT_DONE_DEG = 30.0
#: Fleet zone margin along the road: Rosy Cam pose (~2 cm) + 0.5 s latency at cruise (~4 cm).
FLEET_ZONE_MARGIN_M = 0.06


class LaneCueMixin:
    """LineFollowManager glue (manager lock throughout)."""

    def _init_lane_cue(self) -> None:
        self._cue: Optional[dict] = None
        self._cue_until = 0.0
        self._cue_zone: Optional[Zone] = None

    def set_lane_cue(self, cue: dict, now: Optional[float] = None) -> tuple[bool, Optional[str]]:
        """Keep the newest cue (``LaneCueRequest.model_dump()``). (accepted, reason)."""
        now = self._clock() if now is None else float(now)
        with self._lock:
            if not self._config.fleet_lane_cue_enabled:
                return False, "disabled"
            old = self._cue
            if (old is not None and now < self._cue_until and old["fleet_epoch"] == cue["fleet_epoch"]
                    and cue["seq"] <= old["seq"]):
                return False, "stale"
            self._cue, self._cue_until = dict(cue), now + float(cue["ttl_s"])
            self._cue_zone = self._anchor_cue_zone(cue.get("crosswalk_ahead"), now)
            return True, None

    def lane_cue_status(self, now: Optional[float] = None) -> Optional[dict]:
        now = self._clock() if now is None else float(now)
        with self._lock:
            cue = self._fresh_cue(now)
            return None if cue is None else {**cue, "expires_in_s": round(self._cue_until - now, 3)}

    def _fresh_cue(self, now: float) -> Optional[dict]:
        return self._cue if self._cue is not None and now < self._cue_until else None

    def _anchor_cue_zone(self, ahead, now: float) -> Optional[Zone]:
        pose = self._fresh_pose(now)
        if not ahead or pose is None:
            return None
        near = float(ahead["distance_m"]) + self._config.body_front_x_m
        return Zone(key=(self._return_evidence.epoch, pose.frame), x=pose.x, y=pose.y, yaw=pose.yaw,
                    near=near, far=near + float(ahead["length_m"]), margin=FLEET_ZONE_MARGIN_M)

    def _fleet_crosswalk_zones(self, now: float) -> list:
        return [self._cue_zone] if self._cue_zone is not None and self._fresh_cue(now) else []

    def _lane_cue_guard(self, now: float, guard: Optional[str]) -> Optional[str]:
        """IR first: only an IR that sees nothing (clear) or is off takes the cue's side."""
        cue = self._fresh_cue(now)
        if (cue is None or guard not in (None, "clear") or cue["state"] not in ("ON_LINE", "OFF_LANE")
                or cue.get("side") not in ("left", "right")):
            return guard
        return "right" if cue["side"] == "left" else "left"   # the edge branch turns away from it

    def _lane_cue_override(self, now: float, cap: float):
        """A pivot or a hold the cue asks for, else None (the keep drives)."""
        cue = self._fresh_cue(now)
        if cue is None:
            return None
        state = cue["state"]
        if state == "OFF_MAP":
            return self._stop_decision("HOLD", "fleet_off_map")
        turn = None
        if state == "WRONG_WAY":
            if cue.get("turn_deg") is None:
                return self._stop_decision("HOLD", "fleet_wrong_way")
            if abs(cue["turn_deg"]) > PIVOT_DONE_DEG:
                turn, reason = cue["turn_deg"], "fleet_wrong_way_turn"
        elif state == "OFF_LANE" and cue.get("bearing_deg") is not None \
                and abs(cue["bearing_deg"]) > PIVOT_BEARING_DEG:
            turn, reason = cue["bearing_deg"], "fleet_off_lane_turn"
        if turn is None:
            return None
        rate = min(self._config.ir_guard_turn, self._config.max_angular, cap)
        if rate <= 0.0:
            return self._stop_decision("HOLD", "angular_limit_zero")
        angular = math.copysign(rate, turn)   # REP-103: left +
        self._status = self._status.model_copy(update={
            "mode": self._mode.value, "state": "TRACKING", "linear": 0.0, "angular": angular,
            "reason": reason, "clearance_m": self._clearance})
        return LineFollowDecision(linear=0.0, angular=angular, generation=self._generation,
                                  evidence_revision=self._evidence_revision, mode=self._mode)
