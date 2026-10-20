"""D-24 amendment (2026-10-04): which REST calls are a command, over the real app.

An accepted (2xx) command call wakes a sleeping robot; a refused one, a read and
a WS subscription do not. The PowerManager side is tested in
`middleware/core/services/test/test_power_wake_inputs.py`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from core_api_web.api.app import create_app
from core_api_web.api.command_activity import COMMAND_ROUTES, command_source
from core_common.profile import RobotProfile, robot_config_dir
from core_common.protocol.schemas import PowerMode
from core.services import CoreServices

CONFIG_DIR = Path(__file__).resolve().parents[4] / "contracts" / "foundation" / "config"


COMMANDS = [
    ("POST", "/api/v1/teleop", "teleop"),
    ("POST", "/api/v1/mode", "mode"),
    ("POST", "/api/v1/navigation/goal", "navigation"),
    ("POST", "/api/v1/navigation/home", "navigation"),
    ("POST", "/api/v1/navigation/cancel", "navigation"),
    ("POST", "/api/v1/motion/rotate_to", "navigation"),
    ("POST", "/api/v1/localization/mission", "mission"),
    ("POST", "/api/v1/docking/dock", "docking"),
    ("POST", "/api/v1/docking/station-dock", "docking"),
    ("POST", "/api/v1/docking/station-undock", "docking"),
    ("POST", "/api/v1/docking/station-stop", "docking"),
    ("PUT", "/api/v1/line-follow/mode", "line_follow"),
    ("POST", "/api/v1/swarm/follow", "fleet_task"),
    ("POST", "/api/v1/do", "intent"),
]

NOT_COMMANDS = [
    ("GET", "/api/v1/robot/state"),
    ("GET", "/api/v1/power"),
    ("GET", "/api/v1/teleop"),
    ("POST", "/api/v1/power/mode"),      # a sleep request must never count as activity
    ("POST", "/api/v1/power/wake"),      # handles its own wake (reason api)
    ("POST", "/api/v1/auth/pair"),
    ("POST", "/api/v1/waypoints"),
    ("PUT", "/api/v1/system/info"),
    ("GET", "/ws/state"),
    ("GET", "/api/v1/navigation/goal"),
]


@pytest.mark.parametrize("method,path,source", COMMANDS)
def test_command_routes(method, path, source):
    assert command_source(method, path) == source


@pytest.mark.parametrize("method,path", NOT_COMMANDS)
def test_non_command_routes(method, path):
    assert command_source(method, path) is None


def test_every_command_route_exists_in_the_app(client):
    api, _ = client
    import re
    routes = {(m.upper(), path) for path, ops in api.app.openapi()["paths"].items() for m in ops}
    for method, pattern, _source in COMMAND_ROUTES:
        assert any(m == method and re.fullmatch(pattern, p) for m, p in routes), pattern


@pytest.fixture
def client():
    config = yaml.safe_load((CONFIG_DIR / "rosy_default.yaml").read_text(encoding="utf-8"))
    dev_auth = yaml.safe_load((CONFIG_DIR / "rosy_dev_auth.yaml").read_text(encoding="utf-8"))
    config["auth"] = {**config["auth"], **dev_auth["auth"]}
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    caps = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    svc = CoreServices.build(config, profile, caps, Path(tempfile.mkdtemp()) / "waypoints.json")
    return TestClient(create_app(config, svc)), svc


OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


def test_accepted_rest_command_wakes(client):
    api, svc = client
    svc.power.request_mode(PowerMode.STANDBY, source="test")
    assert api.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    assert svc.power.mode == PowerMode.ACTIVE
    assert svc.power.last_wake_reason == "command"


def test_refused_command_does_not_wake(client):
    api, svc = client
    svc.power.request_mode(PowerMode.STANDBY, source="test")
    assert api.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=VIEWER).status_code == 403
    assert svc.power.mode == PowerMode.STANDBY


def test_reads_do_not_wake(client):
    api, svc = client
    svc.power.request_mode(PowerMode.STANDBY, source="test")
    for path in ("/api/v1/robot/state", "/api/v1/power"):
        assert api.get(path, headers=VIEWER).status_code == 200
    with api.websocket_connect("/ws/state") as ws:
        ws.send_json({"type": "auth", "token": "rosy-dev-viewer"})
        ws.receive_json()
    assert svc.power.mode == PowerMode.STANDBY


def test_operator_sleep_request_is_not_undone_by_its_own_answer(client):
    api, svc = client
    body = api.post("/api/v1/power/mode", json={"mode": "STANDBY"}, headers=OPERATOR).json()
    assert body["mode"] == "STANDBY"
    assert svc.power.mode == PowerMode.STANDBY
