"""ROS-only Jazzy bindings; profile/policy modules remain usable without rclpy."""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable

from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.clock import Clock, ClockType
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import JointState

from .command_owner import (
    ArmCommandConfig,
    ArmCommandOwner,
    CommandDecision,
    JointStateSnapshot,
    TrajectoryCommand,
)
from .pick_place.pick_place_runner import PhaseDispatch
from .joint_state_intake import JointStateIntake
from .watchdog_observation import intake_observation
from .ros_goal_contract import RosGoalEvent
from .ros_trajectory_action import (
    RosTrajectoryActionHandle,  # noqa: F401 - preserve the existing import path
    RosTrajectoryActionPort,
)


class RosArmCommandRuntime:
    """Bind intake/watchdog groups to a local-only policy API; no DDS access control.
    Deployment admits one command source and isolates the vendor graph. A separate
    action executor serializes durable events; owner locks, freshness and stop
    checks remain authoritative. Use ros_owner_executor.OwnerMultiThreadedExecutor
    when policy I/O can block owner callbacks (observed rclpy 7.1.12 scheduling gaps).
    """

    def __init__(
        self,
        node: Any,
        config: ArmCommandConfig,
        *,
        joint_state_topic: str = "/joint_states",
        trajectory_action: str = "/arm_controller/follow_joint_trajectory",
        poll_period_s: float = 0.02,
        on_goal_event: Callable[[RosGoalEvent], None] | None = None,
        owner_clock: str = "steady",
    ) -> None:
        if owner_clock not in {"steady", "sim"}:
            raise ValueError("owner_clock must be 'steady' or 'sim'")
        if not config.enabled:
            raise ValueError("ROS arm runtime requires an explicitly enabled policy")
        if not math.isfinite(poll_period_s) or poll_period_s <= 0:
            raise ValueError("poll_period_s must be a positive finite number")
        if poll_period_s > min(config.max_joint_state_age_s, config.action_timeout_s) / 2:
            raise ValueError("poll_period_s must be at most half of state age and action timeout")
        if not joint_state_topic.strip() or not trajectory_action.strip():
            raise ValueError("joint-state topic and trajectory action must be explicit")
        node.resolve_topic_name(joint_state_topic)
        node.resolve_topic_name(trajectory_action)
        if owner_clock == "sim":
            if node.get_parameter("use_sim_time").value is not True:
                raise ValueError("owner_clock 'sim' requires use_sim_time")
            if config.wall_clock_bound_factor is None:
                raise ValueError("owner_clock 'sim' requires config.wall_clock_bound_factor")

        self._node = node
        self.owner_clock = owner_clock
        self.poll_period_s = poll_period_s
        self._policy_binding = None
        self._joint_state_intake = JointStateIntake(config)
        self._goal_event_lock = threading.RLock()
        self._phase_event_sinks: dict[str, Callable[[RosGoalEvent], bool]] = {}
        self.latest_joint_state: JointStateSnapshot | None = None
        if on_goal_event is not None and not callable(on_goal_event):
            raise ValueError("on_goal_event must be callable when provided")
        self._observer_goal_event = on_goal_event
        self.state_callback_group = MutuallyExclusiveCallbackGroup()
        self.watchdog_callback_group = MutuallyExclusiveCallbackGroup()
        self.action_callback_group = MutuallyExclusiveCallbackGroup()
        self.action_port = RosTrajectoryActionPort(
            node, trajectory_action, self._dispatch_goal_event,
            callback_group=self.action_callback_group,
        )
        # Owner clock (C3b A3). "sim": the node clock, which must be sim time, so owner
        # deadlines run on the trajectory's time base; the steady clock then bounds them at
        # config.wall_clock_bound_factor. "steady" (default, Pilot): steady time only.
        if owner_clock == "sim":
            node_clock = node.get_clock()
            self.monotonic: Callable[[], float] = lambda: node_clock.now().nanoseconds / 1e9
            self.owner = ArmCommandOwner(config, self.action_port, monotonic=self.monotonic,
                                         wall_monotonic=time.monotonic)
        else:
            self.monotonic = time.monotonic
            self.owner = ArmCommandOwner(config, self.action_port, monotonic=time.monotonic)
        self.last_decision = CommandDecision(True, "ready", "ready")
        self.last_terminal_decision: CommandDecision | None = None
        try:
            self._subscription = node.create_subscription(
                JointState, joint_state_topic, self._on_joint_state,
                qos_profile_sensor_data, callback_group=self.state_callback_group,
            )
            self._steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
            self._timer = node.create_timer(
                poll_period_s, self._watchdog_tick, clock=self._steady_clock,
                callback_group=self.watchdog_callback_group,
            )
        except Exception:
            if hasattr(self, "_subscription"):
                node.destroy_subscription(self._subscription)
            self.action_port.destroy()
            raise

    def _on_joint_state(self, message: JointState) -> None:
        callback_entered = time.monotonic()
        prior_attempt = self._joint_state_intake.last_attempt
        try:
            snapshot = self._joint_state_intake.snapshot(
                message.name, message.position,
                stamp_ns=message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec,
                source_now_ns=self._node.get_clock().now().nanoseconds, received_at=self.monotonic())
        except (TypeError, ValueError, OverflowError):
            self._record_joint_intake(callback_entered, prior_attempt)
            # Rejected packets cannot refresh the state or watchdog. Loss of valid
            # feedback reaches the existing stale-state HOLD and cancel path.
            return
        self._record_joint_intake(callback_entered, prior_attempt)
        self.latest_joint_state = snapshot
        def deliver_owner(state):
            binding = self._policy_binding
            if binding is None:
                self.owner.observe_joint_state(snapshot)
            return binding
        binding = self.owner.run_admission_policy(deliver_owner)
        if binding is not None:
            try:
                binding.observe(snapshot)
            except Exception:
                self.last_decision = binding.poll()

    def _record_joint_intake(self, callback_entered, prior_attempt):
        # Immutable publication happens before owner-lock acquisition, including rejection.
        # It neither delivers a snapshot nor changes source/owner/wall freshness.
        try:
            facts = self._joint_state_intake.last_attempt
            self.owner.joint_intake_observation = (None if facts is prior_attempt else intake_observation(
                facts, callback_entered_steady=callback_entered, intake_observed_steady=time.monotonic(),
                intake_sequence=self._joint_state_intake._sequence))
        except Exception:
            self.owner.joint_intake_observation = None

    def submit(self, command: TrajectoryCommand) -> CommandDecision:
        if self._policy_binding is not None:
            return CommandDecision(False,self.owner.state,'policy_session_required',command.command_id)
        return self._submit_policy(command,None)

    def bind_policy_driver(self, binding: Any) -> None:
        def install(state):
            if binding.owner is not self.owner or self._policy_binding is not None or state != 'ready':
                raise ValueError('policy runtime owner differs, not ready or already bound')
            binding.adopt(self.owner._joint_state)
            self.owner.bind_control_admission(binding)
            self._policy_binding = binding
        self.owner.run_admission_policy(install)

    def _submit_policy(self, command: TrajectoryCommand, binding: Any) -> CommandDecision:
        if binding is not self._policy_binding or (binding is not None and binding.check_command(command) is not True):
            raise PermissionError('policy runtime command scope required')
        self.last_decision = self.owner.submit(command)
        if self.last_decision.reason not in {"submitted", "duplicate_ignored"}:
            self.last_terminal_decision = self.last_decision
        elif self.last_decision.reason == "submitted":
            self.last_terminal_decision = None
        return self.last_decision

    def register_phase_event_sink(
        self, command_id: str, sink: Callable[[RosGoalEvent], bool],
    ) -> None:
        """Bind callback delivery before dispatch so fast ROS responses are not lost."""
        if not isinstance(command_id, str) or not command_id or not callable(sink):
            raise ValueError("phase event registration requires command identity and callback")
        with self._goal_event_lock:
            if command_id in self._phase_event_sinks:
                raise ValueError("phase event sink is already registered for this command")
            self._phase_event_sinks[command_id] = sink

    def unregister_phase_event_sink(self, command_id: str) -> None:
        with self._goal_event_lock:
            self._phase_event_sinks.pop(command_id, None)

    def _dispatch_goal_event(self, event: RosGoalEvent) -> None:
        with self._goal_event_lock:
            phase_sink = self._phase_event_sinks.get(event.command_id)
            observer = self._observer_goal_event
        try:
            if phase_sink is not None and phase_sink(event) is not True:
                raise RuntimeError("phase runner did not durably accept the ROS goal event")
            if observer is not None:
                observer(event)
        finally:
            # Unknown is not definitive: the goal response or result can still arrive late.
            if event.kind in {"GOAL_REJECTED", "TERMINAL_RESULT"}:
                self.unregister_phase_event_sink(event.command_id)

    def _watchdog_tick(self) -> None:
        # Steady time preserves polling and the wall bound when sim time is frozen.
        self.last_decision = (self.owner.poll() if self._policy_binding is None else self._policy_binding.poll())
        if self.last_decision.reason in {"action_timeout", "joint_state_stale",
                                         "action_wall_timeout", "joint_state_stale_wall_clock"}:
            handle = self.action_port.last_handle
            if handle is not None:
                handle.mark_timeout()
        if self.last_decision.reason not in {"active", "ready"}:
            self.last_terminal_decision = self.last_decision

    def cancel(self, *, command_id: str, owner: str) -> CommandDecision:
        """Ask the action server to cancel; acceptance is not standstill proof."""
        self.last_decision = self.owner.cancel(command_id=command_id, owner=owner)
        if self.last_decision.reason in {"cancel_requested", "cancel_call_failed"}:
            self.last_terminal_decision = self.last_decision
        return self.last_decision

    def destroy(self) -> None:
        self._node.destroy_timer(self._timer)
        self._node.destroy_subscription(self._subscription)
        self.action_port.destroy()


