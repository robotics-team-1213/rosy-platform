"""Fenced, one-goal-at-a-time execution of a previously validated local plan."""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol

from core_common.protocol.schemas import FleetActionGrant

from .action_runner import StopFence
from .command_owner import TrajectoryCommand
from .gripper_contract import GripperObservation, verify_held_object
from .local_stop import LocalStopBlocked
from .manipulation_plan import (
    ExecutionStateSnapshot,
    PlannedMotionPhase,
    ResolvedPickPlacePlan,
)
from .phase_recorder import ActionPhaseRecorder
from .pose_plan import CellPlanningProfile, CellTransferPlan, validate_cell_transfer_plan
from .ros_goal_contract import RosGoalEvent


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


class PickPlaceRunner:
    """Coordinate ordered ROS phases without granting the model actuator access.

    The caller supplies an ActionPhaseRecorder minted after Fleet peer/grant
    validation, a resolved plan, one local command owner port, and the existing
    generation/stop fence. This class does not produce poses or trajectories.
    """

    _MAX_PENDING_EVENTS = 64

    def __init__(
        self,
        recorder: ActionPhaseRecorder,
        grant: FleetActionGrant,
        plan: ResolvedPickPlacePlan | CellTransferPlan,
        *,
        command_for_phase: Callable[[PlannedMotionPhase], TrajectoryCommand],
        goal_port: PhaseGoalPort,
        submission_fence: StopFence,
        phase_gate: Callable[[str], bool],
        current_fence: Callable[[int, int], bool],
        current_execution_state: Callable[[], ExecutionStateSnapshot],
        start_state_tolerances: Mapping[str, float],
        max_joint_state_age_s: float,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
        cell_profile: CellPlanningProfile | None = None,
        gripper_readback: Callable[[], GripperObservation] | None = None,
        held_object_id: str | None = None,
    ) -> None:
        self.recorder = recorder
        self.grant = grant
        self.plan = plan
        self.command_for_phase = command_for_phase
        self.goal_port = goal_port
        self.submission_fence = submission_fence
        self.phase_gate = phase_gate
        self.current_fence = current_fence
        self.current_execution_state = current_execution_state
        self.monotonic = monotonic
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._event_lock = threading.RLock()
        self._current_phase: PlannedMotionPhase | None = None
        self._current_command: TrajectoryCommand | None = None
        self._current_goal_id: str | None = None
        self._submitting = False
        self._pending_events: list[RosGoalEvent] = []
        self._pending_overflow = False
        self._last_event_sequence = 0
        self._cancel_ack_recorded = False
        self._last_command_state_sequence = -1
        # Feedback journaling (C3b A2): RUNNING is journalled once per goal; later feedback
        # is only counted, and the count is journalled with the terminal result.
        self._running_journaled_goal: str | None = None
        self._feedback_events = 0

        if not isinstance(plan, (ResolvedPickPlacePlan, CellTransferPlan)):
            raise ValueError("plan must be a validated ResolvedPickPlacePlan or CellTransferPlan")
        if not callable(monotonic):
            raise ValueError("fresh execution-state and monotonic clock providers are required")
        # CELL_TRANSFER (simulation, D-402 §3d): after grasp the gripper stops at the
        # object width, so in transfer/release gripper_contract readback judges it,
        # not the start-state value. approach/grasp check it like any joint. The
        # skipped set is the accepted profile's gripper, never the plan's own claim.
        self._unchecked_joints: frozenset[str] = frozenset()
        if isinstance(plan, CellTransferPlan):
            if not isinstance(cell_profile, CellPlanningProfile):
                raise ValueError("a CellTransferPlan requires the accepted cell_profile")
            validate_cell_transfer_plan(
                plan, cell_profile, kinematics_revision=cell_profile.kinematics_revision,
                now_monotonic_s=monotonic(),
            )
            self._unchecked_joints = frozenset({cell_profile.gripper_joint})
            # A4 (C3b): the hold is re-read right before release (C3 run8 dropped the block
            # in transit and still passed every gate).
            if not callable(gripper_readback) or not isinstance(held_object_id, str) or not held_object_id:
                raise ValueError("a CellTransferPlan requires gripper_readback and held_object_id")
        self._cell_profile = cell_profile if isinstance(plan, CellTransferPlan) else None
        self.gripper_readback = gripper_readback
        self.held_object_id = held_object_id
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
        self.start_state_tolerances = normalized_tolerances
        self.max_joint_state_age_s = max_state_age

        if (recorder.action_id != grant.action_id
                or recorder.attempt_id != grant.attempt_id):
            raise ValueError("phase recorder identity must match the Fleet grant")
        if (not callable(command_for_phase) or not callable(phase_gate)
                or not callable(current_fence)):
            raise ValueError("command factory, semantic phase gate, and current fence must be callable")
        if not math_is_aware(self.now()):
            raise ValueError("clock must return timezone-aware timestamps")

    def _tolerances(self, phase: PlannedMotionPhase) -> dict[str, float]:
        """Caller tolerances; for CELL_TRANSFER the accepted profile's after-grasp per-joint
        overrides replace them for that phase (C3b A5), never the plan's own claim."""
        tolerances = dict(self.start_state_tolerances)
        if self._cell_profile is not None:
            tolerances.update(self._cell_profile.phase_start_state_tolerance_rad.get(phase.phase_id, {}))
        return tolerances

    @property
    def active_phase_id(self) -> str | None:
        with self._lock:
            return None if self._current_phase is None else self._current_phase.phase_id

    def _command_digest(self, command: TrajectoryCommand, phase: PlannedMotionPhase,
                        plan: ResolvedPickPlacePlan | CellTransferPlan,
                        state: ExecutionStateSnapshot) -> str:
        document = {
            "command_id": command.command_id,
            "phase_id": phase.phase_id,
            "ordinal": phase.ordinal,
            "joint_names": command.joint_names,
            "points": [
                {
                    "time_from_start_s": point.time_from_start_s,
                    "positions": point.positions,
                    "velocities": point.velocities,
                    "accelerations": point.accelerations,
                }
                for point in command.trajectory_points
            ],
            "planned_source_state_sequence": phase.source_state_sequence,
            "execution_state_sequence": state.sequence,
            "execution_joint_positions": dict(state.joint_positions),
            "start_state_positions": phase.start_state_positions,
            "start_state_tolerances": self._tolerances(phase),
            "calibration_revision": phase.calibration_revision,
            "transform_revision": phase.transform_revision,
            "planning_scene_revision": phase.planning_scene_revision,
            "planner_revision": plan.planner_revision,
        }
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _build_command(
        self, phase: PlannedMotionPhase,
    ) -> tuple[TrajectoryCommand, ExecutionStateSnapshot]:
        state = self.current_execution_state()
        if not isinstance(state, ExecutionStateSnapshot):
            raise ValueError("phase start state provider returned an invalid snapshot")
        current_time = self.monotonic()
        if (not math.isfinite(current_time) or state.observed_at_monotonic_s > current_time
                or current_time - state.observed_at_monotonic_s > self.max_joint_state_age_s):
            raise ValueError("phase start state is stale or from the future")
        if state.sequence <= self._last_command_state_sequence:
            raise ValueError("phase start state sequence did not advance")
        if set(state.joint_positions) != set(phase.joint_names):
            raise ValueError("phase start state joint map does not match the plan")
        if (state.calibration_revision != phase.calibration_revision
                or state.transform_revision != phase.transform_revision
                or state.planning_scene_revision != phase.planning_scene_revision):
            raise ValueError("phase start state calibration, transform, or planning scene changed")
        tolerances = self._tolerances(phase)
        # Owner reference = the planned start (main 11ae6e70: the tolerance budget stays the
        # planned one). Exception: the CELL_TRANSFER gripper after grasp, whose readback is the
        # item width, not the plan (D-402 §3d); it is bound to the value checked here instead.
        expected_start: dict[str, float] = {}
        for name, expected in zip(phase.joint_names, phase.start_state_positions):
            if name in self._unchecked_joints and phase.phase_id in _AFTER_GRASP_PHASES:
                expected_start[name] = state.joint_positions[name]
                continue
            if abs(state.joint_positions[name] - expected) > tolerances[name]:
                raise ValueError("phase start state is outside the planned tolerance")
            expected_start[name] = expected

        command = self.command_for_phase(phase)
        if not isinstance(command, TrajectoryCommand):
            raise TypeError("phase command factory must return TrajectoryCommand")
        if (command.workcell_id != self.grant.workcell_id
                or command.instance_id != self.grant.instance_id
                or command.phase_id != phase.phase_id
                or command.source_state_sequence != phase.source_state_sequence
                or command.calibration_revision != phase.calibration_revision
                or command.joint_names != phase.joint_names
                or command.trajectory_points != phase.points):
            raise ValueError("phase command identity/path does not match the validated plan")
        self._last_command_state_sequence = state.sequence
        # Rebind only after an explicit bounded start-state and revision match. The journal
        # write follows and joint states keep arriving, so ArmCommandOwner repeats this check
        # on its newest fresh state under its lock at the final dispatch edge (C3b A1, b0979ad6).
        return replace(
            command,
            source_state_sequence=state.sequence,
            expected_start_state_positions=expected_start,
            start_state_tolerances=tolerances,
        ), state

    def start(self) -> dict[str, object]:
        """Persist and submit only the first phase of a fresh attempt."""
        if self.phase_gate(self.plan.phases[0].phase_id) is not True:
            raise RuntimeError("semantic workflow gate does not permit the first motion phase")
        if self.recorder.phases():
            raise RuntimeError("phase journal is not empty; automatic replay is forbidden")
        return self._submit_phase(self.plan.phases[0], first=True)

    def advance(self) -> dict[str, object]:
        """Submit the next phase only after matching prior SUCCEEDED evidence.

        Semantic gripper/object checks belong to the transaction caller. This
        method deliberately advances at most one ROS goal and never retries.
        """
        phases = self.recorder.phases()
        if not phases:
            raise RuntimeError("first phase has not been submitted")
        previous = phases[-1]
        if previous["state"] != "SUCCEEDED" or previous["driver_goal_id"] is None:
            raise RuntimeError("next phase requires the prior matching goal to succeed")
        next_ordinal = int(previous["ordinal"]) + 1
        if next_ordinal >= len(self.plan.phases):
            raise RuntimeError("all planned motion phases have already been submitted")
        next_phase = self.plan.phases[next_ordinal]
        if self.phase_gate(next_phase.phase_id) is not True:
            raise RuntimeError("semantic workflow gate does not permit the next motion phase")
        if self._current_phase is None or self._current_phase.ordinal != previous["ordinal"]:
            raise RuntimeError("prior phase identity is not the coordinator's active phase")
        if self._current_goal_id != previous["driver_goal_id"]:
            raise RuntimeError("prior terminal result does not match the active ROS goal")
        if isinstance(self.plan, CellTransferPlan) and next_phase.phase_id == "release":
            try:
                verify_held_object(self.gripper_readback(), object_id=self.held_object_id,
                                   now=self.monotonic(), max_age_s=self.max_joint_state_age_s)
            except Exception as exc:
                self.recorder.hold(reason="ITEM_LOST_IN_TRANSIT")
                raise RuntimeError("item_lost_in_transit: gripper no longer proves the hold; "
                                   "release is not submitted") from exc
        return self._submit_phase(next_phase, first=False)

    def _submit_phase(self, phase: PlannedMotionPhase, *, first: bool) -> dict[str, object]:
        try:
            command, execution_state = self._build_command(phase)
        except Exception as exc:
            self.recorder.hold(reason="PHASE_START_STATE_INVALID")
            raise RuntimeError("phase start state is invalid; execution is held") from exc
        digest = self._command_digest(command, phase, self.plan, execution_state)
        with self._lock:
            if self._submitting:
                raise RuntimeError("another phase submission is already in progress")
            self._current_phase = phase
            self._current_command = command
            self._current_goal_id = None
            self._last_event_sequence = 0
            self._cancel_ack_recorded = False
            self._pending_events.clear()
            self._pending_overflow = False
            self._running_journaled_goal = None
            self._feedback_events = 0
            self._submitting = True

        try:
            self.recorder.begin_phase(
                phase_id=phase.phase_id, ordinal=phase.ordinal, command_digest=digest,
            )
        except Exception:
            with self._lock:
                self._submitting = False
            raise

        def submit_and_record() -> dict[str, object]:
            try:
                response = self.goal_port.submit(
                    command, on_goal_event=self.on_ros_goal_event,
                )
            except Exception:
                response = PhaseDispatch(dispatched=None)
            if not isinstance(response, PhaseDispatch):
                response = PhaseDispatch(dispatched=None)
            if response.dispatched is not True:
                self._record_dispatch_failure(phase, first, response.dispatched)
            return {"dispatched": response.dispatched}

        try:
            result = self.submission_fence.run_if_open(
                authority_epoch=self.grant.authority_epoch,
                dispatch_generation=self.grant.dispatch_generation,
                fleet_fence_current=lambda: self.current_fence(
                    self.grant.authority_epoch, self.grant.dispatch_generation,
                ),
                operation=submit_and_record,
            )
        except LocalStopBlocked:
            self.recorder.hold(reason="STOP_GENERATION_FENCED")
            result = {"reason": "STOP_GENERATION_FENCED"}
        except Exception:
            # The durable intent remains unresolved if storage or result
            # recording failed. Never submit this phase again in this process.
            self.recorder.hold(reason="PHASE_RESULT_RECORDING_UNKNOWN")
            raise

        phase_rows = self.recorder.phases()
        recorded = next((row for row in phase_rows if row["phase_id"] == phase.phase_id), None)
        # Hold the event lock from clearing _submitting until the queue is replayed: a live
        # event (e.g. feedback) must not overtake a queued GOAL_ACCEPTED (C3b run9).
        with self._event_lock:
            with self._lock:
                self._submitting = False
                self._current_goal_id = recorded["driver_goal_id"] if recorded else None
                pending = tuple(self._pending_events)
                overflow = self._pending_overflow
                self._pending_events.clear()
            if overflow:
                self.recorder.hold(reason="ROS_EVENT_BUFFER_OVERFLOW")
            else:
                for event in pending:
                    self._process_ros_goal_event(event)
        if result.get("reason") == "STOP_GENERATION_FENCED":
            return result
        phase_rows = self.recorder.phases()
        recorded = next((row for row in phase_rows if row["phase_id"] == phase.phase_id), None)
        action = self.recorder.parent()
        if recorded is None or action is None:
            self.recorder.hold(reason="PHASE_ACCEPTANCE_RECORDING_UNKNOWN")
            raise RuntimeError("phase dispatch lost its durable journal record")
        return {"action": action, "phase": recorded, "dispatched": result.get("dispatched")}

    def _record_dispatch_failure(self, phase: PlannedMotionPhase, first: bool,
                                 dispatched: bool | None) -> None:
        accepted = False if dispatched is False else None
        if first:
            self.recorder.record_first_submission(
                phase_id=phase.phase_id, accepted=accepted, driver_goal_id=None,
            )
        else:
            self.recorder.record_submission(
                phase_id=phase.phase_id, accepted=accepted, driver_goal_id=None,
            )
        if accepted is None:
            self.recorder.hold(reason="LOCAL_DISPATCH_UNKNOWN")

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


def math_is_aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
