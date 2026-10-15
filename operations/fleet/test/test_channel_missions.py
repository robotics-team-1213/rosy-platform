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
    stale = _post(client, path + "/admit", "operator-secret", {
        "expected_hash": receipt["content_hash"], "expected_revision": 1,
        "expected_generation": generation - 1})
    assert stale.status_code == 409
    assert tasks.store.resource_claims(resource_kind='workcell', resource_id='omx_01') == []
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


def prepare_mission(client):
    receipt = receive(client)
    path = f"/api/fleet/channel-requests/{receipt['request_id']}"
    body = {"kind": "mission", "expected_hash": receipt["content_hash"], "expected_revision": 0,
            "reason": "trusted evidence", "workcell_id": "omx_01", "instance_id": "omx_01_control",
            "candidate": _candidate()}
    return receipt, path, body


def test_reuse_owned_existing_mission_candidate_without_fabricating_observation(tmp_path):
    from test_mission_api import _create
    client, _, _ = _client(tmp_path, channel_config=config())
    source = _create(client).json()['proposal']['proposal_id']
    receipt, path, body = prepare_mission(client)
    body.pop('candidate')
    result = _post(client, path + '/prepare', 'operator-secret', {**body, 'source_proposal_id': source})
    assert result.status_code == 200, result.text
    assert result.json()['work_id'] != source and result.json()['work_status'] == 'PROPOSED'
    proposals = client.app.state.proposal_store
    assert proposals.get(result.json()['work_id'])['candidate'] == proposals.get(source)['candidate']
    assert proposals.get(result.json()['work_id'])['request_key'] == 'discord-' + receipt['request_id']


@pytest.mark.parametrize('change', ['author', 'scope', 'both'])
def test_source_candidate_requires_current_owner_scope_and_exclusive_input(tmp_path, change):
    from test_mission_api import _create
    client, tasks, _ = _client(tmp_path, channel_config=config())
    source = _create(client).json()['proposal']['proposal_id']
    receipt, path, body = prepare_mission(client)
    if change != 'both':
        body.pop('candidate')
    if change == 'author':
        with closing(tasks.store._connect()) as conn, conn:
            conn.execute("UPDATE fleet_proposals SET principal_id='other' WHERE proposal_id=?", (source,))
    if change == 'scope':
        body['instance_id'] = 'other-instance'
    result = _post(client, path + '/prepare', 'operator-secret', {**body, 'source_proposal_id': source})
    assert result.status_code == (404 if change == 'author' else 409 if change == 'scope' else 422)
    assert client.app.state.channel_workflow.read(receipt['request_id'], 'operator-1')['state'] == 'REQUESTED'


@pytest.mark.parametrize('field,value', [
    ('source_mission_id', 'stale-held-mission'), ('source_action_id', 'old-action'),
    ('source_attempt_id', 'old-attempt'), ('source_dispatch_generation', 0),
    ('source_event_watermark', 0), ('source_observation_id', 'old-observation'),
    ('source_observed_at', '2000-01-01T00:00:00Z'), ('supersedes_mission_id', 'old-mission'),
    ('state', 'REJECTED'), ('state', 'UNRESOLVED'), ('state', 'RESOLVING'),
])
def test_feedback_lineage_and_nonready_source_never_become_ordinary_discord_mission(tmp_path, field, value):
    from test_mission_api import _create
    client, tasks, _ = _client(tmp_path, channel_config=config())
    source = _create(client).json()['proposal']['proposal_id']
    receipt, path, body = prepare_mission(client)
    body.pop('candidate')
    with closing(tasks.store._connect()) as conn, conn:
        conn.execute(f'UPDATE fleet_proposals SET {field}=? WHERE proposal_id=?', (value, source))
    response = _post(client, path + '/prepare', 'operator-secret', {**body, 'source_proposal_id': source})
    assert response.status_code == 409, response.text
    assert client.app.state.channel_workflow.read(receipt['request_id'], 'operator-1')['state'] == 'REQUESTED'
    with closing(tasks.store._connect()) as conn:
        assert conn.execute('SELECT COUNT(*) FROM fleet_proposals').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM fleet_missions').fetchone()[0] == 0
    assert tasks.store.resource_claims(resource_kind='workcell', resource_id='omx_01') == []


def test_changed_review_during_resolution_leaves_only_unadmitted_proposal(tmp_path, monkeypatch):
    client, tasks, _ = _client(tmp_path, channel_config=config())
    receipt, path, body = prepare_mission(client)
    owners = client.app.state.channel_missions
    resolve = owners.resolve

    def resolve_then_hold(*args, **kwargs):
        result = resolve(*args, **kwargs)
        owners.workflow.review(receipt['request_id'], 'operator-1', expected_hash=receipt['content_hash'],
                               expected_revision=0, state='HOLD', reason='another tab held this request')
        return result
    monkeypatch.setattr(owners, 'resolve', resolve_then_hold)
    response = _post(client, path + '/prepare', 'operator-secret', body)
    assert response.status_code == 409
    assert owners.workflow.read(receipt['request_id'], 'operator-1')['state'] == 'HOLD'
    with closing(tasks.store._connect()) as conn:
        assert conn.execute("SELECT status FROM fleet_missions").fetchone()[0] == 'PROPOSED'
    assert tasks.store.resource_claims(resource_kind='workcell', resource_id='omx_01') == []


def test_revoked_mapping_blocks_existing_admission(tmp_path):
    client, tasks, _ = _client(tmp_path, channel_config=config())
    receipt, path, body = prepare_mission(client)
    assert _post(client, path + '/prepare', 'operator-secret', body).status_code == 200
    client.app.state.channel_requests.accounts['operator-1'] = 'viewer'
    response = _post(client, path + '/admit', 'operator-secret', {
        'expected_hash': receipt['content_hash'], 'expected_revision': 1, 'expected_generation': 0})
    assert response.status_code == 403
    assert tasks.store.resource_claims(resource_kind='workcell', resource_id='omx_01') == []


