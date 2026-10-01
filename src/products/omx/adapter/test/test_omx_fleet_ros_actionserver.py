"""Exercise Fleet-to-UDS-to-ROS contracts with an in-process ActionServer fixture."""

from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

rclpy = pytest.importorskip("rclpy", reason="requires the ROS 2 Jazzy runtime")
pytest.importorskip("fcntl", reason="requires Linux Unix peer credentials")

FLEET_ROOT = Path(__file__).resolve().parents[4] / "site" / "fleet"
FLEET_TEST_ROOT = FLEET_ROOT / "test"
for entry in (str(FLEET_ROOT), str(FLEET_TEST_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from action_msgs.msg import GoalStatus  # noqa: E402
from control_msgs.action import FollowJointTrajectory  # noqa: E402
from rclpy.action import ActionServer  # noqa: E402
from rclpy.executors import MultiThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402

from core_common.protocol.schemas import FleetActionGrant  # noqa: E402
from fleet.server.local_action_transport import UnixLocalActionTransport  # noqa: E402
from fleet.server.mission_dispatcher import MissionDispatcher  # noqa: E402
from omx_adapter.action_api import ActionApi, UnixActionServer  # noqa: E402
from omx_adapter.action_runner import ActionRunner  # noqa: E402
from omx_adapter.action_store import ActionStore  # noqa: E402
from omx_adapter.command_owner import ArmCommandConfig, TrajectoryCommand  # noqa: E402
from omx_adapter.local_stop import LocalStopController  # noqa: E402
from omx_adapter.manipulation_plan import (  # noqa: E402
    ExecutionStateSnapshot,
    JointTrajectoryPoint,
    PlannedMotionPhase,
    ResolvedObjectPose,
    ResolvedPickPlacePlan,
)
from omx_adapter.pick_place_runner import PickPlaceRunner  # noqa: E402
from omx_adapter.ros_runtime import RosArmCommandRuntime, RosArmPhaseGoalPort  # noqa: E402
from test_mission_dispatcher import _ready_mission  # noqa: E402


def test_fleet_mission_reaches_ros_goal_once_without_claiming_semantic_completion(tmp_path):
    peer_uid = os.getuid()
    workcell_id = "omx-1"
    instance_id = "omx-1-control"
    action_name = "/test/fleet_omx/follow_joint_trajectory"
    joint_state_topic = "/test/fleet_omx/joint_states"
    config = ArmCommandConfig(
        enabled=True, workcell_id=workcell_id, instance_id=instance_id,
        joint_names=("joint1",), position_limits={"joint1": (-0.1, 0.1)},
        allowed_owners=("rule_based",), calibration_revision="cal-1",
        max_joint_state_age_s=5.0, max_goal_duration_s=1.0, action_timeout_s=2.0,
    )

    rclpy.init()
    ros_node = Node("fleet_omx_ros_contract_test")
    state_publisher = ros_node.create_publisher(JointState, joint_state_topic, 10)

    def publish_state():
        message = JointState()
        message.name = ["joint1"]
        message.position = [0.0]
        state_publisher.publish(message)

    state_timer = ros_node.create_timer(0.02, publish_state)
    goals = []
    goal_received = threading.Event()

    def execute_goal(goal_handle):
        goals.append(goal_handle.request)
        goal_received.set()
        goal_handle.succeed()
        result = FollowJointTrajectory.Result()
        result.error_code = FollowJointTrajectory.Result.SUCCESSFUL
        return result

    action_server = ActionServer(
        ros_node, FollowJointTrajectory, action_name, execute_callback=execute_goal,
    )
    runtime = RosArmCommandRuntime(
        ros_node, config, joint_state_topic=joint_state_topic,
        trajectory_action=action_name, poll_period_s=0.01,
    )
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(ros_node)
    spinner = ThreadPoolExecutor(max_workers=1)
    spinning = spinner.submit(executor.spin)

    server = None
    server_thread = None
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if runtime.action_port.server_is_ready():
                publish_state()
                if runtime.latest_joint_state is not None:
                    state_timer.cancel()
                    break
            time.sleep(0.02)
        assert runtime.action_port.server_is_ready()
        assert runtime.latest_joint_state is not None
        time.sleep(0.1)  # allow the last already-published DDS sample to settle

        fleet_store, mission_service, mission, _ = _ready_mission(tmp_path)
        fence = fleet_store.dispatch_control()
        socket_root = tmp_path / "omx"
        socket_dir = socket_root / instance_id
        socket_dir.mkdir(parents=True)
        socket_path = socket_dir / "control.sock"
        action_db = tmp_path / "omx-actions.sqlite3"
        action_store = ActionStore(action_db)
        local_stop = LocalStopController(
            action_db, workcell_id=workcell_id, instance_id=instance_id,
        )

        def fleet_fence_current(epoch, generation):
            current = fleet_store.dispatch_control()
            return (current["dispatch_enabled"]
                    and current["authority_epoch"] == epoch
                    and current["generation"] == generation)

        local_stop.rearm(
            authority_epoch=fence["authority_epoch"],
            dispatch_generation=fence["generation"], operator_confirmed=True,
            fleet_fence_current=fleet_fence_current,
        )
        phase_runners = []
        ros_goal_port = RosArmPhaseGoalPort(runtime)

        def phase_runner_factory(grant, recorder):
            state = runtime.latest_joint_state
            assert state is not None
            position = state.positions["joint1"]

            def resolved_pose(evidence, *, digest):
                return ResolvedObjectPose(
                    object_id=evidence.object_id, observation_id=grant.observation_revision,
                    camera_identity="test-fixture-no-camera",
                    optical_frame_id="test_fixture_optical",
                    rgb_frame_sha256=digest, depth_frame_sha256="d" * 64,
                    capture_time_ns=evidence.capture_time_ns,
                    calibration_revision=evidence.calibration_revision,
                    transform_revision=evidence.transform_revision,
                    workspace_frame_id="omx_base", translation_m=(0.0, 0.0, 0.0),
                    orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
                    covariance_6x6=tuple(0.0 for _ in range(36)),
                    position_stddev_m=0.001,
                )

            point = JointTrajectoryPoint(time_from_start_s=0.25, positions=(position,))
            phase_names = ("approach", "grasp", "transfer", "release")
            phases = tuple(PlannedMotionPhase(
                phase_id=phase_id, ordinal=ordinal, joint_names=("joint1",),
                points=(point,), start_state_positions=(position,),
                source_state_sequence=state.sequence, calibration_revision="cal-1",
                transform_revision="test-tf", planning_scene_revision="test-scene",
            ) for ordinal, phase_id in enumerate(phase_names))
            plan = ResolvedPickPlacePlan(
                source_pose=resolved_pose(grant.source_evidence, digest="c" * 64),
                destination_pose=resolved_pose(grant.destination_evidence, digest="e" * 64),
                phases=phases, planner_revision="bounded-noop-test-fixture",
                planning_scene_revision="test-scene", calibration_revision="cal-1",
                transform_revision="test-tf", source_state_sequence=state.sequence,
                planned_at_monotonic_s=time.monotonic(),
            )

            def current_execution_state():
                latest = runtime.latest_joint_state
                if latest is None:
                    raise RuntimeError("fresh ROS joint state is unavailable")
                return ExecutionStateSnapshot(
                    sequence=latest.sequence, joint_positions=dict(latest.positions),
                    calibration_revision="cal-1", transform_revision="test-tf",
                    planning_scene_revision="test-scene",
                    observed_at_monotonic_s=latest.received_at,
                )

            def command_for_phase(phase):
                return TrajectoryCommand(
                    workcell_id=grant.workcell_id, instance_id=grant.instance_id,
                    command_id=f"{grant.action_id}:{phase.phase_id}",
                    session_id=runtime.owner.session_id, owner="rule_based",
                    positions={"joint1": phase.points[-1].positions[0]},
                    duration_s=phase.points[-1].time_from_start_s,
                    source_state_sequence=phase.source_state_sequence,
                    calibration_revision=phase.calibration_revision,
                    joint_names=phase.joint_names, trajectory_points=phase.points,
                    phase_id=phase.phase_id,
                )

            runner = PickPlaceRunner(
                recorder, grant, plan, command_for_phase=command_for_phase,
                goal_port=ros_goal_port, submission_fence=local_stop,
                phase_gate=lambda phase_id: phase_id == "approach",
                current_fence=fleet_fence_current,
                current_execution_state=current_execution_state,
                start_state_tolerances={"joint1": 0.01}, max_joint_state_age_s=5.0,
            )
            phase_runners.append(runner)
            return runner

        action_runner = ActionRunner(
            action_store, object(), workcell_id=workcell_id, instance_id=instance_id,
            principal_for_peer=lambda uid: "operator-1" if uid == peer_uid else "",
            allowed_peer_uids={peer_uid}, current_fence=fleet_fence_current,
            capability_current=lambda grant: grant.config_revision == "cfg-1",
            submission_fence=local_stop, phase_runner_factory=phase_runner_factory,
            enabled=True,
        )
        server = UnixActionServer(ActionApi(action_runner), socket_path)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        deadline = time.monotonic() + 2.0
        while not socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert socket_path.exists()

        transport = UnixLocalActionTransport(socket_root, timeout_s=0.75)
        dispatcher = MissionDispatcher(
            mission_service, fleet_store, transport,
            {mission["workcell_id"]: mission["instance_id"]},
        )
        submitted = dispatcher.dispatch_next()
        persisted_mission = mission_service.get(mission["mission_id"])
        grant = FleetActionGrant.model_validate(persisted_mission["action_grant"])
        stored_action = action_store.get_action(grant.action_id)
        stored_phases = action_store.action_phases(grant.action_id, attempt_id=grant.attempt_id)
        stored_events = action_store.history(grant.action_id)
        assert submitted["state"] in {"SUBMITTING", "ACCEPTED", "RUNNING"}, (
            submitted.get("state"), submitted.get("reason"),
            stored_action.get("state") if stored_action else None,
            stored_action.get("reason") if stored_action else None,
            [(row["phase_id"], row["state"], row.get("result")) for row in stored_phases],
            [(event["event_type"], event["detail"]) for event in stored_events[-6:]],
            len(phase_runners), len(goals),
        )
        assert goal_received.wait(5.0)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            phases = action_store.action_phases(grant.action_id, attempt_id=grant.attempt_id)
            if phases and phases[0]["state"] == "SUCCEEDED":
                break
            time.sleep(0.01)
        phases = action_store.action_phases(grant.action_id, attempt_id=grant.attempt_id)
        assert [phase["phase_id"] for phase in phases] == ["approach"]
        assert phases[0]["state"] == "SUCCEEDED"
        assert len(goals) == 1
        assert goals[0].trajectory.joint_names == ["joint1"]
        assert list(goals[0].trajectory.points[-1].positions) == [0.0]
        assert runtime.action_port.last_handle is not None
        assert runtime.action_port.last_handle.status == GoalStatus.STATUS_SUCCEEDED
        assert action_store.get_action(grant.action_id)["state"] != "SUCCEEDED"
        assert len(phase_runners) == 1

        reconciled = dispatcher.dispatch_next()
        persisted_mission = mission_service.get(mission["mission_id"])
        assert reconciled["state"] == "ACCEPTED"
        assert persisted_mission["status"] == "RUNNING"
        assert mission["goal_predicate"]["condition"] == "object_in_destination"
        assert all(event["event_type"] != "GOAL_PREDICATE_CONFIRMED"
                   for event in mission_service.history(mission["mission_id"]))

        recovered_store = ActionStore(action_db)
        assert recovered_store.recover_after_restart() == [grant.action_id]
        assert recovered_store.get_action(grant.action_id)["state"] == "UNKNOWN"
        recovered_runner = ActionRunner(
            recovered_store, object(), workcell_id=workcell_id, instance_id=instance_id,
            principal_for_peer=lambda uid: "operator-1" if uid == peer_uid else "",
            allowed_peer_uids={peer_uid}, current_fence=fleet_fence_current,
            capability_current=lambda current: current.config_revision == "cfg-1",
            submission_fence=local_stop, enabled=True,
        )
        server.api.runner = recovered_runner
        duplicate = transport.submit(grant)
        assert duplicate.state.value == "UNKNOWN"
        assert duplicate.created is False
        assert len(goals) == 1, "replayed Fleet grant must not create a second ROS goal"

    finally:
        if server is not None:
            server.stop()
        if server_thread is not None:
            server_thread.join(timeout=2.0)
            assert not server_thread.is_alive()
        executor.shutdown(timeout_sec=2.0)
        spinning.result(timeout=3.0)
        runtime.destroy()
        ros_node.destroy_timer(state_timer)
        action_server.destroy()
        ros_node.destroy_node()
        rclpy.shutdown()
