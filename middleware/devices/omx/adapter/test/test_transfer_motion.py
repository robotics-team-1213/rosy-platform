"""D-856: physical transfer planning needs poses and approved geometry, not a business process."""
from dataclasses import fields, replace

import pytest

from omx_adapter import pose_plan
from test_omx_pose_plan import _planner, _request, _state, kin, profile  # noqa: F401 (shared fixtures)


def _api(name):
    value = getattr(pose_plan, name, None)
    assert value is not None, f"The neutral physical planning API {name} is missing"
    return value


def _motion(request):
    return _api("TransferMotionRequest")(**{name: getattr(request, name) for name in (
        "home", "pick", "place", "pick_approach_z", "place_approach_z", "carry_z")})


def _geometry(**changes):
    values = dict(grasp_width_m=0.03, grasp_depth_m=0.01, height_m=0.03, yaw_symmetric_pi=True)
    return _api("GraspGeometry")(**{**values, **changes})


def test_neutral_request_contains_only_physical_pose_inputs():
    request = _motion(_request())
    assert {field.name for field in fields(request)} == {
        "home", "pick", "place", "pick_approach_z", "place_approach_z", "carry_z"}


def test_neutral_and_existing_cell_plans_preserve_the_same_physics(kin, profile):
    request = _request()
    state = _state(kin, profile)
    previous = _planner(kin).plan_transfer(request, profile, state)
    neutral = _api("AnalyticTransferPlanner")(kin, monotonic=lambda: 100.5)
    result = neutral.plan_transfer(_motion(request), profile, state, geometry=_geometry())
    assert result == previous
    assert isinstance(result, pose_plan.CellTransferPlan)
    assert tuple(phase.phase_id for phase in result.phases) == ("approach", "grasp", "transfer", "release")
    pose_plan.validate_cell_transfer_plan(result, profile, kinematics_revision=kin.revision, now_monotonic_s=100.5)


@pytest.mark.parametrize("geometry", [
    {"grasp_width_m": 0}, {"grasp_depth_m": -0.1}, {"height_m": float("nan")},
    {"height_m": True}, {"yaw_symmetric_pi": False}, {"yaw_symmetric_pi": 1},
])
def test_unusable_physical_geometry_is_rejected_before_planning(geometry):
    with pytest.raises(ValueError):
        _geometry(**geometry)


def test_neutral_planner_preserves_scene_and_fingertip_guards(kin, profile):
    planner = _api("AnalyticTransferPlanner")(kin, monotonic=lambda: 100.5)
    request = _motion(_request())
    with pytest.raises(pose_plan.CellTransferPlanRejected) as invalid:
        planner.plan_transfer(request, profile, _state(kin, profile, scene="another-scene"), geometry=_geometry())
    assert invalid.value.reason == pose_plan.STATE_INVALID
    with pytest.raises(pose_plan.CellTransferPlanRejected) as shallow:
        planner.plan_transfer(request, profile, _state(kin, profile), geometry=_geometry(height_m=0.01))
    assert shallow.value.reason == pose_plan.GRASP_DEPTH_BELOW_FINGERTIPS


def test_legacy_adapter_keeps_recipe_and_cell_authority_before_neutral_calculation(kin, profile):
    _api("AnalyticTransferPlanner")
    request = _request()
    with pytest.raises(pose_plan.CellTransferPlanRejected) as changed_cell:
        _planner(kin, accepted="0" * 64).plan_transfer(request, profile, _state(kin, profile))
    assert changed_cell.value.reason == pose_plan.CELL_HASH_MISMATCH
    with pytest.raises(pose_plan.CellTransferPlanRejected) as changed_item:
        _planner(kin).plan_transfer(replace(request, grasp_width_m=0.04), profile, _state(kin, profile))
    assert changed_item.value.reason == pose_plan.ITEM_GEOMETRY_MISMATCH
