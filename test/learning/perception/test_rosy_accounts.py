from types import SimpleNamespace
import pytest
from learning_rosy_accounts import RosyAccounts
from learning_accounts import AccountError
from test_learning_accounts import accounts


def test_central_subject_preserves_owner_and_rechecks_grants(accounts):
    record = SimpleNamespace(sub='central-alice', aud='project:one',
        permits=lambda resource, capability: capability in {'learning.view','learning.import'})
    receiver = SimpleNamespace(resource='project:one', resolve_session_id=lambda sid: record)
    config = accounts.config()
    config['account_subjects'] = {'central-alice':'alice'}
    managed = RosyAccounts(accounts.db_path, accounts.key_path, config, receiver=receiver)
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
