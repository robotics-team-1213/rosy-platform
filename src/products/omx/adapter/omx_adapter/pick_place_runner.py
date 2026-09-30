"""Fenced, one-goal-at-a-time execution of a previously validated local plan."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Callable, Protocol

from core_common.protocol.schemas import FleetActionGrant

from .action_runner import DriverSubmission, StopFence
from .command_owner import TrajectoryCommand
from .local_stop import LocalStopBlocked
from .manipulation_plan import PlannedMotionPhase, ResolvedPickPlacePlan
from .phase_recorder import ActionPhaseRecorder
from .ros_goal_contract import RosGoalEvent


class PhaseGoalPort(Protocol):
    """One local arm owner; submit returns only after ROS acceptance is known."""

    def submit(self, command: TrajectoryCommand, *,
               on_goal_event: Callable[[RosGoalEvent], bool]) -> DriverSubmission: ...

    def cancel_goal(self, driver_goal_id: str) -> bool | None: ...


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
        plan: ResolvedPickPlacePlan,
        *,
        command_for_phase: Callable[[PlannedMotionPhase], TrajectoryCommand],
        goal_port: PhaseGoalPort,
        submission_fence: StopFence,
        phase_gate: Callable[[str], bool],
        current_fence: Callable[[int, int], bool],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.recorder = recorder
        self.grant = grant
        self.plan = plan
        self.command_for_phase = command_for_phase
        self.goal_port = goal_port
        self.submission_fence = submission_fence
        self.phase_gate = phase_gate
        self.current_fence = current_fence
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._current_phase: PlannedMotionPhase | None = None
        self._current_command: TrajectoryCommand | None = None
        self._current_goal_id: str | None = None
        self._submitting = False
        self._pending_events: list[RosGoalEvent] = []
        self._pending_overflow = False
        self._last_event_sequence = 0
        self._cancel_ack_recorded = False

        if (recorder.action_id != grant.action_id
                or recorder.attempt_id != grant.attempt_id):
            raise ValueError("phase recorder identity must match the Fleet grant")
        if not isinstance(plan, ResolvedPickPlacePlan):
            raise ValueError("plan must be a validated ResolvedPickPlacePlan")
        if (not callable(command_for_phase) or not callable(phase_gate)
                or not callable(current_fence)):
            raise ValueError("command factory, semantic phase gate, and current fence must be callable")
        if not math_is_aware(self.now()):
            raise ValueError("clock must return timezone-aware timestamps")

    @property
    def active_phase_id(self) -> str | None:
        with self._lock:
            return None if self._current_phase is None else self._current_phase.phase_id

    @staticmethod
    def _command_digest(command: TrajectoryCommand, phase: PlannedMotionPhase,
                        plan: ResolvedPickPlacePlan) -> str:
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
            "source_state_sequence": phase.source_state_sequence,
            "calibration_revision": phase.calibration_revision,
            "transform_revision": phase.transform_revision,
            "planning_scene_revision": phase.planning_scene_revision,
            "planner_revision": plan.planner_revision,
        }
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _build_command(self, phase: PlannedMotionPhase) -> TrajectoryCommand:
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
        return command

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
        return self._submit_phase(next_phase, first=False)

    def _submit_phase(self, phase: PlannedMotionPhase, *, first: bool) -> dict[str, object]:
        command = self._build_command(phase)
        digest = self._command_digest(command, phase, self.plan)
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
                response = DriverSubmission(accepted=None)
            if not isinstance(response, DriverSubmission):
                response = DriverSubmission(accepted=None)
            if first:
                recorded = self.recorder.record_first_submission(
                    phase_id=phase.phase_id, accepted=response.accepted,
                    driver_goal_id=response.driver_goal_id,
                )
                if response.accepted is None:
                    self.recorder.hold(reason="DRIVER_ACCEPTANCE_UNKNOWN")
                return recorded
            phase_receipt = self.recorder.record_submission(
                phase_id=phase.phase_id, accepted=response.accepted,
                driver_goal_id=response.driver_goal_id,
            )
            if response.accepted is None:
                self.recorder.hold(reason="DRIVER_ACCEPTANCE_UNKNOWN")
            return {"phase": phase_receipt}

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
                self.on_ros_goal_event(event)
        return result

    def on_ros_goal_event(self, event: RosGoalEvent) -> bool:
        """Persist only facts bound to the active command, phase, and goal."""
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
            if self._submitting and event.kind not in {"GOAL_REJECTED", "GOAL_ACCEPTANCE_UNKNOWN"}:
                if len(self._pending_events) >= self._MAX_PENDING_EVENTS:
                    self._pending_overflow = True
                    return False
                self._pending_events.append(event)
                return True
            if event.sequence <= self._last_event_sequence:
                return False
            self._last_event_sequence = event.sequence

        if event.kind in {"GOAL_ACCEPTANCE_UNKNOWN", "GOAL_REJECTED"}:
            return True
        if goal_id is None or event.goal_id != goal_id:
            return False
        if event.kind == "GOAL_ACCEPTED":
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
            if not math_is_aware(observed_at):
                self.recorder.hold(reason="LOCAL_CLOCK_INVALID")
                return False
            self.recorder.record_terminal(
                phase_id=phase.phase_id, driver_goal_id=goal_id,
                outcome=outcome, result_source="ros-action-result",
                result_observed_at=observed_at.astimezone(timezone.utc).isoformat(),
                result={"status": event.status, "result_code": event.result_code,
                        "event_sequence": event.sequence},
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
