"""Protocol contracts, constructor validation, and ROS goal event journaling mixin for PickPlaceRunner."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol

from core_common.protocol.schemas import FleetActionGrant

from ..command_owner import TrajectoryCommand
from ..gripper_contract import GripperObservation
from ..manipulation_plan import (
    ExecutionStateSnapshot,
    PlannedMotionPhase,
    ResolvedPickPlacePlan,
)
from ..phase_recorder import ActionPhaseRecorder
from ..ros_goal_contract import RosGoalEvent
from ..transfer_motion import (
    ArmPlanningProfile as CellPlanningProfile,
    TransferMotionPlan as CellTransferPlan,
    validate_transfer_motion_plan as validate_cell_transfer_plan,
)

# CELL_TRANSFER phases whose gripper start value is not compared (object in hand).
_AFTER_GRASP_PHASES = frozenset({"transfer", "release"})


class PhaseGoalPort(Protocol):
    """One local arm owner; ROS acceptance arrives later as a goal event."""

    def submit(self, command: TrajectoryCommand, *,
               on_goal_event: Callable[[RosGoalEvent], bool]) -> "PhaseDispatch": ...

    def cancel_goal(self, driver_goal_id: str) -> bool | None: ...


@dataclass(frozen=True)
class PhaseDispatch:
    """Local dispatch result, intentionally separate from ROS goal acceptance."""

    dispatched: bool | None

    def __post_init__(self) -> None:
        if self.dispatched is not True and self.dispatched is not False and self.dispatched is not None:
            raise ValueError("dispatched must be true, false, or unknown")


def math_is_aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _validate_runner_init(
    runner,
    recorder: ActionPhaseRecorder,
    grant: FleetActionGrant,
    plan: ResolvedPickPlacePlan | CellTransferPlan,
    *,
    command_for_phase: Callable[[PlannedMotionPhase], TrajectoryCommand],
    phase_gate: Callable[[str], bool],
    current_fence: Callable[[int, int], bool],
    current_execution_state: Callable[[], ExecutionStateSnapshot],
    start_state_tolerances: Mapping[str, float],
    max_joint_state_age_s: float,
    monotonic: Callable[[], float],
    cell_profile: CellPlanningProfile | None,
    gripper_readback: Callable[[], GripperObservation] | None,
    held_object_id: str | None,
) -> None:
    if not isinstance(plan, (ResolvedPickPlacePlan, CellTransferPlan)):
        raise ValueError("plan must be a validated ResolvedPickPlacePlan or CellTransferPlan")
    if not callable(monotonic):
        raise ValueError("fresh execution-state and monotonic clock providers are required")
    # CELL_TRANSFER (simulation, D-402 §3d): after grasp the gripper stops at the
    # object width, so in transfer/release gripper_contract readback judges it,
    # not the start-state value. approach/grasp check it like any joint. The
    # skipped set is the accepted profile's gripper, never the plan's own claim.
    runner._unchecked_joints = frozenset()
    if isinstance(plan, CellTransferPlan):
        if not isinstance(cell_profile, CellPlanningProfile):
            raise ValueError("a CellTransferPlan requires the accepted cell_profile")
        validate_cell_transfer_plan(
            plan, cell_profile, kinematics_revision=cell_profile.kinematics_revision,
            now_monotonic_s=monotonic(),
        )
        runner._unchecked_joints = frozenset({cell_profile.gripper_joint})
        # A4 (C3b): the hold is re-read right before release (C3 run8 dropped the block
        # in transit and still passed every gate).
        if not callable(gripper_readback) or not isinstance(held_object_id, str) or not held_object_id:
            raise ValueError("a CellTransferPlan requires gripper_readback and held_object_id")
    runner._cell_profile = cell_profile if isinstance(plan, CellTransferPlan) else None
    runner.gripper_readback = gripper_readback
    runner.held_object_id = held_object_id
    if not callable(current_execution_state):
        raise ValueError("fresh execution-state and monotonic clock providers are required")
    if isinstance(max_joint_state_age_s, bool):
        raise ValueError("max_joint_state_age_s must be positive and finite")
    try:
        max_state_age = float(max_joint_state_age_s)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_joint_state_age_s must be positive and finite") from exc
    if not math.isfinite(max_state_age) or max_state_age <= 0:
        raise ValueError("max_joint_state_age_s must be positive and finite")
    tolerances = dict(start_state_tolerances)
    if set(tolerances) != set(plan.phases[0].joint_names):
        raise ValueError("start-state tolerances must cover exactly the planned joints")
    normalized_tolerances = {}
    for name, value in tolerances.items():
        if isinstance(value, bool):
            raise ValueError("start-state tolerances must be finite and non-negative")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("start-state tolerances must be finite and non-negative") from exc
        if not math.isfinite(numeric) or numeric < 0:
            raise ValueError("start-state tolerances must be finite and non-negative")
        normalized_tolerances[name] = numeric
    runner.start_state_tolerances = normalized_tolerances
    runner._phase_joint_sets = {
        phase.phase_id: frozenset(phase.joint_names) for phase in plan.phases
    }
    runner._tolerances_by_phase = {
        phase.phase_id: {
            **normalized_tolerances,
            **(runner._cell_profile.phase_start_state_tolerance_rad.get(phase.phase_id, {})
               if runner._cell_profile is not None else {}),
        }
        for phase in plan.phases
    }
    runner.max_joint_state_age_s = max_state_age

    if (recorder.action_id != grant.action_id
            or recorder.attempt_id != grant.attempt_id):
        raise ValueError("phase recorder identity must match the Fleet grant")
    if (not callable(command_for_phase) or not callable(phase_gate)
            or not callable(current_fence)):
        raise ValueError("command factory, semantic phase gate, and current fence must be callable")
    if not math_is_aware(runner.now()):
        raise ValueError("clock must return timezone-aware timestamps")


class _PickPlaceGoalEventMixin:
    """ROS goal event handling and active-goal cancellation for PickPlaceRunner."""

    def on_ros_goal_event(self, event: RosGoalEvent) -> bool:
        """Persist only facts bound to the active command, phase, and goal."""
        with self._event_lock:
            return self._process_ros_goal_event(event)

    def _process_ros_goal_event(self, event: RosGoalEvent) -> bool:
        with self._lock:
            phase = self._current_phase
            command = self._current_command
            if (phase is None or command is None
                    or event.command_id != command.command_id
                    or event.phase_id != phase.phase_id):
                return False
            goal_id = self._current_goal_id
            if (goal_id is not None and event.kind not in {
                    "GOAL_REJECTED", "GOAL_ACCEPTANCE_UNKNOWN"
            } and event.goal_id != goal_id):
                return False
            if self._submitting:
                if len(self._pending_events) >= self._MAX_PENDING_EVENTS:
                    self._pending_overflow = True
                    return False
                self._pending_events.append(event)
                return True
            if event.sequence <= self._last_event_sequence:
                # Feedback from another callback thread can be overtaken by a later event
                # (re-review N1). It is telemetry: acknowledge, do not journal, do not fail.
                return event.kind == "RUNNING_FEEDBACK"
            self._last_event_sequence = event.sequence

        if event.kind in {"GOAL_ACCEPTANCE_UNKNOWN", "GOAL_REJECTED"}:
            parent = self.recorder.parent()
            if parent is None:
                return False
            accepted = None if event.kind == "GOAL_ACCEPTANCE_UNKNOWN" else False
            if phase.ordinal == 0 and parent["state"] == "SUBMITTING":
                self.recorder.record_first_submission(
                    phase_id=phase.phase_id, accepted=accepted, driver_goal_id=None,
                )
            elif parent["state"] in {"ACCEPTED", "RUNNING"}:
                self.recorder.record_submission(
                    phase_id=phase.phase_id, accepted=accepted, driver_goal_id=None,
                )
            elif (parent["state"] in {"UNKNOWN", "HOLD"}
                  and any(row["phase_id"] == phase.phase_id and row["state"] == "UNKNOWN"
                          for row in self.recorder.phases())):
                return True
            else:
                return False
            if accepted is None:
                self.recorder.hold(reason="ROS_GOAL_ACCEPTANCE_UNKNOWN")
            return True
        if event.kind == "GOAL_ACCEPTED":
            parent = self.recorder.parent()
            if parent is None:
                return False
            if phase.ordinal == 0 and parent["state"] == "SUBMITTING":
                self.recorder.record_first_submission(
                    phase_id=phase.phase_id, accepted=True, driver_goal_id=event.goal_id,
                )
            elif parent["state"] in {"ACCEPTED", "RUNNING"}:
                self.recorder.record_submission(
                    phase_id=phase.phase_id, accepted=True, driver_goal_id=event.goal_id,
                )
            elif parent["state"] in {"UNKNOWN", "HOLD"}:
                rows = self.recorder.phases()
                unresolved = next((row for row in rows if row["phase_id"] == phase.phase_id), None)
                if unresolved is None or unresolved["state"] != "UNKNOWN":
                    return False
                self.recorder.record_late_acceptance(
                    phase_id=phase.phase_id, driver_goal_id=event.goal_id,
                )
                with self._lock:
                    self._current_goal_id = event.goal_id
                self.recorder.record_late_cancel_request(
                    phase_id=phase.phase_id, driver_goal_id=event.goal_id,
                )
                acknowledged = self.goal_port.cancel_goal(event.goal_id)
                if type(acknowledged) is bool:
                    self.recorder.record_cancel_ack(
                        phase_id=phase.phase_id, acknowledged=acknowledged,
                    )
                return True
            else:
                return False
            with self._lock:
                self._current_goal_id = event.goal_id
            if (self.current_fence(self.grant.authority_epoch, self.grant.dispatch_generation)
                    and self.submission_fence.is_open(
                        authority_epoch=self.grant.authority_epoch,
                        dispatch_generation=self.grant.dispatch_generation,
                    )):
                return True
            self.recorder.request_cancel(phase_id=phase.phase_id)
            acknowledged = self.goal_port.cancel_goal(event.goal_id)
            if type(acknowledged) is bool:
                self.recorder.record_cancel_ack(
                    phase_id=phase.phase_id, acknowledged=acknowledged,
                )
            self.recorder.hold(reason="STOP_GENERATION_FENCED_AFTER_GOAL_ACCEPTANCE")
            return True
        if goal_id is None or event.goal_id != goal_id:
            return False
        if event.kind == "RUNNING_FEEDBACK":
            with self._lock:
                self._feedback_events += 1
                if self._running_journaled_goal == goal_id:
                    # ~100 Hz JTC feedback: no storage I/O in the ROS callback (C3 run4).
                    return True
        parent = self.recorder.parent()
        if (parent is not None and parent["state"] in {"UNKNOWN", "HOLD"}
                and any(row["phase_id"] == phase.phase_id and row["state"] == "UNKNOWN"
                        for row in self.recorder.phases())):
            return True
        if event.kind == "RUNNING_FEEDBACK":
            try:
                self.recorder.mark_running(
                    phase_id=phase.phase_id, driver_goal_id=goal_id,
                )
            except Exception:
                rows = self.recorder.phases()
                current = next((row for row in rows if row["phase_id"] == phase.phase_id), None)
                if current is None or current["state"] != "RUNNING":
                    return False
            parent = self.recorder.parent()
            if parent is not None and parent["state"] == "ACCEPTED":
                self.recorder.mark_action_running(driver_goal_id=goal_id)
            with self._lock:
                self._running_journaled_goal = goal_id
            return True
        if event.kind == "CANCEL_ACK":
            if self._cancel_ack_recorded:
                return True
            self.recorder.record_cancel_ack(
                phase_id=phase.phase_id,
                acknowledged=bool(event.cancel_acknowledged),
            )
            self._cancel_ack_recorded = True
            return True
        if event.kind == "TERMINAL_UNKNOWN":
            self.recorder.hold(reason="ROS_TERMINAL_RESULT_UNKNOWN")
            return True
        if event.kind == "TERMINAL_RESULT":
            if event.status == 4 and event.result_code == 0:
                outcome = "SUCCEEDED"
            elif event.status == 5:
                outcome = "CANCELED"
            else:
                outcome = "FAILED"
            observed_at = self.now()
            with self._lock:
                feedback_events = self._feedback_events
            if not math_is_aware(observed_at):
                self.recorder.hold(reason="LOCAL_CLOCK_INVALID")
                return False
            self.recorder.record_terminal(
                phase_id=phase.phase_id, driver_goal_id=goal_id,
                outcome=outcome, result_source="ros-action-result",
                result_observed_at=observed_at.astimezone(timezone.utc).isoformat(),
                result={"status": event.status, "result_code": event.result_code,
                        "event_sequence": event.sequence, "feedback_events": feedback_events},
            )
            return True
        return False

    def cancel_current(self) -> dict[str, object]:
        """Request cancellation of the exact active ROS UUID; ACK is separate."""
        with self._lock:
            phase = self._current_phase
            goal_id = self._current_goal_id
        if phase is None or goal_id is None:
            raise RuntimeError("no accepted ROS goal is active")
        receipt = next((row for row in self.recorder.phases()
                        if row["phase_id"] == phase.phase_id), None)
        if receipt is None or receipt["state"] not in {"ACCEPTED", "RUNNING"}:
            raise RuntimeError("active phase cannot be canceled in its current state")
        requested = self.recorder.request_cancel(phase_id=phase.phase_id)
        acknowledged = self.goal_port.cancel_goal(goal_id)
        if type(acknowledged) is bool and not self._cancel_ack_recorded:
            requested = self.recorder.record_cancel_ack(
                phase_id=phase.phase_id, acknowledged=acknowledged,
            )
            self._cancel_ack_recorded = True
        return requested
