from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

rclpy = pytest.importorskip("rclpy", reason="requires the ROS 2 Jazzy runtime")

from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from action_msgs.msg import GoalStatus

from omx_adapter.command_owner import ArmCommandConfig, TrajectoryCommand
from omx_adapter.ros_runtime import RosArmCommandRuntime


@pytest.mark.skipif(
    not os.environ.get("OMX_VENDOR_SIM_ACTION"),
    reason="requires an explicitly started isolated OMX vendor simulation",
)
def test_runtime_forwards_bounded_noop_goal_to_locked_vendor_simulation():
    action_name = os.environ["OMX_VENDOR_SIM_ACTION"]
    joint_name = "joint1"
    config = ArmCommandConfig(
        enabled=True,
        workcell_id="sim_workcell",
        instance_id="sim_instance",
        joint_names=(joint_name,),
        # This is only a narrow test admission interval around the starting pose.
        # The vendor controller also enforces its own URDF command limits.
        position_limits={joint_name: (-0.1, 0.1)},
        allowed_owners=("rule_based",),
        calibration_revision="simulation-only",
        max_joint_state_age_s=0.5,
        max_goal_duration_s=3.0,
        action_timeout_s=4.0,
    )

    rclpy.init()
    node = Node("omx_runtime_vendor_sim_probe")
    runtime = RosArmCommandRuntime(
        node,
        config,
        joint_state_topic="/joint_states",
        trajectory_action=action_name,
        poll_period_s=0.01,
    )
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    spinner = ThreadPoolExecutor(max_workers=1)
    spinning = spinner.submit(executor.spin)
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if runtime.action_port.server_is_ready() and runtime.latest_joint_state is not None:
                break
            time.sleep(0.02)
        assert runtime.action_port.server_is_ready()
        assert runtime.latest_joint_state is not None

        state = runtime.latest_joint_state
        current_position = state.positions[joint_name]
        command = TrajectoryCommand(
            workcell_id=config.workcell_id,
            instance_id=config.instance_id,
            command_id="vendor-sim-noop",
            session_id=runtime.owner.session_id,
            owner="rule_based",
            positions={joint_name: current_position},
            duration_s=0.2,
            source_state_sequence=state.sequence,
            calibration_revision=config.calibration_revision,
        )
        submitted = runtime.submit(command)
        assert submitted.accepted and submitted.reason == "submitted"

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and runtime.last_terminal_decision is None:
            time.sleep(0.01)
        assert runtime.last_terminal_decision.reason == "completed"

        deadline = time.monotonic() + 2.0
        while (
            time.monotonic() < deadline
            and runtime.latest_joint_state.sequence <= state.sequence
        ):
            time.sleep(0.01)
        assert runtime.latest_joint_state.sequence > state.sequence
        assert abs(runtime.latest_joint_state.positions[joint_name] - current_position) < 0.02

        fresh_state = runtime.latest_joint_state
        cancellable = TrajectoryCommand(
            workcell_id=config.workcell_id,
            instance_id=config.instance_id,
            command_id="vendor-sim-cancel",
            session_id=runtime.owner.session_id,
            owner="rule_based",
            positions={joint_name: current_position + 0.02},
            duration_s=3.0,
            source_state_sequence=fresh_state.sequence,
            calibration_revision=config.calibration_revision,
        )
        assert runtime.submit(cancellable).accepted
        time.sleep(0.1)
        cancellation = runtime.cancel(command_id="vendor-sim-cancel", owner="rule_based")
        assert cancellation.reason == "cancel_requested"
        assert cancellation.cancel_outcome == "call_returned"

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            handle = runtime.action_port.last_handle
            if handle is not None and handle.cancel_acknowledged is not None and handle.done():
                break
            time.sleep(0.01)
        handle = runtime.action_port.last_handle
        assert handle.cancel_acknowledged is True
        assert handle.done()
        assert handle.status == GoalStatus.STATUS_CANCELED
    finally:
        executor.shutdown(timeout_sec=2.0)
        spinning.result(timeout=3.0)
        runtime.destroy()
        node.destroy_node()
        rclpy.shutdown()
