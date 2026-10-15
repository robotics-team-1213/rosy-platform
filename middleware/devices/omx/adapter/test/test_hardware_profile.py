"""Synthetic document validation, never measured hardware acceptance."""
import json

import pytest
import yaml

from omx_adapter.hardware_profile import main, validate_profile


@pytest.fixture
def profile():
    return {
        "schema": "rosy.omx-hardware-profile.v1", "profile": "hardware",
        "measured": {"date": "2026-10-15", "revision": "test-fixture-only",
                     "evidence": "docs/validation/omx-hardware-2026-10-15/result.md"},
        "serial": {"by_id": "/dev/serial/by-id/test-fixture-only", "baudrate": 1000000},
        "joints": {f"joint{i}": {"position": [-1., 1.], "velocity": .1, "acceleration": .2}
                   for i in range(1, 6)},
        "gripper": {"joint": "gripper_joint_1", "position": [0., 1.], "open": .9,
                    "closed": .1, "preload": .01,
                    "jaw": {"pivot_y_m": [.0075, -.0108], "contact_point_m": [.04, -.01],
                            "squeeze_m": .001, "min_grasp_width_m": .01,
                            "max_grasp_width_m": .04, "release_clearance_m": .005}},
        "workspace": {"min_m": [-.1, -.1, .01], "max_m": [.1, .1, .1]},
        "owner": {"max_joint_state_age_s": .2, "action_timeout_s": 10., "wall_clock_bound_factor": 1.},
        "power": {"supply_v": 12., "noted_load_a": .5},
    }


def test_document_validation_does_not_admit_hardware(profile):
    result = validate_profile(profile)
    assert result["profile_document_valid"] is True
    assert result["motion_admitted"] is False
    assert "independent_stop" in result["unverified"]
    assert result["joint_names"] == [f"joint{i}" for i in range(1, 6)]


@pytest.mark.parametrize("path,value", [
    (("profile",), "simulation"), (("schema",), "unknown"),
    (("measured", "revision"), ""), (("measured", "date"), "2026-02-30"),
    (("measured", "evidence"), "docs/validation/omx-hardware-2026-10-14/result.md"),
    (("measured", "evidence"), "docs/validation/omx-hardware-2026-10-15/../sim/result.md"),
    (("serial", "by_id"), "/dev/ttyACM0"), (("serial", "baudrate"), True),
    (("joints", "joint1", "position"), [1., -1.]),
    (("joints", "joint1", "velocity"), float("nan")),
    (("joints", "joint1", "acceleration"), "0.2"),
    (("gripper", "open"), 2.), (("gripper", "closed"), .9),
    (("gripper", "preload"), -.01), (("gripper", "preload"), 1.),
    (("gripper", "jaw", "contact_point_m"), [0., float("inf")]),
    (("gripper", "jaw", "max_grasp_width_m"), .005),
    (("workspace", "max_m"), [-.2, .1, .1]),
    (("owner", "max_joint_state_age_s"), False), (("power", "noted_load_a"), ""),
])
def test_invalid_measurements_are_rejected(profile, path, value):
    target = profile
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_profile(profile)


def test_missing_reordered_and_unknown_fields_are_rejected(profile):
    profile["joints"] = dict(reversed(list(profile["joints"].items())))
    with pytest.raises(ValueError, match="joints"):
        validate_profile(profile)
    profile["joints"] = dict(reversed(list(profile["joints"].items())))
    profile["enabled"] = True
    with pytest.raises(ValueError):
        validate_profile(profile)
    del profile["enabled"]
    del profile["owner"]
    with pytest.raises(ValueError):
        validate_profile(profile)


def test_cli_reports_document_only_and_read_errors(profile, tmp_path, capsys):
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile, sort_keys=False))
    assert main([str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["motion_admitted"] is False
    assert main([str(tmp_path / "missing.yaml")]) == 2
    assert json.loads(capsys.readouterr().out)["profile_document_valid"] is False


def test_cli_rejects_duplicate_yaml_fields(profile, tmp_path, capsys):
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile, sort_keys=False) + "profile: hardware\n")
    assert main([str(path)]) == 2
    assert json.loads(capsys.readouterr().out)["motion_admitted"] is False
