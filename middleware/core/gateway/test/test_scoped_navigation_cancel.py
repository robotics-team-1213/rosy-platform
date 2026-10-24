from uuid import uuid4

import pytest


OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


class Executor:
    def __init__(self):
        self.cancelled = 0

    def send_goal(self, spec, *, correlation_id=None):
        pass

    def cancel_goal(self):
        self.cancelled += 1


@pytest.fixture
def navigation(core_client, monkeypatch):
    client, services = core_client()
    monkeypatch.setattr("core_api_web.api.v1.navigation.require_kept", lambda *_: None)
    executor = Executor()
    services.nav.executor = executor
    return client, services, executor


def goal(client, services, correlation_id):
    response = client.post("/api/v1/navigation/goal", headers=OPERATOR,
                           json={"x": 1.0, "y": 0.5, "correlation_id": correlation_id})
    assert response.status_code == 200, response.text
    services.nav.on_goal_accepted()
    operation = response.json()["operation"]
    return {"expected_boot_id": operation["boot_id"], "run_id": operation["run_id"],
            "correlation_id": correlation_id}


def test_matching_scope_cancels_and_returns_the_original_owner(navigation):
    client, services, executor = navigation
    scope = goal(client, services, "attempt-1")
    response = client.post("/api/v1/navigation/cancel-scoped", headers=OPERATOR, json=scope)
    assert response.status_code == 200, response.text
    assert executor.cancelled == 1
    assert response.json()["operation"]["run_id"] == scope["run_id"]
    assert response.json()["operation"]["result"] == "CANCELED"


@pytest.mark.parametrize("key", ["expected_boot_id", "run_id", "correlation_id"])
def test_changed_scope_preserves_current_goal_and_trip_lease(navigation, monkeypatch, key):
    client, services, executor = navigation
    scope = goal(client, services, "attempt-1")
    scope[key] = "different-attempt" if key == "correlation_id" else str(uuid4())
    trip_changes = []
    monkeypatch.setattr("core_api_web.api.v1.navigation.stop_ends_trip_lease", lambda *_: trip_changes.append(1))
    response = client.post("/api/v1/navigation/cancel-scoped", headers=OPERATOR, json=scope)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NAVIGATION_SCOPE_CHANGED"
    assert executor.cancelled == 0 and trip_changes == []
    assert services.nav.nav_state.value != "CANCELED"


def test_late_cancel_does_not_touch_a_new_goal(navigation):
    client, services, executor = navigation
    old = goal(client, services, "old-attempt")
    assert client.post("/api/v1/navigation/cancel", headers=OPERATOR).status_code == 200
    goal(client, services, "new-attempt")
    before = executor.cancelled
    response = client.post("/api/v1/navigation/cancel-scoped", headers=OPERATOR, json=old)
    assert response.status_code == 409
    assert executor.cancelled == before
    assert services.nav.nav_state.value != "CANCELED"


def test_missing_scope_and_read_only_credentials_cannot_cancel(navigation):
    client, services, executor = navigation
    scope = goal(client, services, "attempt-1")
    invalid = client.post("/api/v1/navigation/cancel-scoped", headers=OPERATOR, json={})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.post("/api/v1/navigation/cancel-scoped", headers=VIEWER, json=scope).status_code == 403
    assert executor.cancelled == 0


def test_successful_old_cancel_cannot_halt_a_replacement_run_or_trip_lease(navigation, monkeypatch):
    client, services, executor = navigation
    scope = goal(client, services, "old-attempt")
    original_cancel = services.nav.cancel
    replacement = []

    def cancel_then_admit_replacement(*args, **kwargs):
        canceled = original_cancel(*args, **kwargs)
        if canceled and not replacement:
            replacement.append(True)
            services.trip_lease.open(lease_id="replacement-lease", trip_id="replacement-trip",
                                    holder="other-fleet", operator_name="other-operator",
                                    ttl_s=5, owner_id="replacement-owner")
            spec = services.nav.resolve_goal(x=2.0, y=0.0, yaw=0.0, waypoint=None)
            services.nav.goal(spec, source="replacement-owner", correlation_id="new-attempt")
            services.nav.on_goal_accepted()
        return canceled

    monkeypatch.setattr(services.nav, "cancel", cancel_then_admit_replacement)
    response = client.post("/api/v1/navigation/cancel-scoped", headers=OPERATOR, json=scope)
    assert response.status_code == 200, response.text
    assert response.json()["operation"]["run_id"] == scope["run_id"]
    assert executor.cancelled == 1
    assert services.nav.native.current.correlation_id == "new-attempt"
    assert services.nav.native.current.phase != "TERMINAL"
    assert services.trip_lease.current()["lease_id"] == "replacement-lease"
    assert response.json()["navigation"] == services.nav.nav_state.value
