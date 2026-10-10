"""D-607 8 REALIGN start and per-tick checks against the LineFollowManager state (manager lock)."""
from __future__ import annotations

from typing import Optional

from core_common.robot_body import NOMINAL_BODY, ROTATION_SECTORS, SWEEP_PAD_M
from core_features.line_follow.model import LineFollowMode
from core_features.line_follow.recovery.stuck.realign.manoeuvre import Manoeuvre
from core_features.line_follow.recovery.stuck.realign.recovery import RealignRecovery
from core_features.line_follow.recovery.stuck.realign.request import MAX_REALIGNS, request_refusal
from core_features.line_follow.recovery.stuck.stuck_recovery import _TURN_CLEAR_M, _TURN_RATE, CROSSWALK


class RealignMixin:
    """LineFollowManager glue (manager lock throughout): the checks read the manager's odom log, scan,
    IR guard, crosswalk gate and D-422 body stop."""

    def _init_recovery(self) -> None:
        super()._init_recovery()
        self._recovery = RealignRecovery(self._events, self._config, live=self._realign_live)

    def stuck_decision(self, stuck_id: str, decision: str, *, realign: Optional[dict] = None, **kwargs) -> str:
        with self._lock:
            now = float(self._clock() if kwargs.get("now") is None else kwargs["now"])
            on = decision == "REALIGN" and self._config.stuck_realign_enabled
            self._recovery.starter = (lambda inp: self._realign_start(now, inp, realign)) if on else None
            return super().stuck_decision(stuck_id, decision, **kwargs)

    def _realign_start(self, now: float, inp, req: Optional[dict]):
        """(Manoeuvre, None) or (None, why) -- every D-607 8 check before the first tick."""
        c, rec = self._config, self._recovery
        why = ("crosswalk_gate" if rec._cause == CROSSWALK or self._crosswalk_armed()
               else "local_recovery_disabled" if not c.recovery_local_enabled
               else request_refusal(req) or ("realign_active" if rec.realigning else None)
               or ("realign_attempts_exhausted" if rec.realigns >= MAX_REALIGNS else None))
        if why is not None:
            return None, why
        yaw0, refused = self._cue_pose_yaw(float(req["pose_stamp"]))
        pose = self._fresh_pose(now)
        key = None if pose is None else (self._return_evidence.epoch, pose.frame)
        if refused is not None or key is None or yaw0[0] != key:
            return None, "pose_stamp_unknown"
        rate = min(_TURN_RATE, self._angular_cap())
        speed = min(inp.linear_ceiling, c.recovery_back_speed)
        if rate <= 0.0 or (req["kind"] == "KTURN" and speed <= 0.0):
            return None, "linear_limit_zero"
        move = Manoeuvre(req, key=key, yaw_at_order=yaw0[1], pose=pose, now=now, rate=rate, speed=speed)
        first = move.twists[move.leg]
        why = self._realign_why(now, inp, move.kind, first[0], first[1] * move.yaw.sign)
        return (None, why) if why is not None else (move, None)

    def _realign_live(self, inp, move: Manoeuvre):
        now, c = inp.now, self._config
        pose = self._fresh_pose(now)
        verdict, out = move.step(now, pose, None if pose is None else (self._return_evidence.epoch, pose.frame))
        if verdict != "move":
            return verdict, out
        if self._mode is LineFollowMode.CAMERA_LINE and c.ir_guard_enabled:
            guard = self._ir_guard(now)          # D-344 §12: the centre passes only a turn-spot PIVOT
            if guard == "stale":
                return "fail", "lane_guard_stale"
            if guard == "centre" and not (move.kind == "PIVOT" and move.turn_spot):
                return "fail", "lane_departure"
        why = self._realign_why(now, inp, move.kind, *out, starting=False)
        return ("move", out) if why is None else ("fail", why)

    def _realign_why(self, now: float, inp, kind: str, linear: float, angular: float,
                     starting: bool = True) -> Optional[str]:
        c = self._config
        if inp.calibration_active:
            return "calibration_active"
        if not c.body_stop_known:
            return "body_geometry_unset"
        if inp.scan_age_s is None or self._body_points is None or self._scan_points is None:
            return "no_scan"
        if inp.scan_age_s > c.clearance_stale_s:
            return "scan_stale"
        if inp.cause == CROSSWALK or self._crosswalk_armed():
            return "crosswalk_gate"
        if linear < 0.0:                         # KTURN reverse arc: the stuck back-off rules as they are
            return self._recovery._back_refusal(inp, starting=starting)
        if kind == "PIVOT":
            if inp.turn_m is None or inp.turn_m < SWEEP_PAD_M + _TURN_CLEAR_M:
                return "turn_blocked"
            base = [(x + c.body_lidar_x_m, y) for x, y in self._body_points]
            if NOMINAL_BODY.seen_sectors(base) < ROTATION_SECTORS:   # geometry-free sector count (D-424)
                return "turn_unseen"
        # D-422 on the twist this tick sends (the tick itself measured the camera's intent).
        saved, self._intended = self._intended, (linear, angular)
        try:
            gap, _, stop, _ = self._body_clearance(now)
        finally:
            self._intended = saved
        if gap is not None and gap <= stop:
            return "turn_blocked" if kind == "PIVOT" else "object_within_stop_distance"
        return None
