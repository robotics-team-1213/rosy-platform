from types import SimpleNamespace
import pytest
from learning_rosy_accounts import RosyAccounts
from learning_accounts import AccountError
from test_learning_accounts import accounts


def test_central_subject_preserves_owner_and_rechecks_grants(accounts):
    old_cookie, _ = accounts.login('alice','alice-password')
    record = SimpleNamespace(sub='central-alice', aud='project:one',
        permits=lambda resource, capability: capability in {'learning.view','learning.import'})
    receiver = SimpleNamespace(resource='project:one', resolve_session_id=lambda sid: record)
    config = accounts.config()
    config['account_subjects'] = {'central-alice':'alice'}
    managed = RosyAccounts(accounts.db_path, accounts.key_path, config, receiver=receiver)
    with pytest.raises(AccountError): accounts.authenticate(old_cookie)
    with pytest.raises(AccountError): accounts.login('alice','alice-password')
    actor = managed.authenticate('browser-session')
    assert actor['user_id'] == 'alice'
    assert actor['capabilities'] == ['import', 'view']
    assert managed.require(actor, 'import')
    with pytest.raises(AccountError): managed.require(actor, 'manage')
    with pytest.raises(AccountError): managed.login('alice', 'alice-password')
    with pytest.raises(AccountError): managed.login_subject('invited-alice')
    record.permits = lambda resource, capability: capability == 'learning.view'
    with pytest.raises(AccountError): managed.require(actor, 'import')
    record.sub = 'unmapped'
    with pytest.raises(AccountError): managed.require(actor, 'view')


def test_subject_cannot_be_remapped_to_another_existing_owner(accounts):
    config = accounts.config()
    config['account_subjects'] = {'central-alice':'alice'}
    record = SimpleNamespace(sub='central-alice', aud='project:one', permits=lambda *args:True)
    receiver = SimpleNamespace(resource='project:one', resolve_session_id=lambda sid:record)
    managed = RosyAccounts(accounts.db_path, accounts.key_path, config, receiver=receiver)
    actor = managed.authenticate('browser-session')
    managed._config['account_subjects']['central-alice'] = 'bob'
    with pytest.raises(AccountError): managed.require(actor,'view')


def test_shared_credential_rechecks_central_owner_without_legacy_permissions(accounts):
    from hashlib import sha256
    from test_learning_accounts import identity
    config = accounts.config()
    config['account_subjects'] = {'central-alice':'alice','central-bob':'bob'}
    for user in config['users']: user['memberships'] = {}
    records = {sha256(name.encode()).hexdigest(): SimpleNamespace(sub='central-'+name,
        aud='project:one', permits=lambda *args:True) for name in ['alice','bob']}
    receiver = SimpleNamespace(resource='project:one', resolve_session_id=records.get)
    managed = RosyAccounts(accounts.db_path, accounts.key_path, config, receiver=receiver)
    alice, bob = managed.authenticate('alice'), managed.authenticate('bob')
    conn = managed.connect_token(alice,'hf_x',transport=identity,sharing='project',resources=['dataset:org/data'])
    assert managed.credential(bob,conn['connection_id'],resource='dataset:org/data')['token'] == 'hf_x'
    owner = records[sha256(b'alice').hexdigest()]
    owner.permits = lambda resource, cap: cap != 'learning.manage'
    with pytest.raises(AccountError): managed.credential(bob,conn['connection_id'])
    owner.permits = lambda *args:True
    records.pop(sha256(b'alice').hexdigest())
    with pytest.raises(AccountError): managed.assert_connection(bob,conn['connection_id'],conn['generation'])
