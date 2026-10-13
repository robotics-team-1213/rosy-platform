"""Real SQLite/encryption/session boundaries, with only the HF network replaced."""
import json
import pytest
from cryptography.fernet import Fernet
from learning_accounts import Accounts, AccountError, hash_password


@pytest.fixture
def accounts(tmp_path):
    key = tmp_path / 'key'; key.write_bytes(Fernet.generate_key()); key.chmod(0o600)
    config = {'project_id': 'one', 'users': [
        {'user_id': 'alice', 'username': 'alice', 'password_hash': hash_password('alice-password'),
         'hf_subjects': ['invited-alice'], 'memberships': {'one': ['view', 'edit', 'approve', 'manage', 'import']}},
        {'user_id': 'bob', 'username': 'bob', 'password_hash': hash_password('bob-password'),
         'memberships': {'one': ['view', 'import'], 'two': ['view', 'import']}}]}
    path = tmp_path / 'config.json'; path.write_text(json.dumps(config)); path.chmod(0o600)
    return Accounts(tmp_path / 'accounts.db', key, path)


def identity(token, **kwargs):
    return {'id': 'subject-' + token[-1], 'name': 'account-' + token[-1], 'type': 'user'}


def test_named_login_expiry_logout_and_live_membership_revoke(accounts):
    token, principal = accounts.login('alice', 'alice-password')
    assert principal['user_id'] == 'alice'
    assert accounts.authenticate(token)['project_id'] == 'one'
    with pytest.raises(AccountError): accounts.login('alice', 'wrong')
    cfg = json.loads(accounts.config_path.read_text()); cfg['users'][0]['memberships'] = {}
    accounts.config_path.write_text(json.dumps(cfg))
    with pytest.raises(AccountError): accounts.require(principal, 'view')
    token, bob = accounts.login('bob', 'bob-password'); accounts.logout(token)
    with pytest.raises(AccountError): accounts.require(bob, 'view')


def test_multiple_encrypted_personal_connections_and_generation_fence(accounts):
    _, alice = accounts.login('alice', 'alice-password'); _, bob = accounts.login('bob', 'bob-password')
    first = accounts.connect_token(alice, 'hf_private_one', transport=identity)
    second = accounts.connect_token(alice, 'hf_private_two', transport=identity)
    assert first['connection_id'] != second['connection_id']
    assert len(accounts.connections(alice)) == 2
    assert accounts.connections(bob) == []
    assert b'hf_private_one' not in accounts.db_path.read_bytes()
    assert 'token' not in json.dumps(accounts.connections(alice))
    with pytest.raises(AccountError): accounts.credential(bob, first['connection_id'])
    cred = accounts.credential(alice, first['connection_id'])
    assert cred['token'] == 'hf_private_one'
    accounts.disconnect(alice, first['connection_id'])
    with pytest.raises(AccountError): accounts.credential(alice, first['connection_id'], cred['generation'])
    assert accounts.credential(alice, second['connection_id'])['token'] == 'hf_private_two'


def test_project_connection_resource_scope_and_cross_project_access(accounts):
    _, alice = accounts.login('alice', 'alice-password'); _, bob = accounts.login('bob', 'bob-password')
    with pytest.raises(AccountError): accounts.connect_token(bob, 'hf_x', sharing='project', resources=['dataset:org/data'], transport=identity)
    conn = accounts.connect_token(alice, 'hf_x', sharing='project', resources=['dataset:org/data'], transport=identity)
    assert accounts.credential(bob, conn['connection_id'], resource='dataset:org/data')['token'] == 'hf_x'
    with pytest.raises(AccountError): accounts.credential(bob, conn['connection_id'], resource='model:org/model')
    with pytest.raises(AccountError): accounts.authorize(bob, 'two', 'view')


def test_pat_does_not_create_login_identity_and_last_login_cannot_unlink(accounts):
    _, alice = accounts.login('alice', 'alice-password')
    accounts.connect_token(alice, 'hf_x', transport=identity)
    with pytest.raises(AccountError): accounts.login_subject('subject-x')
    session, principal = accounts.login_subject('invited-alice')
    assert accounts.authenticate(session)['user_id'] == 'alice'
    cfg = json.loads(accounts.config_path.read_text()); cfg['users'][0].pop('password_hash')
    accounts.config_path.write_text(json.dumps(cfg))
    _, principal = accounts.login_subject('invited-alice')
    with pytest.raises(AccountError): accounts.unlink_subject(principal, 'invited-alice')


def test_identity_link_conflict_not_email_and_login_throttling(accounts):
    _, alice = accounts.login('alice', 'alice-password'); _, bob = accounts.login('bob', 'bob-password')
    accounts.link_subject(alice, 'new-subject')
    with pytest.raises(AccountError): accounts.link_subject(bob, 'new-subject')
    assert accounts.login_subject('new-subject')[1]['user_id'] == 'alice'
    for _ in range(6):
        with pytest.raises(AccountError): accounts.login('nobody', 'wrong', address='same')
    with pytest.raises(AccountError, match='rate'): accounts.login('bob', 'bob-password', address='same')


def test_expired_session_and_replaced_credential_are_fenced(accounts):
    token, alice = accounts.login('alice', 'alice-password')
    conn = accounts.connect_token(alice, 'hf_private_x', transport=identity)
    old_generation = conn['generation']
    replaced = accounts.connect_token(alice, 'hf_new_x', transport=identity)
    assert replaced['connection_id'] == conn['connection_id']
    assert replaced['generation'] == old_generation + 1
    with pytest.raises(AccountError): accounts.credential(alice, conn['connection_id'], old_generation)
    now = accounts.clock(); accounts.clock = lambda: now + 13 * 3600
    with pytest.raises(AccountError): accounts.authenticate(token)


def test_ciphertext_cannot_be_transplanted_between_connections(accounts):
    _, alice = accounts.login('alice', 'alice-password')
    first = accounts.connect_token(alice, 'hf_a', transport=identity)
    second = accounts.connect_token(alice, 'hf_b', transport=identity)
    with accounts._db() as db:
        db.execute('UPDATE learning_connections SET secret=(SELECT secret FROM learning_connections WHERE id=?) WHERE id=?',
                   (first['connection_id'], second['connection_id']))
    with pytest.raises(AccountError): accounts.credential(alice, second['connection_id'])


def test_shared_database_keeps_project_sessions_and_connections_separate(accounts):
    cfg = json.loads(accounts.config_path.read_text()); cfg['project_id'] = 'two'
    other = Accounts(accounts.db_path, accounts.key_path, cfg)
    token, bob = accounts.login('bob', 'bob-password')
    conn = accounts.connect_token(bob, 'hf_b', transport=identity)
    with pytest.raises(AccountError): other.authenticate(token)
    _, other_bob = other.login('bob', 'bob-password')
    assert other.connections(other_bob) == []
    with pytest.raises(AccountError): other.credential(other_bob, conn['connection_id'])

