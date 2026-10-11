import copy
import hashlib
import io
import json

import pytest
from PIL import Image

from omx_adapter.demonstration import DemonstrationRecorder, validate_episode


def provenance():
    return {"simulation": True, "instance_id": "sim01", "source_revision": "a" * 40,
            "vendor_revision": "b" * 40, "world_sha256": "c" * 64, "source_tree_sha256": "e" * 64,
            "calibration_revision": "sim-v1", "clock_domain": "gazebo_sim",
            "joint_names": ["joint1", "gripper_joint_1"],
            "position_limits_rad": {"joint1": [-1, 1], "gripper_joint_1": [-0.5, 0.5]},
            "camera": {"name": "front", "identity": "gazebo:front", "width": 8, "height": 6,
                       "camera_info_sha256": "d" * 64}, "fps": 10}


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (8, 6), (12, 34, 56)).save(output, format="PNG")
    return output.getvalue()


def sample(recorder, timestamp=1_000_000_000, **changes):
    values = {"capture_time_ns": timestamp, "state_time_ns": timestamp - 10_000_000,
              "positions": {"joint1": 0.01, "gripper_joint_1": -0.1},
              "target": {"joint1": 0.02, "gripper_joint_1": -0.1},
              "state_sequence": timestamp // 1_000_000,
              "command_id": "command", "ros_goal_id": "11111111-1111-4111-8111-111111111111",
              "duration_s": 0.4, "image_png": image_bytes(), "received_at_ns": timestamp + 10}
    values.update(changes)
    recorder.sample(**values)


def complete_episode(root):
    recorder = DemonstrationRecorder(root, provenance())
    recorder.start("move the joint")
    sample(recorder)
    sample(recorder, 1_100_000_000)
    return recorder.stop("success")


def test_complete_episode_preserves_units_targets_clock_and_image_hashes(tmp_path):
    manifest = complete_episode(tmp_path)
    assert manifest["status"] == "complete"
    assert manifest["robot_type"] == "omx_sim_ros"
    assert manifest["action_semantics"] == "absolute_joint_position_target_rad"
    assert manifest["task_outcome"] == "success"
    path = tmp_path / manifest["episode_id"]
    validated = validate_episode(path)
    assert validated["samples"][0]["action"] == [0.02, -0.1]
    assert validated["samples"][0]["observation.state"] == [0.01, -0.1]
    assert validated["samples"][0]["capture_time_ns"] == 1_000_000_000
    frame = validated["samples"][0]["image_path"]
    assert hashlib.sha256((path / frame).read_bytes()).hexdigest() == validated["samples"][0]["image_sha256"]


@pytest.mark.parametrize("change,reason", [
    ({"state_time_ns": 800_000_000}, "state_camera_skew"),
    ({"state_time_ns": 1_000_000_001}, "state_from_future"),
    ({"positions": {"joint1": 0.0}}, "joint_map"),
    ({"target": {"joint1": float("nan"), "gripper_joint_1": 0.0}}, "joint_value"),
    ({"target": {"joint1": 1.1, "gripper_joint_1": 0.0}}, "joint_limit"),
    ({"image_png": b"broken"}, "image_invalid"),
    ({"ros_goal_id": None}, "goal_identity"),
])
def test_bad_source_marks_episode_incomplete_and_export_is_rejected(tmp_path, change, reason):
    recorder = DemonstrationRecorder(tmp_path, provenance())
    recorder.start("move the joint")
    sample(recorder, **change)
    manifest = recorder.stop("success")
    assert manifest["status"] == "incomplete"
    assert reason in manifest["issues"]
    with pytest.raises(ValueError, match="incomplete"):
        validate_episode(tmp_path / manifest["episode_id"])


def test_reset_clock_gap_and_unknown_outcome_are_not_complete(tmp_path):
    recorder = DemonstrationRecorder(tmp_path, provenance())
    recorder.start("move the joint")
    sample(recorder)
    sample(recorder, 900_000_000)
    sample(recorder, 1_300_000_000)
    manifest = recorder.stop("unspecified")
    assert {"clock_not_advancing", "frame_gap", "outcome_unspecified"} <= set(manifest["issues"])


