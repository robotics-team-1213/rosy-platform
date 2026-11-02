"""Account authority is independently importable; extraction preserves every authority row."""
import json
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]


def test_migration_preserves_rows_and_refuses_overwrite(standalone, tmp_path):
    from rosy_account.migration import AUTHORITY_TABLES, migrate_authority
    app = standalone[0]
    source, target = app.state.password_sessions.path, tmp_path / 'second-copy.db'
    with sqlite3.connect(source) as db:
        before = {table: db.execute(f'SELECT * FROM {table}').fetchall() for table in AUTHORITY_TABLES}
    counts = migrate_authority(source, target)
    assert counts == {table: len(rows) for table, rows in before.items()}
    with sqlite3.connect(target) as db:
        assert {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} == set(AUTHORITY_TABLES)
        for table, rows in before.items():
            assert db.execute(f'SELECT * FROM {table}').fetchall() == rows
    with pytest.raises(FileExistsError):
        migrate_authority(source, target)


@pytest.fixture
def standalone(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from rosy_account.account_authority import AccountAuthority
    from rosy_account.app import create_app
    from rosy_account.migration import migrate_authority
    from rosy_account.web_assets import build_web
    from test_account_ledger import activated, cookie
    sessions = activated(tmp_path)
    value = cookie(sessions)
    context = sessions.account_context(value)
    key = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    settings = dict(issuer='https://account.test', key_id='one', private_key=key,
        clients={'fleet': {'redirect_uris': ['https://fleet.test/api/fleet/auth/callback'],
                           'resources': ['site:test-site']}})
    AccountAuthority(sessions.path, **settings, resolve_family=lambda db, family: None,
                     revoke_family=lambda db, family: None)
    target = tmp_path / 'standalone.sqlite3'
    migrate_authority(sessions.path, target)
    config = tmp_path / 'authority.json'
    (tmp_path / 'key.pem').write_bytes(key)
    (tmp_path / 'key.pem').chmod(0o600)
    settings.pop('private_key')
    config.write_text(json.dumps({**settings, 'site_id': 'test-site', 'private_key_file': 'key.pem'}))
    config.chmod(0o600)
    web = tmp_path / 'account-web'
    build_web(ROOT, web)
    app = create_app(config=config, db=target, web_root=web / 'console', web_common=web / 'common')
    client = TestClient(app, base_url='https://account.test', follow_redirects=False)
    client.cookies.set('rosy_fleet_session', value)
    return app, client, context, config


def test_minimal_account_image_sources_start_without_fleet(standalone, tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    app, _, _, config = standalone
    source = tmp_path / 'image'
    shutil.copytree(ROOT / 'operations/account/rosy_account', source / 'account/rosy_account')
    for relative in ('__init__.py', 'protocol/__init__.py', 'protocol/account_access.py'):
        target = source / 'foundation/core_common' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'contracts/foundation/core_common' / relative, target)
    code = '''import importlib.abc,sys
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'fleet','drive','rclpy','rospy','rosy'}:
            raise ImportError('Account attempted a control runtime import')
sys.meta_path.insert(0,Boundary())
from rosy_account.app import create_app
from fastapi.testclient import TestClient
import rosy_account,core_common.protocol.account_access
from pathlib import Path
assert Path(rosy_account.__file__).is_relative_to(Path(sys.argv[1]))
assert Path(core_common.protocol.account_access.__file__).is_relative_to(Path(sys.argv[1]))
app=create_app(config=Path(sys.argv[2]),db=Path(sys.argv[3]),
               web_root=Path(sys.argv[4])/'console',web_common=Path(sys.argv[4])/'common')
client=TestClient(app,base_url='https://account.test')
assert client.get('/healthz').status_code==200
assert client.get('/console/login').status_code==200
assert not any(n=='fleet' or n.startswith('fleet.') for n in sys.modules)
'''
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(str(source / name) for name in ('account', 'foundation'))}
    result = subprocess.run([sys.executable, '-c', code, str(source), str(config),
                             str(app.state.password_sessions.path), str(tmp_path / 'account-web')],
                            cwd=source, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_standalone_preserves_session_profile_and_durable_audit(standalone):
    app, client, original, _ = standalone
    response = client.get('/api/fleet/auth/session')
    assert response.status_code == 200
    assert response.json()['account_id'] == original['account_id']
    assert response.json()['session_family'] == original['session_family']
    assert client.get('/api/fleet/auth/connection').json() == {'mode': 'paired', 'password_login': True}
    assert client.get('/console/profile').status_code == 200
    assert client.get('/console/cell').status_code == 404
    assert client.get('/console/assets/login-page.js').status_code == 200
    assert client.get('/console/assets/app-runtime.js').status_code == 404
    assert client.patch('/api/fleet/auth/profile', json={'display_name': 'Alice'},
                        headers={'Origin': 'https://foreign.test'}).status_code == 403
    assert client.patch('/api/fleet/auth/profile', json={'display_name': 'Alice'},
                        headers={'Origin': 'https://account.test'}).status_code == 200
    with sqlite3.connect(app.state.password_sessions.path) as db:
        assert db.execute('SELECT status_code FROM account_http_audit').fetchall() == [(200,)]


def test_standalone_login_fails_closed_when_audit_is_unavailable(standalone, monkeypatch):
    from rosy_account import audit
    from test_password_session import TYPED
    _, client, _, _ = standalone
    def fail(self, **fields):
        raise sqlite3.OperationalError('private-path')
    monkeypatch.setattr(audit.AccountAudit, 'begin_api_audit', fail)
    response = client.post('/api/fleet/auth/login', json={'login': 'alice', 'password': TYPED})
    assert response.status_code == 503
    assert 'private-path' not in response.text


def test_standalone_refuses_bootstrap_even_with_active_database(standalone):
    from rosy_account.app import create_app
    app, _, _, config = standalone
    settings = json.loads(config.read_text())
    config.write_text(json.dumps({**settings, 'bootstrap_admin_login': 'alice'}))
    with pytest.raises(ValueError, match='without bootstrap'):
        create_app(config=config, db=app.state.password_sessions.path,
                   web_root=ROOT / 'applications/fleet/web', web_common=ROOT / 'shared/web')


def test_migration_retains_inactive_orphans_but_rejects_missing_manager(standalone, tmp_path):
    from rosy_account.migration import migrate_authority, validate_database
    app, _, context, _ = standalone
    source = app.state.password_sessions.path
    with sqlite3.connect(source) as db:
        db.execute('INSERT INTO rosy_account_sessions VALUES(?,?,?,?)',
                   ('missing-console', context['account_id'], context['revision'], 'orphan-family'))
        db.execute('INSERT INTO account_oauth_access VALUES(?,?,?,?,?,?)',
                   ('revoked-digest', 'fleet', 'revoked-family', 1, 'site:test-site', 0))
    report = validate_database(source)
    assert report['orphan_session_links'] == 1 and report['inactive_oauth_rows'] == 1
    target = tmp_path / 'with-orphans.db'
    migrate_authority(source, target)
    assert validate_database(target) == report
    with sqlite3.connect(source) as db:
        db.execute("UPDATE rosy_accounts SET grants='[]'")
    failed = tmp_path / 'incomplete.db'
    with pytest.raises(ValueError, match='enabled account manager'):
        migrate_authority(source, failed)
    assert not failed.exists()


def test_healthcheck_uses_verified_tls_and_checks_status(monkeypatch):
    from io import BytesIO
    from contextlib import nullcontext
    from rosy_account import healthcheck
    calls = {}
    class Socket:
        def sendall(self, data):
            assert data.startswith(b'GET /healthz HTTP/1.1')
        def makefile(self, mode):
            return BytesIO(b'HTTP/1.1 200 OK\r\n')
    class Context:
        def wrap_socket(self, raw, *, server_hostname):
            calls['hostname'] = server_hostname
            return nullcontext(Socket())
    def context(*, cafile):
        calls['ca'] = cafile
        return Context()
    monkeypatch.setattr(healthcheck.ssl, 'create_default_context', context)
    monkeypatch.setattr(healthcheck.socket, 'create_connection', lambda *a, **k: nullcontext(object()))
    healthcheck.main([])
    assert calls == {'ca': '/run/secrets/site_ca', 'hostname': 'fleet'}
