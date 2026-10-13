"""Bounded receiver consent and camera key proof. This service never calls a robot."""
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import secrets
import threading
import time

from core_common.protocol import camera_peer as wire
from .camera_peer_crypto import PeerIdentity, fingerprint, verify
from .camera_peer_store import CameraPeerDenied


def iso(wall):
    return datetime.fromtimestamp(wall, timezone.utc).isoformat().replace('+00:00', 'Z')


class CameraPeerService:
    PROFILE = {'profile': 'rosy.camera-peer/1', 'audience': 'fleet-camera-ingest',
               'device_kind': 'overhead-camera', 'source_role': 'camera'}

    def __init__(self, store, *, identity_path, tls_anchor=None, wall=time.time, monotonic=time.monotonic):
        self.store, self.identity_path = store, identity_path
        with closing(store.legacy._connect()) as connection:
            known = [row[0] for row in connection.execute('SELECT receiver_key FROM camera_peer_relationships')]
        self.identity = PeerIdentity(identity_path, known)
        self.receiver_id = 'fleet-' + self.identity.fingerprint[:32]
        self.tls_anchor = tls_anchor
        self.wall, self.monotonic = wall, monotonic
        self.requests, self.challenges = {}, {}
        self.admissions = {'request': deque(), 'proof': deque(), 'status': deque()}
        self.poll_times = {}
        self.lock = threading.RLock()

    def _admit(self, kind):
        now, queue = self.monotonic(), self.admissions[kind]
        while queue and queue[0] <= now - 60:
            queue.popleft()
        if len(queue) >= (600 if kind == 'status' else 30):
            raise CameraPeerDenied('rate limit reached')
        queue.append(now)

    def identity_snapshot(self):
        if not self.tls_anchor:
            raise CameraPeerDenied('verified receiver TLS anchor unavailable')
        return wire.IdentitySnapshot(**self.PROFILE, receiver_id=self.receiver_id,
                                     receiver_public_key=self.identity.public_key,
                                     receiver_key_sha256=self.identity.fingerprint,
                                     **self.tls_anchor).model_dump()

    def _expire(self):
        now = self.monotonic()
        for request_id, entry in tuple(self.requests.items()):
            if entry['deadline'] <= now and entry['state'] == 'pending':
                entry['state'], entry['revision'] = 'expired', entry['revision'] + 1
            if entry['deadline'] + 300 <= now:
                del self.requests[request_id]
        for challenge_id, entry in tuple(self.challenges.items()):
            if entry['deadline'] <= now:
                del self.challenges[challenge_id]
        for request_id, at in tuple(self.poll_times.items()):
            if at + 600 <= now:
                del self.poll_times[request_id]

    def request(self, body):
        with self.lock:
            self._admit('request')  # Invalid key/signature attempts consume the same CPU budget.
            signed = wire.SignedRequest.model_validate(body)
            fields = signed.fields.model_dump()
            if fields['receiver_id'] != self.receiver_id or fields['receiver_key_sha256'] != self.identity.fingerprint:
                raise CameraPeerDenied('receiver identity mismatch')
            self._expire()
            if len(self.requests) >= 16:
                raise CameraPeerDenied('request capacity reached')
            if any(entry['fields']['client_id'] == fields['client_id'] and
                   entry['fields']['nonce'] == fields['nonce'] for entry in self.requests.values()):
                raise CameraPeerDenied('request replayed')
            verify(fields['client_public_key'], signed.signature, 'request', fields)
            request_id, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
            occupied = {entry['display_code'] for entry in self.requests.values()}
            for _ in range(8):
                display_code = ''.join(secrets.choice('23456789ABCDEFGHJKMNPQRSTUVWXYZ') for _ in range(4))
                if display_code not in occupied:
                    break
            else:
                raise CameraPeerDenied('request correlation capacity reached')
            entry = {'fields': fields, 'secret_sha256': sha256(secret.encode()).hexdigest(),
                     'state': 'pending', 'revision': 0, 'deadline': self.monotonic() + 300,
                     'expires_at': iso(self.wall() + 300),
                     'display_code': display_code}
            self.requests[request_id] = entry
            created = wire.CreatedRequest(**self._state(request_id, entry), request_secret=secret)
            return created.model_dump()

    def _state(self, request_id, entry):
        result = dict(self.PROFILE, request_id=request_id, state=entry['state'], revision=entry['revision'],
                      display_code=entry['display_code'], expires_at=entry['expires_at'])
        if entry['state'] == 'approved':
            relationship = self.store.relationship(request_id)
            result.update(relationship_id=request_id, generation=relationship['generation'],
                          source_id=relationship['source_id'], persistent=relationship['expires_at'] is None,
                          authorization_expires_at=None if relationship['expires_at'] is None else iso(relationship['expires_at']),
                          authorization_available=relationship['authorization_available'])
        return wire.StateSnapshot(**result).model_dump()

    def _request_secret(self, request_id, secret):
        self._expire()
        entry = self.requests.get(request_id)
        if entry is None:
            try:
                row = self.store.relationship(request_id)
                entry = {'state':'approved', 'revision':1, 'display_code':row['display_code'],
                         'expires_at':row['request_expires_at'], 'secret_sha256':row['request_secret_sha256']}
            except CameraPeerDenied:
                raise CameraPeerDenied('unknown request') from None
        if not isinstance(secret, str) or len(secret) > 128 or not hmac.compare_digest(
                entry['secret_sha256'] or '', sha256(secret.encode()).hexdigest()):
            raise CameraPeerDenied('unknown request')
        return entry

    def status(self, request_id, secret):
        with self.lock:
            self._admit('status')
            entry = self._request_secret(request_id, secret)
            now = self.monotonic()
            if request_id in self.poll_times and self.poll_times[request_id] + 2 > now:
                raise CameraPeerDenied('status rate limit reached')
            if request_id not in self.poll_times and len(self.poll_times) >= 144:
                raise CameraPeerDenied('status rate limit capacity reached')
            self.poll_times[request_id] = now
            return self._state(request_id, entry)

    def pending(self):
        with self.lock:
            self._expire()
            return [wire.PendingRequest(**self._state(request_id, entry),
                                        client_id=entry['fields']['client_id'], label=entry['fields']['label'],
                                        client_key_sha256=fingerprint(entry['fields']['client_public_key'])).model_dump()
                    for request_id, entry in self.requests.items() if entry['state'] == 'pending']

    def cancel(self, request_id, secret):
        with self.lock:
            entry = self._request_secret(request_id, secret)
            if entry['state'] != 'pending':
                raise CameraPeerDenied('request no longer pending')
            entry['state'], entry['revision'] = 'cancelled', entry['revision'] + 1
            return self._state(request_id, entry)

    def decide(self, request_id, body, *, issuer):
        with self.lock:
            self._expire()
            decision = wire.ReceiverDecision.model_validate(body)
            self.store._issuer(issuer)
            entry = self.requests.get(request_id)
            if entry is None or entry['state'] != 'pending' or entry['revision'] != decision.revision:
                raise CameraPeerDenied('request closed or stale decision')
            if decision.action == 'approve':
                fields = entry['fields']
                secret_sha256 = entry['secret_sha256']
                self.store.approve(relationship_id=request_id, source_id=decision.source_id,
                                   client_key=fields['client_public_key'], receiver_key=self.identity.fingerprint,
                                   client_id=fields['client_id'], label=fields['label'], issuer=issuer,
                                   persist_requested=decision.persist_requested,
                                   request_secret_sha256=secret_sha256, display_code=entry['display_code'],
                                   request_expires_at=entry['expires_at'])
                entry['state'] = 'approved'
            else:
                entry['state'] = 'rejected'
            entry['revision'] += 1
            return self._state(request_id, entry)

    def challenge(self, relationship_id, *, generation):
        with self.lock:
            self._admit('proof')
            self._expire()
            if len(self.challenges) >= 64:
                raise CameraPeerDenied('challenge capacity reached')
            row = self.store.relationship(relationship_id)
            if not row['authorization_available'] or row['receiver_key'] != self.identity.fingerprint:
                raise CameraPeerDenied('relationship unavailable')
            challenge_id, nonce = secrets.token_urlsafe(24), secrets.token_hex(32)
            fields = wire.ChallengeFields(**self.PROFILE, relationship_id=relationship_id,
                        challenge_id=challenge_id, nonce=nonce, receiver_id=self.receiver_id,
                        receiver_key_sha256=self.identity.fingerprint, client_id=row['client_id'],
                        client_key_sha256=fingerprint(row['client_key']), source_id=row['source_id'],
                        generation=generation, expires_at=iso(self.wall() + 60)).model_dump()
            self.store.put_challenge(relationship_id, nonce, expected_generation=generation)
            self.challenges[challenge_id] = {'fields': fields, 'deadline': self.monotonic() + 60}
            return wire.ChallengeSnapshot(fields=fields, receiver_signature=self.identity.sign(
                'receiver-challenge', fields)).model_dump()

    def session(self, body):
        with self.lock:
            self._admit('proof')
            self._expire()
            signed = wire.SignedSession.model_validate(body)
            fields = signed.fields.model_dump()
            entry = self.challenges.get(fields['challenge_id'])
            if entry is None or entry['fields'] != fields:
                raise CameraPeerDenied('challenge mismatch or expired')
            row = self.store.relationship(fields['relationship_id'])
            if not row['authorization_available'] or row['receiver_key'] != self.identity.fingerprint:
                raise CameraPeerDenied('relationship unavailable')
            if (fields['source_id'] != row['source_id'] or fields['generation'] != row['generation']
                    or fields['client_id'] != row['client_id'] or fields['client_key_sha256'] != fingerprint(row['client_key'])):
                raise CameraPeerDenied('relationship proof binding changed')
            verify(row['client_key'], signed.signature, 'session-request', fields)
            token = secrets.token_urlsafe(32)
            issued = self.store.issue(fields['relationship_id'], fields['nonce'], sha256(token.encode()).hexdigest(),
                expected_binding={name:row[name] for name in ('client_key','client_id','receiver_key',
                                                             'source_id','generation','issuer_digest','principal_id')})
            del self.challenges[fields['challenge_id']]
            return wire.SessionSnapshot(**self.PROFILE, relationship_id=fields['relationship_id'],
                        generation=fields['generation'], credential_id=issued['credential_id'],
                        token=token, source_id=issued['source_id'], role='overhead-camera',
                        expires_at=iso(issued['expires_at'])).model_dump()

    def sync_rows(self):
        return [row for row in self.store.legacy.credential_rows() if self.store.allowed_credential(row)]

    def relationships(self):
        with closing(self.store.legacy._connect()) as connection:
            ids = [row[0] for row in connection.execute('SELECT relationship_id FROM camera_peer_relationships')]
        result = []
        for relationship_id in ids:
            row = self.store.relationship(relationship_id)
            result.append(wire.RelationshipSnapshot(**self.PROFILE,relationship_id=relationship_id,
                source_id=row['source_id'],label=row['label'],client_key_sha256=fingerprint(row['client_key']),
                generation=row['generation'],state=row['state'],persistent=row['expires_at'] is None,
                authorization_available=row['authorization_available'],
                authorization_expires_at=None if row['expires_at'] is None else iso(row['expires_at'])).model_dump())
        return result
