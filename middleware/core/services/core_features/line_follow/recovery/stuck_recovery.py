"""D-407 lane stuck recovery: ask the console, else back off a little and re-judge.

ROS-free state machine. The line-follow manager feeds it one ``StuckInput`` per tick
(under its lock) and applies the returned ``StuckAction`` through its own decision, so
the back-off twist leaves through the single CORE ``cmd_vel`` path (D-2). Console answers
arrive through ``answer`` and must carry the open stuck id (a late answer never lands on
the next stuck).

Phases while a stuck is open:
  ASKING           console asked; local fallback after ``recovery_ask_s`` or with no link
  WAITING_CONSOLE  HOLD, console answer only (WAIT, local disabled/refused/exhausted)
  BACKING          short straight back-off at min(D-342 manual linear, recovery_back_speed)
  SETTLING         stopped ``recovery_settle_s``, then lane + front re-judged
  TURNING          timed yaw of one YIELD segment, then the crawl (D-453)
  CRAWLING         timed forward creep of that segment
  YIELDED          stopped off the line; a later YIELD is the next segment
E-stop, IDLE, line-follow OFF and driver-hold loss reach the manager's ``set_mode(OFF)``,
which calls ``reset``: the stuck closes and nothing here can move the wheels again.
"""

from __future__ import annotations

import math
import uuid
from collections import deque
from dataclasses import dataclass, replace
from typing import Callable, Optional

from core_features.line_follow.model import LineFollowConfig

ASKING = "ASKING"
WAITING_CONSOLE = "WAITING_CONSOLE"
BACKING = "BACKING"
SETTLING = "SETTLING"
TURNING = "TURNING"
CRAWLING = "CRAWLING"
YIELDED = "YIELDED"
DECISIONS = ("WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT", "YIELD")
#: D-573 4: a person may be on the crosswalk; only a stopping answer or the operator's own end.
CROSSWALK = "crosswalk_blocked"
CROSSWALK_DECISIONS = ("WAIT", "MANUAL", "ABORT")
NO_MOTION = "no_motion"  # 2026-10-10 user: zero command for stuck_report_s, any reason; Fleet answers
REPORT_ONLY = ("no_progress", "dithering")  # D-407 개정 2026-10-10: commanded, odom still; drives on until answered
_TURN_RATE = 0.3          # rad/s. One yield segment turns, then creeps forward.
_TURN_SKIP = 0.15         # rad. Smaller than this and the crawl starts at once.
_TURN_CLEAR_M = 0.02      # clearance outside the rotation radius a turn requires
_YIELD_MIN_M = 0.05
_YIELD_MAX_M = 2.0
_SOURCE = "line_follow_manager"


@dataclass(frozen=True)
class StuckInput:
    """Everything one tick knows. Distances in metres; None = nothing seen / unknown."""

    now: float
    cause: Optional[str] = None  # obstacle_ahead | lane_lost | crosswalk_blocked | no_motion | REPORT_ONLY | None
    cause_detail: Optional[str] = None   # D-573 4 crosswalk_blocked reason; else the (last) HOLD reason
    lane_visible: bool = False           # fresh, confident lane evidence (re-judge)
    front_clear: bool = True             # no path-band return within obstacle_resume_m
    front_band_m: Optional[float] = None
    # LiDAR-origin distance RESUME refuses below (D-422: the body stop gap seen from the
    # LiDAR in body mode). None = the config's sector_stop_m.
    front_stop_m: Optional[float] = None
    rear_m: Optional[float] = None       # from the body rear (URDF), self-mask applied
    # "clear" (band empty or wider than recovery_rear_clear_m), "blocked", or "unknown"
    # (no geometry / no fresh scan): rear_m None alone cannot tell empty from unknown.
    rear_state: str = "unknown"
    turn_m: Optional[float] = None
    # Rear band behind the body rear that the LiDAR cannot see (range_min, self-mask
    # windows). None = unknown (no range_min, no geometry): never back off.
    rear_blind_m: Optional[float] = None
    trail_m: Optional[float] = None      # net forward CORE-issued travel (ForwardTrail)
    trail_yaw_deg: Optional[float] = None
    trail_age_s: Optional[float] = None  # since the trail's last forward command (None = none)
    scan_age_s: Optional[float] = None   # None = no LiDAR scan ever
    lidar_expected: bool = False         # a LiDAR obstacle stop has seen scans this session
    # Net forward CORE-issued travel since the last `recovered` close (None = unknown).
    moved_since_recovery_m: Optional[float] = None
    geometry_known: bool = False
    console_linked: bool = False
    calibration_active: bool = False
    linear_ceiling: float = 0.0          # D-342 live manual linear limit
    last_lane: Optional[dict] = None
    preview_seq: Optional[int] = None


