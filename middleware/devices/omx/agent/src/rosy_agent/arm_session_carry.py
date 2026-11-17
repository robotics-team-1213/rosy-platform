"""D-977 Decision 4 (2026-11-17): the hardware owner runs an ARM_TRANSFER as the field FOLDED carry on the arm session.

The motion session (chunk_runner under session_lock) is its own process and the only bus writer; this owner never opens
serial. ``Carry.run`` is the field ``transfer_folded``; it sends its commands through ``_PhaseCell``, which writes each of
the four phases (approach, grasp, transfer, release) to the phase journal *before* the phase's first command and its
SUCCEEDED/FAILED only from that step's own result. Cancel, a lost fence and the deadline all end in ``Carry.fold`` (park
through the session FIFO): the session is never signalled and torque is never cut with the arm extended (D-911). A fold
in progress is never interrupted. Seconds below are proposals from repo constants (Fleet poll 0.25 s, FifoCell 300 s), not
measurements.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import threading
import time
from types import SimpleNamespace
from typing import Callable

from omx_adapter.installed_transfer_factory import InstalledArmTransferFactory

_LOG = logging.getLogger(__name__)
PHASES = ("approach", "grasp", "transfer", "release")
PHASE_LENGTHS = (3, 2, 3, 3)  # load+goto+descend | grasp+lift | park+goto+descend | release+lift+park
RESULT_SOURCE = "omx-session-step"
POLL_S, FENCE_LOSS_S, DEADLINE_S = 0.25, 3.0, 300.0


class CarryRefused(RuntimeError):
    """The carry cannot start; nothing moved."""


@dataclass(frozen=True)
class Carry:
    cell: object                      # act(command) -> status dict: the checked gate on the session
    run: Callable[[object], dict]     # the field transfer_folded, given the cell to send through
    fold: Callable[[], dict]          # park through the session FIFO
    sequence: tuple                   # the ten FOLDED commands run() sends after `load`


@dataclass(frozen=True)
class ArmGoals:
    """What a device_trial hardware owner needs to accept ARM_TRANSFER (built from a local config)."""
    installation: object              # rosy_agent.arm_transfer.ArmTransferInstallation
    open_carry: Callable[[object], Carry]
    timing: dict | None = None


def _ok(status) -> bool:
    return isinstance(status, dict) and status.get("ok") is True and not status.get("contact") and not status.get("fault")


def _final_ok(status) -> bool:
    """The last park must report settled, and the jaw reading the release check judges must exist (else it could not run)."""
    state = status.get("state")
    return (_ok(status) and status.get("settled") is True
            and isinstance(state, (list, tuple)) and len(state) > 5 and state[5] is not None)


def _accepted(status) -> bool | None:
    """Did the session take the command (True), refuse it (False), or is it unknown (None)?"""
    error = status.get("error") or ""
    if status.get("fault") == "no runner" or (not status.get("ok") and not status.get("contact")
                                              and not status.get("fault") and "no status" not in error):
        return False
    return None if "no status" in error else True


class SessionCarryExecution:
    def __init__(self, grant, recorder, carry: Carry, *, fence: Callable[[int, int], bool],
                 complete_if_current: Callable, poll_s=POLL_S, fence_loss_s=FENCE_LOSS_S, deadline_s=DEADLINE_S,
                 clock=time.monotonic):
        if len(carry.sequence) != sum(PHASE_LENGTHS) - 1:
            raise ValueError("the carry sequence does not fit the four ARM_TRANSFER phases")
        self.grant, self.recorder, self.carry, self.fence = grant, recorder, carry, fence
        self.complete_if_current, self.poll_s, self.fence_loss_s = complete_if_current, poll_s, fence_loss_s
        self.deadline_s, self.clock = deadline_s, clock
        self._plan = ("load", *carry.sequence)
        self._phase_of = [i for i, n in enumerate(PHASE_LENGTHS) for _ in range(n)]
        self._ptr, self._failed, self._pending, self._statuses = 0, None, None, []
        self._current = None              # phase id begun and not yet terminal
        self._seq, self._hold_seq, self._release_seq = 0, None, None
        self._journal, self._abort_lock = threading.RLock(), threading.Lock()
        self._aborting = False
        self.aborted, self._folding, self._done = threading.Event(), threading.Event(), threading.Event()

    @property
    def active_phase_id(self):
        return self._current

    def start(self):
        threading.Thread(target=self._run, name="arm-session-carry", daemon=True).start()
        threading.Thread(target=self._watch, name="arm-session-watchdog", daemon=True).start()
        return {"started": True}

    def cancel_current(self):
        """Fold through the session FIFO and end HOLD; the session is never signalled."""
        phase = self._current
        if phase is not None:
            with self._journal:
                try:
                    self.recorder.request_cancel(phase_id=phase)
                except Exception:
                    _LOG.exception("cancel request for phase %s was not journaled", phase)
        self._abort("OPERATOR_CANCEL", canceled=True)
        return {"canceled": phase}

    # -- the phase bookkeeping, driven by the commands the field carry sends ------------------------------------
    def _act(self, command: str) -> dict:
        if self.aborted.is_set():
            return {"ok": False, "error": "held: cancelled"}
        if not self._settle():
            return {"ok": False, "error": "held: " + (self._failed or "phase")}
        try:
            if self.fence(self.grant.authority_epoch, self.grant.dispatch_generation) is not True:
                raise PermissionError
        except Exception:
            self._abort("FENCE_CLOSED")
            return {"ok": False, "error": "held: fence closed"}
        expected = self._plan[self._ptr] if self._ptr < len(self._plan) and self._failed is None else None
        word = command.split()[0] if command.split() else ""
        if expected is None or not (word == "load" if expected == "load" else command == expected):
            return self.carry.cell.act(command)      # a recovery command: it moves nothing the journal tracks
        index = self._phase_of[self._ptr]
        first = self._ptr == sum(PHASE_LENGTHS[:index])
        last = self._ptr == sum(PHASE_LENGTHS[:index + 1]) - 1
        if first:
            self._begin(index)
        try:
            status = self.carry.cell.act(command)
        except Exception as error:                   # e.g. the safety monitor stopped the carry: it parked itself
            status = {"ok": False, "fault": "exception", "error": type(error).__name__}
        self._after(index, first, last, command, status)
        return status

    def _begin(self, index):
        phase = PHASES[index]
        commands = self._plan[sum(PHASE_LENGTHS[:index]):sum(PHASE_LENGTHS[:index + 1])]
        digest = sha256(json.dumps([self.grant.request_digest, phase, commands]).encode()).hexdigest()
        with self._journal:
            self.recorder.begin_phase(phase_id=phase, ordinal=index, command_digest=digest)
            self._current = phase

    def _goal(self, phase):
        return f"{self.grant.action_id}:{phase}"

    def _after(self, index, first, last, command, status):
        phase = PHASES[index]
        with self._journal:
            if self.aborted.is_set():
                return                                   # the abort path owns the journal now
            if first:
                accepted = _accepted(status)
                submit = self.recorder.record_first_submission if index == 0 else self.recorder.record_submission
                submit(phase_id=phase, accepted=accepted, driver_goal_id=self._goal(phase) if accepted else None)
                if accepted is not True:
                    self._failed, self._current = f"{phase.upper()}_NOT_ACCEPTED", None
                    return
                self.recorder.mark_running(phase_id=phase, driver_goal_id=self._goal(phase))
            final = self._ptr == len(self._plan) - 1
            if not (_final_ok(status) if final else _ok(status)):
                self._terminal(phase, "FAILED", status if not final or not _ok(status) else
                               {**status, "error": "final park not settled or release check could not run"})
                self._failed = f"{phase.upper()}_STEP_FAILED"
                return
            self._statuses.append(status)
            self._ptr += 1
            if last:
                self._pending = (index, list(self._statuses))
                self._statuses = []

    def _terminal(self, phase, outcome, result):
        self.recorder.record_terminal(
            phase_id=phase, driver_goal_id=self._goal(phase), outcome=outcome, result_source=RESULT_SOURCE,
            result_observed_at=datetime.now(timezone.utc).isoformat(),
            result={k: result.get(k) for k in ("ok", "error", "contact", "fault", "holding", "settled")})
        self._current = None

    def _sequence_of(self, status):
        t = status.get("t")
        self._seq = max(self._seq + 1, int(t * 1000) if isinstance(t, (int, float)) else 0)
        return self._seq

    def _settle(self) -> bool:
        """Close the phase whose last command just returned; the field carry has annotated `holding` by now."""
        with self._journal:
            if self.aborted.is_set() or self._pending is None:
                return not self.aborted.is_set()
            (index, statuses), self._pending = self._pending, None
            phase, status = PHASES[index], statuses[-1]
            if phase == "grasp" and not status.get("holding"):
                self._terminal(phase, "FAILED", {**status, "error": "gripper does not prove the hold"})
                self._failed = "GRASP_NOT_HOLDING"
                return False
            self._terminal(phase, "SUCCEEDED", status)
            if phase == "grasp":
                self._hold_seq = self._sequence_of(status)
            elif phase == "release":
                self._release_seq = self._sequence_of(statuses[0])  # the release step itself, not the final park
            return True

    # -- the worker, the watchdog and the end of a carry --------------------------------------------------------
    def _run(self):
        try:
            result = self.carry.run(SimpleNamespace(act=self._act))
            self._finish(result if isinstance(result, dict) else {})
        except Exception:
            _LOG.exception("arm session carry failed for %s", self.grant.action_id)
            self._abort("CARRY_EXCEPTION")

    def _finish(self, result):
        if self.aborted.is_set():
            return
        settled = self._settle()
        if settled and self._failed is None and self._ptr == len(self._plan) and result.get("result") == "placed":
            observed = datetime.now(timezone.utc).isoformat()

            def complete():
                self.recorder.record_workflow_state(
                    workflow_state="ACTION_SUCCEEDED", object_may_be_held=False,
                    evidence_refs={"gripper_hold_sequence": self._hold_seq, "gripper_release_sequence": self._release_seq})
                return self.recorder.complete_pick_place(result_observed_at=observed, result={"carry": "placed"})
            try:
                with self._journal:
                    self.complete_if_current(self.grant, complete)
            except Exception:
                _LOG.exception("completion was not confirmed for %s", self.grant.action_id)
                self._abort("COMPLETION_UNCONFIRMED")
            self._done.set()
        else:
            self._abort(self._failed or f"CARRY_{str(result.get('result', 'ENDED')).upper()}"[:96])

    def _watch(self):
        started, bad_since = self.clock(), None
        while not self._done.wait(self.poll_s):
            if self._folding.is_set():
                continue                                 # a fold in progress is never interrupted
            now = self.clock()
            try:
                ok = self.fence(self.grant.authority_epoch, self.grant.dispatch_generation) is True
            except Exception:
                ok = False
            bad_since = None if ok else (bad_since if bad_since is not None else now)
            if bad_since is not None and now - bad_since >= self.fence_loss_s:
                self._abort("FENCE_LOST")
            elif now - started >= self.deadline_s:
                self._abort("DEADLINE_EXCEEDED")

    def _abort(self, reason: str, *, canceled=False):
        with self._abort_lock:
            if self._aborting:
                return
            self._aborting = True
        self.aborted.set()
        threading.Thread(target=self._fold_and_hold, args=(reason[:96], canceled), name="arm-session-fold",
                         daemon=True).start()

    def _fold_and_hold(self, reason, canceled):
        self._folding.set()
        try:
            status = self.carry.fold()
        except Exception as error:
            _LOG.exception("fold through the session failed for %s", self.grant.action_id)
            status = {"ok": False, "error": type(error).__name__}
        with self._journal:
            phase = self._current
            try:
                if phase is not None and canceled:
                    self.recorder.record_cancel_ack(phase_id=phase, acknowledged=status.get("ok") is True)
                    self._terminal(phase, "CANCELED", status)
                elif phase is not None:
                    self._terminal(phase, "FAILED", {**status, "error": reason})
            except Exception:
                _LOG.exception("open phase %s was not closed", phase)
            try:
                self.recorder.hold(reason=reason)
            except Exception:
                pass                                     # a canceled terminal already holds the Action
        self._done.set()


def create_session_carry_factory(goals: ArmGoals, *, fence, submission_fence, admission, goal_port):
    installation = goals.installation

    def complete_if_current(grant, operation):
        return submission_fence.run_if_open(
            authority_epoch=grant.authority_epoch, dispatch_generation=grant.dispatch_generation,
            fleet_fence_current=lambda: fence(grant.authority_epoch, grant.dispatch_generation), operation=operation)

    def create(grant, recorder):
        installation.geometry(grant)                     # the grant must name this installed capability
        return SessionCarryExecution(grant, recorder, goals.open_carry(grant), fence=fence,
                                     complete_if_current=complete_if_current, **(goals.timing or {}))
    return InstalledArmTransferFactory(
        create, installation.bindings, installation.capability_revision, installation.config_revision,
        installation.resource_policy_digest, admission, goal_port)
