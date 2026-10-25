"""D-865 P2b policy admission HTTP surface over the decision core.

FastAPI TestClient only — no auth stack, guards are injected no-ops exactly as
`create_app` injects the real ones. The core itself is covered by
`test_policy_admission_core.py` (P2a).
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.missions.policy_admission import (
    PolicyAdmissionCore,
    PolicyAdmissionSettings,
)
from fleet.server.missions.policy_admission_routes import (
    install_policy_admission_routes,
)


def _client(**settings_overrides):
    base = dict(enabled=True, robots=frozenset({"rosy_01"}),
                step_approval_kinds=frozenset({"one_person"}),
                max_admits=3, scope_revision="rev-1")
    base.update(settings_overrides)
    core = PolicyAdmissionCore(PolicyAdmissionSettings(**base),
                               now=lambda: "2026-10-25T00:00:00Z")
    app = FastAPI()
    install_policy_admission_routes(
        app, core=core, read_guard=[], operator_guard=[],
        require_viewer=lambda: "viewer",
        require_named_operator=lambda: "operator")
    return TestClient(app), core


class TestPolicyAdmissionRoutes:
    def test_status_readback_shape(self):
        client, _ = _client()
        response = client.get("/api/fleet/policy-admission")
        assert response.status_code == 200
        body = response.json()
        assert body["status"]["scope"]["enabled"] is True
        assert body["status"]["scope"]["robots"] == ["rosy_01"]
        assert body["status"]["admits_remaining"] == 3
        assert body["status"]["reason"] is None

    def test_toggle_off_and_on_round_trips(self):
        client, _ = _client()
        off = client.post("/api/fleet/policy-admission", json={"enabled": False})
        assert off.status_code == 200
        assert off.json()["status"]["reason"] == "DISABLED"
        assert off.json()["status"]["admits_remaining"] == 0
        on = client.post("/api/fleet/policy-admission", json={"enabled": True})
        assert on.json()["status"]["reason"] is None

    def test_toggle_cannot_enable_an_unconfigured_scope(self):
        client, _ = _client(enabled=False, robots=frozenset(),
                            step_approval_kinds=frozenset({"one_person"}))
        response = client.post("/api/fleet/policy-admission", json={"enabled": True})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "POLICY_ADMISSION_SCOPE_NOT_CONFIGURED"

    def test_toggle_body_is_boolean_only(self):
        client, _ = _client()
        response = client.post("/api/fleet/policy-admission",
                               json={"enabled": True, "robots": ["rosy_02"]})
        assert response.status_code == 422

    def test_audit_lists_policy_decisions_newest_first(self):
        client, core = _client()
        core.record(mission_id="m-1", outcome="ADMITTED", generation=1)
        core.record(mission_id="m-2", outcome="HELD", generation=1,
                    reason="ROBOT_OUT_OF_SCOPE")
        response = client.get("/api/fleet/policy-admission/audit")
        assert response.status_code == 200
        entries = response.json()["entries"]
        assert [entry["mission_id"] for entry in entries] == ["m-2", "m-1"]
        assert entries[0]["principal"] == "fleet-policy-admission"
        assert entries[1]["outcome"] == "ADMITTED"

    def test_budget_readback_after_admissions(self):
        client, core = _client()
        for index in range(3):
            core.record(mission_id=f"m-{index}", outcome="ADMITTED",
                        generation=1)
        status = client.get("/api/fleet/policy-admission").json()["status"]
        assert status["admits_issued"] == 3
        assert status["admits_remaining"] == 0
        assert status["reason"] == "EXHAUSTED"
