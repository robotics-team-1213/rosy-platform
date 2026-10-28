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
from test_control_unit_runtime import config_file, control_unit_ca


def test_control_unit_cli_option_is_explicit_and_optional(monkeypatch):
    monkeypatch.delenv("ROSY_CONTROL_UNIT_CONFIG", raising=False)
    from fleet.cli import parse_args
    args = parse_args(["console", "--robots", "robots.yaml", "--control-unit-config", "unit.yaml"])
    assert args.control_unit_config == Path("unit.yaml")
    assert parse_args(["console", "--robots", "robots.yaml"]).control_unit_config is None


@pytest.mark.parametrize("custom_ca", [False, True])
def test_real_app_builds_control_unit_and_closes_its_transport(tmp_path, monkeypatch, control_unit_ca, custom_ca):
    import httpx
    import ssl
    client_type, options = httpx.AsyncClient, []
    def capture_client(*args, **kwargs):
        client = client_type(*args, **kwargs)
        options.append((client, kwargs))
        return client
    monkeypatch.setattr("fleet.server.control_unit_runtime.httpx.AsyncClient", capture_client)
    console = FleetConsole([RobotEndpoint("a1", "http://robot.invalid", "device-token")], [FakeRobot("a1")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.db"), robot_ids=console.robot_ids)
    users = {sha256(token.encode()).hexdigest(): {"principal_id": identity, "role": role}
             for token, identity, role in [("human-token", "operator-a1", "operator"),
                                           ("parent-token", "control-unit:A", "service")]}
    app = create_app(console, task_service=tasks, site_users=users, start_task_dispatcher=False,
                     control_unit_config=config_file(tmp_path, **({"tls_ca_file": control_unit_ca.name}
                                                                 if custom_ca else {})))
    with TestClient(app) as client:
        response = client.get("/api/fleet/control-unit", headers={"Authorization": "Bearer human-token"})
        assert response.status_code == 200
        assert response.json()["unit_id"] == "A1"
        assert "parent.invalid" not in response.text and "parent-service-token" not in response.text
        transport = app.state.control_unit.peer.http
        assert not transport.is_closed
    assert transport.is_closed
    peer_options = next(option for client, option in options if client is transport)
    assert peer_options["trust_env"] is False and peer_options["follow_redirects"] is False
    if custom_ca:
        assert isinstance(peer_options["verify"], ssl.SSLContext)
        assert peer_options["verify"].check_hostname
        assert peer_options["verify"].verify_mode == ssl.CERT_REQUIRED
    else:
        assert peer_options["verify"] is True


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


def test_cli_control_unit_environment_is_optional_and_explicit_flag_wins(monkeypatch):
    from fleet.cli import parse_args
    monkeypatch.setenv("ROSY_CONTROL_UNIT_CONFIG", "mounted-control-unit.yaml")
    assert parse_args(["console"]).control_unit_config == Path("mounted-control-unit.yaml")
    assert parse_args(["console", "--control-unit-config", "explicit.yaml"]).control_unit_config == Path("explicit.yaml")
    monkeypatch.setenv("ROSY_CONTROL_UNIT_CONFIG", "")
    assert parse_args(["console"]).control_unit_config is None
