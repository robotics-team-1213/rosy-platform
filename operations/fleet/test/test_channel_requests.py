"""Named Discord intake must never create executable work."""
import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from fleet.server.channel_requests import ChannelConfig, ChannelRequests, install_channel_routes
from fleet.server.site_auth import SitePrincipal


KEY = "test-transport-key-" * 3
GUILD, CHANNEL, USER, BOT, MESSAGE = (str(100000000000000000 + i) for i in range(5))


def envelope(**changes):
    return dict(guild_id=GUILD, channel_id=CHANNEL, author_id=USER, message_id=MESSAGE,
                content=f"<@{BOT}> inspect robot", mentions=[BOT], author_bot=False,
                webhook_id=None, **changes)


def fixture(tmp_path, max_rows=1000):
    accounts = {"op": "operator", "other": "operator", "viewer": "viewer"}
    config = ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT,
                           transport_key=KEY, users={USER: "op"})
    journal = ChannelRequests(tmp_path / "tasks.sqlite", config, accounts, max_rows=max_rows)
    app = FastAPI()
    install_channel_routes(app, journal, require_operator=lambda: SitePrincipal("op", "operator"),
                           read_guard=[], clock=lambda: 1000)
    return TestClient(app), journal, accounts


def post(client, body, timestamp="1000", key=KEY):
    raw = json.dumps(body, separators=(",", ":")).encode()
    signature = hmac.new(key.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return client.post("/api/fleet/channel-requests/discord", content=raw,
                       headers={"X-ROSY-Timestamp": timestamp, "X-ROSY-Signature": signature})


def test_durable_dedup_owner_read_and_edit_rejection(tmp_path):
    client, journal, accounts = fixture(tmp_path)
    first = post(client, envelope())
    assert first.status_code == 200
    assert first.json()["status"] == "REQUESTED"
    assert post(client, envelope()).json() == first.json()
    restarted = ChannelRequests(journal.path, journal.config, accounts)
    assert restarted.read("op")[0] == first.json()
    assert restarted.read("other") == []
    body = envelope()
    body["content"] += " edited"
    assert post(client, body).status_code == 409
    assert client.get("/api/fleet/channel-requests").json()["rows"] == [first.json()]
    import sqlite3
    with sqlite3.connect(journal.path) as conn:
        assert set(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()) == {
            ("fleet_channel_requests",),("fleet_channel_withdrawals",)}
        assert conn.execute('SELECT reason FROM fleet_channel_withdrawals').fetchall()==[('MESSAGE_CHANGED',)]
    with pytest.raises(HTTPException):
        restarted.current_receipt(first.json())


@pytest.mark.parametrize("changes", [
    {"guild_id": USER}, {"channel_id": USER}, {"guild_id": None}, {"author_bot": True},
    {"webhook_id": MESSAGE}, {"mentions": []}, {"author_id": MESSAGE},
    {"principal_id": "op"}, {"content": ""}, {"content": "x" * 2001},
])
def test_forbidden_transport_input(tmp_path, changes):
    client, journal, _ = fixture(tmp_path)
    body = envelope()
    body.update(changes)
    assert post(client, body).status_code in (403, 422)
    assert journal.read("op") == []


def test_transport_auth_freshness_revocation_and_capacity(tmp_path):
    client, journal, accounts = fixture(tmp_path, max_rows=1)
    assert post(client, envelope(), key="operator-token").status_code == 401
    assert post(client, envelope(), timestamp="900").status_code == 401
    assert client.post("/api/fleet/channel-requests/discord", json=envelope(),
                       headers={"Authorization": "Bearer operator-token"}).status_code == 401
    assert post(client, envelope()).status_code == 200
    body = envelope()
    body["message_id"] = USER
    assert post(client, body).status_code == 503
    accounts["op"] = "viewer"
    assert post(client, envelope()).status_code == 403
    assert client.get("/api/fleet/channel-requests").status_code == 403
    accounts["op"] = "operator"
    for identity in ("site-console", "development-operator"):
        accounts[identity] = "operator"
        with pytest.raises(Exception) as rejected:
            journal.read(identity)
        assert rejected.value.status_code == 403


def test_config_rejects_unknown_fields_and_short_key():
    with pytest.raises(ValueError):
        ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT, transport_key="short", users={USER: "op"})


def test_discord_projection_and_signature_matches_fleet(tmp_path):
    from rosy_discord.intake import project_message, signed_request
    client, _, _ = fixture(tmp_path)
    message = {"guild_id": GUILD, "channel_id": CHANNEL, "id": MESSAGE,
               "author": {"id": USER}, "content": f"<@{BOT}> inspect robot", "mentions": [{"id": BOT}]}
    projected = project_message(message, guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT)
    body, headers = signed_request(projected, key=KEY, now=1000)
    assert client.post("/api/fleet/channel-requests/discord", content=body, headers=headers).status_code == 200
    for changes in ({"guild_id": None}, {"author": {"id": USER, "bot": True}},
                    {"mentions": []}, {"webhook_id": MESSAGE}):
        assert project_message({**message, **changes}, guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT) is None


