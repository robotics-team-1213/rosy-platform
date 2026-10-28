"""CORE media delegation registry. Restart/revocation always closes old grants."""

import math
import secrets
import threading

from core_common.protocol.media_tokens import MediaClaims, MediaTokenRejected, public_media_key, sign_media, verify_media
from core_common.protocol.media_grants import MediaGrant


class MediaGrantRefused(ValueError):
    pass


class MediaGrantService:
    def __init__(self, *, robot_id, audience, private_key, key_id, owner_allowed):
        MediaClaims.model_validate({'iss': 'robot:' + robot_id, 'aud': audience, 'sub': 'configuration',
            'jti': '0' * 32, 'robot_id': robot_id, 'path': f'robots/{robot_id}/front',
            'action': 'read', 'iat': 0, 'exp': 60})
        if not isinstance(key_id, str) or not 1 <= len(key_id) <= 128:
            raise MediaGrantRefused('invalid media key identity')
        self.robot_id, self.audience = robot_id, audience
        self._private_key, self._key_id = private_key, key_id
        self._public_keys = {key_id: public_media_key(private_key)}
        self.owner_allowed = owner_allowed
        self._records = {}
        self._lock = threading.RLock()

    def _allowed(self, owner, action):
        try:
            return self.owner_allowed(owner, action) is True
        except Exception:
            return False

    @staticmethod
    def _time(now):
        if isinstance(now, bool) or not isinstance(now, (float, int)) or not math.isfinite(now) or now < 0:
            raise MediaGrantRefused('invalid media clock')
        return int(now)

    def _mint(self, grant_id, owner, action, now):
        claims = {'iss': 'robot:' + self.robot_id, 'aud': self.audience, 'sub': owner,
                  'jti': grant_id, 'robot_id': self.robot_id, 'action': action,
                  'path': f'robots/{self.robot_id}/front', 'iat': now, 'exp': now + 60}
        try:
            token = sign_media(claims, self._private_key, self._key_id)
        except MediaTokenRejected:
            raise MediaGrantRefused('media authority is not configured correctly') from None
        return MediaGrant(grant_id, token, now + 60, self.audience, self.robot_id, claims['path'], action)

    def issue(self, token_id, robot_id, action, *, now):
        stamp = self._time(now)
        if robot_id != self.robot_id or action not in ('read', 'publish') or not self._allowed(token_id, action):
            raise MediaGrantRefused('media scope or original authority refused')
        with self._lock:
            self._records = {key: value for key, value in self._records.items() if value['exp'] > stamp}
            if len(self._records) >= 128:
                raise MediaGrantRefused('media grant capacity reached')
            grant_id = secrets.token_hex(16)
            grant = self._mint(grant_id, token_id, action, stamp)
            self._records[grant_id] = {'owner': token_id, 'action': action, 'exp': grant.expires_at}
            return grant

    def renew(self, grant_id, token_id, *, now):
        stamp = self._time(now)
        with self._lock:
            record = self._records.get(grant_id)
            if record is None or record['owner'] != token_id or record['exp'] <= stamp:
                raise MediaGrantRefused('media grant expired or outside scope')
            if not self._allowed(token_id, record['action']):
                self._records.pop(grant_id, None)
                raise MediaGrantRefused('original media authority revoked')
            grant = self._mint(grant_id, token_id, record['action'], stamp)
            record['exp'] = grant.expires_at
            return grant

    def revoke(self, grant_id, token_id):
        with self._lock:
            record = self._records.get(grant_id)
            if record is not None and record['owner'] != token_id:
                raise MediaGrantRefused('media grant owner mismatch')
            self._records.pop(grant_id, None)

    def check(self, token, *, now):
        try:
            claims = verify_media(token, self._public_keys, robot_id=self.robot_id,
                                  audience=self.audience, now=now)
        except MediaTokenRejected:
            return {'active': False}
        with self._lock:
            record = self._records.get(claims.jti)
            if (record is None or record['owner'] != claims.sub or record['action'] != claims.action
                    or record['exp'] <= now):
                return {'active': False}
            if not self._allowed(record['owner'], record['action']):
                self._records.pop(claims.jti, None)
                return {'active': False}
            return {'active': True, 'grant_id': claims.jti, 'robot_id': claims.robot_id,
                    'path': claims.path, 'action': claims.action, 'audience': claims.aud,
                    'expires_at': min(claims.exp, record['exp'])}
