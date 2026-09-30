"""Evidence-only state machine for a fixed-workcell pick-and-place sequence.

This module never submits a ROS goal. A future device adapter may use the
sequence only after hardware, single-writer, gripper, and independent-stop
contracts are accepted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .gripper_contract import (
    GripperObservation,
    HoldReceipt,
    ReleaseReceipt,
    verify_held_object,
    verify_released_object,
)
from .target_evidence import TargetEvidence


class TransactionError(ValueError):
    """The Action evidence is stale, belongs elsewhere, or violates the sequence."""


class PickPlaceState(str, Enum):
    APPROACH = "APPROACH"
    GRASP = "GRASP"
    VERIFY_HOLD = "VERIFY_HOLD"
    TRANSFER = "TRANSFER"
    RELEASE = "RELEASE"
    VERIFY_RELEASE = "VERIFY_RELEASE"
    VERIFY_PLACEMENT = "VERIFY_PLACEMENT"
    COMPLETED = "COMPLETED"
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


@dataclass(frozen=True)
class PlacementEvidence:
    action_id: str
    attempt_id: str
    object_id: str
    destination_id: str
    observation_id: str
    evaluator_id: str
    evaluator_revision: str
    predicate: str
    satisfied: bool
    observed_at: float


class PickPlaceTransaction:
    """Consume independent evidence in order; never perform a driver operation."""

    _STAGE_BY_STATE = {
        PickPlaceState.APPROACH: "approach",
        PickPlaceState.GRASP: "grasp",
        PickPlaceState.TRANSFER: "transfer",
        PickPlaceState.RELEASE: "release",
    }

    def __init__(self, *, action_id: str, attempt_id: str, workcell_id: str,
                 instance_id: str, gripper_sensor_revision: str, owner_generation: int,
                 source: TargetEvidence,
                 destination: TargetEvidence) -> None:
        for name, value in (("action_id", action_id), ("attempt_id", attempt_id),
                            ("workcell_id", workcell_id), ("instance_id", instance_id),
                            ("gripper_sensor_revision", gripper_sensor_revision)):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a non-empty trimmed string")
        if type(owner_generation) is not int or owner_generation < 0:
            raise ValueError("owner_generation must be a non-negative integer")
        if source.object_id == destination.object_id:
            raise ValueError("source and destination must resolve to different objects")
        if (source.observation_id != destination.observation_id
                or source.camera_identity != destination.camera_identity
                or source.calibration_revision != destination.calibration_revision
                or source.transform_revision != destination.transform_revision):
            raise ValueError("source and destination must share one observation revision")
        self.action_id = action_id
        self.attempt_id = attempt_id
        self.workcell_id = workcell_id
        self.instance_id = instance_id
        self.gripper_sensor_revision = gripper_sensor_revision
        self.owner_generation = owner_generation
        self.source = source
        self.destination = destination
        self.state = PickPlaceState.APPROACH
        self.hold_reason: str | None = None
        self.hold_receipt: HoldReceipt | None = None
        self.release_receipt: ReleaseReceipt | None = None
        self._recovered_object_may_be_held = False
        self.last_result_id: str | None = None

    @property
    def object_held(self) -> bool:
        return (self._recovered_object_may_be_held
                or (self.hold_receipt is not None and self.release_receipt is None))

    def _hold(self, reason: str) -> None:
        self.state = PickPlaceState.HOLD
        self.hold_reason = reason

    def record_arm_result(self, result: ArmActionResult) -> PickPlaceState:
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
                observation, object_id=self.source.object_id, now=now, max_age_s=max_age_s,
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
                observation, object_id=self.source.object_id, now=now, max_age_s=max_age_s,
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
        self.state = PickPlaceState.VERIFY_PLACEMENT
        return receipt

    def verify_placement(self, evidence: PlacementEvidence, *, now: float,
                         max_age_s: float) -> PickPlaceState:
        if self.state is not PickPlaceState.VERIFY_PLACEMENT:
            raise TransactionError("transaction is not awaiting destination evidence")
        identity_matches = (
            evidence.action_id == self.action_id and evidence.attempt_id == self.attempt_id
            and evidence.object_id == self.source.object_id
            and evidence.destination_id == self.destination.object_id
            and evidence.predicate == "inside_destination"
            and bool(evidence.observation_id) and bool(evidence.evaluator_id)
            and bool(evidence.evaluator_revision)
        )
        try:
            observed_at = float(evidence.observed_at)
            current, limit = float(now), float(max_age_s)
        except (TypeError, ValueError) as exc:
            self._hold("placement_evidence_invalid")
            raise TransactionError("placement evidence time is invalid") from exc
        if (not identity_matches or isinstance(now, bool) or isinstance(max_age_s, bool)
                or not math.isfinite(observed_at) or not math.isfinite(current)
                or not math.isfinite(limit) or limit <= 0 or current < observed_at
                or current - observed_at > limit or evidence.satisfied is not True):
            self._hold("placement_unconfirmed")
            raise TransactionError("independent placement predicate is not confirmed")
        self.state = PickPlaceState.COMPLETED
        return self.state

    def cancel(self, *, reason: str) -> PickPlaceState:
        if self.state is PickPlaceState.COMPLETED:
            raise TransactionError("completed transaction cannot be canceled")
        _ = reason
        self._hold("cancel_while_object_held" if self.object_held else "cancel_during_action_unknown")
        return self.state

    def snapshot(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id, "attempt_id": self.attempt_id,
            "workcell_id": self.workcell_id, "owner_generation": self.owner_generation,
            "instance_id": self.instance_id,
            "gripper_sensor_revision": self.gripper_sensor_revision,
            "source_object_id": self.source.object_id,
            "destination_object_id": self.destination.object_id,
            "source_observation_id": self.source.observation_id,
            "destination_observation_id": self.destination.observation_id,
            "state": self.state.value, "hold_reason": self.hold_reason,
            "object_held": self.object_held, "last_result_id": self.last_result_id,
        }

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
        recovered._hold("restart_reconciliation_required")
        return recovered
