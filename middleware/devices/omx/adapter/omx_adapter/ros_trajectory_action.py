"""ROS trajectory action delivery isolated from the local owner executor."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable
from uuid import uuid4

from action_msgs.msg import GoalStatus
from control_msgs.action import FollowJointTrajectory
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from trajectory_msgs.msg import JointTrajectoryPoint

from .command_owner import ActionHandle, TrajectoryCommand
from .ros_goal_contract import RosGoalEvent, canonical_ros_goal_id


class RosTrajectoryActionHandle(ActionHandle):
    """Adapt rclpy's asynchronous FollowJointTrajectory handle to ActionHandle."""

    def __init__(
        self,
        action_client: ActionClient,
        command: TrajectoryCommand,
        event_sink: Callable[[RosGoalEvent], None] | None = None,
        *,
        defer_owner_event: Callable[[Callable[[], None]], Any] | None = None,
    ) -> None:
        self._client = action_client
        self._command = command
        self._event_sink = event_sink
        self._defer_owner_event = defer_owner_event
        self._lock = threading.RLock()
        self._event_delivery_lock = threading.RLock()
        self._goal_handle: Any | None = None
        self._done = False
        self._succeeded = False
        self._status: int | None = None
        self._result_observed = False
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
        # Serialize sequence/timestamp/delivery without the general handle lock.
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
                # Replay pre-acceptance feedback once after GOAL_ACCEPTED, outside this lock.
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
            # Publish status before the sink; completion waits for durable delivery.
            self._status = status
            self._result_observed = True
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
            self._deliver_owner_event(lambda: self._report_cancel(False))

    def _deliver_owner_event(self, callback: Callable[[], None]) -> None:
        if self._defer_owner_event is None:
            callback()
            return
        try:
            self._defer_owner_event(callback)
        except Exception:
            # No synchronous owner-thread fallback when the event executor stops.
            with self._lock:
                self._observation_failed = True

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
        """Latch failure immediately; journal outside the local owner's executor."""
        with self._lock:
            if self._done:
                return
            self._done = True
            self._succeeded = False
        self._deliver_owner_event(self._emit_timeout)

    def _emit_timeout(self) -> None:
        with self._lock:
            # Task order is unspecified; do not append unknown after an observed result.
            if self._result_observed:
                return
            goal_id = self._goal_id
        if goal_id is None:
            self._emit("GOAL_ACCEPTANCE_UNKNOWN")
        else:
            self._emit("TERMINAL_UNKNOWN", goal_id=goal_id)


class RosTrajectoryActionPort:
    """One owner's action client, with sink delivery outside its critical executor."""

    def __init__(
        self,
        node: Any,
        action_name: str,
        event_sink: Callable[[RosGoalEvent], None] | None = None,
        callback_group: Any | None = None,
    ) -> None:
        if not isinstance(action_name, str) or not action_name.strip():
            raise ValueError("action_name must be non-empty")
        self._event_sink = event_sink
        self.last_handle: RosTrajectoryActionHandle | None = None
        self._destroyed = False
        # Preserve the owner's relative/private names and remaps on the new node.
        resolved_action = node.resolve_topic_name(action_name)
        self._event_node = Node(
            "omx_action_events_" + uuid4().hex[:12], context=node.context,
            namespace=node.get_namespace(), use_global_arguments=False,
            enable_rosout=False, start_parameter_services=False,
        )
        try:
            self._executor = SingleThreadedExecutor(context=node.context)
            self._client = ActionClient(self._event_node, FollowJointTrajectory, resolved_action,
                                        callback_group=callback_group)
            self._executor.add_node(self._event_node)
            self._thread = threading.Thread(
                target=self._executor.spin, name=self._event_node.get_name(), daemon=True,
            )
            self._thread.start()
        except Exception:
            if hasattr(self, "_executor"):
                self._executor.shutdown(timeout_sec=0)
            if hasattr(self, "_client"):
                self._client.destroy()
            self._event_node.destroy_node()
            raise

    def server_is_ready(self) -> bool:
        return not self._destroyed and self._thread.is_alive() and self._client.server_is_ready()

    def send_goal(self, command: TrajectoryCommand) -> RosTrajectoryActionHandle:
        if not self.server_is_ready():
            raise RuntimeError("FollowJointTrajectory action server is not ready")
        handle = RosTrajectoryActionHandle(
            self._client, command, self._event_sink,
            defer_owner_event=self._executor.create_task,
        )
        self.last_handle = handle
        return handle

    def destroy(self) -> None:
        if self._destroyed:
            return
        stopped = self._executor.shutdown(timeout_sec=2.0)
        self._thread.join(timeout=2.0)
        if not stopped or self._thread.is_alive():
            raise RuntimeError("action event executor did not stop; resources remain owned")
        self._client.destroy()
        self._executor.remove_node(self._event_node)
        self._event_node.destroy_node()
        self._destroyed = True
