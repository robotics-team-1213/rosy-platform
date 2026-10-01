"""core_features.localization.assist — D-395 P2-1/P2-4, CORE's view of the robot node.

Contract: docs/plans/2026-10-01-d395-phase2-interfaces.md §1. The sensing node
(`loc_assist_node`) owns the state machine; CORE only relays. Inbound, the bridge
hands this class the raw JSON of `localization/state`, `localization/candidates`
and `localization/result`. Outbound, the API calls `decide`/`suspect` and the
bridge-bound callables put the JSON on `localization/decision|suspect`.

Two rules are CORE's own:
- `pose_frame` is honest about the snapshot pose. While CORE substitutes odom for
  the map pose (`core.bridge.odometry.odom_owns_pose`), the frame is `odom` even if
  the robot says `map`. CORE never upgrades an `odom` claim to `map`.
- A sensing node that goes quiet fails closed: after `STATE_STALE_S` the status
  reads UNKNOWN (`state_stale`), so navigation stays refused.

No `localization/state` yet means a robot that predates D-395: `status()` is None
and every caller keeps today's behaviour.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator

from core_common.protocol.localization import (
    CandidateReport,
    DecisionSource,
    LocalizationDecision,
    LocalizationStatus,
    LocState,
    MapPose,
    PoseFrame,
    _request_id,
)

#: 2 Hz state from the robot; this many seconds of silence reads as UNKNOWN.
STATE_STALE_S = 3.0
#: Decisions remembered so a result event can name its source and cues.
_KEEP_DECISIONS = 16
#: A topic message larger than this is dropped unparsed.
MAX_RAW_BYTES = 64 * 1024

_log = logging.getLogger(__name__)


def _load(raw: str) -> Optional[dict]:
    if not isinstance(raw, str) or len(raw) > MAX_RAW_BYTES or len(raw.encode("utf-8")) > MAX_RAW_BYTES:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _rejected(what: str, exc: ValidationError) -> None:
    """Log the rejection without the payload: the exception type and error kinds only."""
    _log.warning("ignored %s: %s %s", what, type(exc).__name__,
                 sorted({error["type"] for error in exc.errors(include_input=False)}))


class _Result(BaseModel):
    """`localization/result` (contract §1)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    request_id: str
    accepted: StrictBool
    reason: Optional[str] = Field(default=None, max_length=64)
    state: LocState

    @field_validator("request_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _request_id(value)


class LocalizationAssist:
    def __init__(self, events, robot_id: Callable[[], str], *,
                 monotonic: Callable[[], float] = time.monotonic,
                 on_localized: Optional[Callable[[], None]] = None,
                 on_lost: Optional[Callable[[], None]] = None) -> None:
        self._events = events
        self._robot_id = robot_id
        self._monotonic = monotonic
        #: `received_s` clock; the bridge binds the ROS clock (contract §1).
        self.clock: Callable[[], float] = time.time
        #: Bound by the bridge to the `localization/decision|suspect` publishers.
        self.publish_decision: Optional[Callable[[dict], None]] = None
        self.publish_suspect: Optional[Callable[[dict], None]] = None
        #: CORE's navigation cancel path, run on LOCALIZED (D-395 §7).
        self.on_localized = on_localized
        #: CORE's stop paths, run when the state leaves LOCALIZED (D-395 §2: autonomy only there).
        self.on_lost = on_lost
        self._lock = threading.Lock()
        #: Orders the leave-LOCALIZED halt against every motion start: a start holds
        #: it from its LOCALIZED check to its dispatch; a state change holds it while
        #: it lands and runs the halt. Taken before any manager lock.
        self.gate = threading.RLock()
        self._status: Optional[LocalizationStatus] = None
        self._status_at = 0.0
        self._odom_owns_pose = False
        self._report: Optional[CandidateReport] = None
        self._emitted: Optional[LocState] = None
        self._decisions: "OrderedDict[str, tuple[str, list[str]]]" = OrderedDict()

    def bind_clock(self, clock: Callable[[], float]) -> None:
        """The stale window's clock: the bridge's line clock, i.e. the ROS (sim) clock
        under `use_sim_time`, else monotonic. The robot node publishes its state on
        its own node clock, so a wall-time window flaps below RTF ~0.17 (D-395 S1
        finding 6). `received_s` stays on `clock`, the robot node's ROS clock."""
        with self._lock:
            self._monotonic = clock

    # --- read side ----------------------------------------------------------

    @property
    def reporting(self) -> bool:
        with self._lock:
            return self._status is not None

    def status(self) -> Optional[LocalizationStatus]:
        with self._lock:
            return self._effective()

    def _effective(self) -> Optional[LocalizationStatus]:
        """The caller holds the lock."""
        status = self._status
        if status is None:
            return None
        if self._monotonic() - self._status_at > STATE_STALE_S:
            status = LocalizationStatus(state=LocState.UNKNOWN, pose_frame=status.pose_frame,
                                        reason="state_stale")
        if self._odom_owns_pose and status.pose_frame is PoseFrame.MAP:
            status = status.model_copy(update={"pose_frame": PoseFrame.ODOM})
        return status

    def autonomy_allowed(self) -> bool:
        """D-395: LOCALIZED with a map-frame pose, or a robot that predates D-395."""
        status = self.status()
        return status is None or (status.state is LocState.LOCALIZED
                                  and status.pose_frame is PoseFrame.MAP)

    def candidates(self) -> Optional[CandidateReport]:
        """The latest report, only while it answers the robot's open request."""
        with self._lock:
            status, report = self._effective(), self._report
        if status is None or report is None or status.state is not LocState.CANDIDATES:
            return None
        if status.request_id is not None and status.request_id != report.request_id:
            return None
        return report

    # --- robot -> CORE ------------------------------------------------------

    def on_state(self, raw: str) -> None:
        data = _load(raw)
        try:
            status = LocalizationStatus.model_validate((data or {}).get("status"))
        except ValidationError as exc:
            _rejected("localization state", exc)
            return
        with self.gate:
            with self._lock:
                self._status = status
                self._status_at = self._monotonic()
            self._after_change()

    def tick(self, odom_owns_pose: bool) -> None:
        """State-timer hook: the frame flag and the stale timeout move here."""
        with self.gate:
            with self._lock:
                self._odom_owns_pose = bool(odom_owns_pose)
            self._after_change()

    def _after_change(self) -> None:
        with self._lock:
            status, previous = self._effective(), self._emitted
            if status is None or status.state is previous:
                return
            self._emitted = status.state
        self._events.publish("localization.state", source="localization", data={
            "state": status.state.value,
            "previous": previous.value if previous is not None else None,
            "pose_frame": status.pose_frame.value,
            "reason": status.reason,
            "request_id": status.request_id,
        })
        if status.state is LocState.LOCALIZED:
            self._cancel_navigation()
        elif previous is LocState.LOCALIZED:
            self._run(self.on_lost, "autonomy stop on leaving LOCALIZED")

    def on_candidates(self, raw: str) -> None:
        data = _load(raw)
        try:
            report = CandidateReport.model_validate({**(data or {}), "robot_id": self._robot_id()})
        except ValidationError as exc:
            _rejected("candidate report", exc)
            return
        with self._lock:
            new = self._report is None or self._report.request_id != report.request_id
            self._report = report
        if new:
            self._events.publish("localization.candidates", source="localization", data={
                "request_id": report.request_id,
                "count": len(report.candidates),
                "pickup": report.pickup,
            })

    def on_result(self, raw: str) -> None:
        try:
            result = _Result.model_validate(_load(raw))
        except ValidationError as exc:
            _rejected("localization result", exc)
            return
        request_id, accepted, reason = result.request_id, result.accepted, result.reason
        state = result.state.value
        with self._lock:
            source, cues = self._decisions.get(request_id, (None, []))
        self._events.publish("localization.result", source="localization", data={
            "request_id": request_id,
            "accepted": accepted,
            "reason": reason,
            "state": state,
            "source": source,
            "cues": list(cues),
        })
        if accepted:
            self._cancel_navigation()

    def _cancel_navigation(self) -> None:
        self._run(self.on_localized, "navigation cancel on localization")

    @staticmethod
    def _run(hook: Optional[Callable[[], None]], what: str) -> None:
        if hook is None:
            return
        try:
            hook()
        except Exception:  # a failed stop must not stop the state feed
            _log.exception("%s failed", what)

    # --- CORE -> robot ------------------------------------------------------

    def is_stale(self, decision: LocalizationDecision) -> bool:
        """True when CORE already knows `request_id` is not the open one (§2, 409)."""
        status = self.status()
        if status is None:
            return False
        if status.state is LocState.CANDIDATES and status.request_id is not None:
            return status.request_id != decision.request_id
        # No open request: a candidate index points at nothing. A direct pose
        # (human, overhead, homing) still goes to the robot, which checks it.
        return status.state is not LocState.CANDIDATES and decision.source is DecisionSource.CANDIDATE

    def human_decision(self, x: float, y: float, yaw: float) -> LocalizationDecision:
        """The legacy initial pose, read as `source: human` (contract §1)."""
        status = self.status()
        open_id = status.request_id if status is not None and status.state is LocState.CANDIDATES else None
        return LocalizationDecision(
            request_id=open_id or f"human-{int(self.clock() * 1000)}",
            pose=MapPose(x=x, y=y, yaw=yaw), source=DecisionSource.HUMAN)

    def decide(self, decision: LocalizationDecision) -> None:
        send = self.publish_decision
        if send is None:
            raise RuntimeError("localization decision transport unavailable")
        payload: dict[str, Any] = {"decision": decision.model_dump(mode="json"),
                                   "received_s": self.clock()}
        with self._lock:
            self._decisions[decision.request_id] = (
                decision.source.value, [cue.value for cue in decision.cues])
            self._decisions.move_to_end(decision.request_id)
            while len(self._decisions) > _KEEP_DECISIONS:
                self._decisions.popitem(last=False)
        send(payload)

    def suspect(self, reason: str) -> None:
        send = self.publish_suspect
        if send is None:
            raise RuntimeError("localization suspect transport unavailable")
        send({"reason": reason})
