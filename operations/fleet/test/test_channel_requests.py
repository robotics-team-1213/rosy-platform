"""Named Discord intake must never create executable work."""
import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
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
    body = envelope(); body["content"] += " edited"
    assert post(client, body).status_code == 409
    assert client.get("/api/fleet/channel-requests").json()["rows"] == [first.json()]
    import sqlite3
    with sqlite3.connect(journal.path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("fleet_channel_requests",)]


@pytest.mark.parametrize("changes", [
    {"guild_id": USER}, {"channel_id": USER}, {"guild_id": None}, {"author_bot": True},
    {"webhook_id": MESSAGE}, {"mentions": []}, {"author_id": MESSAGE},
    {"principal_id": "op"}, {"content": ""}, {"content": "x" * 2001},
])
def test_forbidden_transport_input(tmp_path, changes):
    client, journal, _ = fixture(tmp_path)
    body = envelope(); body.update(changes)
    assert post(client, body).status_code in (403, 422)
    assert journal.read("op") == []


def test_transport_auth_freshness_revocation_and_capacity(tmp_path):
    client, journal, accounts = fixture(tmp_path, max_rows=1)
    assert post(client, envelope(), key="operator-token").status_code == 401
    assert post(client, envelope(), timestamp="900").status_code == 401
    assert client.post("/api/fleet/channel-requests/discord", json=envelope(),
                       headers={"Authorization": "Bearer operator-token"}).status_code == 401
    assert post(client, envelope()).status_code == 200
    body = envelope(); body["message_id"] = USER
    assert post(client, body).status_code == 503
    accounts["op"] = "viewer"
    assert post(client, envelope()).status_code == 403
    assert client.get("/api/fleet/channel-requests").status_code == 403


def test_config_rejects_unknown_fields_and_short_key():
    with pytest.raises(ValueError):
        ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT, transport_key="short", users={USER: "op"})
