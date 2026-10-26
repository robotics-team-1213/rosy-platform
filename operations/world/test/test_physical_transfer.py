"""Physical facts keep measured units and missing observations without granting clearance."""
from dataclasses import replace
from importlib import import_module
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def api():
    try:
        return import_module("rosy.world.state.projections.physical_transfer")
    except ModuleNotFoundError:
        pytest.fail("World physical transfer facts are missing")


def owner(**changes):
    module = api()
    link = module.LinkPhysicalState(module.Bounds3((1, 2, 3), (2, 3, 4)), (0, 0, 0), (0, 0, 0))
    return module.ArmPhysicalState(**{**dict(workcell_id="w-1", instance_id="arm-1", journal_id="journal-1",
        owner_session_id="session-1", model_digest="a" * 64, calibration_revision="cal-1",
        transform_revision="tf-1", links_observed_at_ns=200, links={"link-1": link},
        gripper_observed_at_ns=210, gripper_state="OPEN", held_state="NONE", held_object_ref=None), **changes})


def observation(**changes):
    module = api()
    return module.TransferObservation(**{**dict(evidence_id="ev-1", producer_id="observer-1",
        evaluator_revision="eval-1", sequence=1, action_id="a-1", attempt_id="t-1", frame_id="world",
        policy_digest="b" * 64, catalog_digest="c" * 64, bindings_digest="d" * 64,
        object_ref="object-1", object_origin_id="model-origin", object_observed_at_ns=220,
        object_pose=module.PhysicalPose((0.1, 0.2, 0.3), (0, 0, 0, 1)), owners=(owner(),)), **changes})


def test_facts_preserve_real_units_capture_times_and_explicit_missing_object():
    sample = observation()
    assert sample.object_pose.position_m == (0.1, 0.2, 0.3)
    assert sample.sample_times_ns == (220, 200, 210)
    assert replace(sample, object_pose=None).object_pose is None
    assert not hasattr(sample, "satisfied") and not hasattr(sample, "claim_released")


def test_facts_are_deeply_frozen_and_do_not_follow_mutable_producer_maps():
    state = owner()
    source = dict(state.links)
    copied = replace(state, links=source)
    source.clear()
    assert tuple(copied.links) == ("link-1",)
    with pytest.raises(TypeError):
        copied.links["other"] = state.links["link-1"]
    with pytest.raises(AttributeError):
        copied.journal_id = "other"


@pytest.mark.parametrize("position,orientation", [
    ((True, 0, 0), (0, 0, 0, 1)), ((float("nan"), 0, 0), (0, 0, 0, 1)),
    ((10**400, 0, 0), (0, 0, 0, 1)),
    ((0, 0), (0, 0, 0, 1)), ((0, 0, 0), (0, 0, 0, 0)), ((0, 0, 0), (0, 0, 0, 2)),
])
def test_invalid_pose_units_shape_or_quaternion_are_not_normalized_into_evidence(position, orientation):
    with pytest.raises(ValueError):
        api().PhysicalPose(position, orientation)


def test_invalid_bounds_and_nonfinite_velocity_are_rejected():
    module = api()
    with pytest.raises(ValueError):
        module.Bounds3((2, 0, 0), (1, 1, 1))
    with pytest.raises(ValueError):
        module.LinkPhysicalState(module.Bounds3((0, 0, 0), (1, 1, 1)), (float("inf"), 0, 0), (0, 0, 0))


def test_unmeasured_velocity_remains_unknown_instead_of_becoming_zero():
    module = api()
    value = module.LinkPhysicalState(module.Bounds3((0, 0, 0), (1, 1, 1)), None, None)
    assert value.linear_velocity_m_s is None and value.angular_velocity_rad_s is None


@pytest.mark.parametrize("changes", [
    {"journal_id": " "}, {"owner_session_id": "bad\n"}, {"model_digest": "A" * 64},
    {"links_observed_at_ns": True}, {"gripper_state": "clear"}, {"held_state": "safe"},
    {"held_object_ref": "object-1"},
])
def test_owner_facts_reject_ambiguous_identity_and_gripper_data(changes):
    with pytest.raises(ValueError):
        owner(**changes)


def test_missing_links_and_unknown_hold_are_preserved_as_incomplete_facts():
    state = owner(links={}, gripper_state="UNKNOWN", held_state="UNKNOWN")
    assert not state.links and state.held_state == "UNKNOWN"


def test_duplicate_participant_and_untyped_header_are_rejected():
    with pytest.raises(ValueError):
        observation(owners=(owner(), owner()))
    with pytest.raises(ValueError):
        observation(sequence=True)
    with pytest.raises(ValueError):
        observation(policy_digest="unknown")
