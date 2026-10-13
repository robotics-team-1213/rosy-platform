"""Stopped-only perception configuration and transactional camera restart."""
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

from host_lane_perception import LanePerceptionConfig

sys.path.append(str(Path(__file__).resolve().parents[1] / "middleware/perception"))


def idle():
    return dict(schema=2, written_at=datetime.now(timezone.utc).isoformat(),
                robot_mode="IDLE", nav_state="IDLE", line_follow_mode="OFF",
                line_follow_state="OFF", docking_state=None, swarm_active=False,
                swarm_role=None, estop=False, activity_kind=None, calibration_active=False,
                velocity_linear=0.0, velocity_angular=0.0)


@pytest.fixture
def config(tmp_path):
    status = tmp_path / "status.json"
    status.write_text(json.dumps(idle()))
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("/**/line_observer_node:\n  ros__parameters:\n    camera_lane_mode: keep\n    camera_height_m_override: 0.059\n")
    cfg = LanePerceptionConfig(overlay=overlay, status_inputs=status,
                               restart=lambda: None, model_check=lambda: "signed-revision")
    return cfg


@pytest.mark.parametrize("change", [dict(velocity_linear=0.1), dict(velocity_linear=None),
    dict(line_follow_mode="CAMERA_LINE"), dict(calibration_active=True),
    dict(swarm_active=True), dict(activity_kind="MISSION"), dict(nav_state="NAVIGATING"),
    dict(written_at="2020-01-01T00:00:00+00:00")])
def test_busy_or_unknown_status_preserves_config(config, change):
    before = config.overlay.read_bytes()
    config.status_inputs.write_text(json.dumps({**idle(), **change}))
    with pytest.raises(ValueError):
        config.set("learned")
    assert config.overlay.read_bytes() == before


def test_selection_preserves_geometry(config):
    result = config.set("learned")
    assert result["paint_source"] == "learned"
    assert result["applied"] is True
    assert "camera_height_m_override: 0.059" in config.overlay.read_text()


def test_learned_selection_writes_compensated_reuse(config):
    # D-585 2: every_n 2 without motion compensation reused 0 learned masks on device.
    import yaml
    config.set("learned")
    params = yaml.safe_load(config.overlay.read_text())["/**/line_observer_node"]["ros__parameters"]
    assert params["learned_paint_every_n"] == 4
    assert params["learned_paint_motion_compensation"] is True


def test_missing_model_refused(config):
    config.model_check = lambda: (_ for _ in ()).throw(ValueError("missing model"))
    before = config.overlay.read_bytes()
    with pytest.raises(ValueError):
        config.set("learned")
    assert config.overlay.read_bytes() == before


def test_restart_failure_restores_prior_overlay(config):
    before = config.overlay.read_bytes()
    config.restart = lambda: (_ for _ in ()).throw(RuntimeError("restart failed"))
    with pytest.raises(RuntimeError):
        config.set("denoise")
    assert config.overlay.read_bytes() == before


def test_native_lane_agent_refuses_other_host_actions():
    from host_agent import HostAgent
    from host_agent_server import SubprocessCommands
    called = []
    agent = HostAgent(SubprocessCommands(runner=lambda argv: called.append(argv)),
                      allowed_profiles=(), allowed_units=(),
                      allowed_commands=("lane_perception.status", "lane_perception.set"))
    request = dict(schema_version=1, request_id="req1", command="system.reboot",
                   actor={"role": "administrator"}, confirmed=True, params={})
    assert agent.handle(request)["code"] == "HOST_AGENT_COMMAND_UNKNOWN"
    assert not called


def test_native_payload_installs_lane_agent_and_starts_with_runtime():
    root = Path(__file__).resolve().parents[1]
    native = root / "deploy/robot/pinky_pro/native"
    install = (native / "install-native-runtime.sh").read_text()
    assert "host_agent.py host_agent_server.py host_lane_perception.py" in install
    unit = (native / "rosy-host-agent.service").read_text()
    assert "PrivateDevices=true" in unit and "User=root" in unit
    assert "ProtectSystem=true" in unit and "RestrictAddressFamilies=AF_UNIX" in unit
    assert "rosy-host-agent.service" in (native / "rosy-runtime.target").read_text()
