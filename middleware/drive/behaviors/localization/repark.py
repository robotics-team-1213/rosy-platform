"""core_features.localization.repark — fine re-park: a bounded sideways shift made of existing missions.

Safety-tagged (D-430 §1): decides how far and how fast CORE shifts a stopped robot a few centimetres
(cell arm reach fix, D-1051). It adds no wheel path of its own. Every segment is a
`LocalizationMission` run (rotate_to, nudge_forward, nudge_backward), so each keeps the D-424 LiDAR/body
clearance guards, odometry and LiDAR staleness stops, E-stop, mode-change cancel and the CommandManager
arbiter (`select_output`). The sequence is turn θ, drive d, turn back to the start heading by odometry,
then drive the rest along the start heading; odometry closes every step. Any segment that does not end
`done`, or running past the total timeout, stops the robot where it is and reports `aborted`
(the heading may then be off by θ: the caller must not assume it was restored).
"""

from __future__ import annotations

from contextlib import nullcontext
import math
import threading
from typing import Optional
from uuid import UUID

from core_common.protocol.native.receipts import NativeReceipts
from core_common.stop_pose import (REPARK_MAX_FORWARD_M, REPARK_MAX_LEFT_M, REPARK_MAX_TURN_DEG, REPARK_MIN_TURN_DEG,
                                   offset_in_frame)

from core_features.localization.mission import NUDGE, NUDGE_BACK, ROTATE_TO, MissionRefused

MAX_FORWARD_M = REPARK_MAX_FORWARD_M   # nudge_max_m; defined in core_common.stop_pose
MAX_LEFT_M = REPARK_MAX_LEFT_M
MAX_SPEED_MPS = 0.023
MAX_RATE_RPS = 0.09
MIN_THETA_RAD = math.radians(30.0)   # measured on b8xy 2026-11-19: 30 deg, 7 cm gave 38 mm sideways, 2 mm fore-aft
MAX_LEG_M = 0.09            # leaves room under the nudge cap for the sensor-limited shortening
NEGLIGIBLE_M = 0.005
SHORTFALL_M = 0.015          # the measured move may differ from the request by this much per axis


def plan_repark(forward_m: float, left_m: float, turn_deg: float = 0.0) -> list[tuple[str, float]]:
    """Segments for a robot-frame shift (forward +, left +): ("turn", rad) / ("restore", rad) / ("drive", signed m).

    `turn_deg` (left +, at most REPARK_MAX_TURN_DEG) ends the plan with an in-place turn to start heading + turn_deg
    ("restore", rad); it alone is a plan when the shift is below the resolution.
    ValueError when a value is not finite or beyond the caps, or when the fore-aft rest exceeds the cap."""
    if not math.isfinite(turn_deg) or abs(turn_deg) > REPARK_MAX_TURN_DEG:
        raise ValueError(f"the heading trim is limited to {REPARK_MAX_TURN_DEG} degrees")
    if turn_deg and abs(turn_deg) < REPARK_MIN_TURN_DEG:
        raise ValueError(f"a heading trim is at least {REPARK_MIN_TURN_DEG} degree (rotate_to cannot close less)")
    trim = [("restore", math.radians(turn_deg))] if turn_deg else []
    if trim and max(abs(forward_m), abs(left_m)) < NEGLIGIBLE_M:
        return trim
    return _shift_plan(forward_m, left_m) + trim


def _shift_plan(forward_m: float, left_m: float) -> list[tuple[str, float]]:
    if not (math.isfinite(forward_m) and math.isfinite(left_m)):
        raise ValueError("repark values must be finite")
    if abs(forward_m) > MAX_FORWARD_M or abs(left_m) > MAX_LEFT_M:
        raise ValueError(f"repark is limited to {MAX_FORWARD_M} m fore-aft and {MAX_LEFT_M} m sideways")
    if abs(left_m) < NEGLIGIBLE_M:
        if abs(forward_m) < NEGLIGIBLE_M:
            raise ValueError("nothing to move")
        return [("drive", forward_m)]
    theta = max(MIN_THETA_RAD, math.asin(abs(left_m) / MAX_LEG_M))
    leg = abs(left_m) / math.sin(theta)
    rest = forward_m - leg * math.cos(theta)  # forward travel still needed along the start heading
    if abs(rest) > MAX_FORWARD_M:
        raise ValueError("the fore-aft part is too large for this sideways shift")
    plan = [("turn", math.copysign(theta, left_m)), ("drive", leg), ("restore", 0.0)]
    if abs(rest) >= NEGLIGIBLE_M:
        plan.append(("drive", rest))
    return plan