class RosArmPhaseGoalPort:
    """Adapt the shared local owner to PickPlaceRunner's asynchronous contract."""

    def __init__(self, runtime: RosArmCommandRuntime) -> None:
        self.runtime = runtime
        self._lock = threading.RLock()
        self._command_by_goal: dict[str, tuple[str, str]] = {}

    @property
    def command_owner(self):
        return self.runtime.owner

    def submit(
        self, command: TrajectoryCommand, *,
        on_goal_event: Callable[[RosGoalEvent], bool],
    ) -> PhaseDispatch:
        def deliver(event: RosGoalEvent) -> bool:
            if event.kind == "GOAL_ACCEPTED" and event.goal_id is not None:
                with self._lock:
                    self._command_by_goal[event.goal_id] = (command.command_id, command.owner)
            try:
                return on_goal_event(event)
            finally:
                if event.kind in {"TERMINAL_RESULT", "TERMINAL_UNKNOWN"} and event.goal_id is not None:
                    with self._lock:
                        self._command_by_goal.pop(event.goal_id, None)

        self.runtime.register_phase_event_sink(command.command_id, deliver)
        decision = self.runtime.submit(command)
        if decision.accepted and decision.reason == "submitted":
            return PhaseDispatch(dispatched=True)
        self.runtime.unregister_phase_event_sink(command.command_id)
        if decision.reason == "action_submission_failed":
            return PhaseDispatch(dispatched=None)
        return PhaseDispatch(dispatched=False)

    def cancel_goal(self, driver_goal_id: str) -> bool | None:
        with self._lock:
            command = self._command_by_goal.get(driver_goal_id)
        if command is None:
            return None
        command_id, owner = command
        decision = self.runtime.cancel(command_id=command_id, owner=owner)
        if decision.reason == "cancel_requested":
            # The cancel response callback is the ACK source. Local admission is not ACK.
            return None
        return False
