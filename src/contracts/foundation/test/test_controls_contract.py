"""D-411 B: rosy.controls/1 — the device announces its controls; Pilot builds widgets from it."""

import pytest
from pydantic import ValidationError

from core_common.protocol import controls as c


def test_pinky_with_drive_announces_one_base_velocity_control():
    body = c.pinky_controls(provides={"drive", "battery"}, max_linear=0.15, max_angular=0.6,
                            autonomy=("line",))
    assert body == {"schema": "rosy.controls/1", "items": [{
        "id": "base", "kind": "base_velocity", "label": "주행", "max_linear": 0.15,
        "max_angular": 0.6, "pivot": True, "fine": True, "autonomy": ["line"]}]}


def test_autonomy_is_only_what_the_caller_proves():
    (base,) = c.pinky_controls(provides={"drive"}, max_linear=0.15, max_angular=0.6)["items"]
    assert base["autonomy"] == []


def test_zero_limit_means_drive_announced_but_held_at_standstill():
    # PUT /safety/limits accepts 0 (ge=0); capabilities must not turn that into a 500.
    (base,) = c.pinky_controls(provides={"drive"}, max_linear=0.0, max_angular=0.0)["items"]
    assert base["max_linear"] == 0.0 and base["max_angular"] == 0.0
    for bad in (-0.1, float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            c.BaseVelocityControl(id="base", label="주행", max_linear=bad, max_angular=0.5,
                                  pivot=False, fine=False)


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


def test_gripper_presets_are_the_endpoints_with_half_between():
    grip = c.GripperControl(id="gripper", label="그리퍼", joint="gripper_joint_1", closed=0.0, open=1.0,
                            presets={"open": 1.0, "half": 0.5, "close": 0.0})
    assert grip.unit == "rad" and grip.readback == ("position", "grasp")
    for presets in ({"open": 1.2, "half": 0.5, "close": 0.0},   # beyond open
                    {"open": 0.9, "half": 0.5, "close": 0.0},   # open preset is not `open`
                    {"open": 1.0, "half": 0.5, "close": 0.1},   # close preset is not `closed`
                    {"open": 1.0, "half": 0.0, "close": 0.0},   # half on an endpoint
                    {"open": 1.0, "half": 1.0, "close": 0.0}):
        with pytest.raises(ValidationError):
            c.GripperControl(id="gripper", label="그리퍼", joint="g", closed=0.0, open=1.0, presets=presets)
    # closed may be the larger angle; half still lies strictly between.
    assert c.GripperControl(id="gripper", label="그리퍼", joint="g", closed=1.0, open=0.0,
                            presets={"open": 0.0, "half": 0.5, "close": 1.0}).closed == 1.0
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


def test_gripper_may_announce_its_speed_limit():
    presets = c.GripperPresets(open=1.0, half=0.5, close=0.0)
    grip = c.GripperControl(id="gripper", label="그리퍼", joint="g", closed=0.0, open=1.0, presets=presets,
                            max_velocity=0.5)
    assert grip.max_velocity == 0.5
    assert c.GripperControl(id="gripper", label="그리퍼", joint="g", closed=0.0, open=1.0,
                            presets=presets).max_velocity is None
    for bad in (0.0, -1.0, float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            c.GripperControl(id="gripper", label="그리퍼", joint="g", closed=0.0, open=1.0, presets=presets,
                             max_velocity=bad)
