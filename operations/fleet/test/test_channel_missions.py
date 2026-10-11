"""Discord preparation uses actual existing proposal and independent admit owners."""
from contextlib import closing

import pytest

from core_common.protocol.channel_requests import DiscordRequestEnvelope
from fleet.server.channel_requests import ChannelConfig
from test_channel_workflow import GUILD, CHANNEL, USER, BOT, MESSAGE
from test_mission_api import _client, _candidate
from test_cell_job_api import _setup, _post
from test_cell_app_api import _refs


def config():
    return ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT,
                         transport_key="transport-key-" * 3, users={USER: "operator-1"})


def receive(client):
    return client.app.state.channel_requests.receive(DiscordRequestEnvelope(
        guild_id=GUILD, channel_id=CHANNEL, author_id=USER, message_id=MESSAGE,
        mentions=[BOT], author_bot=False, webhook_id=None, content=f"<@{BOT}> inspect arm work"))


@pytest.mark.parametrize("kind", ["mission", "cell_job"])
def test_prepare_and_independent_existing_admit(tmp_path, kind):
    if kind == "mission":
        client, tasks, _ = _client(tmp_path, channel_config=config())
        candidate = {"candidate": _candidate()}
    else:
        client, tasks, _ = _setup(tmp_path, channel_config=config(), cell_app_service_id="cell-service")
        candidate = _refs(client)
    receipt = receive(client)
    path = f"/api/fleet/channel-requests/{receipt['request_id']}"
    body = {"kind": kind, "expected_hash": receipt["content_hash"], "expected_revision": 0,
            "reason": "reviewed trusted evidence", "workcell_id": "omx_01",
            "instance_id": "omx_01_control", **candidate}
    prepared = _post(client, path + "/prepare", "operator-secret", body)
    assert prepared.status_code == 200, prepared.text
    view = prepared.json()
    assert view["state"] == "LINKED" and view["work_kind"] == kind and view["work_status"] == "PROPOSED"
    assert _post(client, path + "/prepare", "operator-secret", body).json() == view
    proposal = client.app.state.proposal_store.get(view["work_id"])
    assert proposal["principal_id"] == ("operator-1" if kind == "mission" else "cell-service")
    assert proposal["request_key"] == "discord-" + receipt["request_id"]
    assert _post(client, path + "/prepare", "operator-secret", {**body, "reason": "different"}).status_code == 409
    assert _post(client, path + "/admit", "viewer-secret", {
        "expected_hash": receipt["content_hash"], "expected_revision": 1,
        "expected_generation": 0}).status_code == 403
    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(expected_generation=control["generation"], actor_id="operator-1")["generation"]
    admitted = _post(client, path + "/admit", "operator-secret", {
        "expected_hash": receipt["content_hash"], "expected_revision": 1,
        "expected_generation": generation})
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["work_status"] == "READY"
    if kind == "cell_job":
        assert _post(client, path + "/admit", "cell-secret", {
            "expected_hash": receipt["content_hash"], "expected_revision": 1,
            "expected_generation": generation}).status_code == 403
    with closing(tasks.store._connect()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fleet_tasks").fetchone()[0] == 0


@pytest.mark.parametrize("change", [
    {"principal_id": "other"}, {"request_key": "arbitrary"}, {"expected_revision": True}, {"reason": " "},
])
def test_untrusted_prepare_fields_never_create_proposal(tmp_path, change):
    client, tasks, _ = _client(tmp_path, channel_config=config())
    receipt = receive(client)
    body = {"kind": "mission", "expected_hash": receipt["content_hash"], "expected_revision": 0,
            "reason": "trusted evidence", "workcell_id": "omx_01", "instance_id": "omx_01_control",
            "candidate": _candidate(), **change}
    response = _post(client, f"/api/fleet/channel-requests/{receipt['request_id']}/prepare", "operator-secret", body)
    assert response.status_code == 422
    with closing(tasks.store._connect()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fleet_proposals").fetchone()[0] == 0
