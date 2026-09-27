"""A native Pinky cannot start mapping from empty or stale approval markers."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy/robot/native/mapping_approval.py"
REVISION = "a" * 40
RELEASE = "2026.09.27-018"


def _module():
    spec = importlib.util.spec_from_file_location("mapping_approval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _device(tmp_path: Path, *, mode: str = "motor") -> Path:
    root = tmp_path / "device"
    release = root / "opt/rosy/current"
    release.mkdir(parents=True)
    (release / "source-revision.txt").write_text(REVISION, encoding="ascii")
    (release / "install").mkdir()
    (release / "install/.rosy-release").write_text(RELEASE, encoding="ascii")
    config = root / "etc/rosy"
    config.mkdir(parents=True)
    (config / "runtime.env").write_text(
        f"ROSY_ROBOT_NUMBER=19\nROSY_RUNTIME_MODE={mode}\n"
        "ROSY_NAVIGATION_BACKEND=slam\nROSY_IO_DRIVE_ENABLED=true\n",
        encoding="ascii",
    )
    return root


def _candidate(tmp_path: Path) -> tuple[dict, Path]:
    evidence = tmp_path / "raw"
    evidence.mkdir()
    preflight = {
        "configured_ids": [1, 2], "responded_ids": [1, 2],
        "torque_free": True,
    }
    preflight_bytes = json.dumps(preflight, sort_keys=True).encode()
    (evidence / "motor-preflight.json").write_bytes(preflight_bytes)
    trials = []
    for direction in ("forward", "reverse", "cw", "ccw"):
        for cause in ("button_release", "command_loss"):
            linear = 0.02 if direction == "forward" else -0.02 if direction == "reverse" else 0.0
            angular = -0.08 if direction == "cw" else 0.08 if direction == "ccw" else 0.0
            raw = {
                "direction": direction, "stop_cause": cause,
                "requested_linear_mps": linear, "requested_angular_rps": angular,
                "stop_requested_at": 1.0,
                "samples": [
                    {"t": 0.9, "linear": linear, "angular": angular, "x": 0.0, "y": 0.0, "yaw": 0.0},
                    {"t": 1.1, "linear": linear, "angular": angular, "x": linear * 0.2, "y": 0.0, "yaw": angular * 0.2},
                    {"t": 1.4, "linear": 0.0, "angular": 0.0, "x": linear * 0.5, "y": 0.0, "yaw": angular * 0.5},
                    {"t": 1.5, "linear": 0.0, "angular": 0.0, "x": linear * 0.5, "y": 0.0, "yaw": angular * 0.5},
                ],
            }
            name = f"{direction}-{cause}.json"
            content = json.dumps(raw, sort_keys=True).encode()
            (evidence / name).write_bytes(content)
            trials.append({
                "direction": direction, "stop_cause": cause,
                "evidence_file": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "observed_direction": True,
            })
    bundle = {
        "schema_version": 1, "robot_number": 19,
        "release_id": RELEASE, "source_revision": REVISION,
        "operator": "operator-a", "safety_operator": "operator-b",
        "test_surface": "floor", "hardware_cut_reachable": True,
        "motor_preflight": {
            "evidence_file": "motor-preflight.json",
            "sha256": hashlib.sha256(preflight_bytes).hexdigest(),
        },
        "trials": trials,
    }
    return bundle, evidence


def _automatic_candidate(tmp_path: Path) -> tuple[dict, Path]:
    bundle, evidence = _candidate(tmp_path)
    bundle["schema_version"] = 2
    bundle.pop("safety_operator")
    bundle.pop("hardware_cut_reachable")
    required = {
        ("forward", "button_release"), ("reverse", "button_release"),
        ("cw", "button_release"), ("ccw", "button_release"),
        ("forward", "command_loss"),
    }
    bundle["trials"] = [
        {key: value for key, value in trial.items() if key != "observed_direction"}
        for trial in bundle["trials"]
        if (trial["direction"], trial["stop_cause"]) in required
    ]
    return bundle, evidence


def test_automatic_g4_seals_five_measured_trials_without_second_operator(tmp_path):
    approval = _module()
    root = _device(tmp_path)
    bundle, evidence = _automatic_candidate(tmp_path)
    result = approval.approve(root, bundle, evidence)
    assert result["ready"] is True
    assert result["trials"] == 5
    assert approval.check(root, runtime_mode="hardware")["ready"] is True


def test_automatic_g4_still_requires_command_loss_stop(tmp_path):
    approval = _module()
    root = _device(tmp_path)
    bundle, evidence = _automatic_candidate(tmp_path)
    bundle["trials"].pop()
    with pytest.raises(ValueError, match="five|command_loss"):
        approval.approve(root, bundle, evidence)
    assert not (root / "etc/rosy/approvals/hardware.approved").exists()


def test_automatic_g4_rejects_a_repeated_trial_in_place_of_command_loss(tmp_path):
    approval = _module()
    root = _device(tmp_path)
    bundle, evidence = _automatic_candidate(tmp_path)
    lost = next(t for t in bundle["trials"] if t["stop_cause"] == "command_loss")
    lost["stop_cause"] = "button_release"
    with pytest.raises(ValueError, match="required direction and stop cause"):
        approval.approve(root, bundle, evidence)


def test_automatic_g4_rechecks_operator_and_raw_digest_at_navigation_start(tmp_path):
    approval = _module()
    root = _device(tmp_path)
    bundle, evidence = _automatic_candidate(tmp_path)
    approval.approve(root, bundle, evidence)
    marker = root / "etc/rosy/approvals/navigation.approved"
    record = json.loads(marker.read_text())
    record["operator"] = "someone-else"
    marker.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="operator differs"):
        approval.check(root, runtime_mode="hardware")
    record["operator"] = bundle["operator"]
    marker.write_text(json.dumps(record))
    raw = root / "etc/rosy/approvals/g4-evidence/forward-command_loss.json"
    raw.write_text("{}")
    with pytest.raises(ValueError, match="digest"):
        approval.check(root, runtime_mode="hardware")


def test_approval_seals_eight_measured_trials_and_navigation_checks_them(tmp_path):
    approval = _module()
    root = _device(tmp_path)
    bundle, evidence = _candidate(tmp_path)

    result = approval.approve(root, bundle, evidence, reviewer="reviewer-c")
    assert result["ready"] is True
    assert len(list((root / "etc/rosy/approvals/g4-evidence").glob("*.json"))) == 9
    assert approval.check(root, runtime_mode="hardware")["ready"] is True

    (root / "etc/rosy/approvals/g4-evidence/forward-button_release.json").write_text(
        "{}", encoding="ascii"
    )
    with pytest.raises(ValueError, match="digest"):
        approval.check(root, runtime_mode="hardware")


def test_floor_trials_do_not_require_lifted_wheels(tmp_path):
    approval = _module()
    root = _device(tmp_path)
    bundle, evidence = _candidate(tmp_path)
    assert "wheels_lifted" not in bundle
    assert approval.approve(root, bundle, evidence, reviewer="reviewer-c")["ready"]


def test_idle_encoder_noise_is_not_counted_as_forward_motion(tmp_path):
    approval = _module()
    _, evidence = _candidate(tmp_path)
    raw = json.loads((evidence / "forward-button_release.json").read_text())
    for sample in raw["samples"]:
        sample["linear"] = 0.0006
        sample["angular"] = 0.0135
    raw["samples"][-1]["x"] = 0.005
    with pytest.raises(ValueError, match="no measured forward motion"):
        approval._validate_trial(raw, "forward", "button_release")


def test_idle_encoder_noise_after_stop_is_zero_but_residual_rotation_is_not(tmp_path):
    approval = _module()
    _, evidence = _candidate(tmp_path)
    raw = json.loads((evidence / "cw-button_release.json").read_text())
    for sample in raw["samples"][-2:]:
        sample["linear"] = 0.0006
        sample["angular"] = 0.0135
    assert approval._validate_trial(raw, "cw", "button_release") == pytest.approx(0.4)

    for sample in raw["samples"][-2:]:
        sample["angular"] = 0.03
    with pytest.raises(ValueError, match="sustained zero velocity"):
        approval._validate_trial(raw, "cw", "button_release")


def test_empty_or_stale_markers_cannot_start_navigation(tmp_path):
    approval = _module()
    root = _device(tmp_path, mode="hardware")
    markers = root / "etc/rosy/approvals"
    markers.mkdir()
    (markers / "hardware.approved").touch()
    (markers / "navigation.approved").touch()
    with pytest.raises(ValueError, match="approval"):
        approval.check(root, runtime_mode="hardware")

    (root / "etc/rosy/runtime.env").write_text(
        "ROSY_ROBOT_NUMBER=19\nROSY_RUNTIME_MODE=motor\n"
        "ROSY_NAVIGATION_BACKEND=slam\nROSY_IO_DRIVE_ENABLED=true\n",
        encoding="ascii",
    )
    bundle, evidence = _candidate(tmp_path)
    approval.approve(root, bundle, evidence, reviewer="reviewer-c")
    (root / "opt/rosy/current/source-revision.txt").write_text("b" * 40)
    with pytest.raises(ValueError, match="revision"):
        approval.check(root, runtime_mode="hardware")


def test_approval_requires_motor_bench_and_distinct_reviewers(tmp_path):
    approval = _module()
    root = _device(tmp_path, mode="hardware")
    bundle, evidence = _candidate(tmp_path)
    with pytest.raises(ValueError, match="motor runtime"):
        approval.approve(root, bundle, evidence, reviewer="reviewer-c")
    assert not (root / "etc/rosy/approvals/hardware.approved").exists()


def test_navigation_rechecks_both_marker_identity_and_drive_configuration(tmp_path):
    approval = _module()
    root = _device(tmp_path)
    bundle, evidence = _candidate(tmp_path)
    approval.approve(root, bundle, evidence, reviewer="reviewer-c")
    marker = root / "etc/rosy/approvals/navigation.approved"
    record = json.loads(marker.read_text())
    record["reviewer"] = "other-reviewer"
    marker.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="same review"):
        approval.check(root, runtime_mode="hardware")
    record["reviewer"] = "reviewer-c"
    marker.write_text(json.dumps(record))

    (root / "etc/rosy/runtime.env").write_text(
        "ROSY_ROBOT_NUMBER=19\nROSY_RUNTIME_MODE=hardware\n"
        "ROSY_NAVIGATION_BACKEND=slam\nROSY_IO_DRIVE_ENABLED=false\n",
        encoding="ascii",
    )
    with pytest.raises(ValueError, match="drive"):
        approval.check(root)


@pytest.mark.parametrize("change,reason", [
    ("missing_trial", "eight"),
    ("slow_stop", "stop latency"),
    ("speed_overrun", "speed"),
    ("same_operator", "different"),
    ("wrong_odom_direction", "odom direction"),
    ("over_10cm", "travel"),
])
def test_invalid_g4_measurements_never_create_approval(tmp_path, change, reason):
    approval = _module()
    root = _device(tmp_path)
    bundle, evidence = _candidate(tmp_path)
    if change == "missing_trial":
        bundle["trials"].pop()
    elif change == "same_operator":
        bundle["safety_operator"] = bundle["operator"]
    else:
        path = evidence / "forward-button_release.json"
        raw = json.loads(path.read_text())
        if change == "slow_stop":
            raw["samples"][-2]["t"] = 1.7
            raw["samples"][-1]["t"] = 1.8
        elif change == "over_10cm":
            raw["samples"][1]["x"] = 0.06
            raw["samples"][2]["x"] = -0.06
            raw["samples"][3]["x"] = 0.005
        else:
            if change == "speed_overrun":
                raw["samples"][0]["linear"] = 0.0311
            else:
                raw["samples"][-1]["x"] = -0.01
        content = json.dumps(raw, sort_keys=True).encode()
        path.write_bytes(content)
        bundle["trials"][0]["sha256"] = hashlib.sha256(content).hexdigest()
    with pytest.raises(ValueError, match=reason):
        approval.approve(root, bundle, evidence, reviewer="reviewer-c")
    assert not (root / "etc/rosy/approvals/hardware.approved").exists()


def test_native_payload_and_systemd_share_the_same_guard():
    builder = (ROOT / "deploy/image/build-native-payload.sh").read_text()
    unit = (ROOT / "deploy/robot/native/rosy-navigation.service").read_text()
    installer = (ROOT / "deploy/robot/native/install-native-runtime.sh").read_text()
    assert "mapping_approval.py" in installer
    assert "mapping_approval.py" in unit
    assert "ExecCondition=" in unit
    assert "install-native-runtime.sh" in builder
