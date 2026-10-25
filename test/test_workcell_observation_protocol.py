"""Pure read-only workcell manifests and arm payloads, without ROS or devices."""
from copy import deepcopy
from hashlib import sha256

import pytest
from pydantic import ValidationError

from core_common.protocol.workcell_observations import ArmObservation, WorkcellObservationManifest


@pytest.fixture
def manifest():
    arms = [{"source_id": f"arm_{side}_feedback", "arm_id": f"arm_{side}", "label": f"Arm {side}",
             "board_id": f"EXAMPLE-BOARD-{side.upper()}",
             "joint_topic": f"/omx_commissioning/arm_{side}/joint_states",
             "joint_names": [f"joint{number}" for number in range(1, 7)],
             "token_env": f"EXAMPLE_ARM_{side.upper()}_TOKEN",
             "credential_sha256": sha256(f"example-arm-{side}".encode()).hexdigest()} for side in ("a", "b")]
    cameras = [{"source_id": "shared_top", "label": "Shared top", "role": "overhead", "arm_id": None,
                "image_topic": "/top_camera/image_raw", "device_path": "/dev/v4l/by-id/example-top",
                "token_env": "EXAMPLE_TOP_TOKEN", "credential_sha256": sha256(b"example-top").hexdigest()}]
    cameras += [{"source_id": f"wrist_{side}", "label": f"Wrist {side}", "role": "wrist",
                 "arm_id": f"arm_{side}", "image_topic": f"/wrist_{side}_camera/image_raw",
                 "device_path": f"/dev/v4l/by-path/example-port-{side}",
                 "token_env": f"EXAMPLE_WRIST_{side.upper()}_TOKEN",
                 "credential_sha256": sha256(f"example-wrist-{side}".encode()).hexdigest()} for side in ("a", "b")]
    return {"schema": "rosy.workcell-observations/1", "workcells": [
        {"workcell_id": "example_cell", "label": "Example cell", "arms": arms, "cameras": cameras}]}


def test_two_followers_can_share_joint_names_with_three_preview_only_cameras(manifest):
    parsed = WorkcellObservationManifest.model_validate(manifest)
    assert parsed.model_dump(by_alias=True) == manifest
    assert parsed.workcells[0].arms[0].joint_names == parsed.workcells[0].arms[1].joint_names


@pytest.mark.parametrize("group,field", [
    ("arms", "source_id"), ("arms", "arm_id"), ("arms", "board_id"), ("arms", "joint_topic"),
    ("cameras", "source_id"), ("cameras", "image_topic"), ("cameras", "device_path"),
    ("cameras", "token_env"),
])
def test_manifest_refuses_ambiguous_source_binding(manifest, group, field):
    rows = manifest["workcells"][0][group]
    rows[1][field] = rows[0][field]
    with pytest.raises(ValidationError):
        WorkcellObservationManifest.model_validate(manifest)


def test_manifest_refuses_source_and_credential_aliases_between_arms_and_cameras(manifest):
    for field in ("source_id", "token_env", "credential_sha256"):
        changed = deepcopy(manifest)
        cell = changed["workcells"][0]
        cell["cameras"][0][field] = cell["arms"][0][field]
        with pytest.raises(ValidationError):
            WorkcellObservationManifest.model_validate(changed)


@pytest.mark.parametrize("group,index,field,value", [
    ("arms", 0, "joint_topic", "/joint_states"), ("arms", 0, "joint_topic", "/arm/command"),
    ("arms", 0, "joint_names", ["joint1", "joint1"]), ("arms", 0, "arm_id", "bad/id"),
    ("cameras", 1, "arm_id", "unregistered_arm"), ("cameras", 0, "arm_id", "arm_a"),
    ("cameras", 1, "device_path", "/dev/video2"), ("cameras", 1, "image_topic", "/control/image_raw"),
    ("cameras", 1, "device_path", "/dev/v4l/by-path/../camera"),
    ("cameras", 1, "token_env", "secret-value"), ("arms", 0, "label", "unsafe\nlabel"),
    ("arms", 0, "source_id", "a" * 33), ("cameras", 0, "source_id", "b" * 33),
    ("arms", 0, "credential_sha256", "f" * 63), ("cameras", 0, "credential_sha256", "F" * 64),
])
def test_manifest_rejects_unbound_or_untrusted_configuration(manifest, group, index, field, value):
    manifest["workcells"][0][group][index][field] = value
    with pytest.raises(ValidationError):
        WorkcellObservationManifest.model_validate(manifest)


def test_manifest_refuses_duplicate_workcells_and_unknown_authority_fields(manifest):
    changed = deepcopy(manifest)
    changed["workcells"].append(deepcopy(changed["workcells"][0]))
    with pytest.raises(ValidationError):
        WorkcellObservationManifest.model_validate(changed)
    manifest["workcells"][0]["arms"][0]["command_topic"] = "/arm/command"
    with pytest.raises(ValidationError):
        WorkcellObservationManifest.model_validate(manifest)


@pytest.fixture
def observation():
    return {"epoch": "0123456789abcdef" * 2, "sequence": 1, "captured_at": 100,
            "positions": {"joint1": 0, "joint2": 0.25}}


def test_arm_payload_accepts_json_numbers_without_resolving_age_or_credentials(observation):
    assert ArmObservation.model_validate(observation).model_dump() == observation


@pytest.mark.parametrize("field,value", [
    ("epoch", "A" * 32), ("epoch", "0" * 31), ("sequence", 0), ("sequence", True),
    ("sequence", "1"), ("sequence", 1.0), ("captured_at", 0), ("captured_at", True),
    ("captured_at", "100"), ("captured_at", float("nan")), ("captured_at", float("inf")),
    ("positions", {}), ("positions", {"joint1": True}), ("positions", {"joint1": "0.2"}),
    ("positions", {"joint1": float("nan")}), ("positions", {"joint1": float("-inf")}),
    ("positions", {f"joint{index}": 0 for index in range(9)}), ("positions", {"bad/joint": 0}),
    ("workcell_id", "another_cell"),
])
def test_arm_payload_rejects_coercion_nonfinite_values_and_identity_override(observation, field, value):
    observation[field] = value
    with pytest.raises(ValidationError):
        ArmObservation.model_validate(observation)
