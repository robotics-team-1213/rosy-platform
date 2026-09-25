"""D-121: Cyclone is applied before rclpy.init. Web does not set RMW."""

from pathlib import Path

import pytest
import yaml

from core_common.rmw import REQUIRED_RMW, apply_cyclone_rmw, cyclone_overlay_patch

ROOT = Path(__file__).resolve().parents[1]


def test_cyclone_overlay_patch_is_dds_rmw_only():
    assert cyclone_overlay_patch() == {"dds": {"rmw": REQUIRED_RMW}}


def test_empty_rmw_is_filled_with_cyclone():
    env = {}
    assert apply_cyclone_rmw(env) == REQUIRED_RMW
    assert env["RMW_IMPLEMENTATION"] == "rmw_cyclonedds_cpp"


def test_cyclone_rmw_is_left_alone():
    env = {"RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"}
    assert apply_cyclone_rmw(env) == "rmw_cyclonedds_cpp"
    assert env["RMW_IMPLEMENTATION"] == "rmw_cyclonedds_cpp"


def test_foreign_rmw_is_corrected_to_cyclone_for_the_next_init():
    """D-122: FastDDS env 로 불려도 이 프로세스 init 은 Cyclone 이다."""
    env = {"RMW_IMPLEMENTATION": "rmw_fastrtps_cpp"}
    assert apply_cyclone_rmw(env) == REQUIRED_RMW
    assert env["RMW_IMPLEMENTATION"] == "rmw_cyclonedds_cpp"


def test_core_does_not_reboot_the_host_to_apply_rmw():
    main = (ROOT / "core" / "main.py").read_text(encoding="utf-8")
    rmw = (ROOT.parents[1] / "contracts" / "core_common" / "core_common" / "rmw.py").read_text(encoding="utf-8")
    assert "system.reboot" not in main
    assert "system.reboot" not in rmw
    assert "reboot" not in rmw


def test_core_main_applies_cyclone_before_rclpy_init():
    text = (ROOT / "core" / "main.py").read_text(encoding="utf-8")
    apply_at = text.find("apply_cyclone_rmw")
    init_at = text.find("rclpy.init")
    assert apply_at != -1
    assert init_at != -1
    assert apply_at < init_at


def test_no_api_changes_rmw():
    api = ROOT / "core" / "api"
    for path in api.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "apply_cyclone_rmw" not in text, path
        assert "/rmw" not in text, path


@pytest.fixture
def rmw_client(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from core_api_web.api.app import create_app
    from core_common.profile import RobotProfile, robot_config_dir
    from core.services import CoreServices
    import yaml

    overlay = tmp_path / "rosy.yaml"
    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", overlay)
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    config_dir = ROOT / "config"
    config = yaml.safe_load((config_dir / "rosy_default.yaml").read_text(encoding="utf-8"))
    # D-193 7: the dev tokens left the defaults; tests opt in like ROSY_DEV_AUTH=1.
    config.update(yaml.safe_load((config_dir / "rosy_dev_auth.yaml").read_text(encoding="utf-8")))
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    caps = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    services = CoreServices.build(config, profile, caps, tmp_path / "wp.json")
    return TestClient(create_app(config, services)), overlay


ADMIN = {"Authorization": "Bearer rosy-dev-admin"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


def test_cyclone_post_without_confirm_does_not_write_overlay(rmw_client):
    tc, overlay = rmw_client
    response = tc.post("/api/v1/system/dds/cyclone", json={}, headers=ADMIN)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert not overlay.exists()


def test_cyclone_post_is_admin_only(rmw_client):
    tc, overlay = rmw_client
    denied = tc.post(
        "/api/v1/system/dds/cyclone", json={"confirmed": True}, headers=VIEWER
    )
    assert denied.status_code == 403
    assert not overlay.exists()


def test_cyclone_post_persists_overlay_and_asks_host_to_reboot(rmw_client):
    tc, overlay = rmw_client
    response = tc.post(
        "/api/v1/system/dds/cyclone", json={"confirmed": True}, headers=ADMIN
    )
    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] is True
    assert body["rmw"] == "rmw_cyclonedds_cpp"
    assert body["reboot"]["available"] is False
    saved = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    assert saved["dds"]["rmw"] == "rmw_cyclonedds_cpp"
