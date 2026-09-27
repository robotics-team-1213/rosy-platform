"""Optional ROS 2 Jazzy bindings for the disabled-by-default OMX policy.

Import this module only in a ROS 2 environment. The package's profile and
command-policy modules remain usable on hosts without rclpy.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any

from action_msgs.msg import GoalStatus
from control_msgs.action import FollowJointTrajectory
from rclpy.action import ActionClient
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


class RosTrajectoryActionHandle(ActionHandle):
    """Adapt rclpy's asynchronous FollowJointTrajectory handle to ActionHandle."""

    def __init__(self, action_client: ActionClient, command: TrajectoryCommand) -> None:
        self._client = action_client
        self._lock = threading.RLock()
        self._goal_handle: Any | None = None
        self._done = False
        self._succeeded = False
        self._status: int | None = None
        self._cancel_requested = False
        self._cancel_acknowledged: bool | None = None

        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(command.positions)
        point = JointTrajectoryPoint()
        point.positions = [command.positions[name] for name in goal.trajectory.joint_names]
        total_ns = round(command.duration_s * 1_000_000_000)
        if total_ns < 1:
            raise ValueError("trajectory duration is below one nanosecond")
        point.time_from_start = Duration(nanoseconds=total_ns).to_msg()
        goal.trajectory.points = [point]

        future = action_client.send_goal_async(goal)
        future.add_done_callback(self._on_goal_response)

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
            return

        if goal_handle is None or not goal_handle.accepted:
            with self._lock:
                self._done = True
                self._succeeded = False
            return

        with self._lock:
            self._goal_handle = goal_handle
            cancel_pending = self._cancel_requested
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._on_result)
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
            self._done = True
            self._succeeded = success
            self._status = status

    def _on_cancel_response(self, future: Any) -> None:
        try:
            response = future.result()
            acknowledged = bool(response.goals_canceling)
        except Exception:
            acknowledged = False
        with self._lock:
            self._cancel_acknowledged = acknowledged

    def _request_cancel(self, goal_handle: Any) -> None:
        future = goal_handle.cancel_goal_async()
        future.add_done_callback(self._on_cancel_response)

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
            return self._done and self._succeeded


class RosTrajectoryActionPort:
    """Single rclpy action client used exclusively by one ArmCommandOwner."""

    def __init__(self, node: Any, action_name: str) -> None:
        if not isinstance(action_name, str) or not action_name.strip():
            raise ValueError("action_name must be non-empty")
        self._client = ActionClient(node, FollowJointTrajectory, action_name)
        self.last_handle: RosTrajectoryActionHandle | None = None

    def server_is_ready(self) -> bool:
        return self._client.server_is_ready()

    def send_goal(self, command: TrajectoryCommand) -> RosTrajectoryActionHandle:
        if not self.server_is_ready():
            raise RuntimeError("FollowJointTrajectory action server is not ready")
        handle = RosTrajectoryActionHandle(self._client, command)
        self.last_handle = handle
        return handle

    def destroy(self) -> None:
        self._client.destroy()


class RosArmCommandRuntime:
    """Bind one policy instance to joint-state input and a steady-time watchdog.

    This exposes an in-process submit API. It deliberately does not create a
    remote action/service endpoint or claim DDS access control. Deployment must
    admit exactly one local command source and isolate the vendor action graph.
    """

    def __init__(
        self,
        node: Any,
        config: ArmCommandConfig,
        *,
        joint_state_topic: str = "/joint_states",
        trajectory_action: str = "/arm_controller/follow_joint_trajectory",
        poll_period_s: float = 0.02,
    ) -> None:
        if not config.enabled:
            raise ValueError("ROS arm runtime requires an explicitly enabled policy")
        if not math.isfinite(poll_period_s) or poll_period_s <= 0:
            raise ValueError("poll_period_s must be a positive finite number")
        if poll_period_s > min(config.max_joint_state_age_s, config.action_timeout_s) / 2:
            raise ValueError("poll_period_s must be at most half of state age and action timeout")
        if not joint_state_topic.strip() or not trajectory_action.strip():
            raise ValueError("joint-state topic and trajectory action must be explicit")

        self._node = node
        self._sequence = 0
        self.latest_joint_state: JointStateSnapshot | None = None
        self.action_port = RosTrajectoryActionPort(node, trajectory_action)
        self.owner = ArmCommandOwner(config, self.action_port, monotonic=time.monotonic)
        self.last_decision = CommandDecision(True, "ready", "ready")
        self.last_terminal_decision: CommandDecision | None = None
        self._subscription = node.create_subscription(
            JointState,
            joint_state_topic,
            self._on_joint_state,
            qos_profile_sensor_data,
        )
        self._steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self._timer = node.create_timer(
            poll_period_s,
            self._watchdog_tick,
            clock=self._steady_clock,
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
            received_at=time.monotonic(),
            calibration_revision=self.owner.config.calibration_revision,
        )
        self.latest_joint_state = snapshot
        self.owner.observe_joint_state(snapshot)

    def submit(self, command: TrajectoryCommand) -> CommandDecision:
        self.last_decision = self.owner.submit(command)
        if self.last_decision.reason not in {"submitted", "duplicate_ignored"}:
            self.last_terminal_decision = self.last_decision
        elif self.last_decision.reason == "submitted":
            self.last_terminal_decision = None
        return self.last_decision

    def _watchdog_tick(self) -> None:
        self.last_decision = self.owner.poll()
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
