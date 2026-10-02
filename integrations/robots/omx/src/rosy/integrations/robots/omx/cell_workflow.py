"""Local Cell workflow consumes durable phases and physical gripper readback."""

from datetime import datetime, timezone
import threading

from omx_adapter.pick_place_transaction import ArmActionResult, PickPlaceWorkflowJournal, TransactionError


class CellTransferWorkflowExecution:
    """Progress one phase at a time through the existing semantic journal.

    ROS callbacks remain on PickPlaceRunner. A local caller polls advance;
    no background owner, command loop, retry, or independent placement verdict
    is created here.
    """

    def __init__(self, execution, workflow: PickPlaceWorkflowJournal, recorder, *,
                 gripper_readback, max_age_s, monotonic, complete_if_current, now=None):
        self.execution = execution
        self.workflow = workflow
        self.recorder = recorder
        self.gripper_readback = gripper_readback
        self.max_age_s = max_age_s
        self.monotonic = monotonic
        if not callable(complete_if_current):
            raise ValueError("a serialized completion fence is required")
        self.complete_if_current = complete_if_current
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._consumed = 0
        self._lock = threading.RLock()

    @property
    def active_phase_id(self):
        return self.execution.active_phase_id

    def start(self):
        with self._lock:
            return self.execution.start()

    def _read_gripper(self):
        try:
            return self.gripper_readback()
        except Exception as exc:
            self.workflow.cancel(reason="GRIPPER_READBACK_UNAVAILABLE")
            raise TransactionError("gripper readback is unavailable") from exc

    def advance(self):
        with self._lock:
            try:
                return self._advance()
            except Exception:
                parent = self.recorder.parent()
                if parent is not None and parent["state"] != "SUCCEEDED":
                    self.workflow.cancel(reason="WORKFLOW_OPERATION_UNCERTAIN")
                raise

    def _advance(self):
        with self._lock:
            parent = self.recorder.parent()
            if parent is None or parent["state"] not in {"ACCEPTED", "RUNNING"}:
                return parent
            phases = self.recorder.phases()
            if not phases:
                raise RuntimeError("first phase has not been submitted")
            phase = phases[-1]
            if phase["state"] in {"FAILED", "CANCELED", "UNKNOWN", "HOLD"}:
                self.workflow.cancel(reason="PHASE_NOT_SUCCEEDED")
                return self.recorder.parent()
            if phase["state"] != "SUCCEEDED":
                return parent
            if phase["ordinal"] == self._consumed:
                tx = self.workflow.transaction
                observed = datetime.fromisoformat(phase["result_observed_at"])
                if observed.tzinfo is None or phase["result_source"] != "ros-action-result":
                    self.workflow.cancel(reason="PHASE_TERMINAL_PROVENANCE_INVALID")
                    return self.recorder.parent()
                self.workflow.record_arm_result(ArmActionResult(
                    tx.action_id, tx.attempt_id, tx.workcell_id, tx.owner_generation,
                    phase["phase_id"], True, True, True, phase["driver_goal_id"], observed.timestamp(),
                ))
                self._consumed += 1
                if phase["phase_id"] == "grasp":
                    self.workflow.verify_gripper_held(
                        self._read_gripper(), now=self.monotonic(), max_age_s=self.max_age_s,
                    )
                elif phase["phase_id"] == "release":
                    observed_at = self.now()
                    if (not isinstance(observed_at, datetime) or observed_at.tzinfo is None
                            or observed_at.utcoffset() is None):
                        raise TransactionError("workflow clock must return an aware timestamp")
                    observation = self._read_gripper()
                    # Read sensors before taking the stop lock. Only durable completion
                    # runs under the final fence; it never waits for ROS goal callbacks.
                    self.complete_if_current(lambda: self.workflow.verify_gripper_released(
                        observation, now=self.monotonic(), max_age_s=self.max_age_s,
                        result_observed_at=observed_at.isoformat(),
                    ))
                    return self.recorder.parent()
            elif phase["ordinal"] != self._consumed - 1:
                self.workflow.cancel(reason="PHASE_SEQUENCE_CHANGED")
                return self.recorder.parent()
            return self.execution.advance()

    def cancel_current(self):
        with self._lock:
            try:
                return self.execution.cancel_current()
            finally:
                self.workflow.cancel(reason="LOCAL_CANCEL")
