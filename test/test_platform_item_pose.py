"""C4b G6: per-step item_at_pose judged by the site from sim_model_pose evidence (D-403 §5)."""

import math
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for relative in ("modules/execution/src", "modules/skills/api/src"):
    if str(ROOT / relative) not in sys.path:
        sys.path.insert(0, str(ROOT / relative))

from rosy.execution.site.item_pose import (  # noqa: E402
    ItemPoseEvidence, ItemPoseTolerance, item_pose_predicate, verify_item_at_pose,
)

CONFIG = ROOT / "deploy/robot/omx/sim/item_pose_goal.yaml"
INPUTS = {  # C3b slot 0: place TCP (0.1525, 0.0275), z_top 0.04, grasp depth 15 mm -> TCP z 0.025
    "item": "box", "destination_pose_base": {"x_m": 0.1525, "y_m": 0.0275, "z_m": 0.025, "yaw_rad": 0.0},
}


def _tolerance():
    return ItemPoseTolerance.from_mapping(yaml.safe_load(CONFIG.read_text(encoding="utf-8")))


def _predicate():
    return item_pose_predicate("job-1", 0, INPUTS, _tolerance())


def _evidence(**pose):
    base = {"x": 0.1525, "y": 0.0275, "z": 0.025, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}
    base.update(pose)
    return ItemPoseEvidence.from_mapping({
        "predicate_id": "job-1:0:item_at_pose", "item_id": "job-1:0",
        "evidence_source": "sim_model_pose", "evidence_id": "e-1", "producer_id": "sim-pose",
        "model_name": "block_0", "pose": base, "observed_at": 100.0,
        "action_id": "a-1", "attempt_id": "t-1", "gripper_state": "OPEN",
        "gripper_evidence_id": "g-1",
    })


def test_config_states_its_basis_and_the_c3b_tolerances():
    tolerance = _tolerance()
    assert (tolerance.xy_m, tolerance.z_m, tolerance.yaw_rad, tolerance.tilt_rad) == (0.005, 0.002, 0.05, 0.05)
    assert tolerance.yaw_period_rad == pytest.approx(math.pi)
    assert "C3b" in tolerance.basis and "0.3" in tolerance.basis


def test_predicate_targets_the_model_centre_of_the_step_place_pose():
    predicate = _predicate()
    assert predicate.item_id == "job-1:0" and predicate.condition == "item_at_pose"
    assert predicate.evidence_source == "sim_model_pose"
    # box: centre = TCP z + grasp_depth - height / 2 = 0.025 + 0.015 - 0.015
    assert predicate.target == {"x": 0.1525, "y": 0.0275, "z": 0.025, "yaw": 0.0}


def test_c3b_achieved_placements_pass_with_pi_symmetric_yaw():
    for dx, yaw in ((-0.0003, 0.0009), (0.00014, math.pi - 0.0039), (0.0003, 0.0042)):
        verdict = verify_item_at_pose(_predicate(), _evidence(x=0.1525 + dx, yaw=yaw), now=101.0,
                                      max_age_s=5.0)
        assert verdict.satisfied, verdict.reasons


@pytest.mark.parametrize("pose, reason", [
    ({"x": 0.1077, "y": 0.0565, "z": 0.0197, "roll": -1.571}, "xy"),   # C3 run8: lying on the table
    ({"x": 0.1489, "y": 0.0896, "yaw": -0.33}, "xy"),                 # C3b: neighbour pushed 24.9 mm
    ({"z": 0.0323}, "z"),
    ({"yaw": 0.2}, "yaw"),
    ({"pitch": -0.32}, "tilt"),
])
def test_failed_placements_are_not_at_pose(pose, reason):
    verdict = verify_item_at_pose(_predicate(), _evidence(**pose), now=101.0, max_age_s=5.0)
    assert not verdict.satisfied and reason in verdict.reasons


def test_stale_wrong_item_or_closed_gripper_evidence_is_not_satisfying():
    assert "stale" in verify_item_at_pose(_predicate(), _evidence(), now=200.0, max_age_s=5.0).reasons
    closed = ItemPoseEvidence.from_mapping({**_evidence().to_dict(), "gripper_state": "CLOSED"})
    assert "gripper" in verify_item_at_pose(_predicate(), closed, now=101.0, max_age_s=5.0).reasons
    other = ItemPoseEvidence.from_mapping({**_evidence().to_dict(), "item_id": "job-1:1"})
    assert "item" in verify_item_at_pose(_predicate(), other, now=101.0, max_age_s=5.0).reasons


def test_producer_cannot_assert_satisfaction_or_another_source():
    with pytest.raises(ValueError):
        ItemPoseEvidence.from_mapping({**_evidence().to_dict(), "satisfied": True})
    with pytest.raises(ValueError):
        ItemPoseEvidence.from_mapping({**_evidence().to_dict(), "evidence_source": "camera_observation"})


def test_tolerance_requires_a_basis_and_positive_values():
    document = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    with pytest.raises(ValueError):
        ItemPoseTolerance.from_mapping({**document, "basis": ""})
    with pytest.raises(ValueError):
        ItemPoseTolerance.from_mapping({**document, "xy_m": 0})


def test_item_without_a_configured_model_offset_has_no_predicate():
    with pytest.raises(ValueError, match="slip_sheet"):
        item_pose_predicate("job-1", 1, {**INPUTS, "item": "slip_sheet"}, _tolerance())
