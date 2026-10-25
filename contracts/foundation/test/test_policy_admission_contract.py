"""D-865 policy admission wire shapes: fail-closed scope, bounded audit, no motion authority."""

import pytest
from pydantic import ValidationError

from core_common.protocol.policy_admission import (
    POLICY_ADMISSION_PRINCIPAL,
    PolicyAdmissionAuditEntry,
    PolicyAdmissionAuditResponse,
    PolicyAdmissionReadResponse,
    PolicyAdmissionScope,
    PolicyAdmissionStatus,
    PolicyAdmissionToggleRequest,
)
from core_common.protocol.schemas import PolicyAdmissionScope as CanonicalScope


def _scope(**overrides):
    base = dict(enabled=True, robots=["rosy_01"], step_approval_kinds=["one_person"],
                max_admits=5, valid_until="2026-12-31T00:00:00Z", scope_revision="rev-1")
    base.update(overrides)
    return PolicyAdmissionScope(**base)


class TestPolicyAdmissionScope:
    def test_enabled_scope_requires_robots_and_kinds(self):
        with pytest.raises(ValidationError):
            _scope(robots=[])
        with pytest.raises(ValidationError):
            _scope(step_approval_kinds=[])

    def test_scope_robots_unique(self):
        with pytest.raises(ValidationError):
            _scope(robots=["rosy_01", "rosy_01"])

    def test_max_admits_positive(self):
        with pytest.raises(ValidationError):
            _scope(max_admits=0)

    def test_unknown_approval_kind_rejected(self):
        with pytest.raises(ValidationError):
            _scope(step_approval_kinds=["two_person"])

    def test_disabled_default_shape_is_closed(self):
        scope = PolicyAdmissionScope(max_admits=1, scope_revision="none")
        assert scope.enabled is False
        assert scope.robots == []
        assert scope.step_approval_kinds == []

    def test_frozen_and_closed(self):
        scope = _scope()
        with pytest.raises(ValidationError):
            scope.enabled = False
        with pytest.raises(ValidationError):
            _scope(extra=1)

    def test_canonical_reexport(self):
        assert CanonicalScope is PolicyAdmissionScope


class TestPolicyAdmissionStatusAndAudit:
    def test_status_defaults_closed(self):
        status = PolicyAdmissionStatus(
            scope=PolicyAdmissionScope(max_admits=1, scope_revision="none"))
        assert status.admits_issued == 0
        assert status.admits_remaining == 0
        assert status.reason is None

    def test_audit_entry_records_policy_principal_and_generation(self):
        entry = PolicyAdmissionAuditEntry(
            mission_id="m-1", decided_at="2026-10-25T00:00:00Z",
            principal=POLICY_ADMISSION_PRINCIPAL, scope_revision="rev-1",
            outcome="ADMITTED", generation=3)
        assert entry.outcome == "ADMITTED"
        assert entry.generation == 3

    def test_audit_rejects_other_principals(self):
        with pytest.raises(ValidationError):
            PolicyAdmissionAuditEntry(
                mission_id="m-1", decided_at="2026-10-25T00:00:00Z",
                principal="harbor", scope_revision="rev-1",
                outcome="ADMITTED", generation=3)

    def test_audit_response_bounded(self):
        entry = PolicyAdmissionAuditEntry(
            mission_id="m-1", decided_at="2026-10-25T00:00:00Z",
            principal=POLICY_ADMISSION_PRINCIPAL, scope_revision="rev-1",
            outcome="HELD", generation=0, reason="OUT_OF_SCOPE")
        with pytest.raises(ValidationError):
            PolicyAdmissionAuditResponse(entries=[entry] * 101)

    def test_toggle_request_is_boolean_only(self):
        assert PolicyAdmissionToggleRequest(enabled=False).enabled is False
        with pytest.raises(ValidationError):
            PolicyAdmissionToggleRequest(enabled=False, robots=["rosy_01"])

    def test_read_response_carries_status(self):
        response = PolicyAdmissionReadResponse(
            status=PolicyAdmissionStatus(
                scope=PolicyAdmissionScope(max_admits=1, scope_revision="none"),
                reason="DISABLED"))
        assert response.status.reason == "DISABLED"
