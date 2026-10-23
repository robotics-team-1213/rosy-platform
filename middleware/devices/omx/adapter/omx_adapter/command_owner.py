"""Hardware-free single-owner policy for a future OMX trajectory client.

This module does not create a ROS node, open serial devices, publish joint
states, or prove that cancellation stopped an actuator. A deployed adapter must
connect its ActionPort to the accepted vendor action and an independent stop
path before enabling any workcell profile.
"""

from __future__ import annotations

from contextlib import contextmanager
import secrets
import threading
import time
from typing import Callable

from .final_state import final_state_reason, normalize_final_state_errors
from .contracts.command_types import (
    KNOWN_OWNERS,
    ActionHandle,
    ActionPort,
    ArmCommandConfig,
    CommandDecision,
    JointStateSnapshot,
    TrajectoryCommand,
    _nonempty,
    _positive_finite,
)
from .manipulation_plan import JointTrajectoryPoint
from .watchdog_observation import JointIntakeObservation, WatchdogObservation, watchdog_observation


def _steady_observation():
    try:
        return time.monotonic()
    except Exception:
        return None  # Diagnostic sampling cannot replace a policy clock read or decision.


class ArmCommandOwner:
    """Serialize command sources and latch faults until fresh, explicit recovery."""

    def __init__(
        self,
        config: ArmCommandConfig,
        action_port: ActionPort,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        wall_monotonic: Callable[[], float] | None = None,
        session_id: str | None = None,
    ) -> None:
        """``monotonic`` is the owner clock (sim time under use_sim_time, else steady wall
        time). ``wall_monotonic`` is given only with a sim owner clock and then requires
        ``config.wall_clock_bound_factor`` (C3b A3)."""
        if wall_monotonic is not None and config.enabled and config.wall_clock_bound_factor is None:
            raise ValueError("a separate wall clock requires config.wall_clock_bound_factor")
        self.config = config
        self._action_port = action_port
        self._monotonic = monotonic
        self._wall = wall_monotonic
        self._joint_state_wall: float | None = None
        self._active_wall: float | None = None
        generated_session = secrets.token_hex(16) if session_id is None else session_id
        self.session_id = _nonempty("session_id", generated_session)
        self._lock = threading.RLock()
        self._state = "ready" if config.enabled else "disabled"
        self._joint_state: JointStateSnapshot | None = None
        self._active: tuple[TrajectoryCommand, ActionHandle, float] | None = None
        self._seen_commands: dict[str, tuple[object, ...]] = {}
        self._highest_observed_sequence = -1
        self._last_command_state_sequence = -1
        self._hold_reason = ""
        self._hold_sequence = -1
        self._control_admission = None
        self.watchdog_observation: WatchdogObservation | None = None
        self.joint_intake_observation: JointIntakeObservation | None = None

    def bind_control_admission(self, admission) -> None:
        """Bind the same-process seat policy before any owner command is admitted."""
        with self._lock:
            if self._active is not None or self._seen_commands or self._control_admission is not None:
                raise RuntimeError("control admission must be bound once before command dispatch")
            if admission.owner is not self:
                raise ValueError("control admission belongs to another owner")
            self._control_admission = admission

    def run_admission_policy(self, operation):
        """Serialize short seat/journal decisions with canonical owner state, without ROS I/O."""
        with self._lock:
            return operation(self._state)

    @contextmanager
    def command_transaction(self):
        """Keep readback selection and synchronous submit together; never await action completion."""
        with self._lock:
            yield

    @property
    def joint_state(self) -> JointStateSnapshot | None:
        """Immutable owner-admitted readback; native intake may still await delivery."""
        with self._lock:
            return self._joint_state

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @staticmethod
    def _fingerprint(command: TrajectoryCommand) -> tuple[object, ...]:
        return (
            command.workcell_id,
            command.instance_id,
            command.owner,
            command.session_id,
            command.phase_id,
            tuple(sorted(command.positions.items())),
            command.joint_names,
            tuple((point.time_from_start_s, point.positions, point.velocities, point.accelerations)
                  for point in command.trajectory_points),
            command.duration_s,
            command.source_state_sequence,
            command.calibration_revision,
            tuple(sorted(command.expected_start_state_positions.items()))
            if command.expected_start_state_positions is not None else None,
            tuple(sorted(command.start_state_tolerances.items()))
            if command.start_state_tolerances is not None else None,
        )

    def _decision(
        self,
        accepted: bool,
        reason: str,
        command_id: str | None = None,
        cancel_outcome: str | None = None,
    ) -> CommandDecision:
        return CommandDecision(accepted, self._state, reason, command_id, cancel_outcome)

    def _clock_jumped_back(self, now: float) -> bool:
        """Owner clock earlier than a recorded stamp: a sim world reset (review minor 2).
        Ages would go negative and no timeout would fire, so it is a HOLD of its own."""
        snapshot = self._joint_state
        return ((snapshot is not None and now < snapshot.received_at)
                or (self._active is not None and now < self._active[2]))

    def _fresh_joint_state(self, now: float) -> bool:
        snapshot = self._joint_state
        if snapshot is None or now < snapshot.received_at:
            return False
        return now - snapshot.received_at <= self.config.max_joint_state_age_s

    def _wall_stale_reason(self) -> str | None:
        return self._wall_stale_check()[0]

    def _wall_stale_check(self) -> tuple[str | None, float | None]:
        """Outer wall-clock bound; only with a sim owner clock (C3b A3)."""
        if self._wall is None or self.config.wall_clock_bound_factor is None:
            return None, None
        factor = self.config.wall_clock_bound_factor
        now = self._wall()
        if (self._joint_state_wall is None
                or now - self._joint_state_wall > self.config.max_joint_state_age_s * factor):
            return "joint_state_stale_wall_clock", now
        if (self._active_wall is not None
                and now - self._active_wall >= self.config.action_timeout_s * factor):
            return "action_wall_timeout", now
        return None, now

    def _watchdog_hold(self, reason, command, now, wall_now=None, *, now_bracket=(None, None)):
        # Freeze the exact decision before cancel() can block or deliver callbacks.
        # A later HOLD poll or feedback does not rewrite this transition's evidence.
        try:
            self.watchdog_observation = watchdog_observation(
                reason, command, self._joint_state, self.config, owner_now=now,
                steady_now=time.monotonic(), joint_wall=self._joint_state_wall,
                active_started_at=self._active[2], active_wall=self._active_wall, wall_now=wall_now,
                intake=self.joint_intake_observation,
                owner_now_steady_before=now_bracket[0], owner_now_steady_after=now_bracket[1])
        except Exception:
            self.watchdog_observation = None  # Evidence failure cannot suppress HOLD/cancel.
        return self._enter_hold(reason)

    def _cancel_active(self) -> str | None:
        active, self._active = self._active, None
        self._active_wall = None
        if active is None:
            return None
        handle = active[1]
        try:
            if handle.done():
                return "already_done"
        except Exception:
            # Try cancellation even if the completion probe failed.
            pass
        try:
            handle.cancel()
        except Exception:
            # HOLD remains latched; dispatch failure is not standstill proof.
            return "call_failed"
        # The method returning is not proof the action server accepted cancellation.
        return "call_returned"

    def _enter_hold(self, reason: str) -> str | None:
        if self._state == "disabled":
            return None
        self._hold_reason = reason
        self._hold_sequence = self._highest_observed_sequence
        self._state = "hold"
        return self._cancel_active()

    def observe_joint_state(self, snapshot: JointStateSnapshot) -> bool:
        with self._lock:
            if not self.config.enabled:
                return False
            if snapshot.sequence <= self._highest_observed_sequence:
                self._enter_hold("joint_state_sequence_not_increasing")
                return False
            self._highest_observed_sequence = snapshot.sequence
            if snapshot.received_at > self._monotonic():
                self._enter_hold("joint_state_from_future")
                return False
            if self._joint_state is not None and snapshot.received_at < self._joint_state.received_at:
                self._enter_hold("owner_clock_jumped_back")
                return False
            if set(snapshot.positions) != set(self.config.joint_names):
                self._enter_hold("joint_state_joint_map_mismatch")
                return False
            if snapshot.calibration_revision != self.config.calibration_revision:
                self._enter_hold("calibration_mismatch")
                return False
            for name, position in snapshot.positions.items():
                lower, upper = self.config.position_limits[name]
                if position < lower or position > upper:
                    self._enter_hold("joint_state_limit")
                    return False
            self._joint_state = snapshot
            if self._wall is not None:
                self._joint_state_wall = self._wall()
            return True

    def submit(self, command: TrajectoryCommand) -> CommandDecision:
        with self._lock:
            command_id = command.command_id
            if not self.config.enabled:
                return self._decision(False, "disabled", command_id)
            if self._state == "hold":
                return self._decision(False, "hold_latched", command_id)
            fingerprint = self._fingerprint(command)
            previous = self._seen_commands.get(command_id)
            if previous is not None:
                if previous == fingerprint and self._active and self._active[0].command_id == command_id:
                    return self._decision(True, "duplicate_ignored", command_id)
                return self._decision(False, "command_id_reused", command_id)
            if self._state == "active":
                return self._decision(False, "busy", command_id)
            now = self._monotonic()
            if self._joint_state is None:
                return self._decision(False, "joint_state_missing", command_id)
            if self._clock_jumped_back(now):
                self._enter_hold("owner_clock_jumped_back")
                return self._decision(False, "owner_clock_jumped_back", command_id)
            if not self._fresh_joint_state(now):
                self._enter_hold("joint_state_stale")
                return self._decision(False, "joint_state_stale", command_id)
            wall_reason = self._wall_stale_reason()
            if wall_reason is not None:
                self._enter_hold(wall_reason)
                return self._decision(False, wall_reason, command_id)
            if command.workcell_id != self.config.workcell_id:
                return self._decision(False, "workcell_mismatch", command_id)
            if command.instance_id != self.config.instance_id:
                return self._decision(False, "instance_mismatch", command_id)
            if command.session_id != self.session_id:
                return self._decision(False, "session_mismatch", command_id)
            if command.owner not in self.config.allowed_owners:
                return self._decision(False, "owner_not_allowed", command_id)
            if command.calibration_revision != self.config.calibration_revision:
                return self._decision(False, "calibration_mismatch", command_id)
            if command.source_state_sequence > self._joint_state.sequence:
                return self._decision(False, "joint_state_sequence_mismatch", command_id)
            if command.source_state_sequence <= self._last_command_state_sequence:
                return self._decision(False, "joint_state_not_advanced", command_id)
            if command.expected_start_state_positions is None:
                if command.source_state_sequence != self._joint_state.sequence:
                    return self._decision(False, "joint_state_sequence_mismatch", command_id)
            else:
                maximum_tolerances = self.config.max_start_state_tolerances
                if maximum_tolerances is None:
                    return self._decision(False, "start_state_tolerance_policy_missing", command_id)
                if any(command.start_state_tolerances[name] > maximum_tolerances[name]
                       for name in command.joint_names):
                    return self._decision(False, "start_state_tolerance_exceeds_policy", command_id)
                if any(
                    abs(self._joint_state.positions[name] - command.expected_start_state_positions[name])
                    > command.start_state_tolerances[name]
                    for name in command.joint_names
                ):
                    return self._decision(False, "start_state_outside_tolerance", command_id)
            if command.duration_s > self.config.max_goal_duration_s:
                return self._decision(False, "duration_limit", command_id)
            if set(command.positions) != set(self.config.joint_names):
                return self._decision(False, "joint_map_mismatch", command_id)
            points = command.trajectory_points
            if len(points) > 1 and (
                self.config.velocity_limits is None or self.config.acceleration_limits is None
            ):
                return self._decision(False, "trajectory_rate_limits_missing", command_id)
            if len(points) > 1 and any(
                point.velocities is None or point.accelerations is None for point in points
            ):
                return self._decision(False, "trajectory_derivatives_missing", command_id)
            for point in points:
                for name, position in zip(command.joint_names, point.positions):
                    lower, upper = self.config.position_limits[name]
                    if position < lower or position > upper:
                        return self._decision(False, "joint_limit", command_id)
                for values, limits, reason in (
                    (point.velocities, self.config.velocity_limits, "velocity_limit"),
                    (point.accelerations, self.config.acceleration_limits, "acceleration_limit"),
                ):
                    if values is None:
                        continue
                    if limits is None:
                        return self._decision(False, "trajectory_rate_limits_missing", command_id)
                    if any(abs(value) > limits[name]
                           for name, value in zip(command.joint_names, values)):
                        return self._decision(False, reason, command_id)
            if self._control_admission is not None and not self._control_admission.check_command(command):
                return self._decision(False, "control_seat_fenced", command_id)
            self._seen_commands[command_id] = fingerprint
            try:
                handle = self._action_port.send_goal(command)
            except Exception:
                self._enter_hold("action_submission_failed")
                return self._decision(False, "action_submission_failed", command_id)
            self._last_command_state_sequence = self._joint_state.sequence
            self._active = (command, handle, now)
            self._active_wall = None if self._wall is None else self._wall()
            post = getattr(self._control_admission, 'check_after_submission', None)
            try:
                admitted = post is None or post(command) is True
            except Exception:
                admitted = False
            if not admitted:
                canceled = self._enter_hold('control_admission_lost')
                return self._decision(False, 'control_admission_lost', command_id, canceled)
            self._state = "active"
            return self._decision(True, "submitted", command_id)

    def poll(self) -> CommandDecision:
        """Check current action/feedback state; the runtime must call this periodically.

        This policy object has no scheduler or ROS executor. A caller that does
        not arrange a bounded periodic invocation gets no autonomous timeout
        enforcement from this method.
        """
        with self._lock:
            if self._state == "disabled":
                return self._decision(False, "disabled")
            if self._state == "hold":
                return self._decision(False, self._hold_reason)
            if self._state != "active" or self._active is None:
                return self._decision(True, "ready")
            command, handle, started_at = self._active
            steady_before = _steady_observation()
            now = self._monotonic()
            now_bracket = (steady_before, _steady_observation())
            if self._clock_jumped_back(now):
                cancel_outcome = self._watchdog_hold("owner_clock_jumped_back", command, now, now_bracket=now_bracket)
                return self._decision(False, "owner_clock_jumped_back", command.command_id, cancel_outcome)
            if not self._fresh_joint_state(now):
                cancel_outcome = self._watchdog_hold("joint_state_stale", command, now, now_bracket=now_bracket)
                return self._decision(
                    False, "joint_state_stale", command.command_id, cancel_outcome
                )
            if now - started_at >= self.config.action_timeout_s:
                cancel_outcome = self._watchdog_hold("action_timeout", command, now, now_bracket=now_bracket)
                return self._decision(False, "action_timeout", command.command_id, cancel_outcome)
            wall_reason, wall_now = self._wall_stale_check()
            if wall_reason is not None:
                cancel_outcome = self._watchdog_hold(wall_reason, command, now, wall_now, now_bracket=now_bracket)
                return self._decision(False, wall_reason, command.command_id, cancel_outcome)
            try:
                if not handle.done():
                    return self._decision(True, "active", command.command_id)
                succeeded = handle.succeeded()
            except Exception:
                succeeded = False
            self._active = None
            self._active_wall = None
            reason = (final_state_reason(self.config.max_final_state_errors, command, self._joint_state)
                      if succeeded else "action_failed")
            if reason is None:
                self._state = "ready"
                return self._decision(True, "completed", command.command_id)
            self._enter_hold(reason)
            return self._decision(False, reason, command.command_id)

    def preempt(self, reason: str) -> CommandDecision:
        """Arbiter-only cross-owner stop (D-442 U3); never dispatch a new goal.

        Arbiter and guard currently share this owner. Producers retain the
        owner-matched cancel API; neither HTTP nor Action IPC exposes preempt.
        Cancellation acknowledgement is not standstill evidence. Only recover
        with explicit confirmation and post-HOLD feedback can clear this latch.
        """
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 128:
            raise ValueError("preempt reason must be a nonempty bounded string")
        with self._lock:
            if self._state == "disabled":
                return self._decision(False, "disabled")
            if self._state == "hold":
                return self._decision(False, self._hold_reason)
            command_id = self._active[0].command_id if self._active is not None else None
            hold_reason = f"preempt:{reason}"
            cancel_outcome = self._enter_hold(hold_reason)
            return self._decision(False, hold_reason, command_id, cancel_outcome)

    def cancel(self, *, command_id: str, owner: str) -> CommandDecision:
        with self._lock:
            if self._state != "active" or self._active is None:
                return self._decision(False, "not_active", command_id)
            active_command = self._active[0]
            if active_command.command_id != command_id or active_command.owner != owner:
                return self._decision(False, "active_command_mismatch", command_id)
            cancel_outcome = self._enter_hold("cancel_requested")
            reason = "cancel_call_failed" if cancel_outcome == "call_failed" else "cancel_requested"
            return self._decision(False, reason, command_id, cancel_outcome)

    def recovery_state(self) -> dict:
        """Atomic, read-only owner feedback for operator recovery, without motion."""
        with self._lock:
            return {"state": self._state, "reason": self._hold_reason,
                    "observed_sequence": self._joint_state.sequence if self._joint_state else None}

    def recover(self, *, operator_confirmed: bool, observed_sequence: int,
                recovery_fence: Callable | None = None) -> CommandDecision:
        with self._lock:
            if self._state != "hold":
                return self._decision(False, "not_in_hold")
            if operator_confirmed is not True:
                return self._decision(False, "operator_confirmation_required")
            now = self._monotonic()
            snapshot = self._joint_state
            if (
                snapshot is None
                or observed_sequence != snapshot.sequence
                or snapshot.sequence <= self._hold_sequence
                or not self._fresh_joint_state(now)
                or snapshot.calibration_revision != self.config.calibration_revision
            ):
                return self._decision(False, "fresh_readback_required")

            def clear_hold() -> CommandDecision:
                self._hold_reason = ""
                self._state = "ready"
                return self._decision(True, "recovered")
            # Transport fencing runs under the owner lock, preserving the
            # stop -> owner -> journal lock order and feedback identity.
            original_reason = self._hold_reason
            try:
                return clear_hold() if recovery_fence is None else recovery_fence(clear_hold)
            except Exception:
                # A failed journal commit cannot leave the failed recovery
                # ready. Restore under the same lock without cancel or motion.
                self._hold_reason = original_reason
                self._state = "hold"
                raise
