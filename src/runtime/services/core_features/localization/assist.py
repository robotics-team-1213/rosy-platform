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

from pydantic import ValidationError

from core_common.protocol.localization import (
    CandidateReport,
    DecisionSource,
    LocalizationDecision,
    LocalizationStatus,
    LocState,
    MapPose,
    PoseFrame,
)

#: 2 Hz state from the robot; this many seconds of silence reads as UNKNOWN.
STATE_STALE_S = 3.0
#: Decisions remembered so a result event can name its source and cues.
_KEEP_DECISIONS = 16

_log = logging.getLogger(__name__)


def _load(raw: str) -> Optional[dict]:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class LocalizationAssist:
    def __init__(self, events, robot_id: Callable[[], str], *,
                 monotonic: Callable[[], float] = time.monotonic,
                 on_localized: Optional[Callable[[], None]] = None) -> None:
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
        self._lock = threading.Lock()
        self._status: Optional[LocalizationStatus] = None
        self._status_at = 0.0
        self._odom_owns_pose = False
        self._report: Optional[CandidateReport] = None
        self._emitted: Optional[LocState] = None
        self._decisions: "OrderedDict[str, tuple[str, list[str]]]" = OrderedDict()

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
            _log.warning("ignored localization state: %s", exc.errors()[:1])
            return
        with self._lock:
            self._status = status
            self._status_at = self._monotonic()
        self._after_change()

    def tick(self, odom_owns_pose: bool) -> None:
        """State-timer hook: the frame flag and the stale timeout move here."""
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

    def on_candidates(self, raw: str) -> None:
        data = _load(raw)
        try:
            report = CandidateReport.model_validate({**(data or {}), "robot_id": self._robot_id()})
        except ValidationError as exc:
            _log.warning("ignored candidate report: %s", exc.errors()[:1])
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
        data = _load(raw) or {}
        request_id, accepted = data.get("request_id"), data.get("accepted")
        state = data.get("state")
        reason = data.get("reason")
        if (not isinstance(request_id, str) or not isinstance(accepted, bool)
                or state not in {item.value for item in LocState}
                or not (reason is None or isinstance(reason, str))):
            _log.warning("ignored localization result: %r", data)
            return
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
        hook = self.on_localized
        if hook is None:
            return
        try:
            hook()
        except Exception:  # a failed cancel must not stop the state feed
            _log.exception("navigation cancel on localization failed")

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
