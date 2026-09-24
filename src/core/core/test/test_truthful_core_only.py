"""US-010: CORE tells the truth when hardware is absent or its state is unknown.

Field evidence (rosy-pinky-e4us, release 005, CORE-only): the API reported a
0% battery, the placeholder name "Rosy 01", five available motion
capabilities and a "source present but silent" safety circuit on a robot whose
hardware runtime was simply off (D-161). Each test below pins one of those.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import core_common.config as config_module

ADMIN = {"Authorization": "Bearer rosy-dev-admin"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}

CONFIG_DIR = Path(__file__).parent.parent / "config"
HARDWARE = {"runtime": {"mode": "hardware", "navigation_backend": "localization"}}
MOTION_IDS = {
    "mobility.move", "mobility.navigate", "mobility.follow", "mobility.lead",
    "perception.localize",
}


# --- 1. battery: no reading is not 0% (D-82 Law 0) ---------------------------

def test_battery_without_a_reading_is_null_not_zero(core_client):
    tc, _svc = core_client()
    body = tc.get("/api/v1/robot/battery", headers=VIEWER).json()
    assert body == {"percent": None, "voltage": None}
    state = tc.get("/api/v1/robot/state", headers=VIEWER).json()
    assert state["battery"] == {"percent": None, "voltage": None}
    assert state["evidence"]["battery"]["evidence"] == "unavailable"


def test_battery_reports_a_real_reading(core_client):
    tc, svc = core_client()
    svc.state.set_battery(64.5, 7.71)
    body = tc.get("/api/v1/robot/battery", headers=VIEWER).json()
    assert body == {"percent": 64.5, "voltage": 7.71}
    evidence = tc.get("/api/v1/robot/state", headers=VIEWER).json()["evidence"]
    assert evidence["battery"]["evidence"] == "fresh"


def test_metrics_and_display_keep_missing_percent_missing(core_client):
    from types import SimpleNamespace

    from core.bridge import display

    tc, svc = core_client()
    metrics = tc.get("/metrics", headers=VIEWER).text
    assert "rosy_battery_percent -1" in metrics
    status = SimpleNamespace(last_wake_reason=None, presence=SimpleNamespace(value="NONE"))
    payload = display.info_payload(svc.state.snapshot(), status, health="ok",
                                   address="-", hold_s=0.0)
    assert payload["battery_percent"] is None
    assert payload["battery_voltage"] is None


# --- 2. identity: the provisioned name, not the config placeholder -----------

def _load(tmp_path, monkeypatch, *, env: dict, overlay: str | None = None):
    local = tmp_path / "rosy.yaml"
    if overlay is not None:
        local.write_text(overlay, encoding="utf-8")
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", local)
    for key in ("ROSY_CONFIG", "ROSY_NAMESPACE", "ROSY_ROBOT_NUMBER",
                "ROSY_DEVICE_NAME", "ROSY_RUNTIME_MODE", "ROSY_NAVIGATION_BACKEND"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # D-193 7: the defaults carry no tokens; the dev viewer token needs the opt-in.
    monkeypatch.delenv("ROSY_DEPLOYMENT", raising=False)
    monkeypatch.setenv("ROSY_DEV_AUTH", "1")
    return config_module.load_config(str(CONFIG_DIR / "rosy_default.yaml"))


def _info(tmp_path, config):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from core_api_web.api.app import create_app
    from core_common.profile import RobotProfile, robot_config_dir
    from core.services import CoreServices

    profile = RobotProfile.load(robot_config_dir("pinky_pro") / "profile.yaml")
    caps = yaml.safe_load((robot_config_dir("pinky_pro") / "capabilities.yaml").read_text(encoding="utf-8"))
    services = CoreServices.build(config, profile, caps, tmp_path / "wp.json")
    return TestClient(create_app(config, services)).get(
        "/api/v1/system/info", headers=VIEWER).json()


PROVISIONED = {
    "ROSY_DEVICE_NAME": "rosy-pinky-e4us",
    "ROSY_ROBOT_NUMBER": "18",
    "ROSY_NAMESPACE": "rosy_18",
    "ROSY_RUNTIME_MODE": "core",
}


def test_provisioned_device_does_not_call_itself_rosy_01(tmp_path, monkeypatch):
    info = _info(tmp_path, _load(tmp_path, monkeypatch, env=PROVISIONED))
    assert info["robot_name"] == "rosy-pinky-e4us"
    assert info["robot_id"] == "rosy_18"
    assert info["robot_number"] == 18


def test_robot_number_alone_derives_the_name(tmp_path, monkeypatch):
    config = _load(tmp_path, monkeypatch, env={"ROSY_ROBOT_NUMBER": "18"})
    assert config["robot"]["name"] == "Rosy 18"


def test_operator_rename_in_overlay_wins_over_provisioned_name(tmp_path, monkeypatch):
    config = _load(tmp_path, monkeypatch, env=PROVISIONED,
                   overlay="robot:\n  name: Rosy 01\n")
    # Even the placeholder text stays when an operator chose it explicitly.
    assert config["robot"]["name"] == "Rosy 01"


def test_unprovisioned_host_keeps_the_default_name(tmp_path, monkeypatch):
    config = _load(tmp_path, monkeypatch, env={})
    assert config["robot"]["name"] == "Rosy 01"


# --- 3. capabilities: advertise only what CORE-only can keep (D-32) ----------

def test_core_only_withholds_motion_capabilities_with_a_reason(core_client):
    from core_common.protocol.schemas import HealthState

    tc, svc = core_client()
    caps = tc.get("/api/v1/system/capabilities", headers=VIEWER).json()
    assert caps["teleop"] is False
    assert caps["slam"] is False
    assert caps["navigation"]["goal_navigation"] is False
    assert caps["navigation"]["return_home"] is False
    assert caps["swarm"] == {"follow": False, "lead": False}
    assert caps["withheld"]["reason"] == "runtime_mode:core"
    assert set(caps["withheld"]["flags"]) == {
        "teleop", "navigation.goal_navigation", "navigation.return_home",
        "swarm.follow", "swarm.lead", "slam",
    }
    # Speed limits and other non-flag fields are untouched.
    assert caps["navigation"]["max_linear_velocity"] == pytest.approx(0.2)
    # The loaded profile itself is not rewritten.
    assert svc.capability.supports("teleop") is True

    svc.state.set_diagnostic("drive", HealthState.OK)
    inventory = tc.get("/api/v1/system/inventory", headers=VIEWER).json()
    assert inventory["device_state"] == "READY"
    rows = {row["id"]: row for row in inventory["descriptors"]}
    assert set(rows) == MOTION_IDS
    for row in rows.values():
        assert row["available"] is False
        assert row["state"] == "blocked"
        assert row["reason"] == "runtime_mode:core"


def test_hardware_runtime_advertises_the_profile(core_client):
    from core_common.protocol.schemas import HealthState

    tc, svc = core_client(config_overrides=HARDWARE)
    caps = tc.get("/api/v1/system/capabilities", headers=VIEWER).json()
    assert caps["teleop"] is True
    assert "withheld" not in caps
    svc.state.set_diagnostic("drive", HealthState.OK)
    rows = tc.get("/api/v1/system/inventory", headers=VIEWER).json()["descriptors"]
    assert all(row["state"] == "available" for row in rows)


def test_core_mode_with_odometry_is_a_bench_and_keeps_its_capabilities(core_client):
    """gz_multi runs CORE in `core` mode against simulated odometry."""
    tc, svc = core_client()
    svc.state.set_pose(0.0, 0.0, 0.0)
    caps = tc.get("/api/v1/system/capabilities", headers=VIEWER).json()
    assert caps["teleop"] is True
    assert caps["swarm"] == {"follow": True, "lead": True}
    assert "withheld" not in caps


# --- 4. evidence: "no source" is not "source went quiet" ---------------------

def test_core_only_channels_are_unavailable_not_disconnected(core_client):
    tc, _svc = core_client()
    evidence = tc.get("/api/v1/robot/state", headers=VIEWER).json()["evidence"]
    for channel in ("pose", "velocity", "battery", "navigation", "safety"):
        assert evidence[channel]["evidence"] == "unavailable", channel


def test_hardware_runtime_still_reports_a_silent_source_as_disconnected(core_client):
    tc, _svc = core_client(config_overrides=HARDWARE)
    evidence = tc.get("/api/v1/robot/state", headers=VIEWER).json()["evidence"]
    for channel in ("pose", "velocity", "battery", "navigation", "safety"):
        assert evidence[channel]["evidence"] == "disconnected", channel


def test_core_only_channel_that_reports_is_judged_normally(core_client):
    tc, svc = core_client()
    svc.state.set_estop(False)
    evidence = tc.get("/api/v1/robot/state", headers=VIEWER).json()["evidence"]
    assert evidence["safety"]["evidence"] in ("fresh", "delayed")
    assert evidence["safety"]["received_at"]


# --- 5. role: the dashboard learns it without probing an admin route --------

@pytest.mark.parametrize("headers, role", [
    (VIEWER, "viewer"),
    ({"Authorization": "Bearer rosy-dev-operator"}, "operator"),
    (ADMIN, "administrator"),
])
def test_system_info_names_the_caller_role(core_client, headers, role):
    tc, _svc = core_client()
    response = tc.get("/api/v1/system/info", headers=headers)
    assert response.status_code == 200
    assert response.json()["caller_role"] == role
