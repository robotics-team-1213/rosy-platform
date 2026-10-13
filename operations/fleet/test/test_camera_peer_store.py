import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from fleet.server.pairing_store import PairingStore
from fleet.server.camera_peer_store import CameraPeerStore, CameraPeerDenied


ISSUER = {'principal_id': 'operator-one', 'role': 'operator',
          'token_sha256': 'a' * 64, 'source': 'site-users'}
CLIENT_KEY = 'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEaxfR8uEsQkf4vOblY6RA8ncDfYEt6zOg9KE5RdiYwpZP40Li/hp/m47n60p8D54WK84zV2sxXs7LtkBoN79R9Q=='


@pytest.fixture
def store(tmp_path):
    legacy = PairingStore(tmp_path / 'fleet.sqlite3', clock=lambda: 1000.)
    return CameraPeerStore(legacy, current_issuers=lambda: [ISSUER],
                           paired_sources=lambda: {'ceiling_north'}, clock=lambda: 1000.)


def approve(store):
    store.approve(relationship_id='request-one', source_id='ceiling_north',
                  client_key=CLIENT_KEY, receiver_key='c'*64, label='Cam',
                  issuer=ISSUER, persist_requested=True)


def issue(store, nonce='nonce-one'):
    store.put_challenge('request-one', nonce, expected_generation=0)
    return store.issue('request-one', nonce, 'b' * 64)


def test_relationship_survives_restart_and_long_offline_without_credential_extension(store):
    approve(store)
    issued = issue(store)
    assert issued['expires_at'] == 1000. + 180 * 86400
    later = CameraPeerStore(store.legacy, current_issuers=lambda: [ISSUER],
                            paired_sources=lambda: {'ceiling_north'}, clock=lambda: 1000. + 400 * 86400)
    assert later.relationship('request-one')['authorization_available'] is True
    renewed = issue(later, 'nonce-two')
    assert renewed['expires_at'] == 1000. + 580 * 86400


@pytest.mark.parametrize('mutation', ['delete-grant', 'generation', 'withdraw-issuer'])
def test_marked_credentials_fail_closed_if_binding_or_issuer_disappears(store, mutation):
    approve(store)
    row = issue(store)
    assert store.allowed_credential(store.legacy.get(row['credential_id']))
    if mutation == 'withdraw-issuer':
        store.current_issuers = lambda: []
    else:
        with sqlite3.connect(store.legacy.path) as connection:
            if mutation == 'delete-grant':
                connection.execute('DELETE FROM camera_peer_relationships')
            else:
                connection.execute('UPDATE camera_peer_relationships SET generation=generation+1')
    assert not store.allowed_credential(store.legacy.get(row['credential_id']))
    with pytest.raises(CameraPeerDenied):
        store.put_challenge('request-one', 'after-withdrawal', expected_generation=0)


def test_two_threads_cannot_consume_the_same_nonce(store):
    approve(store)
    store.put_challenge('request-one', 'same-nonce', expected_generation=0)
    def attempt(_):
        try:
            return store.issue('request-one', 'same-nonce', 'b' * 64)
        except CameraPeerDenied:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(result is not None for result in results) == 1
    assert len(store.legacy.credential_rows()) == 1


def test_revoke_closes_children_and_prevents_nonce_use(store):
    approve(store)
    row = issue(store)
    store.put_challenge('request-one', 'before-revoke', expected_generation=0)
    store.revoke('request-one', actor=ISSUER)
    assert store.legacy.get(row['credential_id'])['state'] == 'revoked'
    assert not store.relationship('request-one')['authorization_available']
    with pytest.raises(CameraPeerDenied):
        store.issue('request-one', 'before-revoke', 'b' * 64)
    assert store.legacy.audit_rows()[-1]['principal_id'] == 'operator-one'


def test_source_assignment_is_not_replaced_by_another_device_key(store):
    approve(store)
    with pytest.raises(CameraPeerDenied):
        store.approve(relationship_id='other', source_id='ceiling_north', client_key='other-key',
                      receiver_key='receiver-key', label='Other', issuer=ISSUER, persist_requested=True)


def test_unknown_expiry_metadata_does_not_create_a_durable_issuer(store):
    untyped = dict(ISSUER, expires_at=2000.)
    store.current_issuers = lambda: [untyped]
    with pytest.raises(CameraPeerDenied):
        store.approve(relationship_id='other', source_id='ceiling_north', client_key='other-key',
                      receiver_key='receiver-key', label='Other', issuer=untyped, persist_requested=True)


def test_legacy_digest_rows_remain_eligible_without_a_relationship(store):
    store.legacy.insert_pending(credential_id='legacy', source_id='ceiling_north',
                                token_sha256=hashlib.sha256(b'old').hexdigest(), device_label='Old',
                                principal_id='operator-one', expires_at=2000.)
    store.legacy.activate('legacy')
    assert store.allowed_credential(store.legacy.get('legacy'))


def test_missing_marker_cannot_turn_a_camera_peer_token_into_legacy(store):
    approve(store)
    row = issue(store)
    with sqlite3.connect(store.legacy.path) as connection:
        connection.execute('UPDATE device_credentials SET peer_relationship_id=NULL,peer_generation=NULL')
    assert not store.allowed_credential(store.legacy.get(row['credential_id']))


def test_failed_credential_insert_rolls_back_nonce_consumption(store):
    approve(store)
    store.put_challenge('request-one', 'one-shot', expected_generation=0)
    with sqlite3.connect(store.legacy.path) as connection:
        connection.execute("CREATE TRIGGER deny_issue BEFORE INSERT ON device_credentials "
                           "BEGIN SELECT RAISE(ABORT, 'fixture insert failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.issue('request-one', 'one-shot', 'b' * 64)
    with sqlite3.connect(store.legacy.path) as connection:
        connection.execute('DROP TRIGGER deny_issue')
    assert store.issue('request-one', 'one-shot', 'b' * 64)['credential_id']


def test_reconnects_replace_active_child_and_keep_bounded_history(store):
    approve(store)
    for number in range(12):
        issue(store, f'nonce-{number}')
    rows = store.legacy.credential_rows()
    assert len(rows) == 4
    assert sum(row['state'] == 'active' for row in rows) == 1


def test_corrupt_stored_key_denies_both_status_authority_and_issued_child(store):
    approve(store)
    row=issue(store)
    with sqlite3.connect(store.legacy.path) as connection:
        connection.execute("UPDATE camera_peer_relationships SET client_key='malformed'")
    assert store.relationship('request-one')['authorization_available'] is False
    assert not store.allowed_credential(store.legacy.get(row['credential_id']))
