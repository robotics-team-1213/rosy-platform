"""Shared wire requests bind identity and scope without granting device authority."""

import pytest
from pydantic import ValidationError


def classes():
    from core_common.protocol.schemas import (
        ControlWorkRequest, ControlIngressRequest, ControlApproveRequest,
        ControlUnitReply, ScopedNavigationCancelRequest,
    )
    return ControlWorkRequest, ControlIngressRequest, ControlApproveRequest, ControlUnitReply, ScopedNavigationCancelRequest


def work():
    return {"delegation_id": "job-1", "target_unit": "A1", "robot_id": "a1",
            "goal": {"x": 1, "y": 2, "yaw": 0}}


def test_canonical_candidate_and_ingress_scope():
    Work, Ingress, Approval, _, _ = classes()
    request = Work(**work())
    assert request.goal.x == 1.0
    inbound = Ingress(**work(), origin_id="R", config_revision="lab-1")
    assert inbound.origin_id == "R"
    assert Approval(expected_revision=3).expected_revision == 3


@pytest.mark.parametrize("field,value", [
    ("origin_id", "spoofed"), ("actor_id", "operator-a"), ("endpoint", "http://untrusted"),
    ("delegation_id", ""), ("delegation_id", True), ("target_unit", " A1"),
    ("robot_id", ""), ("goal", {"x": float("nan"), "y": 0}),
    ("goal", {"x": True, "y": 0}), ("goal", {"x": 0, "y": float("inf")}),
])
def test_candidates_reject_identity_spoofing_and_unbounded_goals(field, value):
    Work, *_ = classes()
    body = dict(work(), **{field: value})
    with pytest.raises(ValidationError):
        Work(**body)


@pytest.mark.parametrize("revision", [True, 0, -1, "3"])
def test_approval_requires_an_exact_positive_revision(revision):
    _, _, Approval, _, _ = classes()
    with pytest.raises(ValidationError):
        Approval(expected_revision=revision)


def test_scoped_cancel_requires_boot_run_and_correlation():
    *_, Cancel = classes()
    body = {"expected_boot_id": "9ed6c9cf-15b1-4245-a2bc-836b21c9bfa2",
            "run_id": "5b4c766a-6cd2-4ebd-9d43-1b67638d92d2", "correlation_id": "attempt-1"}
    assert str(Cancel(**body).run_id) == body["run_id"]
    for missing in body:
        incomplete = {key: value for key, value in body.items() if key != missing}
        with pytest.raises(ValidationError):
            Cancel(**incomplete)


def test_owner_snapshot_is_bounded_and_explicit():
    _, _, _, Reply, _ = classes()
    snapshot = {"origin_id": "R", "delegation_id": "job-1", "request": {
        key: value for key, value in work().items() if key != "delegation_id"},
        "owner_unit": "A1", "config_revision": "lab-1", "status": "PENDING",
        "revision": 1, "owner_revision": 0, "local_actor": None, "local_task_id": None,
        "cancel_requested": False, "result": {}, "updated_at": "2026-10-23T12:00:00+00:00"}
    assert Reply(unit_id="A", config_revision="lab-1", delegation=snapshot).delegation.revision == 1
    for changes in [{"revision": True}, {"status": "STOP_CONFIRMED"},
                    {"result": {"raw": "x" * 70_000}}, {"result": {"x": float("nan")}}]:
        with pytest.raises(ValidationError):
            Reply(unit_id="A", config_revision="lab-1", delegation=dict(snapshot, **changes))
