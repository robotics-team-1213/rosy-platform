"""D-789 delegation remains bound to the live CORE principal and media scope."""

import importlib
import importlib.util

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def implementation():
    assert importlib.util.find_spec('core_features.vision.media_grants'), 'D-789 media grant authority missing'
    return importlib.import_module('core_features.vision.media_grants')


@pytest.fixture
def keys():
    private = Ed25519PrivateKey.generate()
    return (private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()),
            private.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo))


def authority(keys, owners):
    module = implementation()
    return module.MediaGrantService(robot_id='rosy_01', audience='site:lab', private_key=keys[0],
        key_id='media-1', owner_allowed=lambda owner, action: (owner, action) in owners)


def test_media_grant_has_narrow_scope_and_maximum_sixty_second_lifetime(keys):
    owners = {('viewer', 'read')}
    service = authority(keys, owners)
    grant = service.issue('viewer', 'rosy_01', 'read', now=100)
    assert grant.expires_at == 160
    assert grant.path == 'robots/rosy_01/front'
    assert grant.action == 'read'
    assert grant.audience == 'site:lab'
    assert 'viewer' not in repr(grant)
    assert grant.token not in repr(grant)
    assert service.check(grant.token, now=101)['active'] is True


def test_media_grants_refuse_cross_robot_and_role_upgrade(keys):
    service = authority(keys, {('viewer', 'read')})
    for robot, action in [('rosy_02', 'read'), ('rosy_01', 'publish'), ('rosy_01', 'drive')]:
        with pytest.raises(implementation().MediaGrantRefused):
            service.issue('viewer', robot, action, now=100)


def test_media_grant_revalidation_fails_closed_on_revocation_and_authority_loss(keys):
    owners = {('viewer', 'read')}
    service = authority(keys, owners)
    grant = service.issue('viewer', 'rosy_01', 'read', now=100)
    owners.clear()
    assert service.check(grant.token, now=101)['active'] is False
    owners.add(('viewer', 'read'))
    assert service.check(grant.token, now=102)['active'] is False


def test_media_grant_renewal_keeps_id_and_owner_but_requires_original_authority(keys):
    service = authority(keys, {('viewer', 'read')})
    grant = service.issue('viewer', 'rosy_01', 'read', now=100)
    renewed = service.renew(grant.grant_id, 'viewer', now=120)
    assert renewed.grant_id == grant.grant_id
    assert renewed.expires_at == 180
    assert service.check(renewed.token, now=170)['active'] is True
    assert service.check(grant.token, now=170)['active'] is False
    with pytest.raises(implementation().MediaGrantRefused):
        service.renew(grant.grant_id, 'different-viewer', now=121)


def test_media_grant_expiry_revoke_and_restart_deny_prior_credentials(keys):
    owners = {('viewer', 'read')}
    service = authority(keys, owners)
    grant = service.issue('viewer', 'rosy_01', 'read', now=100)
    assert service.check(grant.token, now=160)['active'] is False
    other = service.issue('viewer', 'rosy_01', 'read', now=161)
    service.revoke(other.grant_id, 'viewer')
    assert service.check(other.token, now=162)['active'] is False
    restarted = authority(keys, owners)
    assert restarted.check(other.token, now=162)['active'] is False


def test_media_grant_storage_is_bounded_and_callback_errors_deny(keys):
    service = authority(keys, {('viewer', 'read')})
    for _ in range(128):
        service.issue('viewer', 'rosy_01', 'read', now=100)
    with pytest.raises(implementation().MediaGrantRefused):
        service.issue('viewer', 'rosy_01', 'read', now=100)
    # Expired records are reclaimed before applying the capacity limit.
    grant = service.issue('viewer', 'rosy_01', 'read', now=161)
    service.owner_allowed = lambda *_: (_ for _ in ()).throw(TimeoutError())
    assert service.check(grant.token, now=162)['active'] is False
