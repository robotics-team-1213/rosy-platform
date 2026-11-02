"""D-757 signed access is scoped, short-lived and independent of legacy role ranks."""
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from pydantic import ValidationError

from core_common.protocol.account_access import AccountGrant, AccessRejected, grants_for, sign_access, verify_access


def keys():
    private = Ed25519PrivateKey.generate()
    return (private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()),
            private.public_key().public_bytes(serialization.Encoding.PEM,
                                              serialization.PublicFormat.SubjectPublicKeyInfo))


def claims(**changes):
    return dict(iss='https://account.example.test', aud='robot:r1', sub='account-1',
                sid='family-1', jti='unique-access-id-1', rev=1, iat=1000, exp=1300,
                grants=[{'resource': 'robot:r1', 'capabilities': ['robot.read']}], **changes)


def test_valid_signed_grant_is_bound_to_one_resource():
    private, public = keys()
    token = sign_access(claims(), private, key_id='key-1')
    result = verify_access(token, {'key-1': public}, issuer='https://account.example.test',
                           audience='robot:r1', now=1001)
    assert result.sub == 'account-1'
    assert result.permits('robot:r1', 'robot.read')
    assert not result.permits('robot:r2', 'robot.read')
    assert not result.permits('robot:r1', 'robot.operate')


@pytest.mark.parametrize('capability', ['vault.read', 'vault.operate', 'vault.manage'])
def test_vault_signed_grants_are_site_scoped_without_inheritance(capability):
    private, public = keys()
    data = {**claims(), 'aud': 'site:one', 'grants': [
        {'resource': 'site:one', 'capabilities': [capability]}]}
    result = verify_access(sign_access(data, private, key_id='key-1'), {'key-1': public},
                           issuer=data['iss'], audience='site:one', now=1001)
    assert result.permits('site:one', capability)
    assert not result.permits('site:two', capability)
    for other in ['vault.read', 'vault.operate', 'vault.manage', 'accounts.manage', 'fleet.operate']:
        assert result.permits('site:one', other) == (other == capability)
    for resource in ['robot:r1', 'project:p']:
        with pytest.raises(ValidationError):
            AccountGrant(resource=resource, capabilities=[capability])


# D-955 allows robot:* and project:* in stored grants; every site and capability wildcards stay refused.
@pytest.mark.parametrize('resource,capability', [('site:*', 'fleet.read'), ('robot:r1', '*'),
                                               ('site:local', 'robot.admin'), ('project:p', 'accounts.manage')])
def test_grants_reject_wildcards_and_wrong_resource_kind(resource, capability):
    with pytest.raises(ValidationError):
        AccountGrant(resource=resource, capabilities=[capability])


@pytest.mark.parametrize('change', [{'aud': 'robot:r2'}, {'iss': 'https://other.example.test'},
                                   {'exp': 1400}, {'exp': 1001}, {'iat': 1002}, {'rev': True},
                                   {'sub': ''}, {'sid': ''}, {'exp': float('nan')}])
def test_untrusted_claims_are_refused(change):
    private, public = keys()
    data = {**claims(), **change}
    # The producer must refuse invalid claims, or the receiving resource must refuse them.
    with pytest.raises((AccessRejected, ValidationError, ValueError)):
        token = sign_access(data, private, key_id='key-1')
        verify_access(token, {'key-1': public}, issuer='https://account.example.test',
                      audience='robot:r1', now=1001)


def test_signature_unknown_key_and_tampering_are_refused():
    private, public = keys()
    token = sign_access(claims(), private, key_id='key-1')
    for bad_token, trusted in [(token, {}), (token, {'key-1': keys()[1]}),
                               (token[:-8] + 'AAAAAAAA', {'key-1': public})]:
        with pytest.raises(AccessRejected):
            verify_access(bad_token, trusted, issuer='https://account.example.test',
                          audience='robot:r1', now=1001)


def test_extra_claims_and_cross_resource_grants_are_refused():
    private, _ = keys()
    for change in [{'role': 'administrator'}, {'grants': [
            {'resource': 'robot:r2', 'capabilities': ['robot.admin']}]}]:
        with pytest.raises((AccessRejected, ValidationError)):
            sign_access({**claims(), **change}, private, key_id='key-1')


def test_stored_grant_may_name_every_robot_or_project_but_not_every_site():
    for resource in ('robot:*', 'project:*'):
        AccountGrant.model_validate({'resource': resource, 'capabilities':
                                     ['robot.read' if resource.startswith('robot') else 'learning.view']})
    for resource in ('site:*', 'robot:r*', 'robot:**'):
        with pytest.raises(ValidationError):
            AccountGrant.model_validate({'resource': resource, 'capabilities': ['fleet.read']})


def test_wildcard_resolves_to_one_concrete_resource_and_never_enters_a_token():
    stored = [{'resource': 'robot:*', 'capabilities': ['robot.read', 'robot.operate']},
              {'resource': 'robot:r1', 'capabilities': ['robot.admin', 'robot.read']},
              {'resource': 'project:*', 'capabilities': ['learning.view']}]
    assert grants_for(stored, 'robot:r1') == [
        {'resource': 'robot:r1', 'capabilities': ['robot.admin', 'robot.operate', 'robot.read']}]
    assert grants_for(stored, 'robot:r2') == [
        {'resource': 'robot:r2', 'capabilities': ['robot.operate', 'robot.read']}]
    assert grants_for(stored, 'site:s1') == []
    private, _ = keys()
    with pytest.raises(ValueError):
        sign_access({**claims(), 'aud': 'robot:*',
                     'grants': [{'resource': 'robot:*', 'capabilities': ['robot.read']}]},
                    private, key_id='key-1')
