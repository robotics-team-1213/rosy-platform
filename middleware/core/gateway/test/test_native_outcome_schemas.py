"""D-732 canonical message-family exports retain legacy model identity."""


def test_docking_family_preserves_canonical_identity():
    from core_common.protocol import docking, schemas

    assert docking.DockState is schemas.DockState
    assert docking.DockingStatus is schemas.DockingStatus
    assert docking.DockingStatus().model_dump() == {
        "state": schemas.DockState.UNDOCKED, "dock_id": None,
        "phase": None, "retries": 0, "error": None,
    }


def test_swarm_family_preserves_models_defaults_and_validation():
    from core_common.protocol import schemas, swarm
    from pydantic import ValidationError
    import pytest

    for name in ("SwarmRole", "SwarmStatus", "SwarmReferenceSource", "SwarmFollowParams"):
        assert getattr(swarm, name) is getattr(schemas, name)
    params = swarm.SwarmFollowParams(target_robot_id="robot-a")
    assert params.source is schemas.SwarmReferenceSource.FLEET
    assert params.mode == "offset"
    with pytest.raises(ValidationError):
        swarm.SwarmFollowParams(target_robot_id="robot-a", mode="unsupported")
