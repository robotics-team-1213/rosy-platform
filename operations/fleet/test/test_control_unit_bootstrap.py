"""The real Fleet app and CLI own optional control-unit startup and shutdown."""

from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from test_control_unit_runtime import config_file


def test_control_unit_cli_option_is_explicit_and_optional():
    from fleet.cli import parse_args
    args = parse_args(["console", "--robots", "robots.yaml", "--control-unit-config", "unit.yaml"])
    assert args.control_unit_config == Path("unit.yaml")
    assert parse_args(["console", "--robots", "robots.yaml"]).control_unit_config is None


def test_real_app_builds_control_unit_and_closes_its_transport(tmp_path):
    console = FleetConsole([RobotEndpoint("a1", "http://robot.invalid", "device-token")], [FakeRobot("a1")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.db"), robot_ids=console.robot_ids)
    users = {sha256(token.encode()).hexdigest(): {"principal_id": identity, "role": role}
             for token, identity, role in [("human-token", "operator-a1", "operator"),
                                           ("parent-token", "control-unit:A", "service")]}
    app = create_app(console, task_service=tasks, site_users=users, start_task_dispatcher=False,
                     control_unit_config=config_file(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/fleet/control-unit", headers={"Authorization": "Bearer human-token"})
        assert response.status_code == 200
        assert response.json()["unit_id"] == "A1"
        assert "parent.invalid" not in response.text and "parent-service-token" not in response.text
        transport = app.state.control_unit.peer.http
        assert not transport.is_closed
    assert transport.is_closed


def test_control_unit_refuses_start_without_a_durable_task_journal(tmp_path):
    console = FleetConsole([], [])
    with pytest.raises(ValueError, match="JOURNAL"):
        create_app(console, control_unit_config=config_file(tmp_path))


def test_cli_starts_an_independent_aggregate_without_direct_robots(tmp_path, monkeypatch):
    import asyncio
    import yaml
    from fleet.cli import parse_args, run_console
    robots, users, config = tmp_path / "robots.yaml", tmp_path / "users.yaml", tmp_path / "unit.yaml"
    robots.write_text("robots: []\n", encoding="utf-8")
    users.write_text(yaml.safe_dump({"users": [{"principal_id": "operator-r", "role": "operator",
        "token_sha256": sha256(b"human-token").hexdigest()}]}), encoding="utf-8")
    config.write_text(yaml.safe_dump({"unit_id": "R", "manifest": {"revision": "v1", "units": [{"id": "R"}]},
                                     "peers": {}}), encoding="utf-8")
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    run_console(parse_args(["console", "--robots", str(robots), "--users-file", str(users),
                            "--tasks-db", str(tmp_path / "fleet.db"), "--control-unit-config", str(config)]))
    assert captured["app"].state.control_unit.unit.unit_id == "R"
    assert captured["app"].state.task_service.robot_ids == frozenset()
    asyncio.run(captured["app"].state.control_unit_http.aclose())
