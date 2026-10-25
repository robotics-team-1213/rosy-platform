"""Storage routes keep project, publish, manage and CSRF authority distinct."""
from contextlib import contextmanager
import json
import threading
import time

import pytest

from review_app import make_server
from test_learning_accounts import accounts, sign_in  # noqa: F401
from test_learning_collaboration import request
from test_review_app import open_store
from test_storage_jobs import jobs_setup  # noqa: F401
from test_storage_pool import pool_setup  # noqa: F401


@contextmanager
def running(tmp_path, accounts, storage, jobs):
    folder = tmp_path / 'review'; folder.mkdir()
    server = make_server(open_store(folder), 0, accounts=accounts, storage=storage, storage_jobs=jobs)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def finished(url, session, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status, data = request(url, '/api/learning/storage/jobs', session)
        assert status == 200
        job = next(row for row in data['jobs'] if row['id'] == job_id)
        if not job.get('operation'): return job
        time.sleep(.02)
    pytest.fail('storage operation did not finish')


def test_storage_http_archive_reclaim_restore_and_role_boundaries(tmp_path, jobs_setup, accounts):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    with running(tmp_path, accounts, inventory, build()) as url:
        assert request(url, '/api/learning/storage/pool')[0] == 401
        session, _ = sign_in(accounts, 'alice')
        token = request(url, '/api/accounts/session', session)[1]['token']
        status, data = request(url, '/api/learning/storage/pool', session)
        assert status == 200 and len(data['targets']) == 2
        assert str(artifact.parent) not in json.dumps(data) and 'hf_' not in json.dumps(data)
        body = dict(source_id='raw', artifact_id='run-one', profile='isaac')
        assert request(url, '/api/learning/storage/jobs', session, body)[0] == 403
        status, job = request(url, '/api/learning/storage/jobs', session, body, token)
        assert status == 201
        prefix = '/api/learning/storage/jobs/' + job['id']
        assert request(url, prefix + '/run', session, {}, token)[0] == 202
        assert finished(url, session, job['id'])['status'] == 'verified'
        assert request(url, prefix + '/reclaim', session, {'confirm': 'wrong'}, token)[0] == 400
        assert artifact.exists()
        assert request(url, prefix + '/reclaim', session, {'confirm': job['id']}, token)[0] == 202
        assert finished(url, session, job['id'])['local_present'] is False
        assert request(url, prefix + '/restore', session, {}, token)[0] == 202
        assert finished(url, session, job['id'])['local_present'] is True
        bob, _ = sign_in(accounts, 'bob')
        bob_token = request(url, '/api/accounts/session', bob)[1]['token']
        assert request(url, '/api/learning/storage/jobs', bob)[1]['jobs'] == []
        assert request(url, '/api/learning/storage/jobs', bob, body, bob_token)[0] == 403
        assert request(url, prefix + '/pin', bob, {'pinned': True}, bob_token)[0] == 403
        accounts.logout(session)
        assert request(url, '/api/learning/storage/jobs', session)[0] == 401


def test_storage_http_publish_does_not_grant_destructive_manage(tmp_path, jobs_setup, accounts):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    config = json.loads(accounts.config_path.read_text())
    config['users'][0]['memberships']['one'].remove('manage')
    accounts.config_path.write_text(json.dumps(config))
    # Project connections require their owner's manage grant, so personal ownership is tested separately.
    with running(tmp_path, accounts, inventory, build()) as url:
        session, _ = sign_in(accounts, 'alice')
        token = request(url, '/api/accounts/session', session)[1]['token']
        prefix = '/api/learning/storage/jobs/' + 'a' * 32
        assert request(url, prefix + '/reclaim', session, {'confirm': 'a' * 32}, token)[0] == 403
        assert request(url, '/api/learning/storage/cache/reclaim', session, {}, token)[0] == 403


def test_storage_http_unconfigured_pool_preserves_existing_inventory(tmp_path, jobs_setup, accounts):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    inventory.config.pop('pool')
    with running(tmp_path, accounts, inventory, None) as url:
        session, _ = sign_in(accounts, 'alice')
        token = request(url, '/api/accounts/session', session)[1]['token']
        assert request(url, '/api/learning/storage', session)[1]['roots']
        assert request(url, '/api/learning/storage/pool', session)[1]['status'] == 'not_configured'
        assert request(url, '/api/learning/storage/jobs', session, {}, token)[0] == 400
