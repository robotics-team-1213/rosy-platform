"""D-1005: a re-approval can be measured faster, up to the signed ceiling, and the sealed speed is what binds."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pytest

from test_native_mapping_approval import ROOT, _automatic_candidate, _device, _module

CONFIG = ROOT / "deploy/robot/pinky_pro/config"


def _retime(bundle, evidence, speed, angular, *, change=None):
    """Rewrite every trial of the candidate to run at (speed m/s, angular rad/s); `change` edits each raw dict."""
    for trial in bundle["trials"]:
        path = evidence / trial["evidence_file"]
        raw = json.loads(path.read_text())
        lin = speed if raw["direction"] == "forward" else -speed if raw["direction"] == "reverse" else 0.0
        ang = -angular if raw["direction"] == "cw" else angular if raw["direction"] == "ccw" else 0.0
        raw["requested_linear_mps"], raw["requested_angular_rps"] = lin, ang
        for sample in raw["samples"]:
            moving = sample["linear"] or sample["angular"]
            sample["linear"], sample["angular"] = (lin, ang) if moving else (0.0, 0.0)
        raw["samples"][1]["x"] = lin * 0.2
        raw["samples"][1]["yaw"] = ang * 0.2
        raw["samples"][2]["x"] = raw["samples"][3]["x"] = lin * 0.5
        raw["samples"][2]["yaw"] = raw["samples"][3]["yaw"] = ang * 0.5
        if change:
            change(raw)
        content = json.dumps(raw, sort_keys=True).encode()
        path.write_bytes(content)
        trial["sha256"] = hashlib.sha256(content).hexdigest()


def _sealed(tmp_path, speed=0.02, angular=0.08, change=None):
    approval = _module()
    root = _device(tmp_path)
    bundle, evidence = _automatic_candidate(tmp_path)
    _retime(bundle, evidence, speed, angular, change=change)
    return approval, root, bundle, evidence


def test_the_signed_ceiling_is_the_profile_hardware_limit():
    approval = _module()
    for name in ("profile.hardware.yaml", "profile.motor.yaml", "profile.core.yaml"):
        text = (CONFIG / name).read_text(encoding="utf-8")
        assert float(re.search(r"max_linear_velocity:\s*([0-9.]+)", text).group(1)) == approval.CEILING_LINEAR_MPS
        assert float(re.search(r"max_angular_velocity:\s*([0-9.]+)", text).group(1)) == approval.CEILING_ANGULAR_RPS


def test_the_stop_latency_limit_has_one_value_everywhere():
    text = (ROOT / "deploy/robot/pinky_pro/commissioning_session.py").read_text(encoding="utf-8")
    assert float(re.search(r"MAX_STOP_LATENCY_S = ([0-9.]+)", text).group(1)) == _module().MAX_STOP_LATENCY_S
    trials = (ROOT / "middleware/core/services/core_features/command/approval_trials.py").read_text(encoding="utf-8")
    assert float(re.search(r"STOP_LATENCY_S = ([0-9.]+)", trials).group(1)) == _module().MAX_STOP_LATENCY_S


def test_a_faster_measurement_is_sealed_in_both_markers_and_read_back(tmp_path):
    approval, root, bundle, evidence = _sealed(tmp_path, 0.10, 0.40, change=lambda raw: raw.update(travel_cap_m=0.2))
    result = approval.approve(root, bundle, evidence)
    assert (result["measured_linear_mps"], result["measured_angular_rps"]) == (0.10, 0.40)
    for kind in ("hardware", "navigation"):
        marker = json.loads((root / f"etc/rosy/approvals/{kind}.approved").read_text())
        assert (marker["measured_linear_mps"], marker["measured_angular_rps"]) == (0.10, 0.40)
    found = approval.check(root, runtime_mode="hardware")
    assert (found["measured_linear_mps"], found["measured_angular_rps"]) == (0.10, 0.40)


def test_the_sealed_speed_is_the_fastest_the_robot_was_seen_moving(tmp_path):
    def faster(raw):
        raw["samples"][1]["linear"] = raw["requested_linear_mps"] * 1.4
    approval, root, bundle, evidence = _sealed(tmp_path, 0.10, 0.40, change=faster)
    assert approval.approve(root, bundle, evidence)["measured_linear_mps"] == pytest.approx(0.14)


def test_a_marker_that_names_another_speed_than_its_evidence_fails_closed(tmp_path):
    approval, root, bundle, evidence = _sealed(tmp_path)
    approval.approve(root, bundle, evidence)
    for kind in ("hardware", "navigation"):
        path = root / f"etc/rosy/approvals/{kind}.approved"
        record = json.loads(path.read_text())
        record["measured_linear_mps"] = 0.19
        path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="raw evidence"):
        approval.check(root, runtime_mode="hardware")


def test_two_markers_that_seal_different_speeds_fail_closed(tmp_path):
    approval, root, bundle, evidence = _sealed(tmp_path)
    approval.approve(root, bundle, evidence)
    path = root / "etc/rosy/approvals/navigation.approved"
    record = json.loads(path.read_text())
    record["measured_angular_rps"] = 0.5
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="different measured speeds"):
        approval.check(root, runtime_mode="hardware")


def test_a_marker_without_a_sealed_speed_binds_nothing(tmp_path):
    approval, root, bundle, evidence = _sealed(tmp_path)
    approval.approve(root, bundle, evidence)
    for kind in ("hardware", "navigation"):
        path = root / f"etc/rosy/approvals/{kind}.approved"
        record = json.loads(path.read_text())
        del record["measured_linear_mps"], record["measured_angular_rps"]
        path.write_text(json.dumps(record))
    found = approval.check(root, runtime_mode="hardware")
    assert found["ready"] is True
    assert (found["measured_linear_mps"], found["measured_angular_rps"]) == (None, None)


@pytest.mark.parametrize("speed,angular,reason", [(0.21, 0.4, "speed"), (0.1, 0.81, "speed")])
def test_no_trial_may_be_requested_above_the_signed_ceiling(tmp_path, speed, angular, reason):
    approval, root, bundle, evidence = _sealed(tmp_path, speed, angular)
    with pytest.raises(ValueError, match=reason):
        approval.approve(root, bundle, evidence)
    assert not (root / "etc/rosy/approvals/hardware.approved").exists()


def test_a_measured_speed_beyond_the_request_by_half_again_is_refused(tmp_path):
    def overrun(raw):
        raw["samples"][1]["linear"] = raw["requested_linear_mps"] * 1.6
        raw["samples"][1]["angular"] = raw["requested_angular_rps"] * 1.6
    approval, root, bundle, evidence = _sealed(tmp_path, 0.10, 0.40, change=overrun)
    with pytest.raises(ValueError, match="measured speed"):
        approval.approve(root, bundle, evidence)


def test_travel_must_stay_inside_the_cap_the_trial_recorded(tmp_path):
    def far(raw):
        raw["travel_cap_m"] = 0.04
    approval, root, bundle, evidence = _sealed(tmp_path, 0.10, 0.40, change=far)
    with pytest.raises(ValueError, match="travel exceeds 4 cm"):
        approval.approve(root, bundle, evidence)


@pytest.mark.parametrize("cap", [0.41, 0.0, -0.1])
def test_a_travel_cap_outside_the_signed_ceiling_is_refused(tmp_path, cap):
    approval, root, bundle, evidence = _sealed(tmp_path, change=lambda raw: raw.update(travel_cap_m=cap))
    with pytest.raises(ValueError, match="travel cap"):
        approval.approve(root, bundle, evidence)


def test_the_stop_latency_judgement_is_unchanged_at_higher_speed(tmp_path):
    def slow(raw):
        raw["samples"][-2]["t"], raw["samples"][-1]["t"] = 1.7, 1.8
    approval, root, bundle, evidence = _sealed(tmp_path, 0.10, 0.40, change=slow)
    with pytest.raises(ValueError, match="stop latency"):
        approval.approve(root, bundle, evidence)
