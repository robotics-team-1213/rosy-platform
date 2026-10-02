from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
import re

import pytest

rclpy = pytest.importorskip("rclpy", reason="requires the ROS 2 Jazzy runtime")

from control_msgs.action import FollowJointTrajectory  # noqa: E402
from rclpy.action import ActionServer, CancelResponse  # noqa: E402
from rclpy.executors import MultiThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402

from omx_adapter.command_owner import ArmCommandConfig, TrajectoryCommand  # noqa: E402
from omx_adapter.manipulation_plan import JointTrajectoryPoint  # noqa: E402
from omx_adapter.ros_runtime import RosArmCommandRuntime, RosArmPhaseGoalPort  # noqa: E402


def test_runtime_subscribes_to_feedback_and_submits_through_one_ros_action_client():
    rclpy.init()
    server_node = Node("omx_test_vendor_server")
    feedback_node = Node("omx_test_feedback_source")
    owner_node = Node("omx_test_owner")
    server_goal = {}
    server_goal_received = threading.Event()
    goal_events = []

    def execute(goal_handle):
        server_goal["joint_names"] = list(goal_handle.request.trajectory.joint_names)
        server_goal["points"] = [
            {
                "positions": list(point.positions),
                "velocities": list(point.velocities),
                "accelerations": list(point.accelerations),
                "time": point.time_from_start,
            }
            for point in goal_handle.request.trajectory.points
        ]
        server_goal_received.set()
        feedback = FollowJointTrajectory.Feedback()
        feedback.joint_names = ["joint1", "joint2"]
        feedback.desired.positions = [0.3, -0.15]
        feedback.actual.positions = [0.25, -0.12]
        feedback.error.positions = [0.05, -0.03]
        goal_handle.publish_feedback(feedback)
        goal_handle.succeed()
        result = FollowJointTrajectory.Result()
        result.error_code = FollowJointTrajectory.Result.SUCCESSFUL
        return result

    action_server = ActionServer(
        server_node,
        FollowJointTrajectory,
        "/test/omx/arm_controller/follow_joint_trajectory",
        execute_callback=execute,
    )
    feedback_publisher = feedback_node.create_publisher(JointState, "/test/omx/joint_states", 1)
    config = ArmCommandConfig(
        enabled=True,
        workcell_id="test_workcell",
        instance_id="test_instance",
        joint_names=("joint1", "joint2"),
        position_limits={"joint1": (-1.0, 1.0), "joint2": (-0.5, 0.5)},
        velocity_limits={"joint1": 1.0, "joint2": 1.0},
        acceleration_limits={"joint1": 2.0, "joint2": 2.0},
        allowed_owners=("moveit",),
        calibration_revision="cal-test",
        max_joint_state_age_s=0.5,
        max_goal_duration_s=2.0,
        action_timeout_s=3.0,
    )
    runtime = RosArmCommandRuntime(
        owner_node,
        config,
        joint_state_topic="/test/omx/joint_states",
        trajectory_action="/test/omx/arm_controller/follow_joint_trajectory",
        poll_period_s=0.01,
        on_goal_event=goal_events.append,
    )
    phase_port = RosArmPhaseGoalPort(runtime)
    executor = MultiThreadedExecutor(num_threads=4)
    for node in (server_node, feedback_node, owner_node):
        executor.add_node(node)
    spinner = ThreadPoolExecutor(max_workers=1)
    spinning = spinner.submit(executor.spin)
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if runtime.action_port.server_is_ready():
                message = JointState()
                message.name = ["joint1", "joint2", "gripper_joint_1"]
                message.position = [0.0, 0.1, 0.0]
                feedback_publisher.publish(message)
                if runtime.latest_joint_state is not None:
                    break
            time.sleep(0.02)
        assert runtime.latest_joint_state is not None
        assert set(runtime.latest_joint_state.positions) == {"joint1", "joint2"}

        state = runtime.latest_joint_state
        command = TrajectoryCommand(
            workcell_id=config.workcell_id,
            instance_id=config.instance_id,
            command_id="ros-test-command",
            session_id=runtime.owner.session_id,
            owner="moveit",
            phase_id="approach",
            positions={"joint1": 0.4, "joint2": -0.2},
            trajectory_points=(
                JointTrajectoryPoint(
                    time_from_start_s=0.25, positions=(0.2, -0.1),
                    velocities=(0.1, -0.1), accelerations=(0.2, 0.2),
                ),
                JointTrajectoryPoint(
                    time_from_start_s=0.5, positions=(0.4, -0.2),
                    velocities=(0.2, -0.1), accelerations=(0.1, 0.2),
                ),
            ),
            duration_s=0.5,
            source_state_sequence=state.sequence,
            calibration_revision=config.calibration_revision,
        )
        phase_events = []
        dispatch = phase_port.submit(
            command,
            on_goal_event=lambda event: (phase_events.append(event) or True),
        )
        assert dispatch.dispatched is True
        assert server_goal_received.wait(5.0)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and runtime.last_terminal_decision is None:
            time.sleep(0.01)

        assert runtime.last_terminal_decision.reason == "completed"
        assert server_goal["joint_names"] == ["joint1", "joint2"]
        assert len(server_goal["points"]) == 2
        assert server_goal["points"][0]["positions"] == [0.2, -0.1]
        assert server_goal["points"][0]["velocities"] == [0.1, -0.1]
        assert server_goal["points"][0]["accelerations"] == [0.2, 0.2]
        assert server_goal["points"][0]["time"].nanosec == 250_000_000
        assert server_goal["points"][1]["positions"] == [0.4, -0.2]
        assert server_goal["points"][1]["time"].nanosec == 500_000_000
        assert [event.kind for event in goal_events] == [
            "GOAL_ACCEPTED", "RUNNING_FEEDBACK", "TERMINAL_RESULT",
        ]
        assert all(event.command_id == command.command_id for event in goal_events)
        assert all(event.phase_id == "approach" for event in goal_events)
        assert len({event.goal_id for event in goal_events}) == 1
        assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                            goal_events[0].goal_id)
        assert goal_events[-1].status == 4
        assert goal_events[-1].result_code == FollowJointTrajectory.Result.SUCCESSFUL
        assert [event.sequence for event in goal_events] == [1, 2, 3]
        assert [event.kind for event in phase_events] == [
            "GOAL_ACCEPTED", "RUNNING_FEEDBACK", "TERMINAL_RESULT",
        ]
    finally:
        executor.shutdown(timeout_sec=2.0)
        spinning.result(timeout=3.0)
        runtime.destroy()
        action_server.destroy()
        for node in (server_node, feedback_node, owner_node):
            node.destroy_node()
        rclpy.shutdown()