class ReparkRunner:
    """One repark at a time on top of a LocalizationMission; `tick()` is called from the mission's tick."""

    def __init__(self, mission) -> None:
        self._m = mission
        self._receipts = NativeReceipts()
        self._next_idle_epoch = None
        self._navigation_scope = None
        self._admit_segment = nullcontext
        self._authority = None
        self._lock = threading.RLock()        # runner -> mission gate -> mission lock; never taken from inside the mission
        self._run_n: Optional[int] = None     # the mission run number of the running segment
        self._asked = (0.0, 0.0)
        self._plan: list = []
        self._i = 0
        self._start: Optional[tuple] = None
        self._seg_start: Optional[tuple] = None
        self._deadline = 0.0
        self._kind: Optional[str] = None      # the running segment's mission kind
        self._last: dict = {"state": "idle", "reason": None}

    def status(self) -> dict:
        body = dict(self._last)
        if self._plan and body["state"] == "running":
            body["segment"] = f"{self._i + 1}/{len(self._plan)}"
        return body

    def _by_correlation(self, correlation_id: str):
        current = self._receipts.current
        if current is not None and current.correlation_id == correlation_id:
            return current
        return next((operation for operation in reversed(self._receipts.terminal)
                     if operation.correlation_id == correlation_id), None)

    def scoped_status(self, run_id: UUID | None = None, *, correlation_id: str | None = None) -> dict:
        with self._lock:
            # This proves runner identity/lifecycle only. Shared drive quiescence is separate.
            if correlation_id is not None:
                operation = self._by_correlation(correlation_id)
                if operation is None:
                    return {"owner": self._receipts.owner(), "lookup": "UNKNOWN",
                            "operation": None, "quiescence": None}
                run_id = operation.run_id
            view = self._receipts.readback(run_id)
            operation = self._receipts.current
            epoch = self._next_idle_epoch
            if (operation is not None and operation.phase == "TERMINAL"
                    and (run_id is None or run_id == operation.run_id) and epoch is not None):
                observed_at = self._m._command.idle_zero_write(operation.run_id, epoch)
                if observed_at is not None:
                    view["idle_zero_write"] = {"run_id": str(operation.run_id), "mode_epoch": epoch,
                                               "observed_at": observed_at}
            return view

    def start_scoped(self, forward_m: float, left_m: float, turn_deg: float = 0.0, *, correlation_id: str,
                     expected_boot_id: UUID, expected_owner_generation: int,
                     expected_idle_epoch: int, expected_navigation: dict, admission, authority=None) -> dict:
        with self._lock:
            try:
                self._receipts.expect(expected_boot_id, expected_owner_generation)
            except ValueError as exc:
                raise MissionRefused(str(exc), "repark owner changed before admission") from exc
            if self._by_correlation(correlation_id) is not None:
                raise MissionRefused("REPARK_REQUEST_ALREADY_ADMITTED", "read the original repark receipt")
            self.start(forward_m, left_m, turn_deg, correlation_id=correlation_id,
                       expected_idle_epoch=expected_idle_epoch, expected_navigation=expected_navigation,
                       admission=admission, authority=authority)
            return self.scoped_status()

    def start(self, forward_m: float, left_m: float, turn_deg: float = 0.0, *, correlation_id: str | None = None,
              expected_idle_epoch: int | None = None, expected_navigation: dict | None = None,
              admission=nullcontext, authority=None) -> dict:
        """Start, or raise ValueError (400) / MissionRefused (409). Nothing moves on a refusal."""
        plan = plan_repark(float(forward_m), float(left_m), float(turn_deg))
        with self._lock:
            if self._last["state"] == "running":
                raise MissionRefused("MOTION_BUSY", "a repark is running")
            start, self._odom_epoch = self._m.odom_snapshot()
            if start is None:
                raise MissionRefused("ODOMETRY_STALE", "no fresh odometry to close the shift on")
            operation = self._receipts.admit("repark", correlation_id)
            self._next_idle_epoch = expected_idle_epoch
            self._navigation_scope = expected_navigation
            self._admit_segment = admission
            self._authority = authority
            self._plan, self._i, self._start, self._kind = plan, 0, start, None
            self._asked = (float(forward_m), float(left_m))
            self._deadline = self._m._clock() + 45.0 + (15.0 if abs(turn_deg) >= REPARK_MIN_TURN_DEG else 0.0)  # + the trim leg
            self._last = {"state": "running", "reason": None}
            try:
                self._begin(plan[0])
            except Exception:
                self._plan = []
                self._last = {"state": "idle", "reason": None}
                self._receipts.update(operation.run_id, phase="TERMINAL", result="FAILED",
                                      reason="REPARK_ADMISSION_FAILED")
                raise
            self._receipts.update(operation.run_id, phase="RUNNING")
            return self.status()

    def cancel(self) -> None:
        with self._lock:
            if self._last["state"] == "running":
                if self._m.runs_started == self._run_n:
                    self._m.end("cancelled")  # only our own segment; a foreign mission is not ours to stop
                self._finish("aborted", "cancelled")

    def tick(self) -> None:
        with self._lock:
            if self._last["state"] != "running":
                return
            m = self._m
            seg = m.status()
            ours = m.runs_started == self._run_n and seg.get("kind") == self._kind
            if m._clock() > self._deadline:
                if ours:
                    m.end("timeout")
                self._finish("aborted", "timeout")
                return
            if not ours:  # someone else's mission took the wheels between two segments
                self._finish("aborted", "segment_lost")
                return
            if seg.get("state") == "running":
                return
            if seg.get("state") != "done":
                self._finish("aborted", seg.get("reason") or "segment_lost")
                return
            kind, value = self._plan[self._i]
            end = m.odom_pose(epoch=self._odom_epoch)
            if end is None:
                self._finish("aborted", "odometry_stale")
                return
            if kind == "drive" and abs(offset_in_frame(self._seg_start, end)[0] - value) > SHORTFALL_M:
                # A LiDAR-shortened leg still ends "done"; later legs would be planned from a leg never made.
                self._finish("aborted", "short_of_request")
                return
            self._i += 1
            if self._i >= len(self._plan):
                self._finish("done", None, end)
                return
            try:
                self._begin(self._plan[self._i])
            except (MissionRefused, ValueError) as exc:
                self._finish("aborted", getattr(exc, "code", None) or str(exc))

    def _begin(self, segment) -> None:
        epoch = self._next_idle_epoch
        scope = {} if epoch is None else {
            "expected_idle_epoch": epoch, "expected_navigation": self._navigation_scope,
        }
        if self._authority is not None:
            scope["repark_authority"] = self._authority
        scope["repark_odom_epoch"] = self._odom_epoch
        with self._admit_segment():
            self._start_segment(segment, scope)
        if epoch is not None:
            # The successful scoped segment takes NAVIGATION, then yields IDLE once.
            self._next_idle_epoch = epoch + 2

    def _start_segment(self, segment, scope: dict) -> None:
        kind, value = segment
        m = self._m
        self._seg_start = m.odom_pose(epoch=self._odom_epoch)
        if self._seg_start is None:
            raise MissionRefused("ODOMETRY_STALE", "no fresh odometry for the repark segment")
        if kind in ("turn", "restore"):
            rate_dps = math.degrees(MAX_RATE_RPS) - 0.2   # just under the cap, the goal check is inclusive
            now_yaw = self._seg_start[2]
            target = self._start[2] + value  # restore: the start heading, plus the heading trim of the last segment
            turn = value if kind == "turn" else math.atan2(math.sin(target - now_yaw), math.cos(target - now_yaw))
            timeout = min(15.0, 2.0 * math.degrees(abs(turn)) / rate_dps + 3.0)
            request = {"delta_deg": math.degrees(value)} if kind == "turn" else {"yaw_odom": target}
            m.start_rotate_to(tol_deg=1.0, max_rate_dps=rate_dps, timeout_s=timeout, **scope, **request)
            self._kind = ROTATE_TO
        else:
            self._kind = NUDGE if value > 0 else NUDGE_BACK
            m.start(self._kind, abs(value), 2.0 * abs(value) / MAX_SPEED_MPS + 3.0, speed=MAX_SPEED_MPS, **scope)
        self._run_n = m.runs_started

    def _finish(self, state: str, reason: Optional[str], end=None) -> None:
        if state == "done" and end is None:
            state, reason = "aborted", "odometry_stale"
        elif state != "done" and reason != "odometry_stale":
            end = self._m.odom_pose(epoch=self._odom_epoch)
        self._last = {"state": state, "reason": reason}
        if self._start is not None and end is not None:
            forward, left = offset_in_frame(self._start, end)
            self._last["moved_robot_dxdy_m"] = {"forward_m": round(forward, 4), "left_m": round(left, 4)}
            # A nudge the LiDAR shortened still ends "done"; the shift is not made, so it is not done.
            if state == "done" and (abs(forward - self._asked[0]) > SHORTFALL_M
                                    or abs(left - self._asked[1]) > SHORTFALL_M):
                self._last["state"], self._last["reason"] = "aborted", "short_of_request"
        self._plan = []
        operation = self._receipts.current
        if operation is not None:
            result = ("SUCCEEDED" if self._last["state"] == "done" else
                      "CANCELED" if reason == "cancelled" else "FAILED")
            self._receipts.update(operation.run_id, phase="TERMINAL", result=result,
                                  reason=None if result == "SUCCEEDED" else "REPARK_STOPPED")
            if self._next_idle_epoch is not None:
                self._m._command.arm_idle_zero_write(operation.run_id, self._next_idle_epoch)
