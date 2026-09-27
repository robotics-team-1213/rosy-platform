"""Hardware-free single-owner policy for a future OMX trajectory client.

This module does not create a ROS node, open serial devices, publish joint
states, or prove that cancellation stopped an actuator. A deployed adapter must
connect its ActionPort to the accepted vendor action and an independent stop
path before enabling any workcell profile.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping, Protocol


KNOWN_OWNERS = frozenset({"leader_teleop", "moveit", "rule_based", "learned_policy"})


def _positive_finite(name: str, value: object) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return number


def _nonempty(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ArmCommandConfig:
    """Explicit command policy; disabled and unconfigured by default."""

    enabled: bool = False
    workcell_id: str = ""
    instance_id: str = ""
    joint_names: tuple[str, ...] = ()
    position_limits: Mapping[str, tuple[float, float]] | None = None
    allowed_owners: tuple[str, ...] = ()
    calibration_revision: str = ""
    max_joint_state_age_s: float = 0.5
    max_goal_duration_s: float = 1.0
    action_timeout_s: float = 2.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be boolean")
        if not self.enabled:
            return
        _nonempty("workcell_id", self.workcell_id)
        _nonempty("instance_id", self.instance_id)
        _nonempty("calibration_revision", self.calibration_revision)
        names = tuple(self.joint_names)
        if not names or any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError("enabled command policy requires joint_names")
        if len(set(names)) != len(names):
            raise ValueError("joint_names must be unique")
        limits = dict(self.position_limits or {})
        if set(limits) != set(names):
            raise ValueError("position_limits must exactly match joint_names")
        normalized: dict[str, tuple[float, float]] = {}
        for name in names:
            try:
                lower, upper = limits[name]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"position limit for {name} must contain lower and upper bounds") from exc
            if isinstance(lower, bool) or isinstance(upper, bool):
                raise ValueError(f"position limit for {name} must be finite and increasing")
            values = (float(lower), float(upper))
            if not all(math.isfinite(value) for value in values) or values[0] >= values[1]:
                raise ValueError(f"position limit for {name} must be finite and increasing")
            normalized[name] = values
        object.__setattr__(self, "joint_names", names)
        object.__setattr__(self, "position_limits", MappingProxyType(normalized))
        owners = tuple(self.allowed_owners)
        if not owners or len(set(owners)) != len(owners) or not set(owners) <= KNOWN_OWNERS:
            raise ValueError("allowed_owners must be a non-empty unique subset of known owners")
        object.__setattr__(self, "allowed_owners", owners)
        object.__setattr__(self, "max_joint_state_age_s", _positive_finite(
            "max_joint_state_age_s", self.max_joint_state_age_s
        ))
        object.__setattr__(self, "max_goal_duration_s", _positive_finite(
            "max_goal_duration_s", self.max_goal_duration_s
        ))
        object.__setattr__(self, "action_timeout_s", _positive_finite(
            "action_timeout_s", self.action_timeout_s
        ))
        if self.action_timeout_s < self.max_goal_duration_s:
            raise ValueError("action_timeout_s must be at least max_goal_duration_s")


@dataclass(frozen=True)
class JointStateSnapshot:
    positions: Mapping[str, float]
    sequence: int
    received_at: float
    calibration_revision: str

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("joint-state sequence must be a non-negative integer")
        try:
            received_at = float(self.received_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("joint-state receive time must be finite monotonic time") from exc
        if isinstance(self.received_at, bool) or not math.isfinite(received_at):
            raise ValueError("joint-state receive time must be finite monotonic time")
        object.__setattr__(self, "received_at", received_at)
        normalized = dict(self.positions)
        for name, value in normalized.items():
            if not isinstance(name, str) or not name.strip() or isinstance(value, bool):
                raise ValueError("joint-state positions must be named finite numbers")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("joint-state positions must be named finite numbers") from exc
            if not math.isfinite(number):
                raise ValueError("joint-state positions must be named finite numbers")
            normalized[name] = number
        object.__setattr__(self, "positions", MappingProxyType(normalized))
        _nonempty("calibration_revision", self.calibration_revision)


@dataclass(frozen=True)
class TrajectoryCommand:
    workcell_id: str
    instance_id: str
    command_id: str
    session_id: str
    owner: str
    positions: Mapping[str, float]
    duration_s: float
    source_state_sequence: int
    calibration_revision: str

    def __post_init__(self) -> None:
        for field_name in (
            "workcell_id", "instance_id", "command_id", "session_id", "owner", "calibration_revision"
        ):
            _nonempty(field_name, getattr(self, field_name))
        if type(self.source_state_sequence) is not int or self.source_state_sequence < 0:
            raise ValueError("source_state_sequence must be a non-negative integer")
        normalized = dict(self.positions)
        for name, value in normalized.items():
            if not isinstance(name, str) or not name.strip() or isinstance(value, bool):
                raise ValueError("command positions must be named finite numbers")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("command positions must be named finite numbers") from exc
            if not math.isfinite(number):
                raise ValueError("command positions must be named finite numbers")
            normalized[name] = number
        object.__setattr__(self, "positions", MappingProxyType(normalized))
        object.__setattr__(self, "duration_s", _positive_finite("duration_s", self.duration_s))


class ActionHandle(Protocol):
    def cancel(self) -> object: ...
    def done(self) -> bool: ...
    def succeeded(self) -> bool: ...


class ActionPort(Protocol):
    def send_goal(self, command: TrajectoryCommand) -> ActionHandle: ...


@dataclass(frozen=True)
class CommandDecision:
    accepted: bool
    state: str
    reason: str
    command_id: str | None = None
    cancel_outcome: str | None = None


class ArmCommandOwner:
    """Serialize command sources and latch faults until fresh, explicit recovery."""

    def __init__(
        self,
        config: ArmCommandConfig,
        action_port: ActionPort,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        session_id: str | None = None,
    ) -> None:
        self.config = config
        self._action_port = action_port
        self._monotonic = monotonic
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
            tuple(sorted(command.positions.items())),
            command.duration_s,
            command.source_state_sequence,
            command.calibration_revision,
        )

    def _decision(
        self,
        accepted: bool,
        reason: str,
        command_id: str | None = None,
        cancel_outcome: str | None = None,
    ) -> CommandDecision:
        return CommandDecision(accepted, self._state, reason, command_id, cancel_outcome)

    def _fresh_joint_state(self, now: float) -> bool:
        snapshot = self._joint_state
        if snapshot is None or now < snapshot.received_at:
            return False
        return now - snapshot.received_at <= self.config.max_joint_state_age_s

    def _cancel_active(self) -> str | None:
        active, self._active = self._active, None
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
            if not self._fresh_joint_state(now):
                self._enter_hold("joint_state_stale")
                return self._decision(False, "joint_state_stale", command_id)
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
            if command.source_state_sequence != self._joint_state.sequence:
                return self._decision(False, "joint_state_sequence_mismatch", command_id)
            if command.source_state_sequence <= self._last_command_state_sequence:
                return self._decision(False, "joint_state_not_advanced", command_id)
            if command.duration_s > self.config.max_goal_duration_s:
                return self._decision(False, "duration_limit", command_id)
            if set(command.positions) != set(self.config.joint_names):
                return self._decision(False, "joint_map_mismatch", command_id)
            for name, position in command.positions.items():
                lower, upper = self.config.position_limits[name]
                if position < lower or position > upper:
                    return self._decision(False, "joint_limit", command_id)
            self._seen_commands[command_id] = fingerprint
            try:
                handle = self._action_port.send_goal(command)
            except Exception:
                self._enter_hold("action_submission_failed")
                return self._decision(False, "action_submission_failed", command_id)
            self._last_command_state_sequence = command.source_state_sequence
            self._active = (command, handle, now)
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
            now = self._monotonic()
            if not self._fresh_joint_state(now):
                cancel_outcome = self._enter_hold("joint_state_stale")
                return self._decision(
                    False, "joint_state_stale", command.command_id, cancel_outcome
                )
            if now - started_at >= self.config.action_timeout_s:
                cancel_outcome = self._enter_hold("action_timeout")
                return self._decision(False, "action_timeout", command.command_id, cancel_outcome)
            try:
                if not handle.done():
                    return self._decision(True, "active", command.command_id)
                succeeded = handle.succeeded()
            except Exception:
                succeeded = False
            self._active = None
            if succeeded:
                self._state = "ready"
                return self._decision(True, "completed", command.command_id)
            self._enter_hold("action_failed")
            return self._decision(False, "action_failed", command.command_id)

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

    def recover(self, *, operator_confirmed: bool, observed_sequence: int) -> CommandDecision:
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
            self._hold_reason = ""
            self._state = "ready"
            return self._decision(True, "recovered")
