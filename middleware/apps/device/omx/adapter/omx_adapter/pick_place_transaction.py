"""Evidence-only state machine for a fixed-workcell pick-and-place sequence.

This module never submits a ROS goal. A future device adapter may use the
sequence only after hardware, single-writer, gripper, and independent-stop
contracts are accepted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from core_common.protocol.schemas import FleetCellTransferGrant

from .gripper_contract import (
    GripperObservation,
    HoldReceipt,
    ReleaseReceipt,
    verify_held_object,
    verify_released_object,
)
from .target_evidence import TargetEvidence
from .phase_recorder import ActionPhaseRecorder


class TransactionError(ValueError):
    """The Action evidence is stale, belongs elsewhere, or violates the sequence."""


class PickPlaceState(str, Enum):
    APPROACH = "APPROACH"
    GRASP = "GRASP"
    VERIFY_HOLD = "VERIFY_HOLD"
    TRANSFER = "TRANSFER"
    RELEASE = "RELEASE"
    VERIFY_RELEASE = "VERIFY_RELEASE"
    ACTION_SUCCEEDED = "ACTION_SUCCEEDED"
    HOLD = "HOLD"


@dataclass(frozen=True)
class ArmActionResult:
    action_id: str
    attempt_id: str
    workcell_id: str
    owner_generation: int
    stage: str
    accepted: bool
    terminal: bool
    success: bool
    result_id: str
    observed_at: float


class PickPlaceTransaction:
    """Consume independent evidence in order; never perform a driver operation."""

    _STAGE_BY_STATE = {
        PickPlaceState.APPROACH: "approach",
        PickPlaceState.GRASP: "grasp",
        PickPlaceState.TRANSFER: "transfer",
        PickPlaceState.RELEASE: "release",
    }
    _STATE_REQUIRED_FOR_PHASE = {
        "approach": PickPlaceState.APPROACH,
        "grasp": PickPlaceState.GRASP,
        "transfer": PickPlaceState.TRANSFER,
        "release": PickPlaceState.RELEASE,
    }

    def __init__(self, *, action_id: str, attempt_id: str, workcell_id: str,
                 instance_id: str, gripper_sensor_revision: str, owner_generation: int,
                 source: TargetEvidence,
                 destination: TargetEvidence) -> None:
        self._initialize(action_id=action_id, attempt_id=attempt_id, workcell_id=workcell_id,
                         instance_id=instance_id, gripper_sensor_revision=gripper_sensor_revision,
                         owner_generation=owner_generation)
        if source.object_id == destination.object_id:
            raise ValueError("source and destination must resolve to different objects")
        if (source.observation_id != destination.observation_id
                or source.camera_identity != destination.camera_identity
                or source.calibration_revision != destination.calibration_revision
                or source.transform_revision != destination.transform_revision):
            raise ValueError("source and destination must share one observation revision")
        self.source = source
        self.destination = destination
        self._item_id = source.object_id

    @classmethod
    def for_cell_transfer(cls, grant: FleetCellTransferGrant, *,
                          gripper_sensor_revision: str) -> "PickPlaceTransaction":
        """Bind the same physical gripper sequence to a camera-blind Cell grant."""
        if not isinstance(grant, FleetCellTransferGrant):
            raise ValueError("a validated CELL_TRANSFER grant is required")
        grant = FleetCellTransferGrant.model_validate(grant.model_dump())
        transaction = cls.__new__(cls)
        transaction._initialize(
            action_id=grant.action_id, attempt_id=grant.attempt_id, workcell_id=grant.workcell_id,
            instance_id=grant.instance_id, gripper_sensor_revision=gripper_sensor_revision,
            owner_generation=grant.dispatch_generation,
        )
        transaction.source = None
        transaction.destination = None
        transaction._item_id = grant.cell_transfer.item
        transaction._cell_grant = grant
        return transaction

    def _initialize(self, *, action_id: str, attempt_id: str, workcell_id: str,
                    instance_id: str, gripper_sensor_revision: str, owner_generation: int) -> None:
        for name, value in (("action_id", action_id), ("attempt_id", attempt_id),
                            ("workcell_id", workcell_id), ("instance_id", instance_id),
                            ("gripper_sensor_revision", gripper_sensor_revision)):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a non-empty trimmed string")
        if type(owner_generation) is not int or owner_generation < 0:
            raise ValueError("owner_generation must be a non-negative integer")
        self.action_id = action_id
        self.attempt_id = attempt_id
        self.workcell_id = workcell_id
        self.instance_id = instance_id
        self.gripper_sensor_revision = gripper_sensor_revision
        self.owner_generation = owner_generation
        self.state = PickPlaceState.APPROACH
        self.hold_reason: str | None = None
        self.hold_receipt: HoldReceipt | None = None
        self.release_receipt: ReleaseReceipt | None = None
        self._recovered_object_may_be_held = False
        self.last_result_id: str | None = None

    def workflow_evidence(self) -> dict[str, Any]:
        """Return a bounded journal projection with no raw sensor/image payloads."""
        refs: dict[str, object] = {}
        if self.last_result_id is not None:
            refs["phase_result_id"] = self.last_result_id
        if self.hold_receipt is not None:
            refs["gripper_hold_sequence"] = self.hold_receipt.sequence
        if self.release_receipt is not None:
            refs["gripper_release_sequence"] = self.release_receipt.sequence
        if self.hold_reason is not None:
            refs["hold_reason"] = self.hold_reason
        return {
            "workflow_state": self.state.value,
            "object_may_be_held": self.object_held,
            "evidence_refs": refs,
        }

    def may_submit_phase(self, phase_id: str) -> bool:
        """Authorize only the motion stage reached by verified workflow evidence."""
        expected_state = self._STATE_REQUIRED_FOR_PHASE.get(phase_id)
        return expected_state is not None and self.state is expected_state

    @property
    def object_held(self) -> bool:
        return (self._recovered_object_may_be_held
                or self.state in {
                    PickPlaceState.VERIFY_HOLD, PickPlaceState.TRANSFER,
                    PickPlaceState.RELEASE, PickPlaceState.VERIFY_RELEASE,
                }
                or (self.hold_receipt is not None and self.release_receipt is None))

    def _hold(self, reason: str) -> None:
        self._recovered_object_may_be_held = self.object_held
        self.state = PickPlaceState.HOLD
        self.hold_reason = reason

    def record_arm_result(self, result: ArmActionResult) -> PickPlaceState:
        if self.state is PickPlaceState.ACTION_SUCCEEDED:
            raise TransactionError("local Action is terminal; late arm results cannot change it")
        if self.state is PickPlaceState.HOLD:
            raise TransactionError("transaction is in HOLD")
        if self.state not in self._STAGE_BY_STATE:
            self._hold("unexpected_or_late_driver_result")
            raise TransactionError("driver result arrived outside an active stage")
        expected_stage = self._STAGE_BY_STATE[self.state]
        identity_matches = (
            result.action_id == self.action_id and result.attempt_id == self.attempt_id
            and result.workcell_id == self.workcell_id
            and result.owner_generation == self.owner_generation
        )
        if not identity_matches:
            self._hold("action_attempt_or_owner_mismatch")
            raise TransactionError("driver result identity does not match action attempt or owner generation")
        if result.stage != expected_stage:
            self._hold("unexpected_or_late_driver_result")
            raise TransactionError("driver result stage does not match current attempt")
        try:
            observed_at = float(result.observed_at)
        except (TypeError, ValueError):
            observed_at = math.nan
        if (result.accepted is not True or result.terminal is not True
                or result.success is not True or not isinstance(result.result_id, str)
                or not result.result_id.strip() or result.result_id != result.result_id.strip()
                or isinstance(result.observed_at, bool) or not math.isfinite(observed_at)):
            self._hold("driver_result_unconfirmed")
            raise TransactionError("driver result is not an explicit successful final result")
        self.last_result_id = result.result_id
        if self.state is PickPlaceState.APPROACH:
            self.state = PickPlaceState.GRASP
        elif self.state is PickPlaceState.GRASP:
            self.state = PickPlaceState.VERIFY_HOLD
        elif self.state is PickPlaceState.TRANSFER:
            self.state = PickPlaceState.RELEASE
        else:
            self.state = PickPlaceState.VERIFY_RELEASE
        return self.state

    def verify_gripper_held(self, observation: GripperObservation, *, now: float,
                            max_age_s: float) -> HoldReceipt:
        if self.state is not PickPlaceState.VERIFY_HOLD:
            raise TransactionError("transaction is not awaiting held-object readback")
        try:
            receipt = verify_held_object(
                observation, object_id=self._item_id, now=now, max_age_s=max_age_s,
            )
            if (receipt.workcell_id != self.workcell_id
                    or receipt.instance_id != self.instance_id
                    or receipt.sensor_revision != self.gripper_sensor_revision
                    or receipt.owner_generation != self.owner_generation):
                raise TransactionError("gripper readback workcell or owner generation mismatch")
        except TransactionError:
            self._hold("object_hold_unconfirmed")
            raise
        except (ValueError, TypeError) as exc:
            self._hold("object_hold_unconfirmed")
            raise TransactionError("gripper readback cannot prove the requested object is held") from exc
        self.hold_receipt = receipt
        self._recovered_object_may_be_held = False
        self.state = PickPlaceState.TRANSFER
        return receipt

    def verify_gripper_released(self, observation: GripperObservation, *, now: float,
                                max_age_s: float) -> ReleaseReceipt:
        if self.state is not PickPlaceState.VERIFY_RELEASE:
            raise TransactionError("transaction is not awaiting release readback")
        try:
            receipt = verify_released_object(
                observation, object_id=self._item_id, now=now, max_age_s=max_age_s,
            )
            if (receipt.workcell_id != self.workcell_id
                    or receipt.instance_id != self.instance_id
                    or receipt.sensor_revision != self.gripper_sensor_revision
                    or receipt.owner_generation != self.owner_generation
                    or self.hold_receipt is None
                    or receipt.sequence <= self.hold_receipt.sequence):
                raise TransactionError("gripper readback identity or sequence mismatch")
        except TransactionError:
            self._hold("object_release_unconfirmed")
            raise
        except (ValueError, TypeError) as exc:
            self._hold("object_release_unconfirmed")
            raise TransactionError("gripper readback cannot prove the object was released") from exc
        self.release_receipt = receipt
        self._recovered_object_may_be_held = False
        self.state = PickPlaceState.ACTION_SUCCEEDED
        return receipt

    def cancel(self, *, reason: str) -> PickPlaceState:
        if self.state is PickPlaceState.ACTION_SUCCEEDED:
            raise TransactionError("completed transaction cannot be canceled")
        _ = reason
        self._hold("cancel_while_object_held" if self.object_held else "cancel_during_action_unknown")
        return self.state

    def snapshot(self) -> dict[str, Any]:
        cell_grant = getattr(self, "_cell_grant", None)
        snapshot = {
            "action_id": self.action_id, "attempt_id": self.attempt_id,
            "workcell_id": self.workcell_id, "owner_generation": self.owner_generation,
            "instance_id": self.instance_id,
            "gripper_sensor_revision": self.gripper_sensor_revision,
            "source_object_id": self._item_id,
            "destination_object_id": (cell_grant.cell_transfer.pallet if cell_grant
                                      else self.destination.object_id),
            "source_observation_id": None if cell_grant else self.source.observation_id,
            "destination_observation_id": None if cell_grant else self.destination.observation_id,
            "state": self.state.value, "hold_reason": self.hold_reason,
            "object_held": self.object_held, "last_result_id": self.last_result_id,
        }
        if cell_grant is not None:
            snapshot["cell_grant"] = cell_grant.model_dump(mode="json")
        return snapshot

    @classmethod
    def recover(cls, snapshot: Mapping[str, Any]) -> "PickPlaceTransaction":
        if not isinstance(snapshot, Mapping):
            raise ValueError("transaction snapshot must be a mapping")
        try:
            state = PickPlaceState(snapshot["state"])
            action_id = str(snapshot["action_id"])
            attempt_id = str(snapshot["attempt_id"])
            workcell_id = str(snapshot["workcell_id"])
            instance_id = str(snapshot["instance_id"])
            gripper_sensor_revision = str(snapshot["gripper_sensor_revision"])
            owner_generation = int(snapshot["owner_generation"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("transaction snapshot is incomplete") from exc
        recovered = object.__new__(cls)
        recovered.action_id = action_id
        recovered.attempt_id = attempt_id
        recovered.workcell_id = workcell_id
        recovered.instance_id = instance_id
        recovered.gripper_sensor_revision = gripper_sensor_revision
        recovered.owner_generation = owner_generation
        recovered.source = None
        recovered.destination = None
        recovered._item_id = snapshot.get("source_object_id")
        if "cell_grant" in snapshot:
            grant = FleetCellTransferGrant.model_validate(snapshot["cell_grant"])
            if (grant.action_id != action_id or grant.attempt_id != attempt_id
                    or grant.workcell_id != workcell_id or grant.instance_id != instance_id
                    or grant.dispatch_generation != owner_generation):
                raise ValueError("Cell transaction snapshot identity does not match its grant")
            recovered._cell_grant = grant
            recovered._item_id = grant.cell_transfer.item
        recovered.state = state
        recovered.hold_reason = snapshot.get("hold_reason")
        recovered.hold_receipt = None
        recovered.release_receipt = None
        recovered._recovered_object_may_be_held = (
            snapshot.get("object_held") is True
            or state in {PickPlaceState.GRASP, PickPlaceState.VERIFY_HOLD,
                         PickPlaceState.TRANSFER, PickPlaceState.RELEASE,
                         PickPlaceState.VERIFY_RELEASE}
        )
        recovered.last_result_id = snapshot.get("last_result_id")
        if state is PickPlaceState.ACTION_SUCCEEDED and snapshot.get("object_held") is False:
            recovered.hold_reason = None
        else:
            recovered._hold("restart_reconciliation_required")
        return recovered


class PickPlaceWorkflowJournal:
    """Persist semantic and gripper evidence separately from ROS goal phases.

    This journal does not submit gripper commands or verify Fleet placement
    evidence. The local Action completes only after all four ROS phases and a
    fresh open/no-object readback; Fleet remains responsible for GOAL_CONFIRMED.
    """

    def __init__(self, transaction: PickPlaceTransaction,
                 recorder: ActionPhaseRecorder) -> None:
        if (transaction.action_id != recorder.action_id
                or transaction.attempt_id != recorder.attempt_id):
            raise ValueError("workflow transaction and phase recorder identity mismatch")
        self.transaction = transaction
        self.recorder = recorder
        self._persist_current()

    def phase_gate(self, phase_id: str) -> bool:
        """Pass directly to PickPlaceRunner; stale/unpersisted state fails closed."""
        snapshot = self.transaction.workflow_evidence()
        return (
            self.transaction.may_submit_phase(phase_id)
            and self.recorder.latest_workflow_state() == snapshot["workflow_state"]
        )

    def record_arm_result(self, result: ArmActionResult) -> PickPlaceState:
        return self._apply(lambda: self.transaction.record_arm_result(result))

    def verify_gripper_held(self, observation: GripperObservation, *, now: float,
                            max_age_s: float) -> HoldReceipt:
        return self._apply(lambda: self.transaction.verify_gripper_held(
            observation, now=now, max_age_s=max_age_s,
        ))

    def verify_gripper_released(self, observation: GripperObservation, *, now: float,
                                max_age_s: float,
                                result_observed_at: str) -> ReleaseReceipt:
        receipt = self._apply(lambda: self.transaction.verify_gripper_released(
            observation, now=now, max_age_s=max_age_s,
        ))
        evidence = self.transaction.workflow_evidence()
        try:
            self.recorder.complete_pick_place(
                result_observed_at=result_observed_at,
                result={"workflow_state": evidence["workflow_state"],
                        "object_may_be_held": evidence["object_may_be_held"],
                        "evidence_refs": evidence["evidence_refs"]},
            )
        except Exception:
            parent = self.recorder.parent()
            if parent is not None and parent["state"] in {
                "SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN",
            }:
                self._force_hold("ACTION_COMPLETION_UNCERTAIN")
            raise
        return receipt

    def cancel(self, *, reason: str) -> PickPlaceState:
        state = self._apply(lambda: self.transaction.cancel(reason=reason))
        if state is PickPlaceState.HOLD:
            self._hold_action()
        return state

    def _apply(self, operation: Callable[[], Any]) -> Any:
        try:
            result = operation()
        except TransactionError:
            if self.transaction.state is PickPlaceState.HOLD:
                self._force_hold(self.transaction.hold_reason or "WORKFLOW_EVIDENCE_REJECTED")
            raise
        try:
            self._persist_current()
        except Exception as exc:
            self._force_hold("WORKFLOW_JOURNAL_FAILED")
            raise TransactionError("workflow state could not be durably recorded") from exc
        return result

    def _persist_current(self) -> None:
        evidence = self.transaction.workflow_evidence()
        if evidence["workflow_state"] == PickPlaceState.HOLD.value:
            self._hold_action()
            evidence = self.transaction.workflow_evidence()
        self.recorder.record_workflow_state(**evidence)

    def _hold_action(self) -> None:
        reason = self.transaction.hold_reason or "WORKFLOW_HOLD"
        parent = self.recorder.parent()
        if parent is not None and parent["state"] in {
            "SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN",
        }:
            self.recorder.hold(reason=reason)

    def _force_hold(self, reason: str) -> None:
        self.transaction._hold(reason)
        try:
            self._persist_current()
        except Exception:
            self._hold_action()
