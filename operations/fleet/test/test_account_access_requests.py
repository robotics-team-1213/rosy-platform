"""D-988 access requests: bounded public intake, administrator decision through the ledger's own paths."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from test_account_service_separation import standalone  # noqa: F401  (fixture)

ORIGIN = {'origin': 'https://account.test'}
URL = '/api/fleet/auth/access-requests'
GRANTS = [{'resource': 'site:test-site', 'capabilities': ['fleet.read']}]


def anonymous(app):
    return TestClient(app, base_url='https://account.test')


def rows(app, sql='SELECT * FROM rosy_access_requests ORDER BY created_at'):
    with sqlite3.connect(app.state.password_sessions.path) as db:
        db.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in db.execute(sql)]
        except sqlite3.OperationalError:  # the table appears with the first valid request
            return []


def send(client, **body):
    return client.post(URL, headers=ORIGIN, json=body)


def test_anonymous_request_is_stored_pending_without_any_grant_or_account(standalone):
    app, admin, _, _ = standalone
    accounts_before = admin.get('/api/fleet/auth/accounts', headers=ORIGIN).json()
    reply = send(anonymous(app), name='Dana Kim', username='dana', resource='project:demo', note='please')
    assert reply.status_code == 202 and reply.json() == {'status': 'received'}
    [row] = rows(app)
    assert (row['kind'], row['state'], row['username'], row['resource'], row['account_id']) == (
        'new_account', 'pending', 'dana', 'project:demo', None)
    assert admin.get('/api/fleet/auth/accounts', headers=ORIGIN).json() == accounts_before
    assert '127.0.0.1' not in json.dumps(row) and 'testclient' not in json.dumps(row)  # only a digest is kept


def test_same_answer_for_existing_login_new_login_and_repeat(standalone):
    app, _, _, _ = standalone
    client = anonymous(app)
    answers = {(r.status_code, json.dumps(r.json())) for r in (
        send(client, name='A', username='alice'), send(client, name='B', username='nobody'),
        send(client, name='B', username='nobody'))}
    assert len(answers) == 1
    assert [r['username'] for r in rows(app)] == ['alice', 'nobody']  # the repeat is silently merged


@pytest.mark.parametrize('body', [
    {'name': '', 'username': 'dana'}, {'name': 'D', 'username': 'Bad Name'}, {'name': 'D', 'username': ''},
    {'name': 'D', 'username': 'dana', 'resource': 'site:'}, {'name': 'D', 'username': 'dana', 'note': 'x' * 501},
    {'name': 'D', 'username': 'dana', 'role': 'admin'}, {'name': 'D\x00', 'username': 'dana'}])
def test_invalid_fields_are_refused(standalone, body):
    app, _, _, _ = standalone
    assert send(anonymous(app), **body).status_code == 422 and rows(app) == []


def test_csrf_and_size_limits(standalone):
    app, _, _, _ = standalone
    client = anonymous(app)
    assert client.post(URL, json={'name': 'D', 'username': 'dana'}).status_code == 403
    assert client.post(URL, headers={'origin': 'https://evil.test'}, json={'name': 'D', 'username': 'd'}).status_code == 403
    assert client.post(URL, headers=ORIGIN, content=b'x' * 5000).status_code == 413
    assert client.post(URL, headers=ORIGIN, content=b'[1]').status_code == 422
    assert rows(app) == []


def test_per_client_and_global_pending_caps(standalone, monkeypatch):
    app, _, _, _ = standalone
    client = anonymous(app)
    for number in range(5):
        assert send(client, name='N', username=f'user{number}').status_code == 202
    over = send(client, name='N', username='user5')
    assert over.status_code == 429 and over.json()['detail']['code'] == 'REQUESTS_FULL'
    from rosy_account import access_requests
    monkeypatch.setattr(access_requests, 'MAX_PENDING', 5)
    monkeypatch.setattr(access_requests, 'MAX_PENDING_PER_CLIENT', 99)
    assert send(client, name='N', username='user6').status_code == 429
    assert len(rows(app)) == 5


def test_admin_routes_need_a_manager_and_public_post_does_not_list(standalone):
    app, admin, _, _ = standalone
    assert anonymous(app).get(URL).status_code == 401
    send(anonymous(app), name='Dana', username='dana')
    [request] = admin.get(URL, headers=ORIGIN).json()
    assert request['username'] == 'dana' and 'client_sha256' not in request and request['login_taken'] is False
    assert anonymous(app).post(f'{URL}/{request["request_id"]}/approve', headers=ORIGIN,
                               json={'role': 'viewer', 'grants': []}).status_code == 401


def test_approve_new_account_uses_the_ledger_and_forces_a_first_password_change(standalone):
    app, admin, _, _ = standalone
    send(anonymous(app), name='Dana Kim', username='dana', resource='site:test-site')
    request_id = rows(app)[0]['request_id']
    refused = admin.post(f'{URL}/{request_id}/approve', headers=ORIGIN,
                         json={'role': 'viewer', 'grants': GRANTS, 'password': 'x'})
    assert refused.status_code == 422 and rows(app)[0]['state'] == 'pending'  # nothing half-approved
    assert not [a for a in admin.get('/api/fleet/auth/accounts', headers=ORIGIN).json() if a['login'] == 'dana']
    done = admin.post(f'{URL}/{request_id}/approve', headers=ORIGIN,
                      json={'role': 'viewer', 'grants': GRANTS, 'password': 'initial secret 1'})
    assert done.status_code == 200 and done.json()['account']['password_change_required'] is True
    account = done.json()['account']
    assert (account['login'], account['principal_id'], account['grants']) == ('dana', 'Dana Kim', GRANTS)
    [row] = rows(app)
    assert row['state'] == 'approved' and row['decided_by'] and row['decided_at']
    audit = rows(app, "SELECT operation FROM rosy_account_audit WHERE operation IN ('create','access-approve')")
    assert {a['operation'] for a in audit} == {'create', 'access-approve'}
    assert admin.post(f'{URL}/{request_id}/approve', headers=ORIGIN,
                      json={'role': 'viewer', 'grants': GRANTS, 'password': 'initial secret 1'}).status_code == 422
    assert 'initial secret' not in json.dumps(rows(app, 'SELECT * FROM rosy_access_requests'))


def test_signed_in_request_uses_the_session_identity_and_approval_updates_grants(standalone):
    app, admin, _, _ = standalone
    admin.post('/api/fleet/auth/accounts', headers=ORIGIN, json={
        'login': 'bob', 'principal_id': 'bob', 'role': 'viewer', 'password': 'bob!', 'grants': []})
    bob = anonymous(app)
    assert bob.post('/api/fleet/auth/login', headers=ORIGIN, json={'login': 'bob', 'password': 'bob!'}).status_code == 204
    assert bob.post('/api/fleet/auth/change-password', headers=ORIGIN,
                    json={'password': 'bob changed secret'}).status_code == 204
    assert send(bob, name='Mallory', username='alice', resource='project:demo', note='need it').status_code == 202
    [row] = rows(app)
    assert (row['kind'], row['username'], row['requester_name'], row['state']) == ('grant', 'bob', 'bob', 'pending')
    account = next(a for a in admin.get('/api/fleet/auth/accounts', headers=ORIGIN).json() if a['login'] == 'bob')
    assert account['grants'] == []  # asking changed nothing
    grants = [{'resource': 'project:demo', 'capabilities': ['learning.view']}]
    stale = admin.post(f'{URL}/{row["request_id"]}/approve', headers=ORIGIN,
                       json={'role': 'viewer', 'grants': grants, 'revision': account['revision'] + 5})
    assert stale.status_code == 409 and rows(app)[0]['state'] == 'pending'
    done = admin.post(f'{URL}/{row["request_id"]}/approve', headers=ORIGIN,
                      json={'role': 'viewer', 'grants': grants, 'revision': account['revision']})
    assert done.status_code == 200 and done.json()['account']['grants'] == grants
    assert rows(app)[0]['state'] == 'approved'


def test_reject_needs_a_reason_and_is_audited(standalone):
    app, admin, _, _ = standalone
    send(anonymous(app), name='Dana', username='dana')
    request_id = rows(app)[0]['request_id']
    assert admin.post(f'{URL}/{request_id}/reject', headers=ORIGIN, json={'reason': '  '}).status_code == 422
    assert admin.post(f'{URL}/{request_id}/reject', headers=ORIGIN, json={'reason': 'unknown person'}).status_code == 200
    [row] = rows(app)
    assert (row['state'], row['reason']) == ('rejected', 'unknown person')
    [audit] = rows(app, "SELECT * FROM rosy_account_audit WHERE operation='access-reject'")
    assert json.loads(audit['after_state'])['reason'] == 'unknown person'
    assert admin.post(f'{URL}/{request_id}/reject', headers=ORIGIN, json={'reason': 'again'}).status_code == 422
    assert admin.post(f'{URL}/nope/reject', headers=ORIGIN, json={'reason': 'r'}).status_code == 404
