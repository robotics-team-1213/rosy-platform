"""Shared artifact boundaries, provenance and incompatible owner/action bindings."""
import copy
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts/learning/src"))
from rosy.contracts.learning import seal, validate_episode, validate_dataset, validate_policy, validate_promotion


REF = {"path": "source.jsonl", "sha256": "a" * 64, "bytes": 0}


def episode():
    return seal({"schema": "rosy.episode/1", "episode_id": "episode-1", "profile": "omx_demonstration_v1",
                 "device": "sim-arm", "robot_type": "omx_sim_ros", "environment": "sim",
                 "clock_domain": "gazebo_sim", "task": "transfer", "skill": None,
                 "revisions": {"policy": None, "model": None, "calibration": None, "camera_profile": None},
                 "sources": [REF], "streams": {"observation": REF, "action": REF, "events": REF},
                 "correlations": {"action_ids": [], "attempt_ids": []},
                 "status": "complete", "outcome": {"task": "unknown", "action": "succeeded",
                 "judge": "unknown", "evidence": []}})


def policy():
    return seal({"schema": "rosy.policy-artifact/1", "profile": "omx_joint_target_v1",
                 "robot_type": "omx_sim_ros", "environment": "sim", "files": [REF],
                 "device_profile_revision": "profile-1", "camera_profile_revision": "camera-1",
                 "joint_names": ["j1", "j2"], "normalization": REF, "cameras": [],
                 "observation": {"names": ["j1", "j2"], "units": ["rad", "rad"], "shape": [2]},
                 "action": {"names": ["j1", "j2"], "units": ["rad", "rad"],
                            "semantics": "absolute_joint_position_target_rad",
                            "limits": [[-1, 1], [-2, 2]]},
                 "owner": {"kind": "omx_local_controller", "controller_revision": "controller-1",
                           "envelope_revision": "envelope-1"},
                 "timing": {"period_ns": 100000000, "max_observation_age_ns": 50000000,
                            "max_action_age_ns": 50000000}, "failure_mode": "hold",
                 "reset_events": ["stop", "hold", "lease_change", "episode_change"],
                 "dataset_revisions": ["b" * 64], "evaluations": [REF],
                 "tool_revision": "trainer-1"})


def test_episode_preserves_unknown_and_does_not_infer_task_success():
    value = validate_episode(episode())
    assert value["outcome"]["task"] == "unknown"
    assert value["revisions"]["calibration"] is None
    value["device"] = "changed"
    with pytest.raises(ValueError, match="revision"):
        validate_episode(value)


@pytest.mark.parametrize("change", [
    {"clock_domain": ""}, {"environment": "real", "clock_domain": "gazebo_sim"},
    {"sources": [{**REF, "path": "../secret"}]},
    {"correlations": {"action_ids": [], "attempt_ids": [], "mission_id": "invented"}},
])
def test_episode_refuses_invalid_clock_escape_and_device_mission_claims(change):
    doc = episode()
    doc.update(change)
    with pytest.raises(ValueError):
        validate_episode(seal(doc))


def test_artifact_file_hash_is_checked_when_root_is_supplied(tmp_path):
    doc = episode()
    (tmp_path / REF["path"]).write_bytes(b"")
    with pytest.raises(ValueError, match="hash"):
        validate_episode(doc, root=tmp_path)


