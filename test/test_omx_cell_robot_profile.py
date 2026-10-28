"""Per-device profile association pins the native recorder without granting motion authority."""
import copy
import importlib
import json
from pathlib import Path
import sys

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"


@pytest.fixture
def profiles(monkeypatch):
    monkeypatch.syspath_prepend(str(OMX))
    return importlib.import_module("cell_robot_profile")


@pytest.fixture
def profile_file(tmp_path, profiles):
    robot = {"type": "omx_follower", "id": "arm-a", "port": "/dev/serial/by-id/fixture-a", "cameras": {}}
    document = {"schema": profiles.SCHEMA, "device_id": "fixture-device-a", "instance_id": "arm-a",
                "robot_config_sha256": profiles.digest(robot), "operating_envelope_path": "arm-a/review.json",
                "work_dir": "arm-a"}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, robot, document


def test_profile_pins_existing_robot_and_resolves_its_own_evidence_paths(profile_file, profiles):
    path, robot, document = profile_file
    loaded = profiles.load(path, robot_config=robot)
    assert loaded["binding"] == {"device_id": document["device_id"], "instance_id": "arm-a",
                                  "robot_config_sha256": profiles.digest(robot),
                                  "profile_sha256": profiles.digest(document)}
    assert Path(loaded["work_dir"]) == path.parent / "arm-a"
    assert Path(loaded["operating_envelope_path"]) == path.parent / "arm-a/review.json"


@pytest.mark.parametrize("field,value", [("id", "arm-b"), ("port", "/dev/serial/by-id/fixture-b"),
                                         ("max_relative_target", 1.0)])
def test_another_robot_or_changed_settings_cannot_use_the_profile(profile_file, profiles, field, value):
    path, robot, _ = profile_file
    with pytest.raises(ValueError):
        profiles.load(path, robot_config={**robot, field: value})


@pytest.mark.parametrize("change", [{"device_id": ""}, {"device_id": "../arm"},
    {"instance_id": ""}, {"robot_config_sha256": "invalid"}, {"enabled": True},
    {"operating_envelope_path": None}, {"work_dir": ""}, {"device_id": "<device-id>"}])
def test_incomplete_or_authority_bearing_profile_is_rejected(profile_file, profiles, change):
    path, _, document = profile_file
    path.write_text(json.dumps({**document, **change}))
    with pytest.raises(ValueError):
        profiles.load(path)


def test_profiles_for_two_arms_have_independent_identity_paths_and_digests(profile_file, profiles, tmp_path):
    path, robot, document = profile_file
    a = profiles.load(path, robot_config=robot)
    other = {**robot, "id": "arm-b", "port": "/dev/serial/by-id/fixture-b"}
    b_path = tmp_path / "b.json"
    b_path.write_text(json.dumps({**document, "device_id": "fixture-device-b", "instance_id": "arm-b",
        "robot_config_sha256": profiles.digest(other), "work_dir": "arm-b", "operating_envelope_path": "arm-b/review.json"}))
    b = profiles.load(b_path, robot_config=other)
    assert a["binding"] != b["binding"] and a["work_dir"] != b["work_dir"]


def test_review_updates_do_not_make_the_profile_digest_circular(profile_file, profiles):
    path, _, _ = profile_file
    first = profiles.load(path)
    review = Path(first["operating_envelope_path"])
    review.parent.mkdir(parents=True)
    review.write_text('{"reviews": []}')
    assert profiles.load(path)["binding"] == first["binding"]
    review.write_text('{"reviews": [{"task_sha256": "new"}]}')
    assert profiles.load(path)["binding"] == first["binding"]


def test_profile_change_invalidates_binding_even_when_robot_config_is_unchanged(profile_file, profiles):
    path, robot, document = profile_file
    first = profiles.load(path, robot_config=robot)
    path.write_text(json.dumps({**document, "operating_envelope_path": "replacement/review.json"}))
    assert profiles.load(path, robot_config=robot)["binding"] != first["binding"]


def test_binding_pipeline_selects_profile_owned_paths_without_touching_vendor_config(profile_file, profiles):
    path, robot, _ = profile_file
    vendor = copy.deepcopy(robot)
    config = {"operating_profile_path": str(path), "work_dir": "wrong", "operating_envelope_path": "wrong"}
    configured = profiles.bind_pipeline(config)
    assert configured["work_dir"] == str(path.parent / "arm-a")
    assert configured["operating_envelope_path"] == str(path.parent / "arm-a/review.json")
    assert config["work_dir"] == "wrong" and robot == vendor
