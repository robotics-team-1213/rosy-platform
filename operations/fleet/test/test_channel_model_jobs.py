"""Model jobs and Discord answers share one durable owner-scoped journal."""
import json
import time

import pytest
from fastapi import HTTPException

from fleet.server.channel_replies import ChannelReplyOutbox
from test_channel_workflow import fixture


def model_jobs(tmp_path):
    from fleet.server.channel_deliberation import ChannelModelJobs, status_problem
    _, journal, _, accounts, receipt = fixture(tmp_path)
    clock = [time.time()]
    journal.reply_outbox = ChannelReplyOutbox(journal, clock=lambda: clock[0])
    jobs = ChannelModelJobs(journal, 'c' * 64, clock=lambda: clock[0])
    snapshot = {'robots': [{'robot_id': 'pinky', 'online': False, 'state': None}]}
    p = status_problem(receipt, snapshot, now=clock[0])
    return jobs, journal, accounts, receipt, snapshot, p, clock


def test_job_reserves_before_send_and_reopen_cannot_replay(tmp_path):
    from fleet.server.channel_deliberation import ChannelModelJobs
    jobs, journal, _, receipt, snapshot, p, _ = model_jobs(tmp_path)
    first = jobs.stage(receipt, p, snapshot)
    assert jobs.stage(receipt, p, snapshot) == first
    request = receipt['request_id']
    attempt = jobs.reserve(request, 'primary')
    with journal._connect() as conn:
        row = conn.execute('SELECT state FROM fleet_channel_model_jobs WHERE request_id=?', (request,)).fetchone()
        assert row[0] == 'RUNNING'
        assert conn.execute('SELECT count(*) FROM fleet_channel_model_attempts').fetchone()[0] == 1
    with pytest.raises(HTTPException): jobs.reserve(request, 'primary')
    restarted = ChannelModelJobs(journal, 'c' * 64)
    restarted.recover()
    assert restarted.read(request, 'op')['state'] == 'UNKNOWN'
    assert restarted.read(request, 'op')['action_admissible'] is False
    with pytest.raises(HTTPException): restarted.reserve(request, 'reviewer')
    assert attempt['role'] == 'primary'


@pytest.mark.parametrize('change', ['owner', 'account', 'content', 'profile', 'deadline'])
def test_changed_scope_is_refused_before_reserving_model(tmp_path, change):
    jobs, journal, accounts, receipt, snapshot, p, clock = model_jobs(tmp_path)
    jobs.stage(receipt, p, snapshot)
    if change == 'owner': journal.config.users[receipt['author_id']] = 'other'
    elif change == 'account': accounts['op'] = 'viewer'
    elif change == 'content':
        with journal._connect() as conn:
            changed = {**receipt, 'content': 'changed'}
            conn.execute('UPDATE fleet_channel_requests SET receipt=?', (json.dumps(changed),))
    elif change == 'profile': jobs.profile_set_hash = 'd' * 64
    else: clock[0] += 61
    with pytest.raises((HTTPException, ValueError)): jobs.reserve(receipt['request_id'], 'primary')
    with journal._connect() as conn:
        assert conn.execute('SELECT count(*) FROM fleet_channel_model_attempts').fetchone()[0] == 0


def test_result_and_reply_roll_back_together_and_answer_once(tmp_path, monkeypatch):
    jobs, journal, _, receipt, snapshot, p, _ = model_jobs(tmp_path)
    jobs.stage(receipt, p, snapshot)
    jobs.reserve(receipt['request_id'], 'primary')
    original = journal.reply_outbox.enqueue
    monkeypatch.setattr(journal.reply_outbox, 'enqueue', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        jobs.finish(receipt['request_id'], state='ANSWERED', result={'verdict': 'abstain'}, summary='Read-only status')
    assert jobs.read(receipt['request_id'], 'op')['state'] == 'RUNNING'
    monkeypatch.setattr(journal.reply_outbox, 'enqueue', original)
    jobs.finish(receipt['request_id'], state='ANSWERED', result={'verdict': 'abstain'}, summary='Read-only status')
    value = jobs.read(receipt['request_id'], 'op')
    assert value['result'] == {'verdict': 'abstain'} and value['action_admissible'] is False
    with pytest.raises(HTTPException):
        jobs.finish(receipt['request_id'], state='ANSWERED', result={}, summary='duplicate')
    with pytest.raises(HTTPException): jobs.read(receipt['request_id'], 'other')
    assert len(journal.reply_outbox.rows('op')) == 1


def test_status_input_keeps_question_as_data_and_ignores_snapshot_secrets(tmp_path):
    from fleet.server.channel_deliberation import status_problem
    _, _, _, receipt, snapshot, p, clock = model_jobs(tmp_path)
    assert p.goal == 'request' and p.necessity == 'READ_ONLY_QUERY'
    assert p.facts_json == '{"state":"offline"}'
    secret = {'robot_id': 'pinky', 'online': False, 'state': None, 'token': 'private', 'base_url': 'private'}
    assert status_problem(receipt, {'robots': [secret]}, now=clock[0]).digest == p.digest
    with pytest.raises(ValueError): status_problem(receipt, {'robots': [{'robot_id': 'pinky', 'online': 'false'}]}, now=clock[0])


def test_late_model_cost_is_retained_after_deadline_or_owner_revocation(tmp_path):
    jobs, journal, accounts, receipt, snapshot, p, clock = model_jobs(tmp_path)
    jobs.stage(receipt, p, snapshot)
    attempt = jobs.reserve(receipt['request_id'], 'primary')
    clock[0] += 61
    accounts['op'] = 'viewer'
    jobs.record_attempt(receipt['request_id'], 'primary', state='RESULT',
        result={'verdict': 'abstain'}, known_cost_usd=.1,
        input_hash=attempt['input_hash'], profile_set_hash=attempt['profile_set_hash'])
    with journal._connect() as conn:
        assert conn.execute('SELECT known_cost_usd FROM fleet_channel_model_attempts').fetchone()[0] == .1
        assert conn.execute('SELECT count(*) FROM fleet_channel_reply_outbox').fetchone()[0] == 0


def test_forged_question_cannot_keep_original_receipt_hash(tmp_path):
    from fleet.server.channel_deliberation import status_problem
    jobs,journal,_,receipt,snapshot,_,clock=model_jobs(tmp_path)
    forged={**receipt,'content':'a different question'}
    problem=status_problem(forged,snapshot,now=clock[0])
    with pytest.raises(HTTPException):jobs.stage(forged,problem,snapshot)
    with pytest.raises(HTTPException):jobs.reject(forged)
    assert journal.reply_outbox.rows('op')==[]


def test_publish_checks_observation_inside_transaction(tmp_path):
    jobs,_,_,receipt,snapshot,p,_=model_jobs(tmp_path)
    jobs.stage(receipt,p,snapshot)
    with pytest.raises(HTTPException):
        jobs.finish(receipt['request_id'],state='ANSWERED',result={},summary='wrong',observation_guard=lambda:False)
    assert jobs.read(receipt['request_id'],'op')['state']=='PENDING'
    with pytest.raises(HTTPException): jobs.reserve(receipt['request_id'], 'reviewer')
