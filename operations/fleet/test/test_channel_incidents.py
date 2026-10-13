"""Discord relations commit with the existing named current-incident claim owner."""
import json
import sqlite3
from contextlib import closing

import pytest

from core_common.protocol.channel_requests import DiscordRequestEnvelope
from fleet.incidents.handoff import judgment_revision
from fleet.server.channel_replies import ChannelReplyOutbox
from fleet.server.channel_requests import ChannelConfig
from fakes import FakeRobot
from test_channel_workflow import GUILD, CHANNEL, USER, BOT, MESSAGE
from test_line_stuck_api import _console, _named_app, _state, _auth, OPERATOR, VIEWER


def make_channel_incident(tmp_path):
    robot = FakeRobot('rosy_01', state=_state())
    config = ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT,
                           transport_key='transport-key-' * 3, users={USER: 'op-7'})
    client, store = _named_app(_console(robot), tmp_path, channel_config=config)
    journal = client.app.state.channel_requests
    journal.reply_outbox = ChannelReplyOutbox(journal)
    receipt = journal.receive(DiscordRequestEnvelope(guild_id=GUILD, channel_id=CHANNEL,
        author_id=USER, message_id=MESSAGE, mentions=[BOT], author_bot=False, webhook_id=None,
        content=f'<@{BOT}> inspect current incident'))
    current = client.get('/api/fleet/state', headers=_auth(VIEWER)).json()['robots'][0]['judgment']
    body = {'expected_hash': receipt['content_hash'], 'expected_revision': 0, 'robot_id': 'rosy_01',
            'stuck_id': 'stuck-abc', 'judgment_revision': judgment_revision(current), 'reason': 'named review'}
    path = f"/api/fleet/channel-requests/{receipt['request_id']}"
    return client, store, robot, receipt, path, body


def post(client, path, body, token=OPERATOR):
    return client.post(path + '/incident', json=body, headers=_auth(token))


def test_current_claim_relation_retry_and_closed_reply_have_no_device_authority(tmp_path):
    client, store, robot, receipt, path, body = make_channel_incident(tmp_path)
    result = post(client, path, body)
    assert result.status_code == 200, result.text
    view = result.json()
    assert view['state'] == 'LINKED' and view['work_kind'] == 'incident' and view['work_status'] == 'CLAIMED'
    assert view['incident'] == {key: body[key] for key in ('robot_id', 'stuck_id', 'judgment_revision')}
    assert post(client, path, body).json() == view
    assert post(client, path, {**body, 'stuck_id': 'another-case'}).status_code == 409
    handoff = client.app.state.line_stuck._log.handoff
    assert handoff.get('rosy_01', 'stuck-abc')['principal_id'] == 'op-7'
    with closing(store._connect()) as conn:
        assert conn.execute('SELECT COUNT(*) FROM fleet_incident_claims').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM fleet_tasks').fetchone()[0] == 0
    robot._state = _state(stuck=None)
    client.app.state.fleet_gather.max_age_s = 0
    client.get('/api/fleet/state', headers=_auth(VIEWER))
    assert client.get(path + '/review', headers=_auth(OPERATOR)).json()['work_status'] == 'CLOSED'
    outbox = client.app.state.channel_requests.reply_outbox
    outbox.observe_results()
    outbox.observe_results()
    replies = outbox.rows('op-7')
    assert sum(row['kind'] == 'INCIDENT:CLOSED' for row in replies) == 1
    assert not [call for call in robot.calls if call[0] in {'line_stuck_decision', 'goal', 'cancel', 'estop'}]


@pytest.mark.parametrize('change', ['hash', 'revision', 'judgment', 'closed', 'stale', 'owner', 'mapping'])
def test_current_case_and_named_request_guards_leave_no_relation_or_claim(tmp_path, change):
    client, store, _, receipt, path, body = make_channel_incident(tmp_path)
    if change in {'hash', 'judgment'}:
        body['expected_hash' if change == 'hash' else 'judgment_revision'] = '0' * 64
    if change == 'revision':
        body['expected_revision'] = 1
    if change == 'mapping':
        client.app.state.channel_requests.config.users[USER] = 'other'
    if change == 'owner':
        log = client.app.state.line_stuck._log
        current = client.app.state.line_stuck.judgment_view('rosy_01')
        log.handoff.claim('rosy_01', 'stuck-abc', current, 'other', now=current['evaluated_at'])
    with closing(store._connect()) as conn, conn:
        if change == 'closed':
            conn.execute('UPDATE fleet_line_stuck_episodes SET closed_at=1')
        if change == 'stale':
            raw = conn.execute('SELECT assessment FROM fleet_judgment_current').fetchone()[0]
            old = json.loads(raw)
            old['evaluated_at'] = 0
            conn.execute('UPDATE fleet_judgment_current SET assessment=?', (json.dumps(old),))
    result = post(client, path, body)
    assert result.status_code == (403 if change == 'mapping' else 409), result.text
    with closing(store._connect()) as conn:
        assert conn.execute('SELECT COUNT(*) FROM fleet_channel_workflow').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM fleet_incident_claims').fetchone()[0] == (change == 'owner')
    assert post(client, path, body, VIEWER).status_code == 403


def test_changed_review_at_claim_and_reply_failure_rollback_both_owners(tmp_path, monkeypatch):
    client, store, _, receipt, path, body = make_channel_incident(tmp_path)
    app = client.app
    handoff = app.state.line_stuck._log.handoff
    original = handoff.claim
    def changed(*args, **kwargs):
        app.state.channel_workflow.review(receipt['request_id'], 'op-7', expected_hash=receipt['content_hash'],
            expected_revision=0, state='HOLD', reason='other tab held request')
        return original(*args, **kwargs)
    monkeypatch.setattr(handoff, 'claim', changed)
    assert post(client, path, body).status_code == 409
    assert handoff.get('rosy_01', 'stuck-abc') is None
    monkeypatch.setattr(handoff, 'claim', original)
    body['expected_revision'] = 1
    with closing(store._connect()) as conn, conn:
        conn.execute("""CREATE TRIGGER fail_incident_reply BEFORE INSERT ON fleet_channel_reply_outbox
            WHEN NEW.kind='LINKED' BEGIN SELECT RAISE(ABORT, 'reply write failed'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='reply write failed'):
        post(client, path, body)
    assert handoff.get('rosy_01', 'stuck-abc') is None
    assert app.state.channel_workflow.read(receipt['request_id'], 'op-7')['state'] == 'HOLD'
    assert ('rosy_01', 'stuck-abc') in app.state.line_stuck._handoff_pending
