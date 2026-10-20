"""Bounded observations of G2 uncertainty; never changes command or HOLD decisions."""
from collections import deque
from collections.abc import Mapping
from hashlib import sha256
from itertools import islice
import json
import math
from pathlib import Path
from queue import Empty, Queue
import sys
import threading
import time

from g2_ports import write_json

_KINDS = frozenset({"TERMINAL_UNKNOWN", "GOAL_ACCEPTANCE_UNKNOWN"})
_WATCHDOG_REASONS = frozenset({"action_timeout", "joint_state_stale", "action_wall_timeout",
                              "joint_state_stale_wall_clock"})


def _text(value, limit=160):
    return value[:limit] if isinstance(value, str) else None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _integer(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _decision(value):
    if value is None:
        return None
    return {"accepted": value.accepted if type(getattr(value, "accepted", None)) is bool else None,
            "state": _text(getattr(value, "state", None), 32),
            "reason": _text(getattr(value, "reason", None)),
            "command_id": _text(getattr(value, "command_id", None), 256),
            "cancel_outcome": _text(getattr(value, "cancel_outcome", None), 64)}


def _intake_facts(value):
    if type(value) is not dict:
        return None
    result = {key: _integer(value.get(key)) for key in
              ("stamp_ns", "source_now_ns", "prior_accepted_stamp_ns")}
    result.update({key: _number(value.get(key)) for key in ("received_at", "wall_received_at")})
    result["accepted"] = value.get("accepted") if type(value.get("accepted")) is bool else None
    for key, allowed in (("rejection_code", {"STAMP_REJECTED", "SOURCE_STALE", "ARRAY_SHAPE", "NONFINITE", "INPUT_INVALID"}),
                         ("error_type", {"TypeError", "ValueError", "OverflowError"})):
        item = value.get(key)
        if type(item) is str and item in allowed:
            result[key] = item
    return result


def _decision_intake(value):
    if value is None:
        return None
    result = {key: _integer(getattr(value, key, None)) for key in
              ("stamp_ns", "source_now_ns", "intake_sequence")}
    for key in ("received_at", "callback_entered_steady", "intake_received_steady", "intake_observed_steady"):
        number = getattr(value, key, None)
        result[key] = (number if type(number) in (int, float) and abs(number) <= 2**63 - 1 else None)
    accepted = getattr(value, "accepted", None)
    result["accepted"] = accepted if type(accepted) is bool else None
    code = getattr(value, "rejection_code", None)
    codes = {"STAMP_REJECTED", "SOURCE_STALE", "ARRAY_SHAPE", "NONFINITE", "INPUT_INVALID"}
    result["rejection_code"] = code if type(code) is str and code in codes else None
    return result


def _watchdog_transition(value, command_id):
    if value is None:
        return None
    result = {key: _number(getattr(value, key, None)) for key in
              ("owner_now", "owner_now_steady_before", "owner_now_steady_after", "steady_now",
               "joint_received_at", "source_age_s", "joint_wall",
               "active_started_at", "active_wall", "wall_now", "max_joint_state_age_s",
               "action_timeout_s", "wall_clock_bound_factor")}
    reason = getattr(value, "reason", None)
    result["reason"] = (reason if type(reason) is str
                        and reason in _WATCHDOG_REASONS | {"owner_clock_jumped_back"} else None)
    captured_command = getattr(value, "command_id", None)
    result["command_id"] = _text(captured_command, 256)
    truncated = getattr(value, "command_id_truncated", None)
    result["command_id_truncated"] = truncated if type(truncated) is bool else None
    result["joint_sequence"] = _integer(getattr(value, "joint_sequence", None))
    result["intake"] = _decision_intake(getattr(value, "intake", None))
    result["matches_event_command"] = (truncated is False and type(captured_command) is str
                                       and len(captured_command) <= 256 and captured_command == command_id)
    return result


def _failure(code, error_type=None):
    # Never print an exception message or repr: it may include arbitrary private input.
    try:
        print(json.dumps({"event": "G2_TERMINAL_DIAGNOSTIC_FAILED", "code": code,
                          "error_type": error_type}),
              file=sys.stderr, flush=True)
    except Exception:
        pass  # Diagnostic failure cannot become another command callback failure.


class TerminalDiagnostics:
    def __init__(self, directory, *, wall_clock=time.time, steady_clock=time.monotonic, max_records=64):
        if type(max_records) is not int or not 1 <= max_records <= 64:
            raise ValueError("G2 terminal record limit must be between 1 and 64")
        self.directory = Path(directory)
        self.wall_clock, self.steady_clock = wall_clock, steady_clock
        self.max_records = max_records
        self._seen, self._lock, self._limit_reported = set(), threading.Lock(), False
        self._queue, self._closing = Queue(maxsize=max_records), threading.Event()
        self._failures, self.last_failure = deque(maxlen=8), None
        self._writer = threading.Thread(target=self._write_pending, name="g2-terminal-evidence", daemon=True)
        self._writer.start()

    def observe(self, event, runtime):
        """Return enqueue success; asynchronous write failures are separately visible."""
        if getattr(event, "kind", None) not in _KINDS:
            return True
        try:
            command, goal = event.command_id, event.goal_id
            if (not isinstance(command, str) or not 1 <= len(command) <= 256
                    or (goal is not None and (not isinstance(goal, str) or not 1 <= len(goal) <= 64))):
                raise ValueError("event identity exceeds diagnostic bounds")
            identity = sha256(json.dumps([command, goal], separators=(",", ":")).encode()).hexdigest()
            if not self._lock.acquire(blocking=False):
                self.report_failure("SNAPSHOT_BUSY")
                return False
            try:
                if identity in self._seen:
                    return True
                if self._closing.is_set():
                    self.report_failure("RECORDER_CLOSED")
                    return False
                if len(self._seen) >= self.max_records:
                    if not self._limit_reported:
                        self._limit_reported = True
                        self.report_failure("RECORD_LIMIT")
                    return False
                # A failed diagnostic is attempted once too; never flood the ROS callback/log.
                self._seen.add(identity)
                payload = self._snapshot(event, runtime)
                if len(json.dumps(payload, sort_keys=True, allow_nan=False).encode()) > 16384:
                    self.report_failure("PAYLOAD_LIMIT")
                    return False
                self._queue.put_nowait((identity, payload))
                return True
            finally:
                self._lock.release()
        except Exception as error:
            self.report_failure("SNAPSHOT_OR_WRITE_FAILED", error)
            return False

    def report_failure(self, code, error=None):
        """Bounded best-effort telemetry; callback and close paths never flush stderr."""
        try:
            record = (_text(code, 64), type(error).__name__[:80] if error is not None else None)
            self.last_failure = {"code": record[0], "error_type": record[1]}
            self._failures.append(record)
        except Exception:
            pass

    def _write_pending(self):
        while True:
            while True:
                try:
                    code, error_type = self._failures.popleft()
                except IndexError:
                    break
                _failure(code, error_type)  # Only this daemon may perform stderr I/O.
            try:
                identity, payload = self._queue.get(timeout=.05)
            except Empty:
                if self._closing.is_set() and not self._failures:
                    return
                continue
            try:
                self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                write_json(self.directory / (identity + ".json"), payload)
            except Exception as error:
                self.report_failure("SNAPSHOT_OR_WRITE_FAILED", error)
            finally:
                self._queue.task_done()

    def close(self, *, timeout=.5):
        """Bound shutdown even when the daemon writer is blocked in filesystem I/O."""
        timeout = min(max(_number(timeout) or 0, 0), 1.0)
        deadline = time.monotonic() + timeout
        if not self._lock.acquire(timeout=timeout):
            self.report_failure("DRAIN_SNAPSHOT_BUSY")
            return False
        try:
            self._closing.set()
        finally:
            self._lock.release()
        self._writer.join(max(0, deadline - time.monotonic()))
        if self._writer.is_alive():
            self.report_failure("DRAIN_TIMEOUT")
            return False
        return True

    def _snapshot(self, event, runtime):
        current = _decision(getattr(runtime, "last_decision", None))
        previous = _decision(getattr(runtime, "last_terminal_decision", None))
        owner = runtime.owner
        owner_joint = getattr(owner, "_joint_state", None)
        intake = getattr(runtime, "_joint_state_intake", None)
        latest = runtime.latest_joint_state
        joint = None
        if latest is not None:
            positions = latest.positions
            if not isinstance(positions, Mapping):
                raise TypeError("joint positions require a mapping")
            joint = {"sequence": _integer(latest.sequence), "received_at": _number(latest.received_at),
                     "positions": {name: _number(position) for name, position in islice(positions.items(), 32)
                                   if isinstance(name, str) and 0 < len(name) <= 64},
                     "positions_truncated": len(positions) > 32}
        handle = getattr(getattr(runtime, "action_port", None), "last_handle", None)
        handle_snapshot = None
        if handle is not None:
            done, acknowledged = getattr(handle, "_done", None), getattr(handle, "_cancel_acknowledged", None)
            handle_snapshot = {"done": done if type(done) is bool else None,
                               "status": _integer(getattr(handle, "_status", None)),
                               "cancel_acknowledged": acknowledged if type(acknowledged) is bool else None}
        watchdog = (event.kind == "TERMINAL_UNKNOWN" and current is not None
                    and current["state"] == "hold" and current["command_id"] == event.command_id
                    and current["reason"] in _WATCHDOG_REASONS)
        return {"schema": "rosy.g2-terminal-diagnostic/1", "snapshot_atomic": False,
                "producer_identity": "UNPROVEN",  # Concurrent snapshots do not identify a Python call stack.
                "cause_classification": "WATCHDOG_DECISION" if watchdog else "UNRESOLVED_ROS_EVENT",
                "event": {"kind": event.kind, "command_id": event.command_id,
                          "phase_id": _text(event.phase_id, 64), "goal_id": event.goal_id,
                          "sequence": _integer(event.sequence),
                          "observed_at_monotonic_s": _number(event.observed_at_monotonic_s)},
                "last_decision": current, "last_terminal_decision": previous,
                "watchdog_transition": _watchdog_transition(
                    getattr(owner, "watchdog_observation", None), event.command_id),
                "owner_state": _text(getattr(owner, "_state", None), 32),
                "owner_reason": _text(getattr(owner, "_hold_reason", None)),
                "clocks": {"owner_clock": _text(runtime.owner_clock, 16),
                           "owner": _number(runtime.monotonic()), "steady": _number(self.steady_clock()),
                           "wall": _number(self.wall_clock())},
                "joint_state": joint, "owner_joint_state_wall": _number(getattr(owner, "_joint_state_wall", None)),
                "owner_joint_state": None if owner_joint is None else {
                    "sequence": _integer(getattr(owner_joint, "sequence", None)),
                    "received_at": _number(getattr(owner_joint, "received_at", None))},
                "intake_last_attempt": _intake_facts(getattr(intake, "last_attempt", None)),
                "intake_last_rejection": _intake_facts(getattr(intake, "last_rejection", None)),
                "intake_counts": {key: _integer(getattr(intake, key, None)) for key in
                                  ("attempt_count", "accepted_count", "rejected_count")},
                "bounds": {key: _number(getattr(getattr(owner, "config", None), key, None)) for key in
                           ("max_joint_state_age_s", "action_timeout_s", "wall_clock_bound_factor",
                            "max_goal_duration_s")},
                "last_source_stamp_ns": _integer(getattr(getattr(runtime, "_joint_state_intake", None),
                                                        "_last_stamp_ns", None)),
                "handle": handle_snapshot}


def dispatch_g2_event(event, *, holder, diagnostics):
    """The ROS runtime calls this observer after the canonical phase sink has run."""
    try:
        pilot = holder.get("pilot")
        if pilot is not None:
            pilot.on_goal_event(event)
    finally:
        try:
            owner = holder.get("owner")
            if owner is not None:
                diagnostics.observe(event, owner.runtime)
            elif getattr(event, "kind", None) in _KINDS:
                diagnostics.report_failure("RUNTIME_UNAVAILABLE")
        except Exception as error:
            diagnostics.report_failure("OBSERVER_FAILED", error)
