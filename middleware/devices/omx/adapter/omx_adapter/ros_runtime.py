"""Optional ROS 2 Jazzy bindings for the disabled-by-default OMX policy.

Import this module only in a ROS 2 environment. The package's profile and
command-policy modules remain usable on hosts without rclpy.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable

from action_msgs.msg import GoalStatus
from control_msgs.action import FollowJointTrajectory
from rclpy.action import ActionClient
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.clock import Clock, ClockType
from rclpy.duration import Duration
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint

from .command_owner import (
    ActionHandle,
    ArmCommandConfig,
    ArmCommandOwner,
    CommandDecision,
    JointStateSnapshot,
    TrajectoryCommand,
)
from .pick_place_runner import PhaseDispatch
from .ros_goal_contract import RosGoalEvent, canonical_ros_goal_id


class RosTrajectoryActionHandle(ActionHandle):
    """Adapt rclpy's asynchronous FollowJointTrajectory handle to ActionHandle."""

    def __init__(
        self,
        action_client: ActionClient,
        command: TrajectoryCommand,
        event_sink: Callable[[RosGoalEvent], None] | None = None,
    ) -> None:
        self._client = action_client
        self._command = command
        self._event_sink = event_sink
        self._lock = threading.RLock()
        self._event_delivery_lock = threading.RLock()
        self._goal_handle: Any | None = None
        self._done = False
        self._succeeded = False
        self._status: int | None = None
        self._cancel_requested = False
        self._cancel_acknowledged: bool | None = None
        self._goal_id: str | None = None
        self._event_sequence = 0
        self._feedback_sequence = 0
        self._early_feedback = 0
        self._acceptance_emitted = False
        self._pending_cancel_acks: list[bool] = []
        self._observation_failed = False

        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(command.joint_names)
        points = []
        for planned in command.trajectory_points:
            point = JointTrajectoryPoint()
            point.positions = list(planned.positions)
            if planned.velocities is not None:
                point.velocities = list(planned.velocities)
            if planned.accelerations is not None:
                point.accelerations = list(planned.accelerations)
            total_ns = round(planned.time_from_start_s * 1_000_000_000)
            if total_ns < 1:
                raise ValueError("trajectory point time is below one nanosecond")
            point.time_from_start = Duration(nanoseconds=total_ns).to_msg()
            points.append(point)
        goal.trajectory.points = points

        future = action_client.send_goal_async(goal, feedback_callback=self._on_feedback)
        future.add_done_callback(self._on_goal_response)

    def _emit(self, kind: str, *, goal_id: str | None = None, **facts: Any) -> bool:
        # Sequence allocation, timestamp and durable delivery form one ordered
        # stream. Do not hold the general handle state lock through a sink.
        with self._event_delivery_lock:
            return self._emit_serialized(kind, goal_id=goal_id, **facts)

    def _emit_serialized(self, kind: str, *, goal_id: str | None = None, **facts: Any) -> bool:
        if self._event_sink is None:
            return True
        with self._lock:
            self._event_sequence += 1
            sequence = self._event_sequence
        try:
            self._event_sink(RosGoalEvent(
                kind=kind,  # type: ignore[arg-type]
                command_id=self._command.command_id,
                phase_id=self._command.phase_id,
                goal_id=goal_id,
                observed_at_monotonic_s=time.monotonic(),
                sequence=sequence,
                **facts,
            ))
            return True
        except Exception:
            # Telemetry is not allowed to break the ROS executor or imply success.
            with self._lock:
                first_failure = not self._observation_failed
                self._observation_failed = True
                goal_handle = self._goal_handle
            if first_failure and goal_handle is not None:
                try:
                    self._request_cancel(goal_handle)
                except Exception:
                    pass
            return False

    def _on_feedback(self, message: Any) -> None:
        with self._lock:
            goal_id = self._goal_id
            if goal_id is None or not self._acceptance_emitted:
                # rclpy may run feedback (action-client callback group) before the send-goal
                # future's done callback has recorded the goal id AND emitted GOAL_ACCEPTED.
                # Count it and replay one RUNNING_FEEDBACK after GOAL_ACCEPTED; never fail the
                # observation for it (review B1, re-review N1). No lock is held while emitting.
                self._early_feedback += 1
                return
            self._feedback_sequence += 1
            feedback_sequence = self._feedback_sequence
        self._emit(
            "RUNNING_FEEDBACK",
            goal_id=goal_id,
            feedback_sequence=feedback_sequence,
        )

    @property
    def cancel_acknowledged(self) -> bool | None:
        """Whether the server accepted the cancel request; not a stop proof."""
        with self._lock:
            return self._cancel_acknowledged

    @property
    def status(self) -> int | None:
        """Final action status, populated only after the result future resolves."""
        with self._lock:
            return self._status

    def _on_goal_response(self, future: Any) -> None:
        try:
            goal_handle = future.result()
        except Exception:
            with self._lock:
                self._done = True
                self._succeeded = False
            self._emit("GOAL_ACCEPTANCE_UNKNOWN")
            return

        if goal_handle is None or not goal_handle.accepted:
            with self._lock:
                self._done = True
                self._succeeded = False
            self._emit("GOAL_REJECTED")
            return

        try:
            goal_id = canonical_ros_goal_id(goal_handle.goal_id.uuid)
        except Exception:
            with self._lock:
                self._goal_handle = goal_handle
                self._observation_failed = True
            self._emit("GOAL_ACCEPTANCE_UNKNOWN")
            try:
                self._request_cancel(goal_handle)
            except Exception:
                pass
            return

        with self._lock:
            self._goal_handle = goal_handle
            self._goal_id = goal_id
            cancel_pending = self._cancel_requested
        self._emit("GOAL_ACCEPTED", goal_id=goal_id)
        # One step with _on_feedback: feedback counted up to here is replayed once; feedback
        # after this point is emitted live, so none can precede GOAL_ACCEPTED (N1).
        with self._lock:
            self._acceptance_emitted = True
            early_cancel_acks, self._pending_cancel_acks = self._pending_cancel_acks, []
            early_feedback = self._early_feedback
            if early_feedback:
                self._feedback_sequence += 1
                feedback_sequence = self._feedback_sequence
        if early_feedback:
            self._emit("RUNNING_FEEDBACK", goal_id=goal_id, feedback_sequence=feedback_sequence)
        for acknowledged in early_cancel_acks:
            self._emit("CANCEL_ACK", goal_id=goal_id, cancel_acknowledged=acknowledged)
        try:
            result_future = goal_handle.get_result_async()
            result_future.add_done_callback(self._on_result)
        except Exception:
            self._emit("TERMINAL_UNKNOWN", goal_id=goal_id)
            with self._lock:
                self._done = True
                self._succeeded = False
        if cancel_pending:
            self._request_cancel(goal_handle)

    def _on_result(self, future: Any) -> None:
        try:
            wrapped = future.result()
            status = wrapped.status
            success = (
                status == GoalStatus.STATUS_SUCCEEDED
                and wrapped.result.error_code == FollowJointTrajectory.Result.SUCCESSFUL
            )
        except Exception:
            status = None
            success = False
        with self._lock:
            goal_id = self._goal_id
            # The ROS status is a fact as soon as the result resolves; record it before the
            # sinks journal it, so a reader that sees the journal also sees the status (WSL
            # loop: journal SUCCEEDED while status was still None). done/succeeded stay last.
            self._status = status
        if status is None or goal_id is None:
            self._emit("TERMINAL_UNKNOWN", goal_id=goal_id)
        else:
            result_code = getattr(getattr(wrapped, "result", None), "error_code", None)
            self._emit(
                "TERMINAL_RESULT",
                goal_id=goal_id,
                status=int(status),
                result_code=int(result_code) if result_code is not None else None,
            )
        with self._lock:
            self._done = True
            self._succeeded = success and not self._observation_failed
            self._status = status

    def _on_cancel_response(self, future: Any) -> None:
        try:
            response = future.result()
            acknowledged = bool(response.goals_canceling)
        except Exception:
            acknowledged = False
        self._report_cancel(acknowledged)

    def _report_cancel(self, acknowledged: bool) -> None:
        with self._lock:
            self._cancel_acknowledged = acknowledged
            goal_id = self._goal_id
            if goal_id is not None and not self._acceptance_emitted:
                self._pending_cancel_acks.append(acknowledged)
                return
        if goal_id is not None:
            self._emit("CANCEL_ACK", goal_id=goal_id, cancel_acknowledged=acknowledged)

    def _request_cancel(self, goal_handle: Any) -> None:
        try:
            future = goal_handle.cancel_goal_async()
            future.add_done_callback(self._on_cancel_response)
        except Exception:
            self._report_cancel(False)

    def cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True
            goal_handle = self._goal_handle
        if goal_handle is not None:
            self._request_cancel(goal_handle)

    def done(self) -> bool:
        with self._lock:
            return self._done

    def succeeded(self) -> bool:
        with self._lock:
            return self._done and self._succeeded and not self._observation_failed

    def mark_timeout(self) -> None:
        """Emit an unresolved acceptance/result fact when the local owner times out."""
        with self._lock:
            if self._done:
                return
            self._done = True
            self._succeeded = False
            goal_id = self._goal_id
        if goal_id is None:
            self._emit("GOAL_ACCEPTANCE_UNKNOWN")
        else:
            self._emit("TERMINAL_UNKNOWN", goal_id=goal_id)