def test_tampered_image_and_path_escape_are_rejected_before_conversion(tmp_path):
    manifest = complete_episode(tmp_path)
    path = tmp_path / manifest["episode_id"]
    records = [json.loads(line) for line in (path / "samples.jsonl").read_text().splitlines()]
    (path / records[0]["image_path"]).write_bytes(image_bytes() + b"changed")
    with pytest.raises(ValueError, match="image hash"):
        validate_episode(path)
    records[0]["image_path"] = "../outside.png"
    payload = "".join(json.dumps(row) + "\n" for row in records).encode()
    (path / "samples.jsonl").write_bytes(payload)
    manifest["samples_sha256"] = hashlib.sha256(payload).hexdigest()
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="image path"):
        validate_episode(path)


def test_native_normalized_units_or_hardware_provenance_cannot_enter_sim_recorder(tmp_path):
    wrong = copy.deepcopy(provenance())
    wrong["simulation"] = False
    with pytest.raises(ValueError, match="simulation"):
        DemonstrationRecorder(tmp_path, wrong)


# --- D-411 C: action.gripper -----------------------------------------------------------

def gripper_provenance():
    return {**provenance(), "gripper_joint": "gripper_joint_1"}


def test_gripper_column_is_written_validated_and_exported(tmp_path):
    recorder = DemonstrationRecorder(tmp_path, gripper_provenance())
    recorder.start("grip")
    sample(recorder)
    sample(recorder, 1_100_000_000, target={"joint1": 0.02, "gripper_joint_1": 0.3})
    manifest = recorder.stop("success")
    assert manifest["status"] == "complete", manifest["issues"]
    rows = validate_episode(tmp_path / manifest["episode_id"])["samples"]
    assert [row["action.gripper"] for row in rows] == [-0.1, 0.3]
    assert all(row["action.gripper"] == row["action"][-1] for row in rows)


def test_gripper_column_must_match_the_action(tmp_path):
    manifest = complete_episode_with(tmp_path, gripper_provenance())
    path = tmp_path / manifest["episode_id"]
    lines = (path / "samples.jsonl").read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    row["action.gripper"] = 0.4
    lines[0] = json.dumps(row, sort_keys=True)
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    (path / "samples.jsonl").write_bytes(payload)
    stored = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    stored["samples_sha256"] = hashlib.sha256(payload).hexdigest()
    (path / "manifest.json").write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(ValueError, match="gripper_action"):
        validate_episode(path)


def test_gripper_joint_must_be_a_recorded_joint(tmp_path):
    with pytest.raises(ValueError, match="gripper joint"):
        DemonstrationRecorder(tmp_path, {**provenance(), "gripper_joint": "finger"})


def test_gripper_goals_may_take_up_to_two_seconds(tmp_path):
    from core_common.protocol.omx_sim import GRIPPER_GOAL_MAX_DURATION_S
    from omx_adapter.demonstration import MAX_GOAL_DURATION_S
    assert MAX_GOAL_DURATION_S == GRIPPER_GOAL_MAX_DURATION_S
    recorder = DemonstrationRecorder(tmp_path, provenance())
    recorder.start("slow grip")
    sample(recorder, duration_s=1.6)
    sample(recorder, 1_100_000_000, duration_s=2.5)
    assert recorder.status()["issues"] == ["goal_duration"]


def test_episodes_without_gripper_joint_still_validate(tmp_path):
    manifest = complete_episode(tmp_path)
    path = tmp_path / manifest["episode_id"]
    assert "action.gripper" not in (path / "samples.jsonl").read_text(encoding="utf-8")
    assert "gripper_joint" not in manifest["provenance"]
    validate_episode(path)


def complete_episode_with(root, source):
    recorder = DemonstrationRecorder(root, source)
    recorder.start("move the joint")
    sample(recorder)
    sample(recorder, 1_100_000_000)
    return recorder.stop("success")
