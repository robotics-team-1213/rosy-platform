"""Fenced, one-goal-at-a-time execution of a previously validated local plan."""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, replace  # noqa: F401
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol  # noqa: F401

from core_common.protocol.schemas import FleetActionGrant

from ..action_runner import StopFence
from ..command_owner import TrajectoryCommand
from ..gripper_contract import GripperObservation, verify_held_object
from ..local_stop import LocalStopBlocked
from ..manipulation_plan import (
    ExecutionStateSnapshot,
    PlannedMotionPhase,
    ResolvedPickPlacePlan,
)
from ..phase_gate import PHASE_WAIT
from ..phase_command_digest import phase_command_digest
from ..phase_recorder import ActionPhaseRecorder
from ..transfer_motion import (  # noqa: F401
    ArmPlanningProfile as CellPlanningProfile,
    TransferMotionPlan as CellTransferPlan,
    validate_transfer_motion_plan as validate_cell_transfer_plan,
)
from ..ros_goal_contract import RosGoalEvent
from .pick_place_runner_helpers import (  # noqa: F401
    _AFTER_GRASP_PHASES,
    PhaseDispatch,
    PhaseGoalPort,
    _PickPlaceGoalEventMixin,
    _validate_runner_init,
    math_is_aware,
)

_LOG = logging.getLogger(__name__)


class PickPlaceRunner(_PickPlaceGoalEventMixin):
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
        self._submission = threading.local()
        self._pending_events: list[RosGoalEvent] = []
        self._pending_overflow = False
        self._last_event_sequence = 0
        self._cancel_ack_recorded = False
        self._last_command_state_sequence = -1
        # Feedback journaling (C3b A2): RUNNING is journalled once per goal; later feedback
        # is only counted, and the count is journalled with the terminal result.
        self._running_journaled_goal: str | None = None
        self._feedback_events = 0

        _validate_runner_init(
            self,
            recorder,
            grant,
            plan,
            command_for_phase=command_for_phase,
            phase_gate=phase_gate,
            current_fence=current_fence,
            current_execution_state=current_execution_state,
            start_state_tolerances=start_state_tolerances,
            max_joint_state_age_s=max_joint_state_age_s,
            monotonic=monotonic,
            cell_profile=cell_profile,
            gripper_readback=gripper_readback,
            held_object_id=held_object_id,
        )

    def _tolerances(self, phase: PlannedMotionPhase) -> dict[str, float]:
        """Caller tolerances; for CELL_TRANSFER the accepted profile's after-grasp per-joint
        overrides replace them for that phase (C3b A5), never the plan's own claim."""
        return dict(self._tolerances_by_phase[phase.phase_id])

    @property
    def active_phase_id(self) -> str | None:
        with self._lock:
            return None if self._current_phase is None else self._current_phase.phase_id

    def _command_digest(self, command: TrajectoryCommand, phase: PlannedMotionPhase,
                        plan: ResolvedPickPlacePlan | CellTransferPlan,
                        state: ExecutionStateSnapshot) -> str:
        return phase_command_digest(command, phase, plan, state, self._tolerances_by_phase[phase.phase_id])

    def current_submission_digest(self, command):
        """Only the exact synchronous command on its submitting thread has this capability."""
        current = getattr(self._submission, "current", None)
        return current[1] if current is not None and current[0] is command else None

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
        if state.joint_positions.keys() != self._phase_joint_sets[phase.phase_id]:
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
        """Persist and submit only the first phase of a fresh attempt. On PHASE_WAIT (D-780 barrier,
        arrival journaled) nothing is submitted; the owner's tick calls start again after release."""
        gate = self.phase_gate(self.plan.phases[0].phase_id)
        if gate is PHASE_WAIT:
            return {"waiting": self.plan.phases[0].phase_id}
        if gate is not True:
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
        gate = self.phase_gate(next_phase.phase_id)
        if gate is PHASE_WAIT:
            return {"waiting": next_phase.phase_id}
        if gate is not True:
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
            self._submission.current = (command, digest)
            try:
                response = self.goal_port.submit(
                    command, on_goal_event=self.on_ros_goal_event,
                )
            except Exception:
                # The journal says only LOCAL_DISPATCH_UNKNOWN; the cause must still reach the owner's log.
                _LOG.exception("phase %s dispatch outcome unknown", phase.phase_id)
                response = PhaseDispatch(dispatched=None)
            finally:
                del self._submission.current
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
        if overflow or pending:
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
        record = self.recorder.record_first_submission if first else self.recorder.record_submission
        record(phase_id=phase.phase_id, accepted=accepted, driver_goal_id=None)
        if accepted is None:
            self.recorder.hold(reason="LOCAL_DISPATCH_UNKNOWN")
