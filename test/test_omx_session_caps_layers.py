"""Servo tuning layers (D-951 6): the OMX-AI model's gains, then the site caps file, then the robot's profile."""
import importlib
import json
from pathlib import Path

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
SITE = {"11": {"pwm": 300}, "12": {"pwm": 600, "p": 1600}, "13": {"pwm": 600},
        "14": {"pwm": 300, "current": 250, "p": 800}, "15": {"pwm": 300, "current": 250},
        "16": {"pwm": 300, "current": 250}}


@pytest.fixture
def caps(monkeypatch):
    monkeypatch.syspath_prepend(str(OMX))
    return importlib.import_module("session_caps")


def site(tmp_path, **changes):
    path = tmp_path / "caps.json"
    path.write_text(json.dumps({**SITE, **changes}))
    return path


def profile(tmp_path, caps, servo):
    profiles = importlib.import_module("cell_robot_profile")
    robot = {"type": "omx_follower", "id": "arm-a", "port": "/dev/serial/by-id/fixture-a", "cameras": {}}
    document = {"schema": profiles.SCHEMA, "device_id": "fixture-device-a", "instance_id": "arm-a",
                "robot_config_sha256": profiles.digest(robot), "operating_envelope_path": "review.json",
                "work_dir": "work", **({"servo": servo} if servo is not None else {})}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document))
    return path


def test_the_model_gives_the_loaded_elbow_and_wrist_an_i_gain(caps, tmp_path):
    """2026-11-01: with I 0 both arms' elbow and wrist stopped short under load (TCP 12.3 mm -> 3.3 mm with I 50)."""
    loaded = caps.load_caps(site(tmp_path), model=caps.model_tuning())
    assert loaded[13] == {"pwm_limit": 600, "i_gain": 50}
    assert loaded[14] == {"pwm_limit": 300, "current_limit": 250, "p_gain": 800, "i_gain": 50}
    assert all("i_gain" not in loaded[motor] for motor in (11, 12, 15, 16))


def test_the_site_file_overrides_the_model_and_the_robot_overrides_both(caps, tmp_path):
    path = site(tmp_path, **{"13": {"pwm": 600, "i": 30}, "14": {"pwm": 300, "current": 250, "i": 30}})
    loaded = caps.load_caps(path, model=caps.model_tuning(), robot=caps.robot_tuning(profile(tmp_path, caps, {"14": {"i": 70}})))
    assert loaded[13]["i_gain"] == 30 and loaded[14]["i_gain"] == 70
    assert loaded[14]["current_limit"] == 250, "the robot layer changes only the keys it names"


def test_no_profile_or_no_servo_adds_nothing(caps, tmp_path):
    assert caps.robot_tuning(None) == {}
    assert caps.robot_tuning(profile(tmp_path, caps, None)) == {}


@pytest.mark.parametrize("servo", [{"14": {"pwm": 400}}, {"14": {"current": 300}}, {"17": {"i": 50}},
                                   {"wrist": {"i": 50}}, {"14": 50}, [50]])
def test_a_robot_tuning_cannot_carry_commissioning_caps_or_unknown_motors(caps, tmp_path, servo):
    with pytest.raises((SystemExit, ValueError)):
        caps.robot_tuning(profile(tmp_path, caps, servo))


def test_merged_values_keep_the_guard_ranges(caps, tmp_path):
    with pytest.raises(SystemExit, match="i 0..1600"):
        caps.load_caps(site(tmp_path), model=caps.model_tuning(), robot={14: {"i": 5000}})
    with pytest.raises(SystemExit, match="acc"):  # a profile still needs acc and vel together
        caps.load_caps(site(tmp_path), robot={12: {"acc": 8}})


def test_the_servo_is_part_of_the_profile_identity(caps, tmp_path):
    profiles = importlib.import_module("cell_robot_profile")
    before = profiles.load(profile(tmp_path, caps, {"14": {"i": 50}}))["binding"]["profile_sha256"]
    after = profiles.load(profile(tmp_path, caps, {"14": {"i": 60}}))["binding"]["profile_sha256"]
    assert before != after


def test_the_model_file_states_its_evidence(caps):
    document = json.loads(caps.MODEL_TUNING.read_text(encoding="utf-8"))
    assert set(document["evidence"]) == set(document["motors"])
