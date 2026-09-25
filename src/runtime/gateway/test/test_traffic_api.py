"""Traffic policy supervision API permissions and stopped-only apply."""

from core_features.command.arbitration import Mode


VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}


def test_status_is_viewable_but_policy_stage_requires_operator(core_client):
    client, _services = core_client()

    status = client.get("/api/v1/traffic", headers=VIEWER)

    assert status.status_code == 200
    assert status.json()["status"]["mode"] == "DISABLED"
    assert status.json()["active"]["policy_revision"] == "traffic-policy-v1"
    blocked = client.post(
        "/api/v1/traffic/policy/stage",
        json={"mode": "MONITOR_ONLY"},
        headers=VIEWER,
    )
    assert blocked.status_code == 403


def test_operator_stages_then_applies_policy_only_while_stopped(core_client):
    client, services = core_client()
    services.state.set_velocity(0.08, 0.0)

    staged = client.post(
        "/api/v1/traffic/policy/stage",
        json={
            "mode": "ENFORCED",
            "policy_revision": "traffic-policy-v2",
            "approach_distance_m": 0.40,
        },
        headers=OPERATOR,
    )
    moving = client.post(
        "/api/v1/traffic/policy/apply", headers=OPERATOR)

    assert staged.status_code == 200
    assert staged.json()["staged"]["mode"] == "ENFORCED"
    assert services.traffic_policy.mode.value == "DISABLED"
    assert moving.status_code == 409
    assert moving.json()["error"]["code"] == "ROBOT_MUST_BE_STOPPED"

    services.state.set_velocity(0.0, 0.0)
    applied = client.post(
        "/api/v1/traffic/policy/apply", headers=OPERATOR)

    assert applied.status_code == 200
    assert applied.json()["active"]["mode"] == "ENFORCED"
    assert applied.json()["staged"] is None
    assert services.traffic_policy.mode.value == "ENFORCED"
    types = [event.type for event in services.events.history()]
    assert "nav.traffic_policy_staged" in types
    assert "nav.traffic_policy_applied" in types


def test_apply_is_blocked_by_active_navigation_even_at_zero_velocity(
        core_client):
    client, services = core_client()
    services.modes.transition(Mode.NAVIGATION)
    client.post(
        "/api/v1/traffic/policy/stage",
        json={"mode": "MONITOR_ONLY"}, headers=OPERATOR)

    response = client.post(
        "/api/v1/traffic/policy/apply", headers=OPERATOR)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ROBOT_MUST_BE_STOPPED"


def test_apply_requires_fresh_zero_velocity_or_estop_proof(core_client):
    client, _services = core_client()
    client.post(
        "/api/v1/traffic/policy/stage",
        json={"mode": "MONITOR_ONLY"}, headers=OPERATOR)

    response = client.post(
        "/api/v1/traffic/policy/apply", headers=OPERATOR)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ROBOT_MUST_BE_STOPPED"


def test_invalid_policy_values_fail_without_replacing_active_config(
        core_client):
    client, services = core_client()

    response = client.post(
        "/api/v1/traffic/policy/stage",
        json={
            "stop_distance_m": 0.50,
            "approach_distance_m": 0.20,
        },
        headers=OPERATOR,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert services.traffic_policy.configuration()["staged"] is None


def test_simulation_signal_control_is_capability_gated(core_client):
    client, _services = core_client()
    unavailable = client.put(
        "/api/v1/traffic/simulation/signal",
        json={"colour": "GREEN"}, headers=OPERATOR)
    assert unavailable.status_code == 501

    sim_client, sim_services = core_client(config_overrides={
        "runtime": {"mode": "simulation"},
        "traffic_policy": {
            "mode": "DISABLED",
            "map_id": "map_260905_update_v2",
            "scene_revision": "road-scene-v1",
            "policy_revision": "traffic-policy-v1",
            "simulation_signal_control": True,
        },
    })
    changed = sim_client.put(
        "/api/v1/traffic/simulation/signal",
        json={"colour": "GREEN"}, headers=OPERATOR)

    assert changed.status_code == 200
    assert changed.json() == {"available": True, "colour": "GREEN"}
    assert sim_services.traffic_policy.configuration()[
        "simulation_signal"]["colour"] == "GREEN"