class RosTrajectoryActionPort:
    """Single rclpy action client used exclusively by one ArmCommandOwner."""

    def __init__(
        self,
        node: Any,
        action_name: str,
        event_sink: Callable[[RosGoalEvent], None] | None = None,
        callback_group: Any | None = None,
    ) -> None:
        if not isinstance(action_name, str) or not action_name.strip():
            raise ValueError("action_name must be non-empty")
        self._client = ActionClient(node, FollowJointTrajectory, action_name,
                                    callback_group=callback_group)
        self._event_sink = event_sink
        self.last_handle: RosTrajectoryActionHandle | None = None

    def server_is_ready(self) -> bool:
        return self._client.server_is_ready()

    def send_goal(self, command: TrajectoryCommand) -> RosTrajectoryActionHandle:
        if not self.server_is_ready():
            raise RuntimeError("FollowJointTrajectory action server is not ready")
        handle = RosTrajectoryActionHandle(self._client, command, self._event_sink)
        self.last_handle = handle
        return handle

    def destroy(self) -> None:
        self._client.destroy()


class RosArmCommandRuntime:
    """Bind one policy instance to joint-state input and a steady-time watchdog.

    This exposes an in-process submit API. It deliberately does not create a
    remote action/service endpoint or claim DDS access control. Deployment must
    admit exactly one local command source and isolate the vendor action graph.

    Joint-state intake, the watchdog and the action client each use a separate
    mutually exclusive callback group. Slow policy guard I/O must not exclude
    joint callback entry. Owner/session locks still serialize accepted state and
    control; separate groups do not waive freshness or stop checks. Use a
    MultiThreadedExecutor; three workers permit all three groups to make progress.
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

        self._node = node
        self.owner_clock = owner_clock
        self.poll_period_s = poll_period_s
        self._policy_binding = None
        self._sequence = 0
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
            if node.get_parameter("use_sim_time").value is not True:
                raise ValueError("owner_clock 'sim' requires use_sim_time")
            if config.wall_clock_bound_factor is None:
                raise ValueError("owner_clock 'sim' requires config.wall_clock_bound_factor")
            node_clock = node.get_clock()
            self.monotonic: Callable[[], float] = lambda: node_clock.now().nanoseconds / 1e9
            self.owner = ArmCommandOwner(config, self.action_port, monotonic=self.monotonic,
                                         wall_monotonic=time.monotonic)
        else:
            self.monotonic = time.monotonic
            self.owner = ArmCommandOwner(config, self.action_port, monotonic=time.monotonic)
        self.last_decision = CommandDecision(True, "ready", "ready")
        self.last_terminal_decision: CommandDecision | None = None
        self._subscription = node.create_subscription(
            JointState,
            joint_state_topic,
            self._on_joint_state,
            qos_profile_sensor_data,
            callback_group=self.state_callback_group,
        )
        self._steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self._timer = node.create_timer(
            poll_period_s,
            self._watchdog_tick,
            clock=self._steady_clock,
            callback_group=self.watchdog_callback_group,
        )

    def _on_joint_state(self, message: JointState) -> None:
        self._sequence += 1
        reported_positions = {
            name: value for name, value in zip(message.name, message.position)
        }
        positions = {
            name: reported_positions[name]
            for name in self.owner.config.joint_names
            if name in reported_positions
        }
        snapshot = JointStateSnapshot(
            positions=positions,
            sequence=self._sequence,
            received_at=self.monotonic(),
            calibration_revision=self.owner.config.calibration_revision,
        )
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
        # Steady-clock timer: it keeps polling (and the wall bound keeps working) when sim
        # time is frozen.
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
