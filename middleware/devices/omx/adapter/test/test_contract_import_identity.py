"""Legacy import paths share the canonical ROS-free contract classes."""

import importlib

import pytest


@pytest.mark.parametrize("module_name", [
    "camera_contract", "gripper_contract", "manipulation_plan", "target_evidence",
])
def test_legacy_contract_exports_are_canonical_objects(module_name):
    legacy = importlib.import_module(f"omx_adapter.{module_name}")
    canonical = importlib.import_module(f"omx_adapter.contracts.{module_name}")
    for name, value in vars(canonical).items():
        if getattr(value, "__module__", None) == canonical.__name__:
            assert getattr(legacy, name) is value
    for name in legacy.__all__:
        assert getattr(legacy, name) is getattr(canonical, name)


def test_owner_accepts_trajectory_points_from_both_import_paths():
    from omx_adapter import command_owner
    from omx_adapter.contracts import command_types, manipulation_plan
    from omx_adapter.manipulation_plan import JointTrajectoryPoint

    for name in ("ArmCommandConfig", "JointStateSnapshot", "TrajectoryCommand",
                 "ActionHandle", "ActionPort", "CommandDecision"):
        assert getattr(command_owner, name) is getattr(command_types, name)
    assert JointTrajectoryPoint is manipulation_plan.JointTrajectoryPoint
    point = JointTrajectoryPoint(time_from_start_s=0.5, positions=(0.2,))
    command = command_owner.TrajectoryCommand(
        workcell_id="cell", instance_id="instance", command_id="command",
        session_id="session", owner="pilot_sim", positions={"joint": 0.2},
        duration_s=0.5, source_state_sequence=1, calibration_revision="calibration",
        trajectory_points=(point,),
    )
    assert command.trajectory_points == (point,)
