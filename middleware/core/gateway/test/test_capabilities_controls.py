"""D-411 B: CORE announces Pinky's controls from adapter provides (or teleop)."""

import pytest

from core_common.domain.adapters import AdapterManifest, AdapterRegistry

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


def _controls(client):
    response = client.get("/api/v1/system/capabilities", headers=VIEWER)
    assert response.status_code == 200
    return response.json()["controls"]


def _live_core(core_client):
    # The default fixture is core mode: CAP-001 withholds teleop until
    # odometry proves a base is attached (D-32), as test_api does.
    client, svc = core_client()
    svc.state.set_velocity(0.0, 0.0)
    return client, svc


def test_core_without_a_live_base_announces_nothing(core_client):
    client, _ = core_client()
    assert _controls(client) == {"schema": "rosy.controls/1", "items": []}


def test_teleop_capable_core_announces_base_velocity(core_client):
    client, svc = _live_core(core_client)
    controls = _controls(client)
    assert controls["schema"] == "rosy.controls/1"
    (base,) = controls["items"]
    assert base["kind"] == "base_velocity" and base["autonomy"] == ["line"]
    assert base["max_linear"] == svc.safety.limits.manual_linear
    assert base["max_angular"] == svc.safety.limits.manual_angular


def test_zero_manual_limit_is_announced_not_a_server_error(core_client):
    client, svc = _live_core(core_client)
    svc.safety.limits.manual_linear = 0.0
    (base,) = _controls(client)["items"]
    assert base["max_linear"] == 0.0


def test_autonomy_is_empty_without_a_line_follow_service(core_client):
    client, svc = _live_core(core_client)
    svc.line_follow = None
    (base,) = _controls(client)["items"]
    assert base["autonomy"] == []


def test_manifest_without_drive_announces_nothing(core_client):
    client, svc = _live_core(core_client)
    svc.adapter_registry = AdapterRegistry([AdapterManifest(id="omx", provides=())])
    assert _controls(client)["items"] == []


def test_enabled_manifest_providing_drive_announces_base(core_client):
    client, svc = _live_core(core_client)
    svc.adapter_registry = AdapterRegistry([AdapterManifest(id="pinky", provides=("drive", "battery"))])
    (base,) = _controls(client)["items"]
    assert base["id"] == "base" and base["kind"] == "base_velocity"


def test_manifest_drive_with_withheld_teleop_announces_nothing(core_client):
    client, svc = core_client()  # no odometry: CAP-001 withholds teleop
    svc.adapter_registry = AdapterRegistry([AdapterManifest(id="pinky", provides=("drive",))])
    assert _controls(client)["items"] == []


def test_withheld_teleop_drops_the_drive_control(core_client):
    client, svc = _live_core(core_client)
    svc.capability._data["teleop"] = False
    assert _controls(client)["items"] == []


def test_d491_trip_caps_follow_robot_package_services_and_limits(core_client):
    from core_common.profile import DEFAULT_ROBOT

    client, svc = _live_core(core_client)
    (base,) = _controls(client)["items"]
    assert base["robot_kind"] == (svc.config.get("robot") or {}).get("model", DEFAULT_ROBOT)
    limits = svc.safety.limits
    assert base["trip_max_linear"] == min(limits.max_linear, limits.fleet_linear,
                                          svc.line_follow.config.max_linear)
    assert base["junction_turn"] is False              # no live keep-mode evidence yet
    assert base["junction_pivot"] is True              # D-507 2: takes the window/pivot fields
    lf = svc.line_follow  # D-495: a fresh keep_debug frame with corner_turning on
    lf.observe_junction("no_boundary", lf._clock(), corner_turning=True)
    assert _controls(client)["items"][0]["junction_turn"] is False  # no enforce floor proof
    lf.bind_return_motion(lambda now, v, w: True, proof_configured=lambda: True)
    assert _controls(client)["items"][0]["junction_turn"] is True
    navigation = svc.capability._data.setdefault("navigation", {})
    navigation["goal_navigation"] = False
    assert _controls(client)["items"][0]["drive_modes"] == ["lane"]
    svc.config.setdefault("robot", {})["model"] = "other_base"
    svc.line_follow = None
    (base,) = _controls(client)["items"]
    assert base["robot_kind"] == "other_base" and base["drive_modes"] == []
    assert base["junction_turn"] is False and base["junction_pivot"] is False
    assert base["trip_max_linear"] == min(limits.max_linear, limits.fleet_linear)


def test_d491_free_mode_needs_live_goal_navigation(core_client, monkeypatch):
    from core_api_web.api.v1 import system

    client, svc = _live_core(core_client)
    monkeypatch.setattr(system, "withhold_hardware_flags", lambda data, _reasons: data)
    svc.capability._data.setdefault("navigation", {})["goal_navigation"] = True
    assert _controls(client)["items"][0]["drive_modes"] == ["lane", "free"]


@pytest.mark.parametrize("model", ["Pinky", "pinky-pro", "p" * 65, 7])
def test_d491_unusable_robot_model_omits_robot_kind_not_a_500(core_client, model):
    client, svc = _live_core(core_client)
    svc.config.setdefault("robot", {})["model"] = model
    (base,) = _controls(client)["items"]
    assert "robot_kind" not in base and "lane" in base["drive_modes"]


def test_d491_nan_odom_does_not_fail_the_state_api(core_client):
    client, svc = core_client()
    svc.state.set_odom_pose(0.5, 0.25, 0.0)
    svc.state.set_odom_pose(float("nan"), 0.0, 0.0)
    response = client.get("/api/v1/robot/state", headers=VIEWER)
    assert response.status_code == 200
    assert response.json()["odom_pose"]["x"] == 0.5
