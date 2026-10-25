"""No-JSON first use, private proof, activation and normal archive lifecycle."""
from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import threading
import time

import pytest

from review_app import make_server
from test_review_app import open_store
from test_learning_accounts import accounts, sign_in  # noqa: F401
from test_storage_pool import pool_setup  # noqa: F401
from test_storage_jobs import Remote
from test_learning_collaboration import request


@pytest.fixture
def setup_server(tmp_path, accounts, pool_setup, monkeypatch):
    _, actor, config, now = pool_setup
    for quota in config['quotas'].values(): quota['remaining_bytes'] = 1048576
    remote = Remote()
    if importlib.util.find_spec('storage_setup'):
        import storage_setup
        original = storage_setup.StorageSetup.__init__
        def configured(self, *args, **kwargs):
            kwargs.update(clock=lambda: now[0], transport=remote)
            original(self, *args, **kwargs)
        monkeypatch.setattr(storage_setup.StorageSetup, '__init__', configured)
    folder = tmp_path / 'review'; folder.mkdir()
    store = open_store(folder)
    @contextmanager
    def running():
        server = make_server(store, 0, accounts=accounts)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try: yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
    body = dict(revision=0, targets=config['targets'], quotas=config['quotas'], reserve_bytes=0,
                cache_policy=dict(enabled=False, max_bytes=1048576))
    return running, body, remote, folder, now


def session_for(url, accounts, name='alice'):
    session, _ = sign_in(accounts, name)
    token = request(url, '/api/accounts/session', session)[1]['token']
    return session, token


def idle(url, session):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status, data = request(url, '/api/learning/storage/settings', session)
        assert status == 200
        if not data.get('operation'): return data
        time.sleep(.02)
    pytest.fail('storage setup operation did not finish')


def test_no_json_http_setup_verifies_activates_prepares_and_archives(setup_server, accounts):
    running, body, remote, folder, now = setup_server
    with running() as url:
        assert request(url, '/api/learning/storage/settings')[0] == 401
        session, token = session_for(url, accounts)
        status, data = request(url, '/api/learning/storage/settings', session)
        assert status == 200 and data['can_manage'] and not data['enabled']
        assert str(folder) not in json.dumps(data) and 'hf_0' not in json.dumps(data)
        assert request(url, '/api/learning/storage/settings', session, body)[0] == 403
        assert request(url, '/api/learning/storage/settings', session, body, token)[0] == 200
        assert request(url, '/api/learning/storage/settings/activate', session, dict(revision=1), token)[0] == 400
        assert request(url, '/api/learning/storage/settings/verify', session, dict(revision=1, confirm=True), token)[0] == 202
        assert idle(url, session)['result']['status'] == 'verified'
        assert request(url, '/api/learning/storage/settings/activate', session, dict(revision=1), token)[0] == 200
        assert request(url, '/api/learning/storage/pool', session)[1]['enabled'] is True
        exports = folder / 'storage-data' / 'exports'
        data = exports / 'episode-one'; data.mkdir(); (data / 'episode.json').write_text('{"frames":5}')
        status, sources = request(url, '/api/learning/storage/sources', session)
        assert status == 200 and any(row['artifact_id'] == 'episode-one' for row in sources['folders'])
        prepare = dict(kind='folder', artifact_id='episode-one', profile='dataset',
            provenance=dict(source_revision='c' * 40), confirm_completed=True, archive=True)
        assert request(url, '/api/learning/storage/sources/prepare', session, prepare, token)[0] == 202
        state = idle(url, session)
        assert state['result']['status'] == 'verified' and state['result']['bytes_verified']
        assert (data / 'storage-source.json').is_file()
        prefix = '/api/learning/storage/jobs/' + state['result']['id']
        assert request(url, prefix + '/reclaim', session, dict(confirm=state['result']['id']), token)[0] == 202
        from test_storage_jobs_http import finished
        assert finished(url, session, state['result']['id'])['local_present'] is False
        assert request(url, prefix + '/restore', session, {}, token)[0] == 202
        assert finished(url, session, state['result']['id'])['local_present'] is True
    with running() as url:
        session, token = session_for(url, accounts)
        assert request(url, '/api/learning/storage/settings', session)[1]['enabled'] is True
        assert request(url, '/api/learning/storage/jobs', session)[1]['jobs']


def test_setup_routes_preserve_roles_csrf_and_fenced_updates(setup_server, accounts):
    running, body, remote, folder, now = setup_server
    with running() as url:
        session, token = session_for(url, accounts)
        bob, bob_token = session_for(url, accounts, 'bob')
        public = request(url, '/api/learning/storage/settings', bob)[1]
        assert public['can_manage'] is False and 'targets' not in public
        assert request(url, '/api/learning/storage/settings', bob, body, bob_token)[0] == 403
        assert request(url, '/api/learning/storage/settings', session, body, token)[0] == 200
        assert request(url, '/api/learning/storage/settings', session, body, token)[0] == 400
        assert request(url, '/api/learning/storage/settings/verify', session, dict(revision=1), token)[0] == 400
        assert remote.commits == 0
        bad = dict(kind='folder', artifact_id='../private', profile='dataset', provenance={}, confirm_completed=True, archive=True)
        assert request(url, '/api/learning/storage/sources/prepare', session, bad, token)[0] == 400
        assert not (folder.parent / 'private').exists()