def test_runtime_timeout_latches_hold_and_late_cancel_result_does_not_reopen_owner():
    rclpy.init()
    server_node = Node("omx_test_timeout_server")
    feedback_node = Node("omx_test_timeout_feedback")
    owner_node = Node("omx_test_timeout_owner")
    server_goal_received = threading.Event()
    server_cancelled = threading.Event()
    goal_events = []

    def execute(goal_handle):
        server_goal_received.set()
        # Keep the accepted ROS goal alive past the local owner's deadline.
        time.sleep(1.2)
        if goal_handle.is_cancel_requested:
            server_cancelled.set()
            goal_handle.canceled()
        else:
            goal_handle.succeed()
        result = FollowJointTrajectory.Result()
        result.error_code = FollowJointTrajectory.Result.SUCCESSFUL
        return result

    action_name = "/test/omx/timeout/arm_controller/follow_joint_trajectory"
    action_server = ActionServer(
        server_node, FollowJointTrajectory, action_name,
        execute_callback=execute,
        cancel_callback=lambda _goal_handle: CancelResponse.ACCEPT,
    )
    feedback_topic = "/test/omx/timeout/joint_states"
    feedback_publisher = feedback_node.create_publisher(JointState, feedback_topic, 1)
    config = ArmCommandConfig(
        enabled=True,
        workcell_id="test_workcell",
        instance_id="test_instance",
        joint_names=("joint1",),
        position_limits={"joint1": (-1.0, 1.0)},
        allowed_owners=("moveit",),
        calibration_revision="cal-test",
        max_joint_state_age_s=0.5,
        max_goal_duration_s=0.6,
        action_timeout_s=0.8,
    )
    runtime = RosArmCommandRuntime(
        owner_node, config,
        joint_state_topic=feedback_topic,
        trajectory_action=action_name,
        poll_period_s=0.01,
        on_goal_event=goal_events.append,
    )
    executor = MultiThreadedExecutor(num_threads=4)
    for node in (server_node, feedback_node, owner_node):
        executor.add_node(node)
    spinner = ThreadPoolExecutor(max_workers=1)
    spinning = spinner.submit(executor.spin)
    publisher_stop = threading.Event()

    def publish_fresh_state():
        while not publisher_stop.is_set():
            message = JointState()
            message.name = ["joint1"]
            message.position = [0.0]
            feedback_publisher.publish(message)
            publisher_stop.wait(0.03)

    publisher = threading.Thread(target=publish_fresh_state, daemon=True)
    publisher.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if runtime.action_port.server_is_ready() and runtime.latest_joint_state is not None:
                break
            time.sleep(0.01)
        assert runtime.action_port.server_is_ready()
        assert runtime.latest_joint_state is not None
        state = runtime.latest_joint_state
        command = TrajectoryCommand(
            workcell_id=config.workcell_id,
            instance_id=config.instance_id,
            command_id="timeout-command",
            session_id=runtime.owner.session_id,
            owner="moveit",
            positions={"joint1": 0.1},
            duration_s=0.6,
            source_state_sequence=state.sequence,
            calibration_revision=config.calibration_revision,
        )
        assert runtime.submit(command).accepted
        assert server_goal_received.wait(5.0)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and runtime.owner.state != "hold":
            time.sleep(0.01)
        assert runtime.owner.state == "hold"
        assert runtime.owner.poll().reason == "action_timeout"
        assert runtime.last_terminal_decision.reason == "action_timeout"
        assert runtime.submit(command).reason == "hold_latched"

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not server_cancelled.is_set():
            time.sleep(0.01)
        assert server_cancelled.is_set()
        handle = runtime.action_port.last_handle
        assert handle is not None
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and handle.status is None:
            time.sleep(0.01)
        assert handle.done()
        assert handle.cancel_acknowledged is True
        assert handle.status == 5  # ROS action CANCELED; not physical standstill evidence.
        assert runtime.owner.state == "hold"
        assert runtime.owner.poll().reason == "action_timeout"
        assert runtime.submit(command).reason == "hold_latched"
        assert [event.kind for event in goal_events].count("TERMINAL_RESULT") == 1
    finally:
        publisher_stop.set()
        publisher.join(timeout=1.0)
        executor.shutdown(timeout_sec=2.0)
        spinning.result(timeout=3.0)
        runtime.destroy()
        action_server.destroy()
        for node in (server_node, feedback_node, owner_node):
            node.destroy_node()
        rclpy.shutdown()


