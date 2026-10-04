#!/usr/bin/env python3
"""Run one bounded post-mapping Nav2 goal without publishing velocity."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import time

import rclpy
from action_msgs.msg import GoalStatus
from lifecycle_msgs.msg import State
from lifecycle_msgs.srv import GetState
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


_SCRIPT_PATH = Path(__file__).resolve()
for _policy_dir in (
    _SCRIPT_PATH.parent,
    _SCRIPT_PATH.parents[1] / "launch",
):
    if (_policy_dir / "pinky_acceptance_policy.py").is_file():
        sys.path.insert(0, str(_policy_dir))
        break
else:  # pragma: no cover - packaging tests protect the installed runtime
    raise RuntimeError("pinky_acceptance_policy.py is missing from the install")

from pinky_acceptance_policy import (  # noqa: E402
    goal_position_error,
    nav_result_passes,
)


STATUS_NAMES = {
    GoalStatus.STATUS_UNKNOWN: "UNKNOWN",
    GoalStatus.STATUS_ACCEPTED: "ACCEPTED",
    GoalStatus.STATUS_EXECUTING: "EXECUTING",
    GoalStatus.STATUS_CANCELING: "CANCELING",
    GoalStatus.STATUS_SUCCEEDED: "SUCCEEDED",
    GoalStatus.STATUS_CANCELED: "CANCELED",
    GoalStatus.STATUS_ABORTED: "ABORTED",
}


class PinkyNav2Probe(Node):
    def __init__(self) -> None:
        super().__init__("pinky_nav2_probe")
        self.declare_parameter("run_id", "unset")
        self.declare_parameter("goal_x", -0.20)
        self.declare_parameter("goal_y", -0.15)
        self.declare_parameter("goal_yaw", 0.0)
        self.declare_parameter("max_position_error_m", 0.08)
        self.declare_parameter("server_timeout_s", 120.0)
        self.declare_parameter("result_timeout_s", 180.0)
        self.run_id = str(self.get_parameter("run_id").value)
        self.goal_xy = (
            float(self.get_parameter("goal_x").value),
            float(self.get_parameter("goal_y").value),
        )
        self.goal_yaw = float(self.get_parameter("goal_yaw").value)
        self.max_error = float(
            self.get_parameter("max_position_error_m").value
        )
        # Validate before contacting Nav2.
        nav_result_passes("UNKNOWN", 0.0, self.max_error)
        self.pose_xy: tuple[float, float] | None = None
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.status = self.create_publisher(
            String, "navigation/probe_status", qos
        )
        self.create_subscription(Odometry, "odom", self._on_odom, 10)
        self.client = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self.lifecycle_client = self.create_client(GetState, "bt_navigator/get_state")

    def _on_odom(self, msg: Odometry) -> None:
        self.pose_xy = (
            float(msg.pose.pose.position.x),
            float(msg.pose.pose.position.y),
        )

    def publish(self, phase: str, **extra) -> None:
        payload = {"run_id": self.run_id, "phase": phase, **extra}
        message = String()
        message.data = json.dumps(payload, sort_keys=True)
        self.status.publish(message)
        self.get_logger().info(message.data)

    def wait_future(self, future, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while rclpy.ok() and not future.done() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
        return future.done()

    def wait_for_nav2_active(self, timeout_s: float) -> bool:
        """Wait for lifecycle activation, not merely action-server discovery."""
        deadline = time.monotonic() + timeout_s
        self.publish("waiting_for_active")
        remaining = max(0.0, deadline - time.monotonic())
        if not self.lifecycle_client.wait_for_service(timeout_sec=remaining):
            return False
        while rclpy.ok() and time.monotonic() < deadline:
            future = self.lifecycle_client.call_async(GetState.Request())
            remaining = max(0.0, deadline - time.monotonic())
            if not self.wait_future(future, min(2.0, remaining)):
                continue
            response = future.result()
            if (
                response is not None
                and response.current_state.id == State.PRIMARY_STATE_ACTIVE
            ):
                self.publish("nav2_active")
                return True
            rclpy.spin_once(self, timeout_sec=0.1)
        return False

    def run(self) -> bool:
        server_timeout = float(self.get_parameter("server_timeout_s").value)
        self.publish("waiting_for_server")
        if not self.client.wait_for_server(timeout_sec=server_timeout):
            self.publish("failed", reason="nav2_server_timeout")
            return False
        if not self.wait_for_nav2_active(server_timeout):
            self.publish("failed", reason="nav2_activation_timeout")
            return False
        while rclpy.ok() and self.pose_xy is None:
            rclpy.spin_once(self, timeout_sec=0.1)

        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = self.goal_xy[0]
        goal.pose.pose.position.y = self.goal_xy[1]
        goal.pose.pose.orientation.z = math.sin(self.goal_yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(self.goal_yaw / 2.0)
        self.publish("goal_sent", goal_xy=list(self.goal_xy))
        send_future = self.client.send_goal_async(goal)
        if not self.wait_future(send_future, server_timeout):
            self.publish("failed", reason="goal_response_timeout")
            return False
        handle = send_future.result()
        if handle is None or not handle.accepted:
            self.publish("failed", reason="goal_rejected")
            return False
        self.publish("goal_accepted")
        result_timeout = float(self.get_parameter("result_timeout_s").value)
        result_future = handle.get_result_async()
        if not self.wait_future(result_future, result_timeout):
            handle.cancel_goal_async()
            self.publish("failed", reason="navigation_timeout")
            return False
        wrapped = result_future.result()
        status = STATUS_NAMES.get(wrapped.status, str(wrapped.status))
        error = goal_position_error(self.pose_xy, self.goal_xy)
        passed = nav_result_passes(status, error, self.max_error)
        self.publish(
            "complete" if passed else "failed",
            action_status=status,
            final_pose_xy=list(self.pose_xy),
            goal_xy=list(self.goal_xy),
            position_error_m=error,
            max_position_error_m=self.max_error,
            passed=passed,
        )
        return passed


def main() -> None:
    rclpy.init()
    node = PinkyNav2Probe()
    passed = False
    try:
        passed = node.run()
        # Give transient-local discovery and the collector a bounded chance to
        # receive the terminal sample before process exit.
        deadline = time.monotonic() + 0.5
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
    except KeyboardInterrupt:
        node.publish("failed", reason="interrupted")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
