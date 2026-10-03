"""D-411 B: CORE announces Pinky's controls from adapter provides (or teleop)."""

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