def test_slow_feedback_handling_cannot_starve_the_joint_state_subscription():
    """C3b A2: a feedback handler slower than max_joint_state_age_s (C3 run4/run7 journal
    writes took up to 0.64 s) must not delay joint-state intake on a MultiThreadedExecutor."""
    rclpy.init()
    server_node = Node("omx_test_flood_server")
    feedback_node = Node("omx_test_flood_state")
    owner_node = Node("omx_test_flood_owner")
    slow_feedbacks = []

    def execute(goal_handle):
        for _ in range(40):  # 40 feedback messages over ~0.8 s
            feedback = FollowJointTrajectory.Feedback()
            feedback.joint_names = ["joint1"]
            goal_handle.publish_feedback(feedback)
            time.sleep(0.02)
        goal_handle.succeed()
        result = FollowJointTrajectory.Result()
        result.error_code = FollowJointTrajectory.Result.SUCCESSFUL
        return result

    action_name = "/test/omx/flood/arm_controller/follow_joint_trajectory"
    action_server = ActionServer(server_node, FollowJointTrajectory, action_name,
                                 execute_callback=execute)
    state_topic = "/test/omx/flood/joint_states"
    state_publisher = feedback_node.create_publisher(JointState, state_topic, 10)
    config = ArmCommandConfig(
        enabled=True, workcell_id="test_workcell", instance_id="test_instance",
        joint_names=("joint1",), position_limits={"joint1": (-1.0, 1.0)},
        allowed_owners=("moveit",), calibration_revision="cal-test",
        max_joint_state_age_s=0.2, max_goal_duration_s=2.0, action_timeout_s=4.0,
    )
    runtime = RosArmCommandRuntime(owner_node, config, joint_state_topic=state_topic,
                                   trajectory_action=action_name, poll_period_s=0.01)
    phase_port = RosArmPhaseGoalPort(runtime)
    executor = MultiThreadedExecutor(num_threads=4)
    for node in (server_node, feedback_node, owner_node):
        executor.add_node(node)
    spinner = ThreadPoolExecutor(max_workers=1)
    spinning = spinner.submit(executor.spin)
    stop = threading.Event()

    def publish_states():
        while not stop.is_set():
            message = JointState()
            message.name = ["joint1"]
            message.position = [0.0]
            state_publisher.publish(message)
            stop.wait(0.01)

    publisher = threading.Thread(target=publish_states, daemon=True)
    publisher.start()

    def slow_sink(event):
        if event.kind == "RUNNING_FEEDBACK" and not slow_feedbacks:
            slow_feedbacks.append(event)
            time.sleep(0.6)  # 3x max_joint_state_age_s inside the ROS callback
        return True

    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not (
                runtime.action_port.server_is_ready() and runtime.latest_joint_state is not None):
            time.sleep(0.01)
        state = runtime.latest_joint_state
        command = TrajectoryCommand(
            workcell_id=config.workcell_id, instance_id=config.instance_id,
            command_id="flood-command", session_id=runtime.owner.session_id, owner="moveit",
            positions={"joint1": 0.1}, duration_s=1.0, source_state_sequence=state.sequence,
            calibration_revision=config.calibration_revision, phase_id="approach",
            start_state_window={"joint1": (0.0, 0.01)},
        )
        assert phase_port.submit(command, on_goal_event=slow_sink).dispatched is True
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and runtime.last_terminal_decision is None:
            time.sleep(0.01)
        assert slow_feedbacks, "the server never sent feedback"
        assert runtime.last_terminal_decision.reason == "completed", runtime.last_terminal_decision
        assert runtime.owner.state == "ready"
    finally:
        stop.set()
        publisher.join(timeout=1.0)
        executor.shutdown(timeout_sec=2.0)
        spinning.result(timeout=3.0)
        runtime.destroy()
        action_server.destroy()
        for node in (server_node, feedback_node, owner_node):
            node.destroy_node()
        rclpy.shutdown()
