"""Owner-installed physical references and measured-state reach checks (D-856)."""
from dataclasses import fields, replace
from importlib import import_module

import pytest

from omx_adapter.kinematics import TopDownPose
from omx_adapter.transfer_motion import GraspGeometry, TransferPlanRejected, STATE_INVALID
from test_omx_pose_plan import _request, _state, kin, profile  # noqa: F401


def _api():
    try:
        return import_module("omx_adapter.transfer_preflight")
    except ModuleNotFoundError:
        pytest.fail("owner-side neutral transfer preflight is missing")


def _catalog(kin, profile, **changes):
    api = _api()
    request = _request()
    values = dict(workcell_id="arm-cell", instance_id="arm-a", profile_revision=profile.revision,
                  kinematics_revision=kin.revision, calibration_revision="omx-f-gazebo-only-v1",
                  transform_revision="tf-sim-1", planning_scene_revision=kin.planning_scene_revision,
                  home=request.home, carry_z=request.carry_z,
                  poses={"p1": api.TransferPose(request.pick, request.pick_approach_z),
                         "p2": api.TransferPose(request.place, request.place_approach_z)},
                  geometries={"g1": GraspGeometry(0.03, 0.01, 0.03, True)})
    return api.ArmTransferCatalog(**{**values, **changes})


def _service(kin, profile, *, state=None, clock=lambda: 100.01, catalog=None):
    catalog = catalog or _catalog(kin, profile)
    return _api().TransferPreflight(catalog, profile, kin,
                                    execution_state=lambda: state or _state(kin, profile), monotonic=clock)


def _check(service, **changes):
    values = dict(catalog_digest=service.catalog.digest, source="p1", target="p2", geometry="g1")
    return service.check_transfer(**{**values, **changes})


def test_owner_catalog_copies_physical_data_and_seals_its_content(kin, profile):
    catalog = _catalog(kin, profile)
    assert catalog.digest == _catalog(kin, profile).digest
    assert catalog.digest != _catalog(kin, profile, carry_z=0.12).digest
    assert catalog.digest != _catalog(kin, profile, instance_id="arm-b").digest
    poses = dict(catalog.poses)
    copied = _catalog(kin, profile, poses=poses)
    poses.clear()
    assert copied.poses == catalog.poses
    with pytest.raises(TypeError):
        catalog.poses["new"] = catalog.poses["p1"]
    assert not {"job_id", "recipe_sha256", "pallet", "layer"} & {f.name for f in fields(catalog)}


def test_check_returns_snapshot_facts_without_trajectory_or_execution_authority(kin, profile):
    result = _check(_service(kin, profile))
    assert result.catalog_digest == _catalog(kin, profile).digest
    assert (result.source, result.target, result.geometry) == ("p1", "p2", "g1")
    assert result.source_state_sequence == 7
    assert result.observed_at_monotonic_s == 100.0
    assert result.checked_at_monotonic_s == 100.01
    assert result.calibration_revision == "omx-f-gazebo-only-v1"
    assert result.transform_revision == "tf-sim-1"
    assert not {"plan", "phases", "grant", "action_id", "permit", "cargo_arrived"} & {
        f.name for f in fields(result)}


@pytest.mark.parametrize("changes,reason", [
    ({"catalog_digest": "0" * 64}, "CATALOG_MISMATCH"),
    ({"source": "missing"}, "REFERENCE_UNAVAILABLE"),
    ({"target": "missing"}, "REFERENCE_UNAVAILABLE"),
    ({"geometry": "missing"}, "REFERENCE_UNAVAILABLE"),
])
def test_unaccepted_references_are_rejected_before_state_read(kin, profile, changes, reason):
    service = _service(kin, profile)
    service.execution_state = lambda: pytest.fail("unaccepted input must not read owner state")
    with pytest.raises(TransferPlanRejected) as failure:
        _check(service, **changes)
    assert failure.value.reason == reason


@pytest.mark.parametrize("changes", [
    {"observed_at_monotonic_s": 99.0}, {"observed_at_monotonic_s": 101.0},
    {"calibration_revision": "changed"}, {"transform_revision": "changed"},
    {"planning_scene_revision": "changed"},
])
def test_stale_future_or_changed_measured_state_is_rejected(kin, profile, changes):
    state = replace(_state(kin, profile), **changes)
    with pytest.raises(TransferPlanRejected) as failure:
        _check(_service(kin, profile, state=state))
    assert failure.value.reason == STATE_INVALID


@pytest.mark.parametrize("end", [101.0, 99.9, float("nan"), True])
def test_calculation_expiry_or_invalid_clock_cannot_return_a_ready_result(kin, profile, end):
    ticks = iter([100.01, 100.01, end])
    with pytest.raises(TransferPlanRejected) as failure:
        _check(_service(kin, profile, clock=lambda: next(ticks)))
    assert failure.value.reason == STATE_INVALID


def test_unreachable_target_uses_existing_physical_rejection(kin, profile):
    catalog = _catalog(kin, profile)
    poses = {**catalog.poses, "p2": _api().TransferPose(TopDownPose(2, 0, 0.05, 0), 0.085)}
    with pytest.raises(TransferPlanRejected):
        _check(_service(kin, profile, catalog=_catalog(kin, profile, poses=poses)))


def test_wrong_installed_profile_is_rejected_at_service_construction(kin, profile):
    with pytest.raises(ValueError):
        _service(kin, profile, catalog=_catalog(kin, profile, profile_revision="0" * 64))
