"""D-789 site media leases cannot outlive their original CORE authority."""

import importlib
from pathlib import Path
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from core_common.protocol.media_tokens import sign_media


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def implementation():
    assert (ROOT / 'src/rosy_media/authority.py').is_file(), 'D-789 site session authority missing'
    return importlib.import_module('rosy_media.authority')


@pytest.fixture
def media():
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)
    online, kicked = [True], []

    def token(action='read', grant_id='a' * 32, now=100):
        return sign_media(dict(iss='robot:rosy_01', aud='site:lab', sub='owner', jti=grant_id,
            robot_id='rosy_01', path='robots/rosy_01/front', action=action, iat=now, exp=now+60),
            private, 'media-1')

    def check(robot_id, bearer, now):
        if online[0] == 'offline':
            raise TimeoutError()
        from core_common.protocol.media_tokens import verify_media
        claims = verify_media(bearer, {'media-1': public}, robot_id=robot_id, audience='site:lab', now=now)
        return dict(active=online[0], grant_id=claims.jti, robot_id=robot_id, path=claims.path,
                    action=claims.action, audience=claims.aud, expires_at=claims.exp)

    authority = implementation().MediaAuthority(audience='site:lab',
        public_keys={'rosy_01': {'media-1': public}}, validate_online=check, kick=kicked.append)
    return authority, token, online, kicked


def test_first_viewer_intent_starts_source_and_promotes_startup_lease(media):
    authority, token, _, _ = media
    assert authority.demand('rosy_01', now=100)['active'] is False
    assert authority.intent(token(), now=100)
    assert authority.demand('rosy_01', now=101)['active'] is True
    assert authority.authorize(token(), 'read', 'robots/rosy_01/front', 'viewer-1', now=102)
    # Past the ten-second startup lease, before the first twenty-second renewal.
    assert authority.demand('rosy_01', now=115)['active'] is True
    assert authority.authorize(token('publish', 'b'*32), 'publish', 'robots/rosy_01/front',
                               'publisher-1', now=115)


def test_media_scope_replay_and_anonymous_requests_are_denied(media):
    authority, token, _, _ = media
    assert authority.authorize('', 'read', 'robots/rosy_01/front', 'x', now=100) is False
    authority.intent(token(), now=100)
    assert authority.authorize(token(), 'publish', 'robots/rosy_01/front', 'x', now=101) is False
    assert authority.authorize(token(), 'read', 'robots/rosy_02/front', 'x', now=101) is False
    assert authority.authorize(token(), 'read', 'robots/rosy_01/front', 'viewer-1', now=101)
    assert authority.authorize(token(), 'read', 'robots/rosy_01/front', 'viewer-2', now=101) is False


@pytest.mark.parametrize('failure', [False, 'offline'])
def test_existing_media_is_kicked_when_core_revokes_or_disappears(media, failure):
    authority, token, online, kicked = media
    authority.intent(token(), now=100)
    authority.authorize(token(), 'read', 'robots/rosy_01/front', 'viewer-1', now=101)
    authority.authorize(token('publish', 'b'*32), 'publish', 'robots/rosy_01/front', 'publisher-1', now=101)
    online[0] = failure
    authority.tick(now=102)
    assert set(kicked) == {'viewer-1', 'publisher-1'}
    assert authority.demand('rosy_01', now=102)['active'] is False


def test_media_renewal_updates_same_session_and_cannot_change_owner(media):
    authority, token, _, kicked = media
    authority.intent(token(), now=100)
    authority.authorize(token(), 'read', 'robots/rosy_01/front', 'viewer-1', now=101)
    assert authority.renew('viewer-1', token(now=120), now=120)
    assert authority.renew('viewer-1', token(grant_id='c'*32, now=120), now=120) is False
    authority.tick(now=165)
    assert kicked == []
    authority.tick(now=181)
    assert kicked == ['viewer-1']


def test_cancelled_or_expired_startup_demand_does_not_publish(media):
    authority, token, _, _ = media
    grant_id = authority.intent(token(), now=100)
    assert authority.cancel_intent(grant_id, token(), now=101)
    assert authority.demand('rosy_01', now=101)['active'] is False
    authority.intent(token(), now=102)
    assert authority.demand('rosy_01', now=113)['active'] is False


def test_slow_reader_is_removed_without_degrading_healthy_reader(media):
    authority, token, _, kicked = media
    authority.intent(token(), now=100)
    authority.authorize(token(), 'read', 'robots/rosy_01/front', 'slow', now=101)
    healthy = token(grant_id='c'*32)
    authority.intent(healthy, now=100)
    authority.authorize(healthy, 'read', 'robots/rosy_01/front', 'healthy', now=101)
    assert authority.report_queue('slow', token(), queue_ms=600, now=102)
    assert authority.report_queue('slow', token(), queue_ms=600, now=104)
    assert kicked == ['slow']
    assert authority.demand('rosy_01', now=104)['active'] is True