def test_proposal_expiring_before_relation_is_rejected_without_nested_writer(tmp_path, monkeypatch):
    client, tasks, _ = _client(tmp_path, channel_config=config())
    receipt, path, body = prepare_mission(client)
    owners = client.app.state.channel_missions
    resolve = owners.resolve

    def expire(*args, **kwargs):
        result = resolve(*args, **kwargs)
        with closing(tasks.store._connect()) as conn, conn:
            conn.execute("UPDATE fleet_proposals SET expires_at='2000-01-01T00:00:00+00:00'")
        return result
    monkeypatch.setattr(owners, 'resolve', expire)
    response = _post(client, path + '/prepare', 'operator-secret', body)
    assert response.status_code == 409
    assert owners.workflow.read(receipt['request_id'], 'operator-1')['state'] == 'REQUESTED'
    with closing(tasks.store._connect()) as conn:
        assert conn.execute("SELECT status FROM fleet_missions").fetchone()[0] == 'PROPOSED'


def test_link_reply_failure_rolls_back_relation_without_admission(tmp_path):
    import sqlite3
    from fleet.server.channel_replies import ChannelReplyOutbox
    client, tasks, _ = _client(tmp_path, channel_config=config())
    journal = client.app.state.channel_requests
    journal.reply_outbox = ChannelReplyOutbox(journal)
    receipt, path, body = prepare_mission(client)
    with closing(tasks.store._connect()) as conn, conn:
        conn.execute("""CREATE TRIGGER deny_link_reply BEFORE INSERT ON fleet_channel_reply_outbox
            WHEN NEW.kind='LINKED' BEGIN SELECT RAISE(ABORT, 'reply unavailable'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        _post(client, path + '/prepare', 'operator-secret', body)
    assert client.app.state.channel_workflow.read(receipt['request_id'], 'operator-1')['state'] == 'REQUESTED'
    with closing(tasks.store._connect()) as conn:
        assert conn.execute("SELECT status FROM fleet_missions").fetchone()[0] == 'PROPOSED'
        assert conn.execute("SELECT COUNT(*) FROM fleet_channel_reply_outbox WHERE kind='LINKED'").fetchone()[0] == 0


@pytest.mark.parametrize('kind', ['mission', 'cell_job'])
def test_existing_work_result_replies_distinguish_action_and_goal(tmp_path, kind):
    from fleet.server.channel_replies import ChannelReplyOutbox
    if kind == 'mission':
        client, tasks, _ = _client(tmp_path, channel_config=config())
        candidate = {'candidate': _candidate()}
    else:
        client, tasks, _ = _setup(tmp_path, channel_config=config(), cell_app_service_id='cell-service')
        candidate = _refs(client)
    journal = client.app.state.channel_requests
    journal.reply_outbox = outbox = ChannelReplyOutbox(journal)
    receipt, path, body = prepare_mission(client)
    body.pop('candidate')
    response = _post(client, path + '/prepare', 'operator-secret', {**body, 'kind': kind, **candidate})
    assert response.status_code == 200, response.text
    table = 'fleet_missions' if kind == 'mission' else 'fleet_cell_jobs'
    for status in ('ACTION_SUCCEEDED', 'GOAL_CONFIRMED', 'HOLD'):
        with closing(tasks.store._connect()) as conn, conn:
            conn.execute(f'UPDATE {table} SET status=? WHERE mission_id=?', (status, response.json()['work_id']))
        if status == 'HOLD':
            journal.accounts['operator-1'] = 'viewer'
        outbox.observe_results()
        outbox.observe_results()
    with closing(tasks.store._connect()) as conn:
        rows = conn.execute("SELECT kind, state, content FROM fleet_channel_reply_outbox WHERE kind LIKE ?",
                            (kind.upper() + ':%',)).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        (kind.upper() + ':ACTION_SUCCEEDED', 'PENDING'),
        (kind.upper() + ':GOAL_CONFIRMED', 'PENDING'), (kind.upper() + ':HOLD', 'SUPERSEDED')]
    assert 'ACTION_SUCCEEDED' in rows[0][2] and 'GOAL_CONFIRMED' in rows[1][2] and rows[2][2] == ''


def test_channel_admit_is_wired_to_the_real_named_operator_guard(tmp_path):
    """Security review: through install_channel_feature and build_role_guards, an unnamed operator is refused.

    Swapping the admit route back to require_operator turns this 403 into the owner's 404.
    """
    from hashlib import sha256
    from fleet.server.channel_requests import install_channel_feature
    from fleet.server.site_auth import SitePrincipal, build_role_guards
    client, tasks, _ = _client(tmp_path)
    _, require_operator, require_named_operator, _ = build_role_guards(
        lambda: SitePrincipal("site-console", "operator"), {})  # a shared console token: no named credential
    install_channel_feature(
        client.app, config=config(), task_service=tasks, site_logins={},
        principals={sha256(b"operator-secret").hexdigest(): SitePrincipal("operator-1", "operator")},
        require_operator=require_operator, require_named_operator=require_named_operator, read_guard=[],
        console=client.app.state.console, existing_tokens=(), secret_owners=(),
        proposals=client.app.state.proposal_store, mission_admit=lambda *a, **k: None)
    receipt = receive(client)
    refused = client.post(f"/api/fleet/channel-requests/{receipt['request_id']}/admit", json={
        "expected_hash": receipt["content_hash"], "expected_revision": 1, "expected_generation": 0})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "OPERATOR_IDENTITY_REQUIRED")
