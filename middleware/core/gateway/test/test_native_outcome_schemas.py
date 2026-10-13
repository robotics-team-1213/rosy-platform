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


def test_native_operation_phase_result_coherence():
    from core_common.protocol.native_operation import NativeOperation
    from pydantic import ValidationError
    from uuid import uuid4
    import pytest

    base = {"run_id": str(uuid4()), "boot_id": str(uuid4()), "kind": "home"}
    accepted = NativeOperation(**base, phase="SUBMITTED")
    assert accepted.result is None
    with pytest.raises(ValidationError):
        NativeOperation(**base, phase="SUBMITTED", result="SUCCEEDED")
    with pytest.raises(ValidationError):
        NativeOperation(**base, phase="TERMINAL")
    terminal = NativeOperation(**base, phase="TERMINAL", result="CANCELED", reason="CANCELED")
    with pytest.raises(ValidationError):
        terminal.result = "SUCCEEDED"


def test_native_operation_rejects_unbounded_or_untyped_reason():
    from core_common.protocol.native_operation import NativeOperation
    from pydantic import ValidationError
    from uuid import uuid4
    import pytest

    base = {"run_id": str(uuid4()), "boot_id": str(uuid4()), "kind": "teleop", "phase": "SUBMITTED"}
    for reason in ("raw error with user content", "X" * 65):
        with pytest.raises(ValidationError):
            NativeOperation(**base, reason=reason)
    with pytest.raises(ValidationError):
        NativeOperation(**{**base, "phase": "UNKNOWN"})


def test_uncertain_backend_outcome_is_nonterminal():
    from core_common.protocol.native_operation import NativeOperation
    from uuid import uuid4

    operation = NativeOperation(
        run_id=str(uuid4()), boot_id=str(uuid4()), kind="navigate",
        phase="SUBMITTED", reason="BACKEND_RESULT_UNKNOWN",
    )
    assert operation.result is None
    assert operation.phase == "SUBMITTED"
