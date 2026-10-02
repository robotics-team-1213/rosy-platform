"""D-411 B: rosy.controls/1 — the device announces its controls; Pilot builds widgets from it."""

import pytest
from pydantic import ValidationError

from core_common.protocol import controls as c


def test_pinky_with_drive_announces_one_base_velocity_control():
    body = c.pinky_controls(provides={"drive", "battery"}, max_linear=0.15, max_angular=0.6)
    assert body == {"schema": "rosy.controls/1", "items": [{
        "id": "base", "kind": "base_velocity", "label": "주행", "max_linear": 0.15,
        "max_angular": 0.6, "pivot": True, "fine": True, "autonomy": ["line"]}]}


def test_no_drive_no_controls():
    assert c.pinky_controls(provides=set(), max_linear=0.15, max_angular=0.6)["items"] == []


def test_joint_jog_is_bounded_goal_with_limits():
    jog = c.JointJogControl(id="arm", label="팔", joints=[{"name": "joint1", "lower": -1.0, "upper": 1.0}],
                            max_step_rad=0.05, duration_s=0.4)
    assert jog.command == "bounded_goal"
    for bad in ({"max_step_rad": 0.06}, {"duration_s": 1.5}, {"joints": []},
                {"joints": [{"name": "j", "lower": 1.0, "upper": 1.0}]},
                {"joints": [{"name": "j", "lower": 0, "upper": 1}, {"name": "j", "lower": 0, "upper": 1}]}):
        with pytest.raises(ValidationError):
            c.JointJogControl(**{"id": "arm", "label": "팔",
                                 "joints": [{"name": "joint1", "lower": -1.0, "upper": 1.0}],
                                 "max_step_rad": 0.05, "duration_s": 0.4, **bad})


def test_gripper_presets_stay_between_open_and_closed():
    grip = c.GripperControl(id="gripper", label="그리퍼", joint="gripper_joint_1", closed=0.0, open=1.0,
                            presets={"open": 1.0, "half": 0.5, "close": 0.0})
    assert grip.unit == "rad" and grip.readback == ("position", "grasp")
    with pytest.raises(ValidationError):
        c.GripperControl(id="gripper", label="그리퍼", joint="g", closed=0.0, open=1.0,
                         presets={"open": 1.2, "half": 0.5, "close": 0.0})
    with pytest.raises(ValidationError):
        c.GripperControl(id="gripper", label="그리퍼", joint="g", closed=0.5, open=0.5,
                         presets={"open": 0.5, "half": 0.5, "close": 0.5})


def test_descriptor_discriminates_kinds_and_rejects_duplicate_ids():
    body = {"schema": "rosy.controls/1", "items": [
        {"id": "base", "kind": "base_velocity", "label": "주행", "max_linear": 0.1, "max_angular": 0.5,
         "pivot": False, "fine": False}]}
    parsed = c.ControlsDescriptor.model_validate(body)
    assert isinstance(parsed.items[0], c.BaseVelocityControl)
    with pytest.raises(ValidationError):
        c.ControlsDescriptor.model_validate({**body, "items": body["items"] * 2})
    with pytest.raises(ValidationError):
        c.ControlsDescriptor.model_validate({**body, "items": [{"id": "x", "kind": "laser", "label": "x"}]})
