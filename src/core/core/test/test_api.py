"""API 통합 테스트 — 실제 서비스(ROS 무의존) + FastAPI TestClient (P1-9)."""

import importlib
import json
import time

import pytest

fastapi_test = importlib.import_module  # noqa: F841

from pathlib import Path

from core_api_web.api.app import create_app
from core_features.command.manager import Twist
from core_events.events.audit import FileAuditLog
from core_common.profile import RobotProfile
from core.services import CoreServices

import yaml


@pytest.fixture
def client(tmp_path, monkeypatch):
    httpx = pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", tmp_path / "rosy.yaml")
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    config = yaml.safe_load((Path(__file__).parent.parent / "config" / "rosy_default.yaml").read_text(encoding="utf-8"))
    profile = RobotProfile.load(Path(__file__).parent.parent / "config" / "profile.pinky_pro.yaml")
    caps = yaml.safe_load((Path(__file__).parent.parent / "config" / "capabilities.yaml").read_text(encoding="utf-8"))
    services = CoreServices.build(config, profile, caps, tmp_path / "wp.json")
    app = create_app(config, services)
    return TestClient(app), services


ADMIN = {"Authorization": "Bearer rosy-dev-admin"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


def test_policy_stop_uses_existing_admin_release_and_does_not_resume(client):
    from core_features.command.arbitration import Mode
    from core_features.safety.manager import SafetyDecision
    tc, svc = client
    svc.safety.bind_policy(lambda request: SafetyDecision(
        request.command_id, request.source, request.calibration_revision,
        request.now, request.now + .1, 0., 0., 'stop'), 'calibration-1')
    svc.modes.transition(Mode.MANUAL)
    svc.command.teleop(.05, .1)
    assert svc.command.select_output() == Twist()
    assert svc.state.snapshot().safety.estop
    assert tc.post('/api/v1/safety/release', headers=OPERATOR).status_code == 403
    assert tc.post('/api/v1/safety/release', headers=ADMIN).status_code == 200
    assert svc.modes.mode is Mode.IDLE
    assert not svc.state.snapshot().safety.estop
    assert not svc.command.manual_active


def test_admin_can_rename_robot_but_not_rebind_id(client, tmp_path, monkeypatch):
    overlay = tmp_path / "rosy.yaml"
    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", overlay)
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    tc, _svc = client
    renamed = tc.put("/api/v1/system/info", json={"robot_name": "Bay 7"}, headers=ADMIN)
    assert renamed.status_code == 200
    assert renamed.json()["robot_name"] == "Bay 7"
    locked = tc.put("/api/v1/system/info", json={"robot_id": "rosy_07"}, headers=ADMIN)
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "IDENTITY_LOCKED"
    assert tc.put("/api/v1/system/info", json={"robot_id": "NOPE"}, headers=ADMIN).status_code == 400
    assert tc.put("/api/v1/system/info", json={"robot_id": "rosy_08"}, headers=OPERATOR).status_code == 403


def test_tokens_are_admin_only_and_never_echo_secrets(client):
    tc, _svc = client
    assert tc.get("/api/v1/system/tokens", headers=VIEWER).status_code == 403
    listed = tc.get("/api/v1/system/tokens", headers=ADMIN).json()["tokens"]
    blob = json.dumps(listed)
    assert "rosy-dev-admin" not in blob
    assert "rosy-dev-operator" not in blob
    # Nothing in the listing is derived from the secret — no fingerprint, no hint.
    assert all(set(item) == {"id", "role", "label", "created_at", "legacy"} for item in listed)

    created = tc.post(
        "/api/v1/system/tokens",
        json={"token": "rosy-extra-operator-token", "role": "operator", "label": "bay 7 tablet"},
        headers=ADMIN,
    )
    assert created.status_code == 201
    assert "rosy-extra-operator-token" not in json.dumps(created.json())
    assert created.json()["label"] == "bay 7 tablet"
    extra = {"Authorization": "Bearer rosy-extra-operator-token"}
    assert tc.get("/api/v1/system/info", headers=extra).status_code == 200

    duplicate = tc.post(
        "/api/v1/system/tokens",
        json={"token": "rosy-extra-operator-token", "role": "viewer"},
        headers=ADMIN,
    )
    assert duplicate.status_code == 409

    token_id = created.json()["id"]
    assert tc.delete(f"/api/v1/system/tokens/{token_id}", headers=ADMIN).status_code == 204
    assert tc.get("/api/v1/system/info", headers=extra).status_code == 401


def test_a_generated_token_is_returned_once_and_then_only_by_id(client):
    tc, _svc = client
    created = tc.post("/api/v1/system/tokens", json={"role": "viewer"}, headers=ADMIN)
    assert created.status_code == 201
    secret = created.json()["token"]
    assert len(secret) >= 32
    assert tc.get("/api/v1/system/info", headers={"Authorization": f"Bearer {secret}"}).status_code == 200

    listed = tc.get("/api/v1/system/tokens", headers=ADMIN).json()["tokens"]
    assert secret not in json.dumps(listed)
    assert any(item["id"] == created.json()["id"] for item in listed)


def test_an_operator_chosen_token_must_be_long_enough(client):
    tc, _svc = client
    too_short = tc.post("/api/v1/system/tokens",
                        json={"token": "short", "role": "viewer"}, headers=ADMIN)
    assert too_short.status_code == 400
    bad_role = tc.post("/api/v1/system/tokens",
                       json={"token": "x" * 20, "role": "wizard"}, headers=ADMIN)
    assert bad_role.status_code == 400
    assert "role" in bad_role.text


def test_writing_a_token_migrates_the_plaintext_defaults_to_hashes(client, tmp_path):
    tc, _svc = client
    overlay = tmp_path / "rosy.yaml"
    assert tc.post("/api/v1/system/tokens", json={"role": "viewer"}, headers=ADMIN).status_code == 201

    saved = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    stored = saved["auth"]["tokens"]
    raw = overlay.read_text(encoding="utf-8")
    assert "rosy-dev-admin" not in raw
    assert "rosy-dev-viewer" not in raw
    assert all(set(item) == {"id", "role", "sha256", "label", "created_at"} for item in stored)
    assert all(len(item["sha256"]) == 64 for item in stored)
    # The packaged plaintext tokens still authenticate; only their storage changed.
    assert tc.get("/api/v1/system/info", headers=ADMIN).status_code == 200


def test_the_last_administrator_and_the_token_in_use_cannot_be_deleted(client):
    tc, _svc = client
    listed = tc.get("/api/v1/system/tokens", headers=ADMIN).json()["tokens"]
    admins = [item for item in listed if item["role"] == "administrator"]
    assert len(admins) == 1
    assert tc.delete(f"/api/v1/system/tokens/{admins[0]['id']}", headers=ADMIN).status_code == 400

    second = tc.post("/api/v1/system/tokens", json={"role": "administrator"}, headers=ADMIN)
    other = {"Authorization": f"Bearer {second.json()['token']}"}
    # With two administrators the original goes, and then the survivor is pinned.
    assert tc.delete(f"/api/v1/system/tokens/{admins[0]['id']}", headers=other).status_code == 204
    assert tc.delete(f"/api/v1/system/tokens/{second.json()['id']}", headers=other).status_code == 400
    assert tc.delete("/api/v1/system/tokens/nope", headers=other).status_code == 404


def test_system_info_and_capabilities(client):
    tc, svc = client
    r = tc.get("/api/v1/system/info", headers=VIEWER)
    assert r.status_code == 200
    assert r.json()["robot_id"] == "rosy_01"
    assert r.json()["hardware_model"] == "Pinky Pro"
    assert r.json()["runtime_mode"] == "core"
    assert "ros_namespace" in r.json()
    assert "ros_domain_id" in r.json()
    assert "robot_number" in r.json()
    # The default fixture is `core` mode: until odometry proves a base is
    # attached, CAP-001 withholds the hardware flags (D-32, D-161).
    r = tc.get("/api/v1/system/capabilities", headers=VIEWER)
    assert r.json()["swarm"] == {"follow": False, "lead": False}
    svc.state.set_velocity(0.0, 0.0)
    r = tc.get("/api/v1/system/capabilities", headers=VIEWER)
    assert r.json()["swarm"] == {"follow": True, "lead": True}
    assert "withheld" not in r.json()


def test_inventory_is_booting_before_diagnostics_arrive(client):
    tc, svc = client
    inventory = tc.get("/api/v1/system/inventory", headers=VIEWER)
    assert inventory.status_code == 200
    body = inventory.json()
    assert body["device_state"] == "BOOTING"
    by_id = {item["id"]: item for item in body["descriptors"]}
    assert by_id["mobility.move"]["available"] is False
    assert by_id["mobility.move"]["state"] == "blocked"
    assert by_id["mobility.move"]["reason"] == "device_state:BOOTING"
    robot = tc.get("/api/v1/robot/state", headers=VIEWER)
    assert robot.status_code == 200
    assert robot.json()["mode"] == "IDLE"
    assert svc.modes.mode.value == "IDLE"


def test_inventory_leaves_booting_after_a_diagnostic(client):
    from core_common.protocol.schemas import HealthState

    tc, svc = client
    svc.state.set_diagnostic("drive", HealthState.OK)
    svc.state.set_velocity(0.0, 0.0)  # odometry: a base is attached
    body = tc.get("/api/v1/system/inventory", headers=VIEWER).json()
    assert body["device_state"] == "READY"
    by_id = {item["id"]: item for item in body["descriptors"]}
    assert by_id["mobility.move"]["available"] is True
    assert by_id["mobility.move"]["state"] == "available"
    assert by_id["mobility.move"]["reason"] is None
    robot = tc.get("/api/v1/robot/state", headers=VIEWER).json()
    assert robot["mode"] == "IDLE"


def test_robot_state_carries_server_judged_evidence(client):
    tc, svc = client
    body = tc.get("/api/v1/robot/state", headers=VIEWER).json()
    evidence = body["evidence"]
    for channel in ("pose", "velocity", "battery", "navigation", "safety", "docking"):
        record = evidence[channel]
        assert record["evidence"] in ("fresh", "delayed", "disconnected", "unavailable")
        assert isinstance(record["stale_after_s"], (int, float))
        # Default fixture is CORE-only: no channel has a configured source.
        assert record["evidence"] == "unavailable"
        assert record["received_at"] is None
    assert evidence["pose"]["stale_after_s"] == 2.0
    assert evidence["velocity"]["stale_after_s"] == 0.5
    assert evidence["safety"]["stale_after_s"] == 0.2

    svc.state.set_pose(1.0, 2.0, 0.0)
    svc.state.set_velocity(0.1, 0.0)
    fresh = tc.get("/api/v1/robot/state", headers=VIEWER).json()["evidence"]
    assert fresh["pose"]["evidence"] == "fresh"
    assert fresh["velocity"]["evidence"] == "fresh"
    assert fresh["pose"]["received_at"]
    assert fresh["battery"]["evidence"] == "unavailable"


def test_inventory_is_a_mobile_base_without_pick_or_rfid(client):
    tc, _svc = client
    response = tc.get("/api/v1/system/inventory", headers=VIEWER)
    assert response.status_code == 200
    body = response.json()
    assert body["device"]["device_type"] == "mobile_base"
    ids = body["capability_ids"]
    assert "mobility.move" in ids
    assert "mobility.navigate" in ids
    assert "mobility.follow" in ids
    assert "mobility.lead" in ids
    assert "perception.localize" in ids
    assert "mobility.dock" not in ids
    assert "manipulate.pick" not in ids
    assert "scan_rfid" not in ids
    assert "infer" not in ids
    assert "train" not in ids
    blob = json.dumps(body)
    assert "pick" not in blob
    assert "rfid" not in blob


def test_system_runtime_requires_viewer_and_returns_safe_snapshot(client):
    tc, svc = client

    class FakeRuntimeProbe:
        def snapshot(self):
            return {
                "hostname": "rosy-pi",
                "temperature_c": 51.2,
                "unavailable": [],
            }

    svc.runtime_probe = FakeRuntimeProbe()

    assert tc.get("/api/v1/system/runtime").status_code == 401
    response = tc.get("/api/v1/system/runtime", headers=VIEWER)

    assert response.status_code == 200
    assert response.json()["hostname"] == "rosy-pi"
    assert response.json()["temperature_c"] == 51.2
    assert "rosy-dev-admin" not in response.text


def test_auth_roles(client):
    tc, _ = client
    assert tc.get("/api/v1/robot/state").status_code == 401            # UNAUTHORIZED
    assert tc.get("/api/v1/robot/state", headers=VIEWER).status_code == 200
    assert tc.post("/api/v1/teleop", json={}, headers=VIEWER).status_code == 403   # FORBIDDEN
    assert tc.post("/api/v1/teleop", json={}, headers=OPERATOR).status_code in (200, 409)
    assert tc.post("/api/v1/safety/release", headers=OPERATOR).status_code == 403  # release는 Admin


def test_teleop_flow_and_watchdog_zero(client):
    tc, svc = client
    assert tc.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    r = tc.post("/api/v1/teleop", json={"linear": 0.1, "angular": 0.0}, headers=OPERATOR)
    assert r.status_code == 200
    assert svc.command.select_output().linear == pytest.approx(0.1)
    svc.command.clear_manual()
    assert svc.command.select_output().linear == 0.0


def test_navigation_mode_requires_capability_and_clears_stale_twist(client):
    tc, svc = client
    svc.command.set_nav_twist(Twist(0.2, 0.0))
    svc.capability._data["navigation"]["goal_navigation"] = False

    unsupported = tc.post(
        "/api/v1/mode",
        json={"mode": "NAVIGATION"},
        headers=OPERATOR,
    )

    assert unsupported.status_code == 501
    assert svc.modes.mode.value == "IDLE"

    svc.capability._data["navigation"]["goal_navigation"] = True
    accepted = tc.post(
        "/api/v1/mode",
        json={"mode": "NAVIGATION"},
        headers=OPERATOR,
    )

    assert accepted.status_code == 200
    assert svc.command.select_output().linear == 0.0


def test_a_goal_enters_navigation_mode_so_nav_cmd_vel_reaches_the_wheels(client):
    tc, svc = client

    class LocalExecutor:
        def send_goal(self, spec):
            return None

        def cancel_goal(self):
            return None

        def send_initial_pose(self, *a):
            return None

    svc.nav.executor = LocalExecutor()
    assert svc.modes.mode.value == "IDLE"
    svc.command.set_nav_twist(Twist(0.12, 0.0), now=time.monotonic())
    assert svc.command.select_output(now=time.monotonic()).linear == 0.0

    accepted = tc.post(
        "/api/v1/navigation/goal",
        json={"x": 1.0, "y": 0.5, "yaw": 0.0},
        headers=OPERATOR,
    )
    assert accepted.status_code == 200
    assert svc.modes.mode.value == "NAVIGATION"
    assert accepted.json()["mode"] == "NAVIGATION"
    now = time.monotonic()
    svc.command.set_nav_twist(Twist(0.12, 0.0), now=now)
    assert svc.command.select_output(now=now).linear == pytest.approx(0.12)


def test_safety_stop_release_cycle(client):
    tc, svc = client
    assert tc.post("/api/v1/safety/stop", headers=VIEWER).status_code == 200   # 누구나 (SAF-001)
    assert svc.safety.estop is True
    assert svc.command.teleop(0.1, 0.0)[0] is False                            # 차단 확인
    assert tc.post("/api/v1/safety/release", headers=ADMIN).status_code == 200
    assert svc.safety.estop is False
    types = [e.type for e in svc.events.history()]
    assert "safety.estop" in types and "safety.estop_released" in types


def test_admin_can_update_manual_speed_limits(client):
    tc, svc = client
    ceiling = svc.safety.limits.max_linear
    updated = tc.put(
        "/api/v1/safety/limits",
        json={"manual_linear": 0.10, "manual_angular": 0.40},
        headers=ADMIN,
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["limits"]["manual_linear"] == pytest.approx(0.10)
    assert body["limits"]["manual_angular"] == pytest.approx(0.40)
    assert svc.safety.limits.manual_linear == pytest.approx(0.10)
    assert "config.changed" in [event.type for event in svc.events.history()]

    denied = tc.put("/api/v1/safety/limits", json={"manual_linear": 0.05}, headers=OPERATOR)
    assert denied.status_code == 403

    clipped = tc.put("/api/v1/safety/limits", json={"manual_linear": ceiling + 1.0}, headers=ADMIN)
    assert clipped.status_code == 200
    assert clipped.json()["limits"]["manual_linear"] == pytest.approx(ceiling)


def test_safety_state_includes_battery_policy(client):
    tc, _svc = client
    body = tc.get("/api/v1/safety/state", headers=VIEWER).json()
    assert body["fleet_loss_policy"] == "STOP"
    assert body["battery"]["warning_percent"] == pytest.approx(20)
    assert body["battery"]["critical_percent"] == pytest.approx(10)
    assert body["battery"]["deep_percent"] == pytest.approx(5)
    assert body["battery"]["critical_policy"] == "RETURN_HOME"


def test_admin_can_update_battery_and_fleet_policy(client, tmp_path, monkeypatch):
    overlay = tmp_path / "rosy.yaml"
    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", overlay)
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    tc, svc = client
    updated = tc.put(
        "/api/v1/safety/limits",
        json={
            "fleet_loss_policy": "HOLD",
            "battery_warning_percent": 25,
            "battery_critical_percent": 12,
            "battery_deep_percent": 6,
            "battery_critical_policy": "STOP",
        },
        headers=ADMIN,
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["fleet_loss_policy"] == "HOLD"
    assert body["battery"]["warning_percent"] == pytest.approx(25)
    assert body["battery"]["critical_policy"] == "STOP"
    assert svc.safety.fleet_loss_policy == "HOLD"
    assert svc.safety.battery_policy.critical_action == "STOP"
    assert svc.battery._cfg.warning_percent == pytest.approx(25)
    saved = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    assert saved["safety"]["fleet_loss_policy"] == "HOLD"
    assert saved["safety"]["battery_warning_percent"] == pytest.approx(25)


def test_inverted_battery_thresholds_are_rejected(client):
    tc, svc = client
    before = svc.safety.battery_policy.warning_percent
    denied = tc.put(
        "/api/v1/safety/limits",
        json={"battery_warning_percent": 8, "battery_critical_percent": 12, "battery_deep_percent": 5},
        headers=ADMIN,
    )
    assert denied.status_code == 400
    assert svc.safety.battery_policy.warning_percent == before


def test_negative_speed_limits_are_rejected(client):
    tc, svc = client
    before = svc.safety.limits.manual_linear
    denied = tc.put(
        "/api/v1/safety/limits",
        json={"manual_linear": -0.2},
        headers=ADMIN,
    )
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "VALIDATION_ERROR"
    assert svc.safety.limits.manual_linear == before


def test_empty_limits_put_does_not_write_overlay(client, tmp_path, monkeypatch):
    overlay = tmp_path / "rosy.yaml"
    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", overlay)
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    tc, svc = client
    before = svc.safety.limits.manual_linear
    updated = tc.put("/api/v1/safety/limits", json={}, headers=ADMIN)
    assert updated.status_code == 200
    assert svc.safety.limits.manual_linear == before
    assert not overlay.exists()


def test_failed_overlay_write_does_not_apply_limits(client, tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("file", encoding="utf-8")
    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", blocker / "rosy.yaml")
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    tc, svc = client
    before = svc.safety.limits.manual_linear
    updated = tc.put(
        "/api/v1/safety/limits",
        json={"manual_linear": 0.01},
        headers=ADMIN,
    )
    assert updated.status_code == 500
    assert updated.json()["error"]["code"] == "INTERNAL_ERROR"
    assert svc.safety.limits.manual_linear == before


def test_limits_persist_follow_rosy_config_env(client, tmp_path, monkeypatch):
    env_overlay = tmp_path / "from-env.yaml"
    env_overlay.write_text("robot:\n  id: env_robot\n", encoding="utf-8")
    local = tmp_path / "rosy.yaml"
    local.write_text("robot:\n  id: local_robot\n", encoding="utf-8")
    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", local)
    monkeypatch.setenv("ROSY_CONFIG", str(env_overlay))
    tc, _svc = client
    updated = tc.put(
        "/api/v1/safety/limits",
        json={"manual_linear": 0.07, "manual_angular": 0.22},
        headers=ADMIN,
    )
    assert updated.status_code == 200
    env_saved = yaml.safe_load(env_overlay.read_text(encoding="utf-8"))
    local_saved = yaml.safe_load(local.read_text(encoding="utf-8"))
    assert env_saved["robot"]["id"] == "env_robot"
    assert env_saved["safety"]["manual_linear"] == pytest.approx(0.07)
    assert "safety" not in local_saved


def test_admin_speed_limits_persist_to_local_overlay(client, tmp_path, monkeypatch):
    overlay = tmp_path / "rosy.yaml"
    overlay.write_text("robot:\n  id: rosy_01\n", encoding="utf-8")
    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", overlay)
    monkeypatch.delenv("ROSY_CONFIG", raising=False)

    tc, svc = client
    updated = tc.put(
        "/api/v1/safety/limits",
        json={"manual_linear": 0.09, "manual_angular": 0.33},
        headers=ADMIN,
    )
    assert updated.status_code == 200
    saved = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    assert saved["robot"]["id"] == "rosy_01"
    assert saved["safety"]["manual_linear"] == pytest.approx(0.09)
    assert saved["safety"]["manual_angular"] == pytest.approx(0.33)
    assert svc.config["safety"]["manual_linear"] == pytest.approx(0.09)

    from core_common.config import load_config
    reloaded = load_config()
    assert reloaded["safety"]["manual_linear"] == pytest.approx(0.09)


def test_waypoints_crud_and_goal(client):
    tc, svc = client
    wp = {"name": "zone_a", "x": 1.5, "y": 2.5, "yaw": 0.0, "map_id": None, "metadata": {}}
    assert tc.post("/api/v1/waypoints", json=wp, headers=OPERATOR).status_code == 201
    dup = tc.post("/api/v1/waypoints", json=wp, headers=OPERATOR)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "WAYPOINT_EXISTS"

    class LocalExecutor:
        sent = []

        def send_goal(self, spec):
            LocalExecutor.sent.append(spec)

        def cancel_goal(self):
            pass

        def send_initial_pose(self, *a):
            pass

    svc.nav.executor = LocalExecutor()
    r = tc.post("/api/v1/navigation/goal", json={"waypoint": "zone_a"}, headers=OPERATOR)
    assert r.status_code == 200
    assert LocalExecutor.sent[0].x == 1.5
    missing = tc.post("/api/v1/navigation/goal", json={"waypoint": "ghost"}, headers=OPERATOR)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"

    poses = []

    class PoseExecutor(LocalExecutor):
        def send_initial_pose(self, x, y, yaw):
            poses.append((x, y, yaw))

    svc.nav.executor = PoseExecutor()
    pose = tc.post(
        "/api/v1/localization/initialpose",
        json={"x": 0.4, "y": -1.2, "yaw": 1.57},
        headers=OPERATOR,
    )
    assert pose.status_code == 200
    assert poses == [(0.4, -1.2, 1.57)]
    assert any(event.type == "localization.initialpose" for event in svc.events.history())
    assert tc.post(
        "/api/v1/localization/initialpose",
        json={"x": 0.0, "y": 0.0},
        headers=VIEWER,
    ).status_code == 403


def test_disabled_navigation_capabilities_return_501(client):
    tc, svc = client
    svc.capability._data["navigation"]["goal_navigation"] = False
    svc.capability._data["navigation"]["return_home"] = False

    goal = tc.post(
        "/api/v1/navigation/goal",
        json={"x": 1.0, "y": 2.0, "yaw": 0.0},
        headers=OPERATOR,
    )
    home = tc.post("/api/v1/navigation/home", headers=OPERATOR)

    assert goal.status_code == 501
    assert goal.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"
    assert goal.json()["error"]["detail"]["capability"] == "navigation.goal_navigation"
    assert goal.json()["error"]["detail"]["concept_id"] == "mobility.navigate"
    assert home.status_code == 501
    assert home.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"
    assert home.json()["error"]["detail"]["capability"] == "navigation.return_home"
    assert home.json()["error"]["detail"]["concept_id"] == "mobility.navigate"


def test_audit_log_is_admin_only_and_survives_the_ring_buffer(client):
    tc, svc = client
    svc.events.publish("mode.changed", source="api")
    assert tc.get("/api/v1/logs/audit", headers=VIEWER).status_code == 403
    assert tc.get("/api/v1/logs/audit", headers=OPERATOR).status_code == 403
    body = tc.get("/api/v1/logs/audit", headers=ADMIN).json()
    types = [event["type"] for event in body["events"]]
    assert "mode.changed" in types
    restarted = FileAuditLog(svc.audit.path).history()
    assert any(event.type == "mode.changed" for event in restarted)


def test_events_since_seq(client):
    tc, svc = client
    svc.events.publish("nav.completed")
    svc.events.publish("safety.watchdog")
    r = tc.get("/api/v1/events", headers=VIEWER).json()
    assert r["last_seq"] >= 2
    r2 = tc.get("/api/v1/events", params={"since_seq": r["last_seq"] - 1}, headers=VIEWER).json()
    assert len(r2["events"]) == 1


def test_error_shape_err101(client):
    tc, _ = client
    r = tc.post("/api/v1/teleop", json={"linear": 1.0}, headers=VIEWER)
    body = r.json()
    assert set(body.keys()) == {"error"}
    assert {"code", "message", "detail"} <= set(body["error"].keys())   # ERR-101


# --- Docking API (DNC-001~003) -------------------------------------------------


@pytest.fixture
def docking_client(tmp_path, monkeypatch):
    """docking.supported=true 로 켜진 로봇. 기본 capabilities 는 false 다."""
    httpx = pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", tmp_path / "rosy.yaml")
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    config = yaml.safe_load((Path(__file__).parent.parent / "config" / "rosy_default.yaml").read_text(encoding="utf-8"))
    profile = RobotProfile.load(Path(__file__).parent.parent / "config" / "profile.pinky_pro.yaml")
    caps = yaml.safe_load((Path(__file__).parent.parent / "config" / "capabilities.yaml").read_text(encoding="utf-8"))
    caps["docking"] = {"supported": True}
    services = CoreServices.build(config, profile, caps, tmp_path / "wp.json")
    app = create_app(config, services)
    return TestClient(app), services


def _register_dock(services, dock_id="dock_1", map_id=None):
    from core_features.docking.database import DockInstance, DockType
    services.docking._db.add_type(
        DockType(name="rosy_v1", detector="simulated", staging_offset_m=0.7))
    return services.docking._db.add(DockInstance(
        id=dock_id, type="rosy_v1", x=2.5, y=1.8, yaw=0.0,
        map_id=map_id, agent_url="http://10.0.0.50"))


class TestDockingStubContract:
    """DNC-003 — 이 계약이 회귀하면 안 된다. 기능을 넣으면서 스텁을 깨는 것이
    가장 흔한 사고다."""

    def test_dock_returns_501_when_unsupported(self, client):
        tc, _ = client
        r = tc.post("/api/v1/docking/dock", json={}, headers=OPERATOR)
        assert r.status_code == 501
        assert r.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"

    def test_undock_returns_501_when_unsupported(self, client):
        tc, _ = client
        r = tc.post("/api/v1/docking/undock", headers=OPERATOR)
        assert r.status_code == 501
        assert r.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"

    def test_capabilities_still_report_docking_false(self, client):
        tc, _ = client
        r = tc.get("/api/v1/system/capabilities", headers=VIEWER)
        assert r.json()["docking"]["supported"] is False


class TestDockingStatus:
    def test_status_is_readable_by_a_viewer(self, docking_client):
        tc, _ = docking_client
        r = tc.get("/api/v1/docking/status", headers=VIEWER)
        assert r.status_code == 200
        assert r.json()["state"] == "UNDOCKED"

    def test_status_is_readable_even_when_unsupported(self, client):
        """상태 조회까지 501 로 막으면 대시보드가 "도킹 없음"을 표시할 수 없다."""
        tc, _ = client
        r = tc.get("/api/v1/docking/status", headers=VIEWER)
        assert r.status_code == 200


class TestDockCrud:
    def test_an_operator_can_register_and_list_a_dock(self, docking_client):
        tc, services = docking_client
        r = tc.post("/api/v1/docking/types", headers=ADMIN, json={
            "name": "rosy_v1", "detector": "simulated", "staging_offset_m": 0.7})
        assert r.status_code == 200

        r = tc.post("/api/v1/docking/docks", headers=ADMIN, json={
            "id": "dock_1", "type": "rosy_v1", "x": 2.5, "y": 1.8, "yaw": 0.0,
            "agent_url": "http://10.0.0.50"})
        assert r.status_code == 200

        r = tc.get("/api/v1/docking/docks", headers=VIEWER)
        assert [d["id"] for d in r.json()["docks"]] == ["dock_1"]

    def test_a_dock_of_an_unknown_type_is_refused(self, docking_client):
        tc, _ = docking_client
        r = tc.post("/api/v1/docking/docks", headers=ADMIN, json={
            "id": "dock_1", "type": "ghost", "x": 0.0, "y": 0.0, "yaw": 0.0})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "UNKNOWN_DOCK_TYPE"

    def test_a_duplicate_dock_is_refused(self, docking_client):
        tc, services = docking_client
        _register_dock(services)
        r = tc.post("/api/v1/docking/docks", headers=ADMIN, json={
            "id": "dock_1", "type": "rosy_v1", "x": 0.0, "y": 0.0, "yaw": 0.0})
        assert r.json()["error"]["code"] == "DOCK_EXISTS"

    def test_an_unknown_dock_is_404(self, docking_client):
        tc, _ = docking_client
        r = tc.delete("/api/v1/docking/docks/nope", headers=ADMIN)
        assert r.status_code == 404

    def test_a_viewer_cannot_register_a_dock(self, docking_client):
        tc, _ = docking_client
        r = tc.post("/api/v1/docking/docks", headers=VIEWER, json={
            "id": "dock_1", "type": "rosy_v1", "x": 0.0, "y": 0.0, "yaw": 0.0})
        assert r.status_code == 403

    def test_teaching_records_the_current_pose(self, docking_client):
        tc, services = docking_client
        _register_dock(services)
        services.state.set_pose(7.0, 3.0, 1.5)
        r = tc.post("/api/v1/docking/docks/dock_1/teach", headers=OPERATOR)
        assert r.status_code == 200
        assert r.json()["x"] == pytest.approx(7.0)
        assert services.docking._db.get("dock_1").y == pytest.approx(3.0)

    def test_teaching_an_unknown_dock_is_404(self, docking_client):
        tc, _ = docking_client
        r = tc.post("/api/v1/docking/docks/nope/teach", headers=OPERATOR)
        assert r.status_code == 404


class TestDockingCommands:
    def test_dock_accepts_an_id(self, docking_client):
        tc, services = docking_client
        _register_dock(services)
        r = tc.post("/api/v1/docking/dock", json={"dock": "dock_1"}, headers=OPERATOR)
        assert r.status_code == 200
        assert r.json()["state"] == "DOCKING"

    def test_dock_without_an_id_uses_the_single_dock(self, docking_client):
        tc, services = docking_client
        _register_dock(services)
        r = tc.post("/api/v1/docking/dock", json={}, headers=OPERATOR)
        assert r.status_code == 200

    def test_an_unknown_dock_id_is_404(self, docking_client):
        tc, services = docking_client
        _register_dock(services)
        r = tc.post("/api/v1/docking/dock", json={"dock": "nope"}, headers=OPERATOR)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"

    def test_a_dock_on_another_map_is_refused(self, docking_client):
        tc, services = docking_client
        _register_dock(services, map_id="warehouse_b")
        services.state.set_map_id("warehouse_a")
        r = tc.post("/api/v1/docking/dock", json={"dock": "dock_1"}, headers=OPERATOR)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "MAP_MISMATCH"

    def test_docking_under_estop_is_refused(self, docking_client):
        tc, services = docking_client
        _register_dock(services)
        services.safety.trigger_estop("test")
        r = tc.post("/api/v1/docking/dock", json={"dock": "dock_1"}, headers=OPERATOR)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "EMERGENCY_ACTIVE"

    def test_a_viewer_cannot_command_docking(self, docking_client):
        tc, services = docking_client
        _register_dock(services)
        r = tc.post("/api/v1/docking/dock", json={"dock": "dock_1"}, headers=VIEWER)
        assert r.status_code == 403

    def test_undocking_when_not_docked_is_refused(self, docking_client):
        tc, services = docking_client
        _register_dock(services)
        r = tc.post("/api/v1/docking/undock", headers=OPERATOR)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "NOT_DOCKED"

    def test_cancel_returns_to_undocked(self, docking_client):
        tc, services = docking_client
        _register_dock(services)
        tc.post("/api/v1/docking/dock", json={"dock": "dock_1"}, headers=OPERATOR)
        r = tc.post("/api/v1/docking/cancel", headers=OPERATOR)
        assert r.status_code == 200
        assert r.json()["state"] == "UNDOCKED"


class TestDockingSnapshot:
    def test_the_state_snapshot_carries_docking(self, docking_client):
        tc, _ = docking_client
        r = tc.get("/api/v1/robot/state", headers=VIEWER)
        assert r.json()["docking"]["state"] == "UNDOCKED"

    def test_existing_snapshot_fields_are_untouched(self, docking_client):
        tc, _ = docking_client
        body = r = tc.get("/api/v1/robot/state", headers=VIEWER).json()
        for key in ("robot_id", "mode", "navigation", "pose", "velocity",
                    "battery", "safety", "power"):
            assert key in body