@dataclass(frozen=True)
class StuckAction:
    kind: str = "pass"     # pass (base decision) | hold (zero) | back | resume | yield
    linear: float = 0.0
    angular: float = 0.0


class ForwardTrail:
    """The CORE-issued line-follow twists, to prove the space behind was just driven through.

    User decision 2026-10-02 (D-407 rear blind zone): back off into the blind band only over
    ground the robot drove forward over. ``measure`` integrates the issued twists over the
    ``window_s`` of commands that ends at the last forward command (the robot has stood still
    or backed off since): net forward metres (reverse subtracts) and total |yaw| in degrees.
    A gap in the record counts no travel; a record older than ``STALE_S`` reads as missing.
    """

    MAX_DT_S = 0.25    # one issued twist never covers more than this (nav timeout order)
    STALE_S = 1.0

    def __init__(self, maxlen: int = 4000) -> None:
        self._samples: deque = deque(maxlen=maxlen)

    def clear(self) -> None:
        self._samples.clear()

    def record(self, now: float, linear: float, angular: float) -> None:
        if self._samples and now < self._samples[-1][0]:
            self._samples.clear()            # clock went backwards: trust nothing before
        self._samples.append((float(now), float(linear), float(angular)))

    def net_since(self, since: float, now: float) -> float:
        """Net forward metres issued from ``since`` to ``now`` (gaps count no travel)."""
        samples = [sample for sample in self._samples if sample[0] >= since]
        net = 0.0
        for index, (t, lin, _) in enumerate(samples):
            end = samples[index + 1][0] if index + 1 < len(samples) else now
            net += lin * max(0.0, min(end - t, self.MAX_DT_S))
        return net

    def last_forward_at(self) -> Optional[float]:
        """Time of the newest forward (linear > 0) issued twist, or None."""
        for t, lin, _ in reversed(self._samples):
            if lin > 0.0:
                return t
        return None

    def measure(self, now: float, window_s: float) -> tuple[Optional[float], Optional[float]]:
        samples = list(self._samples)
        if not samples or now - samples[-1][0] > self.STALE_S:
            return None, None
        forward = [t for t, lin, _ in samples if lin > 0.0]
        if not forward:
            return None, None
        start = forward[-1] - window_s
        net = yaw = 0.0
        for index, (t, lin, ang) in enumerate(samples):
            if t < start:
                continue
            end = samples[index + 1][0] if index + 1 < len(samples) else now
            dt = max(0.0, min(end - t, self.MAX_DT_S))
            net += lin * dt
            yaw += abs(ang) * dt
        return net, math.degrees(yaw)


class AnswerRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StuckRecovery:
    def __init__(self, events, config: LineFollowConfig, *,
                 new_id: Callable[[], str] = lambda: f"stuck-{uuid.uuid4().hex[:12]}") -> None:
        self._events = events
        self._config = config
        self._new_id = new_id
        self._id: Optional[str] = None
        self._last: Optional[StuckInput] = None
        # (stuck id, attempts, monotonic time) of the last `recovered` close: a stuck that
        # re-opens soon after, or before the robot drove on, is the same stuck (2026-10-02).
        self._recovered: Optional[tuple[str, int, float]] = None
        self._restuck_of: Optional[str] = None
        self._clear()

    def _clear(self) -> None:
        self._id = None
        self._cause: Optional[str] = None
        self._phase: Optional[str] = None
        self._opened_at = 0.0
        self._deadline: Optional[float] = None
        self._attempts = 0
        self._speed = 0.0
        self._until = 0.0
        self._angular = 0.0
        self._yield_m = 0.0
        self._last_answer: Optional[str] = None
        self._operator_required = False
        self._detail: Optional[str] = None

    @property
    def stuck_id(self) -> Optional[str]:
        return self._id

    @property
    def phase(self) -> Optional[str]:
        return self._phase

    @property
    def recovered_at(self) -> Optional[float]:
        return None if self._recovered is None else self._recovered[2]

    # ---- tick -----------------------------------------------------------------
    def step(self, inp: StuckInput) -> StuckAction:
        self._last = inp
        if self._id is not None and (inp.cause == CROSSWALK) != (self._cause == CROSSWALK):
            # D-573 4: the crosswalk gate's stuck never shares an id with another cause; a back-off
            # or yield in progress ends here (the gate holds the robot anyway).
            self._close("crosswalk_blocked" if inp.cause == CROSSWALK else "cleared", inp.now)
        if self._id is None:
            if inp.cause is None or inp.calibration_active:
                return StuckAction()
            self._open(inp)
        if self._cause == CROSSWALK:
            self._detail = inp.cause_detail
            return StuckAction("hold")
        if self._cause in (NO_MOTION, *REPORT_ONLY) and inp.cause is not None:
            self._detail = inp.cause_detail
        if self._phase == BACKING:
            return self._backing(inp)
        if self._phase in (TURNING, CRAWLING, YIELDED):
            # A finished yield stays off the paint. A cleared cause must not resume the line.
            return self._yielding(inp)
        if self._phase == SETTLING:
            return self._settling(inp)
        if inp.cause is None:
            # 스스로 풀렸다(앞 물체가 비켰다). 막힘 사건을 닫고 원래 결정대로 간다.
            self._close("cleared", inp.now)
            return StuckAction()
        if (self._phase == ASKING
                and (not inp.console_linked or inp.now >= (self._deadline or inp.now))):
            return self._local(inp, "no_console" if not inp.console_linked else "ask_timeout")
        return StuckAction("pass" if self._cause in REPORT_ONLY and self._last_answer is None else "hold")

    def reset(self, reason: str, now: float) -> None:
        if self._id is not None:
            self._close(reason, now)
        self._recovered = None               # a new line-follow session starts fresh

    def require_operator(self, inp: StuckInput) -> None:
        """Hold exhausted D-468 recovery for an operator while preserving current evidence."""
        self._last = inp
        if self._id is None:
            if inp.cause is None or inp.calibration_active:
                return
            self._open(inp, ask=False)
        self._operator_required = True  # D-468: no second autonomous back-off
        if self._phase == WAITING_CONSOLE:
            return  # already escalated: called every tick, ask once per stuck opening
        self._console_only("attempts_exhausted" if self._attempts >= self._config.recovery_max_attempts
                           else "local_candidates_exhausted", inp.now)

    # ---- console ----------------------------------------------------------------
    def answer(self, now: float, stuck_id: str, decision: str, by: str,
               principal_ref: Optional[str] = None, *,
               yield_m: Optional[float] = None, yield_turn_rad: Optional[float] = None) -> str:
        """Apply a console answer; returns hold | back | resume | manual | idle | yield."""
        if decision not in DECISIONS:
            raise AnswerRefused("VALIDATION_ERROR", f"unknown stuck decision {decision!r}")
        if self._id is None or stuck_id != self._id:
            self._answered(stuck_id, decision, by, principal_ref, False, "stuck_id_mismatch")
            raise AnswerRefused("STUCK_ID_MISMATCH",
                                "no open stuck with this id (late or wrong answer)")
        why = self._answer_refusal(decision, now, yield_m, yield_turn_rad)
        if why is not None:
            self._answered(stuck_id, decision, by, principal_ref, False, why,
                           evidence=self._last_or(now) if decision == "BACK_AND_RETRY" else None)
            raise AnswerRefused("STUCK_DECISION_REFUSED", f"{decision} refused: {why}")
        self._answered(stuck_id, decision, by, principal_ref, True, None)
        self._last_answer = decision
        if decision == "WAIT":
            if self._phase == YIELDED:
                return "hold"                     # already off the line; do not resume later
            if self._phase == BACKING:
                self._result("aborted", "console_wait")
            self._console_only("console_wait", now)
            return "hold"
        if decision == "YIELD":
            self._start_yield(self._last_or(now), now, float(yield_m), float(yield_turn_rad))
            return "yield"
        if decision == "BACK_AND_RETRY":
            self._start_back(replace(self._last_or(now), now=now), "console")
            return "back"
        reason = {"RESUME": "console_resume", "MANUAL": "console_manual",
                  "ABORT": "console_abort"}[decision]
        self._close(reason, now)
        return {"RESUME": "resume", "MANUAL": "manual", "ABORT": "idle"}[decision]

    def _answer_refusal(self, decision: str, now: float, yield_m: Optional[float] = None,
                        yield_turn_rad: Optional[float] = None) -> Optional[str]:
        last = self._last_or(now)
        if self._cause == CROSSWALK and decision not in CROSSWALK_DECISIONS:
            return "crosswalk_gate"           # D-573 4: no moving answer while a person may be there
        if self._operator_required and decision == "BACK_AND_RETRY":  # YIELD stays: operator-owned
            return "lane_return_fleet_required"
        if decision == "YIELD":
            # A lost reply may be resent; an active segment must never restart its timer.
            if self._phase in (TURNING, CRAWLING):
                return "yield_active"
            return self._yield_refusal(last, yield_m, yield_turn_rad)
        if decision == "RESUME":
            if last.scan_age_s is None and (last.lidar_expected or self._cause == "obstacle_ahead"):
                return "no_scan"
            if last.scan_age_s is not None and last.scan_age_s > self._config.clearance_stale_s:
                return "scan_stale"
            stop = self._config.sector_stop_m if last.front_stop_m is None else last.front_stop_m
            if last.front_band_m is not None and last.front_band_m < stop:
                return "object_within_stop_distance"
        if decision == "BACK_AND_RETRY":
            if not self._config.recovery_local_enabled:
                return "local_recovery_disabled"
            if self._attempts >= self._config.recovery_max_attempts:
                return "attempts_exhausted"
            return self._back_refusal(last)
        return None

    def _last_or(self, now: float) -> StuckInput:
        return self._last if self._last is not None else StuckInput(now=now)

    # ---- local recovery ---------------------------------------------------------
    def _yield_refusal(self, inp: StuckInput, yield_m: Optional[float],
                       yield_turn_rad: Optional[float]) -> Optional[str]:
        # The peer is in front until the turn finishes, so the front band is not a reason to refuse.
        unset = yield_m is None or yield_turn_rad is None
        if unset or not math.isfinite(yield_m) or not math.isfinite(yield_turn_rad):
            return "yield_unset"
        if not _YIELD_MIN_M <= yield_m <= _YIELD_MAX_M:
            return "yield_distance"
        if abs(yield_turn_rad) > math.pi + 1e-6:
            return "yield_turn"
        if inp.calibration_active:
            return "calibration_active"
        if not inp.geometry_known:
            return "body_geometry_unset"
        if inp.scan_age_s is None:
            return "no_scan"
        if inp.scan_age_s > self._config.clearance_stale_s:
            return "scan_stale"
        if min(inp.linear_ceiling, self._config.recovery_back_speed) <= 0.0:
            return "linear_limit_zero"
        if abs(yield_turn_rad) > _TURN_SKIP and (inp.turn_m is None or inp.turn_m < _TURN_CLEAR_M):
            return "turn_blocked"
        return None

    def _start_yield(self, inp: StuckInput, now: float, yield_m: float, yield_turn_rad: float) -> None:
        self._speed = min(inp.linear_ceiling, self._config.recovery_back_speed)
        self._yield_m = yield_m
        self._deadline = None
        if abs(yield_turn_rad) > _TURN_SKIP:
            self._phase = TURNING
            self._angular = math.copysign(_TURN_RATE, yield_turn_rad)
            self._until = now + abs(yield_turn_rad) / _TURN_RATE
        else:
            self._phase = CRAWLING
            self._angular = 0.0
            self._until = now + yield_m / self._speed

    def _yielding(self, inp: StuckInput) -> StuckAction:
        if self._phase == YIELDED:
            return StuckAction("hold")
        why = self._yield_live_refusal(inp)
        if why is not None:
            self._result("aborted", why, inp=inp)
            self._console_only("local_aborted", inp.now)
            return StuckAction("hold")
        if self._phase == TURNING:
            if inp.now >= self._until:
                self._phase = CRAWLING
                self._angular = 0.0
                self._until = inp.now + self._yield_m / self._speed
                return StuckAction("hold")
            return StuckAction("yield", 0.0, self._angular)
        if inp.now >= self._until:
            self._phase = YIELDED
            self._angular = 0.0
            return StuckAction("hold")
        return StuckAction("yield", self._speed, 0.0)

    def _yield_live_refusal(self, inp: StuckInput) -> Optional[str]:
        if inp.calibration_active:
            return "calibration_active"
        if not inp.geometry_known:
            return "body_geometry_unset"
        if inp.scan_age_s is None:
            return "no_scan"
        if inp.scan_age_s > self._config.clearance_stale_s:
            return "scan_stale"
        if self._phase == TURNING and (inp.turn_m is None or inp.turn_m < _TURN_CLEAR_M):
            return "turn_blocked"
        if self._phase == CRAWLING:
            stop = self._config.sector_stop_m if inp.front_stop_m is None else inp.front_stop_m
            if inp.front_band_m is not None and inp.front_band_m < stop:
                return "object_within_stop_distance"
            if self._speed <= 0.0:
                return "linear_limit_zero"
        return None

    def _back_refusal(self, inp: StuckInput, starting: bool = True) -> Optional[str]:
        config = self._config
        if inp.calibration_active:
            return "calibration_active"
        if not inp.geometry_known:
            return "body_geometry_unset"
        if inp.scan_age_s is None:
            return "no_scan"
        if inp.scan_age_s > config.clearance_stale_s:
            return "scan_stale"
        if inp.rear_blind_m is None:
            return "rear_blind"                # range_min unknown: the blind band is unknown
        if (inp.rear_blind_m > config.recovery_rear_clear_m and starting
                and not self._trail_covers(inp)):
            # 보이지 않는 뒤 띠는 방금 앞으로 지나온 길일 때만 들어간다(사용자 결정 2026-10-02).
            # 보이는 뒤 여유(rear_blocked)는 아래에서 전·중 계속 본다.
            return "rear_blind"
        if inp.rear_m is not None and inp.rear_m <= config.recovery_rear_clear_m:
            return "rear_blocked"
        if min(inp.linear_ceiling, config.recovery_back_speed) <= 0.0:
            return "linear_limit_zero"
        return None

    def _trail_covers(self, inp: StuckInput) -> bool:
        config = self._config
        # Decision 2026-10-02: the ground just driven is trusted only while the last forward
        # command is at most recovery_trail_max_age_s old (standing still for the console counts).
        return (inp.trail_m is not None and inp.trail_yaw_deg is not None
                and inp.trail_age_s is not None
                and inp.trail_age_s <= config.recovery_trail_max_age_s
                and inp.trail_m >= config.recovery_back_m
                and inp.trail_yaw_deg <= config.recovery_trail_yaw_deg)

    def _local(self, inp: StuckInput, trigger: str) -> StuckAction:
        if not self._config.recovery_local_enabled:
            self._console_only("local_disabled", inp.now)
            return StuckAction("hold")
        if self._attempts >= self._config.recovery_max_attempts:
            self._console_only("attempts_exhausted", inp.now)
            return StuckAction("hold")
        why = self._back_refusal(inp)
        if why is not None:
            self._result("refused", why, attempt=self._attempts, inp=inp)
            self._console_only("local_refused", inp.now)
            return StuckAction("hold")
        self._start_back(inp, trigger)
        return StuckAction("back", -self._speed)

    def _start_back(self, inp: StuckInput, trigger: str) -> None:
        config = self._config
        self._attempts += 1
        self._speed = min(inp.linear_ceiling, config.recovery_back_speed)
        self._until = inp.now + config.recovery_back_m / self._speed
        self._phase = BACKING
        self._deadline = None
        self._events.publish(
            "nav.line_stuck_local_attempt", severity="warning", source=_SOURCE,
            data={"stuck_id": self._id, "attempt": self._attempts, "trigger": trigger,
                  "back_m": config.recovery_back_m, "speed_mps": self._speed,
                  "rear_clearance_m": inp.rear_m, "rear_blind_m": inp.rear_blind_m,
                  "trail_m": inp.trail_m, "trail_age_s": inp.trail_age_s},
        )

    def _backing(self, inp: StuckInput) -> StuckAction:
        # The trail was checked at the start for the whole recovery_back_m; it shrinks as
        # the robot backs over it, so only the live checks repeat here.
        why = self._back_refusal(inp, starting=False)
        if why is not None:
            # 후진 중에도 뒤 여유·scan 신선도를 본다. 하나라도 어긋나면 즉시 0.
            self._result("aborted", why, inp=inp)
            self._console_only("local_aborted", inp.now)
            return StuckAction("hold")
        if inp.now >= self._until:
            self._phase = SETTLING
            self._until = inp.now + self._config.recovery_settle_s
            return StuckAction("hold")
        return StuckAction("back", -self._speed)

    def _settling(self, inp: StuckInput) -> StuckAction:
        if inp.now < self._until:
            return StuckAction("hold")
        if inp.lane_visible and inp.front_clear:
            self._result("recovered", None, lane=inp.lane_visible, front=inp.front_clear)
            self._close("recovered", inp.now)
            return StuckAction("resume")
        self._result("still_stuck", None, lane=inp.lane_visible, front=inp.front_clear)
        return self._local(inp, "retry")

    # ---- events -----------------------------------------------------------------
    def _open(self, inp: StuckInput, ask: bool = True) -> None:
        self._clear()
        self._id = self._new_id()
        self._cause = inp.cause
        self._detail = inp.cause_detail
        self._opened_at = inp.now
        self._restuck_of = None
        if self._recovered is not None:
            previous, attempts, at = self._recovered
            moved = inp.moved_since_recovery_m
            if (inp.now - at < self._config.recovery_restuck_s
                    or moved is None or moved < self._config.recovery_restuck_m):
                # Clarification 2026-10-02: the same stuck for attempt counting, so a
                # recover -> re-stuck cycle cannot back off forever.
                self._attempts = attempts
                self._restuck_of = previous
            self._recovered = None
        self._events.publish(
            "nav.line_stuck_opened", severity="warning", source=_SOURCE,
            data={"stuck_id": self._id, "cause": inp.cause,
                  "front_clearance_m": inp.front_band_m, "rear_clearance_m": inp.rear_m,
                  "turn_clearance_m": inp.turn_m, "rear_blind_m": inp.rear_blind_m,
                  "rear_state": inp.rear_state, "last_lane": inp.last_lane, "preview_seq": inp.preview_seq,
                  "restuck_of": self._restuck_of, "attempts": self._attempts,
                  **({"detail": inp.cause_detail} if inp.cause in (CROSSWALK, NO_MOTION, *REPORT_ONLY) else {})},
        )
        if not ask:
            return
        if inp.cause in (CROSSWALK, NO_MOTION, *REPORT_ONLY):  # no local back-off, no ASKING fallback
            self._console_only("crosswalk_gate" if inp.cause == CROSSWALK else inp.cause, inp.now)
            return
        if self._attempts >= self._config.recovery_max_attempts:
            self._console_only("attempts_exhausted", inp.now)
            return
        if not self._config.recovery_local_enabled:
            self._console_only("local_disabled", inp.now)  # no ASKING: one ask, no local fallback
            return
        self._phase = ASKING
        self._deadline = inp.now + self._config.recovery_ask_s
        self._asked(inp.console_linked, self._config.recovery_ask_s, "opened")

    def _console_only(self, reason: str, now: float) -> None:
        self._phase = WAITING_CONSOLE
        self._deadline = None
        linked = self._last.console_linked if self._last is not None else False
        self._asked(linked, None, reason)

    def _asked(self, linked: bool, fallback_s: Optional[float], reason: str) -> None:
        self._events.publish(
            "nav.line_stuck_asked", source=_SOURCE,
            data={"stuck_id": self._id, "cause": self._cause, "console_linked": linked,
                  "local_fallback_s": fallback_s, "attempts": self._attempts,
                  "reason": reason,
                  "decisions": list(self._decisions())},
        )

    def _answered(self, stuck_id: str, decision: str, by: str, principal_ref: Optional[str],
                  accepted: bool, reason: Optional[str],
                  evidence: Optional[StuckInput] = None) -> None:
        # principal_ref: the CORE token *record id* (configured id or digest[:12], already public
        # in the token list), never the secret. A key named like a credential ("token_id") was
        # refused by Fleet's audit store (EVENT_NOT_AUDITABLE, D-407 re-run 2026-10-02).
        # evidence: the scan a refused BACK_AND_RETRY was judged on, so the console sees why.
        self._events.publish(
            "nav.line_stuck_answered", source=_SOURCE,
            data={"stuck_id": stuck_id, "decision": decision, "by": by,
                  "principal_ref": principal_ref, "accepted": accepted, "reason": reason,
                  "rear_blind_m": None if evidence is None else evidence.rear_blind_m,
                  "trail_m": None if evidence is None else evidence.trail_m,
                  "trail_yaw_deg": None if evidence is None else evidence.trail_yaw_deg,
                  "trail_age_s": None if evidence is None else evidence.trail_age_s},
        )

    def _result(self, result: str, reason: Optional[str], *, attempt: Optional[int] = None,
                lane: Optional[bool] = None, front: Optional[bool] = None,
                inp: Optional[StuckInput] = None) -> None:
        # inp: the scan the refusal / abort was judged on (rear value, blind band, trail).
        self._events.publish(
            "nav.line_stuck_local_result", source=_SOURCE,
            data={"stuck_id": self._id,
                  "attempt": self._attempts if attempt is None else attempt,
                  "result": result, "reason": reason,
                  "lane_visible": lane, "front_clear": front,
                  "rear_clearance_m": None if inp is None else inp.rear_m,
                  "rear_blind_m": None if inp is None else inp.rear_blind_m,
                  "trail_m": None if inp is None else inp.trail_m,
                  "trail_yaw_deg": None if inp is None else inp.trail_yaw_deg,
                  "trail_age_s": None if inp is None else inp.trail_age_s},
        )

    def _close(self, reason: str, now: float) -> None:
        if reason == "recovered":
            self._recovered = (self._id, self._attempts, now)
        self._events.publish(
            "nav.line_stuck_closed", source=_SOURCE,
            data={"stuck_id": self._id, "cause": self._cause, "reason": reason,
                  "attempts": self._attempts, "held_s": round(now - self._opened_at, 2)},
        )
        self._clear()

    def status(self, now: float) -> Optional[dict]:
        if self._id is None:
            return None
        remaining = None if self._deadline is None else round(max(0.0, self._deadline - now), 2)
        return {
            "stuck_id": self._id, "cause": self._cause, "phase": self._phase,
            "held_s": round(max(0.0, now - self._opened_at), 2),
            "attempts": self._attempts, "max_attempts": self._config.recovery_max_attempts,
            "local_enabled": self._config.recovery_local_enabled,
            "ask_remaining_s": remaining, "last_answer": self._last_answer,
            "decisions": list(self._decisions()),
            **({"detail": self._detail} if self._cause in (CROSSWALK, NO_MOTION, *REPORT_ONLY) else {}),
        }

    def _decisions(self) -> tuple:
        return CROSSWALK_DECISIONS if self._cause == CROSSWALK else DECISIONS
