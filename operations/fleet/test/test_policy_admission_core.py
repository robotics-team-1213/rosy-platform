"""D-865 P2a policy admission core: scope parsing, switch, budget, audit.

Pure unit tests — no FastAPI, no store. The P2b assembly (routes, loop, config
wiring) lands separately; until then this core is connected to no execution path.
"""

import pytest
from pydantic import ValidationError

from fleet.server.missions.policy_admission import (
    AUDIT_LIMIT,
    PolicyAdmissionCore,
    PolicyAdmissionSettings,
)


def _clock():
    times = iter(["2026-10-25T00:00:00Z", "2026-10-25T00:00:01Z",
                  "2026-10-25T00:00:02Z"])
    return lambda: next(times, "2026-10-25T00:00:09Z")


def _settings(**overrides):
    base = dict(enabled=True, robots=frozenset({"rosy_01"}),
                step_approval_kinds=frozenset({"one_person"}),
                max_admits=2, valid_until="2026-12-31T00:00:00Z",
                scope_revision="rev-1")
    base.update(overrides)
    return PolicyAdmissionSettings(**base)


def _core(**overrides):
    return PolicyAdmissionCore(_settings(**overrides), _clock())


class TestSettingsFromConfig:
    def test_absent_section_is_disabled(self):
        settings = PolicyAdmissionSettings.from_config(None)
        assert settings.enabled is False
        assert settings.robots == frozenset()

    def test_enabled_section_requires_robots_and_kinds(self):
        with pytest.raises(ValueError):
            PolicyAdmissionSettings.from_config({"enabled": True,
                                                 "max_admits": 1})

    def test_unsupported_approval_kind_rejected(self):
        with pytest.raises(ValueError):
            PolicyAdmissionSettings.from_config(
                {"enabled": True, "robots": ["rosy_01"],
                 "step_approval_kinds": ["two_person"]})

    def test_bad_max_admits_rejected(self):
        with pytest.raises(ValueError):
            PolicyAdmissionSettings.from_config(
                {"enabled": True, "robots": ["rosy_01"], "max_admits": 0})

    def test_non_mapping_rejected(self):
        with pytest.raises(ValueError):
            PolicyAdmissionSettings.from_config(["enabled"])

    def test_minimal_enabled_section(self):
        settings = PolicyAdmissionSettings.from_config({"robots": ["rosy_01"]})
        assert settings.enabled is True
        assert settings.max_admits == 1
        assert settings.step_approval_kinds == frozenset({"one_person"})


class TestScopeStatusAndToggle:
    def test_unconfigured_status_is_closed(self):
        core = PolicyAdmissionCore(PolicyAdmissionSettings(), _clock())
        status = core.status()
        assert status.scope.enabled is False
        assert status.admits_remaining == 0
        assert status.reason == "NOT_CONFIGURED"

    def test_active_status_has_budget(self):
        status = _core().status()
        assert status.scope.enabled is True
        assert status.admits_remaining == 2
        assert status.reason is None

    def test_toggle_off_and_back_on(self):
        core = _core()
        assert core.toggle(enabled=False).reason == "DISABLED"
        assert core.toggle(enabled=True).reason is None

    def test_toggle_cannot_enable_unconfigured_scope(self):
        core = PolicyAdmissionCore(PolicyAdmissionSettings(), _clock())
        with pytest.raises(ValueError):
            core.toggle(enabled=True)

    def test_toggle_does_not_change_scope_contents(self):
        core = _core()
        core.toggle(enabled=False)
        assert core.status().scope.robots == ["rosy_01"]
        assert core.status().scope.max_admits == 2


class TestHoldReason:
    def test_in_scope_returns_none(self):
        assert _core().hold_reason(robot_id="rosy_01",
                                   approval_rule="one_person") is None

    def test_robot_out_of_scope(self):
        assert _core().hold_reason(robot_id="rosy_02",
                                   approval_rule="one_person") == "ROBOT_OUT_OF_SCOPE"

    def test_approval_rule_out_of_scope(self):
        assert _core().hold_reason(robot_id="rosy_01",
                                   approval_rule="two_person") == "APPROVAL_RULE_OUT_OF_SCOPE"

    def test_disabled_by_switch(self):
        core = _core()
        core.toggle(enabled=False)
        assert core.hold_reason(robot_id="rosy_01",
                                approval_rule="one_person") == "DISABLED"

    def test_budget_exhaustion_does_not_reset(self):
        core = _core()  # max_admits=2
        core.record(mission_id="m-1", outcome="ADMITTED", generation=1)
        core.record(mission_id="m-2", outcome="ADMITTED", generation=1)
        assert core.hold_reason(robot_id="rosy_01",
                                approval_rule="one_person") == "EXHAUSTED"
        assert core.status().admits_remaining == 0
        assert core.status().reason == "EXHAUSTED"
        assert core.hold_reason(robot_id="rosy_01",
                                approval_rule="one_person") == "EXHAUSTED"

    def test_held_decisions_do_not_consume_budget(self):
        core = _core()
        core.record(mission_id="m-1", outcome="HELD", generation=1,
                    reason="ROBOT_OUT_OF_SCOPE")
        assert core.status().admits_remaining == 2


class TestAudit:
    def test_records_policy_principal_and_revision(self):
        core = _core()
        entry = core.record(mission_id="m-1", outcome="ADMITTED", generation=3)
        assert entry.principal == "fleet-policy-admission"
        assert entry.scope_revision == "rev-1"
        assert entry.generation == 3

    def test_audit_newest_first_and_bounded(self):
        core = PolicyAdmissionCore(_settings(max_admits=10_000), _clock())
        for index in range(AUDIT_LIMIT + 5):
            core.record(mission_id=f"m-{index}", outcome="HELD", generation=0,
                        reason="ROBOT_OUT_OF_SCOPE")
        entries = core.audit().entries
        assert len(entries) == AUDIT_LIMIT
        assert entries[0].mission_id == f"m-{AUDIT_LIMIT + 4}"

    def test_wire_audit_shape_is_valid(self):
        core = _core()
        core.record(mission_id="m-1", outcome="ADMITTED", generation=1)
        assert core.audit().entries[0].model_validate(
            core.audit().entries[0].model_dump()) is not None

    def test_scope_wire_model_rejects_out_of_v1_kinds(self):
        from core_common.protocol.policy_admission import PolicyAdmissionScope
        with pytest.raises(ValidationError):
            PolicyAdmissionScope(enabled=True, robots=["rosy_01"],
                                 step_approval_kinds=["two_person"],
                                 max_admits=1, scope_revision="rev-1")