def test_episode_verifies_actual_bytes_and_then_refuses_tamper(tmp_path):
    doc = episode()
    ref = {**REF, "sha256": hashlib.sha256(b"").hexdigest()}
    doc["sources"] = [ref]
    doc["streams"] = {kind: ref for kind in ("observation", "action", "events")}
    (tmp_path / ref["path"]).write_bytes(b"")
    doc = seal(doc)
    assert validate_episode(doc, root=tmp_path)["revision"] == doc["revision"]
    (tmp_path / ref["path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash"):
        validate_episode(doc, root=tmp_path)


def test_stage_jump_and_different_policy_cannot_use_promotion_evidence():
    candidate = policy()
    checks = [{"kind": kind, "verdict": "pass", "report": REF} for kind in
              ("offline_eval", "sim_eval", "owner_contract", "independent_task_outcome")]
    doc = seal({"schema": "rosy.promotion-record/1", "policy_revision": "f" * 64,
                "from_stage": "unregistered", "to_stage": "L0", "checks": checks, "authority": None})
    with pytest.raises(ValueError, match="revision"):
        validate_promotion(doc, candidate)
    doc.update(policy_revision=candidate["revision"], to_stage="L3")
    with pytest.raises(ValueError, match="stage"):
        validate_promotion(seal(doc), candidate)


def test_policy_can_preserve_unknown_camera_profile_with_explicit_rig():
    doc = policy()
    doc["camera_profile_revision"] = None
    doc["cameras"] = [{"name": "front", "identity": "gazebo:front", "calibration_sha256": "c" * 64,
                      "source_shape": [3, 240, 320], "model_shape": [3, 64, 64],
                      "color": "rgb", "scale": 1 / 255}]
    assert validate_policy(seal(doc))["camera_profile_revision"] is None
    doc["environment"] = "real"
    candidate = seal(doc)
    checks = [{"kind": k, "verdict": "pass", "report": REF} for k in
              ("offline_eval", "sim_eval", "owner_contract", "independent_task_outcome", "shadow_eval", "stop_readback")]
    promotion = seal({"schema": "rosy.promotion-record/1", "policy_revision": candidate["revision"],
                      "from_stage": "L0", "to_stage": "L1", "checks": checks, "authority": None})
    with pytest.raises(ValueError, match="camera"):
        validate_promotion(promotion, candidate)


@pytest.mark.parametrize("field,value", [
    ("owner", {"kind": "pinky_core_command_manager", "controller_revision": "c", "envelope_revision": "e"}),
    ("joint_names", ["j2", "j1"]), ("failure_mode", "clamp"), ("reset_events", ["stop"]),
    ("timing", {"period_ns": True, "max_observation_age_ns": 1, "max_action_age_ns": 1}),
])
def test_policy_refuses_incompatible_owner_order_and_timing(field, value):
    doc = policy()
    doc[field] = value
    with pytest.raises(ValueError):
        validate_policy(seal(doc))


def test_pinky_velocity_semantics_and_units_are_distinct():
    doc = policy()
    doc.update(profile="pinky_base_velocity_v1", robot_type="pinky_pro", joint_names=[])
    doc["action"] = {"names": ["linear_x", "angular_z"], "units": ["m/s", "rad/s"],
                     "semantics": "base_velocity_candidate", "limits": [[-.1, .1], [-.2, .2]]}
    doc["owner"]["kind"] = "pinky_core_command_manager"
    assert validate_policy(seal(doc))["action"]["semantics"] == "base_velocity_candidate"
    doc["action"]["units"] = ["rad", "rad"]
    with pytest.raises(ValueError):
        validate_policy(seal(doc))


def test_dataset_requires_distinct_source_episode_revisions():
    doc = seal({"schema": "rosy.dataset-manifest/1", "episodes": [episode()["revision"]],
                "transformation": {"tool_revision": "curation-1", "config_sha256": "c" * 64},
                "files": [REF]})
    assert validate_dataset(doc)["episodes"]
    doc["episodes"] *= 2
    with pytest.raises(ValueError):
        validate_dataset(seal(doc))


def test_promotion_requires_evidence_and_explicit_authority_for_physical_use():
    candidate = policy()
    checks = [{"kind": kind, "verdict": "pass", "report": REF} for kind in
              ("offline_eval", "sim_eval", "owner_contract", "independent_task_outcome")]
    doc = seal({"schema": "rosy.promotion-record/1", "policy_revision": candidate["revision"],
                "from_stage": "unregistered", "to_stage": "L0", "checks": checks, "authority": None})
    assert validate_promotion(doc, candidate)["to_stage"] == "L0"
    doc["checks"][0]["verdict"] = "unknown"
    with pytest.raises(ValueError):
        validate_promotion(seal(doc), candidate)
    doc.update(from_stage="L1", to_stage="L2", checks=copy.deepcopy(checks))
    with pytest.raises(ValueError):
        validate_promotion(seal(doc), candidate)