def test_create_app_wiring_requires_accounts_and_isolated_key(tmp_path):
    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.swarm.robots import RobotEndpoint
    console = FleetConsole([RobotEndpoint("r1", "http://127.0.0.1:8080", "robot-token")], [FakeRobot("r1")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite"), robot_ids=("r1",))
    config = ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT, transport_key=KEY, users={USER: "op"})
    users = {hashlib.sha256(b"operator-secret").hexdigest(): {"principal_id": "op", "role": "operator"}}
    with pytest.raises(ValueError):
        create_app(console, task_service=tasks, channel_config=config)
    with pytest.raises(ValueError):
        create_app(console, task_service=tasks, channel_config=config, console_token=KEY, site_users=users)
    app = create_app(console, task_service=tasks, channel_config=config, site_users=users,
                     start_task_dispatcher=False)
    client = TestClient(app)
    assert client.get("/api/fleet/channel-requests").status_code == 401
    response = client.get("/api/fleet/channel-requests", headers={"Authorization": "Bearer operator-secret"})
    assert response.json() == {"rows": []}


def test_transport_rejects_oversize_and_malformed_signature(tmp_path):
    client, _, _ = fixture(tmp_path)
    assert client.post("/api/fleet/channel-requests/discord", content=b"x" * 8193).status_code == 413
    response = client.post("/api/fleet/channel-requests/discord", json=envelope(),
                           headers={"X-ROSY-Timestamp": "1000", "X-ROSY-Signature": "wrong"})
    assert response.status_code == 401


@pytest.mark.parametrize("service_name", ["goal_evidence_service", "cell_goal_evidence_service"])
def test_evidence_producer_credential_cannot_be_transport_key(tmp_path, service_name):
    from types import SimpleNamespace
    from fleet.server.channel_requests import install_channel_feature
    from test_mission_api import _client
    client, tasks, _ = _client(tmp_path, goal_evidence_enabled=True)
    producer = SimpleNamespace(token=KEY)
    setattr(client.app.state, service_name, SimpleNamespace(registry=SimpleNamespace(producers=(producer,))))
    config = ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT,
                           transport_key=KEY, users={USER: "operator-1"})
    with pytest.raises(ValueError, match="isolated"):
        install_channel_feature(
            client.app, config=config, task_service=tasks,
            principals={}, site_logins={}, require_operator=None, require_named_operator=None, read_guard=[],
            console=client.app.state.console, existing_tokens=(), secret_owners=())
    assert not hasattr(client.app.state, "channel_requests")


@pytest.mark.parametrize("kind", ["missing", "malformed", "shared", "producer"])
def test_bot_token_file_is_optional_private_and_isolated(tmp_path, kind):
    from types import SimpleNamespace
    from fleet.server.channel_requests import install_channel_feature
    from test_mission_api import _client
    client, tasks, _ = _client(tmp_path, goal_evidence_enabled=True)
    path = tmp_path / "bot.token"
    token = "private-bot-test-token-" * 3
    if kind != "missing":
        path.write_text("invalid token" if kind == "malformed" else KEY if kind == "shared" else token)
    if kind == "producer":
        producer = SimpleNamespace(token=token)
        client.app.state.goal_evidence_service = SimpleNamespace(registry=SimpleNamespace(producers=(producer,)))
    config = ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT,
                           transport_key=KEY, users={USER: "operator-1"}, bot_token_file=str(path))
    with pytest.raises(ValueError) as error:
        install_channel_feature(
            client.app, config=config, task_service=tasks, principals={}, site_logins={},
            require_operator=None, require_named_operator=None, read_guard=[], console=client.app.state.console,
            existing_tokens=(), secret_owners=())
    assert token not in str(error.value) and KEY not in str(error.value)
    assert not hasattr(client.app.state, "channel_requests")


def test_optional_intake_file_only_disables_when_absent(tmp_path):
    path = tmp_path / "intake.json"
    assert ChannelConfig.load(path, optional=True) is None
    path.write_text('{"transport_key":"private-invalid-config"}')
    with pytest.raises(ValueError, match="invalid Discord intake configuration"):
        ChannelConfig.load(path, optional=True)


def test_discord_config_flags_are_mutually_exclusive():
    from fleet.cli import parse_args
    args = parse_args(["console", "--robots", "robots.yaml", "--discord-intake-config-optional", "intake.json"])
    assert str(args.discord_intake_config_optional) == "intake.json"
    with pytest.raises(SystemExit):
        parse_args(["console", "--robots", "robots.yaml", "--discord-intake-config", "a.json",
                    "--discord-intake-config-optional", "b.json"])
