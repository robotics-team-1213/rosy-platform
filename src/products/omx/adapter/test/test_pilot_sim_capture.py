import time
from types import SimpleNamespace as NS

from omx_adapter.pilot_sim_capture import PilotSimCapture
from omx_adapter.ros_goal_contract import RosGoalEvent
from test_demonstration import sample


def camera():
    image = NS(width=8, height=6, encoding="rgb8", step=24, data=bytes([12, 34, 56] * 48))
    metadata = NS(capture_time_ns=1_100_000_000, received_at=time.monotonic(), sequence=1,
                  camera_identity="gazebo:front", width=8, height=6)
    return NS(latest_frame=(metadata, image, None), is_fresh=lambda: True,
              gate=NS(config=NS(camera_info_sha256="d" * 64)))


def create_capture(tmp_path):
    config = NS(joint_names=("joint1", "gripper_joint_1"),
                position_limits={"joint1": (-1, 1), "gripper_joint_1": (-0.5, 0.5)},
                calibration_revision="sim-v1", max_joint_state_age_s=0.5)
    runtime = NS(arm=NS(owner=NS(config=config, state="ready")), instance_id="sim01",
                 snapshot=lambda: {"ready": True})
    source = {"source_revision": "a" * 40, "vendor_revision": "b" * 40,
              "world_sha256": "c" * 64, "source_tree_sha256": "e" * 64}
    capture = PilotSimCapture(runtime, tmp_path, source, sim_time_ns=lambda: 1_050_000_000)
    capture.camera = camera()
    return capture


def state(ns, position):
    return NS(header=NS(stamp=NS(sec=ns // 1_000_000_000, nanosec=ns % 1_000_000_000)),
              name=["joint1", "gripper_joint_1"], position=[position, -0.1])


def test_record_matches_past_source_state_not_latest_future_state(tmp_path):
    capture = create_capture(tmp_path)
    capture.start("move joint")
    capture.prepare(NS(command_id="command", positions={"joint1": 0.02, "gripper_joint_1": -0.1},
                       duration_s=0.4))
    capture.on_goal_event(RosGoalEvent(kind="GOAL_ACCEPTED", command_id="command", phase_id=None,
                                      goal_id="11111111-1111-4111-8111-111111111111",
                                      observed_at_monotonic_s=time.monotonic(), sequence=1))
    capture.observe_joint_state(state(1_090_000_000, 0.01))
    capture.observe_joint_state(state(1_110_000_000, 0.9))
    capture.camera.latest_frame[0].sequence = 2
    capture.tick()
    assert capture.status()["frame_count"] == 1
    assert capture.camera_jpeg().startswith(b"\xff\xd8")
    capture.interrupt("lease_expired")
    result = capture.status()
    assert result["status"] == "incomplete"
    assert "lease_expired" in result["issues"]


def test_local_dispatch_without_ros_acceptance_produces_no_training_frames(tmp_path):
    capture = create_capture(tmp_path)
    capture.start("move joint")
    capture.prepare(NS(command_id="command", positions={"joint1": 0.02, "gripper_joint_1": -0.1},
                       duration_s=0.4))
    capture.observe_joint_state(state(1_090_000_000, 0.01))
    capture.tick()
    assert capture.status()["frame_count"] == 0
    capture.interrupt("owner_restart")
    assert capture.status()["status"] == "incomplete"


def test_ros_acceptance_callback_never_writes_to_recording_storage(tmp_path):
    capture = create_capture(tmp_path)
    capture.start("move joint")
    capture.prepare(NS(command_id="command", positions={"joint1": 0.02, "gripper_joint_1": -0.1},
                       duration_s=0.4))
    writes = []
    capture.recorder.event = lambda event: writes.append(event)
    capture.on_goal_event(RosGoalEvent(kind="GOAL_ACCEPTED", command_id="command", phase_id=None,
                                      goal_id="11111111-1111-4111-8111-111111111111",
                                      observed_at_monotonic_s=time.monotonic(), sequence=1))
    assert writes == []
    capture.tick()
    assert writes[0]["kind"] == "GOAL_ACCEPTED"
    capture.interrupt("test_shutdown")


def test_operator_stop_cannot_hide_a_pending_ros_failure(tmp_path):
    capture = create_capture(tmp_path)
    episode = capture.start("move joint")
    capture.on_goal_event(RosGoalEvent(kind="GOAL_REJECTED", command_id="command", phase_id=None, goal_id=None,
                                      observed_at_monotonic_s=time.monotonic(), sequence=1))
    closed = capture.stop(episode["episode_id"], "success")
    assert "goal_acceptance_or_result_unknown" in closed["issues"]
    assert closed["status"] == "incomplete"


def test_delayed_camera_pairs_historical_state_while_live_stream_is_fresh(tmp_path):
    capture = create_capture(tmp_path)
    capture.start("move joint")
    capture.prepare(NS(command_id="command", positions={"joint1": 0.02, "gripper_joint_1": -0.1},
                       duration_s=0.4))
    capture.on_goal_event(RosGoalEvent(kind="GOAL_ACCEPTED", command_id="command", phase_id=None,
                                      goal_id="11111111-1111-4111-8111-111111111111",
                                      observed_at_monotonic_s=time.monotonic(), sequence=1))
    capture.observe_joint_state(state(1_090_000_000, 0.01))
    old = capture._states.pop()
    capture._states.append((*old[:3], time.monotonic() - 1))
    capture.observe_joint_state(state(1_900_000_000, 0.9))
    capture.camera.latest_frame[0].sequence = 2
    capture.tick()
    assert capture.status()["frame_count"] == 1
    # A stale live stream is still rejected independently of source pairing.
    newest = capture._states.pop()
    capture._states.append((*newest[:3], time.monotonic() - 1))
    capture.camera.latest_frame[0].sequence = 3
    capture.tick()
    assert "joint_readback_stale" in capture.status()["issues"]


def test_interrupt_arriving_during_stop_storage_drain_is_in_manifest(tmp_path):
    capture = create_capture(tmp_path)
    episode = capture.start("move joint")
    sample(capture.recorder)
    sample(capture.recorder, 1_100_000_000)
    capture._events.append({"kind": "TERMINAL_RESULT"})
    original = capture.recorder.event

    def write_with_lease_expiry(event):
        original(event)
        capture.request_interrupt("control_released")

    capture.recorder.event = write_with_lease_expiry
    closed = capture.stop(episode["episode_id"], "success")
    assert closed["frame_count"] == 2
    assert closed["status"] == "incomplete"
    assert "control_released" in closed["issues"]


def test_gripper_mode_records_the_gripper_joint_and_action_column(tmp_path):
    import json
    capture = create_capture(tmp_path)
    assert capture.start("legacy")["provenance"]["gripper_joint"] is None
    capture.stop(capture.status()["episode_id"], "failure")
    capture = create_capture(tmp_path)
    capture.runtime.gripper, capture.runtime._gripper_spec = "gripper_joint_1", (0.4, 0.0)
    episode = capture.start("grip")
    assert episode["provenance"]["gripper_joint"] == "gripper_joint_1"
    capture.prepare(NS(command_id="command", positions={"joint1": 0.0, "gripper_joint_1": 0.3},
                       duration_s=1.6))
    capture.on_goal_event(RosGoalEvent(kind="GOAL_ACCEPTED", command_id="command", phase_id=None,
                                      goal_id="11111111-1111-4111-8111-111111111111",
                                      observed_at_monotonic_s=time.monotonic(), sequence=1))
    capture.observe_joint_state(state(1_090_000_000, 0.01))
    capture.camera.latest_frame[0].sequence = 2
    capture.tick()
    assert capture.status()["issues"] == []
    row = json.loads((tmp_path / episode["episode_id"] / "samples.jsonl").read_text().splitlines()[0])
    assert row["action.gripper"] == 0.3 and row["duration_s"] == 1.6
