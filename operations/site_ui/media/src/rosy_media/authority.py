"""Bounded media leases. The transport adapter must tick at least once a second."""

import base64
import json
import math
import threading

from core_common.protocol.media_tokens import MediaTokenRejected, verify_media


class MediaAuthority:
    def __init__(self, *, audience, public_keys, validate_online, kick, site_keys=None):
        if not 1 <= len(public_keys) <= 6:
            raise ValueError('D-789 supports one to six registered robot sources')
        self.audience, self._keys = audience, public_keys
        # D-801: the site's own READ-only grant keys, separate from every robot key.
        self._site_keys = dict(site_keys or {})
        self._validate_online, self._kick = validate_online, kick
        self._intents, self._sessions = {}, {}
        self._lock = threading.RLock()

    def _claims(self, token, now):
        for robot_id, keys in self._keys.items():
            try:
                claims = verify_media(token, keys, robot_id=robot_id, audience=self.audience, now=now)
            except MediaTokenRejected:
                continue
            # A robot key never speaks for the site.
            return claims if claims.iss == 'robot:' + robot_id else None
        robot_id = _unverified_robot(token) if self._site_keys else None
        if robot_id not in self._keys:
            return None
        try:
            claims = verify_media(token, self._site_keys, robot_id=robot_id, audience=self.audience, now=now)
        except MediaTokenRejected:
            return None
        return claims if claims.iss == self.audience and claims.action == 'read' else None

    def _online(self, token, claims, now):
        try:
            result = self._validate_online(claims.robot_id, token, now)
            return (result.get('active') is True and result.get('grant_id') == claims.jti
                    and result.get('robot_id') == claims.robot_id and result.get('path') == claims.path
                    and result.get('action') == claims.action and result.get('audience') == claims.aud
                    and now < result.get('expires_at', 0) <= claims.exp)
        except Exception:
            return False

    def _validated(self, token, now):
        claims = self._claims(token, now)
        return claims if claims and self._online(token, claims, now) else None

    def intent(self, token, *, now):
        claims = self._validated(token, now)
        if claims is None or claims.action != 'read':
            return None
        with self._lock:
            self._intents = {key: value for key, value in self._intents.items() if value['expires'] > now}
            if len(self._intents) >= 128:
                return None
            self._intents[claims.jti] = {'claims': claims, 'token': token, 'expires': min(now + 10, claims.exp)}
            return claims.jti

    def cancel_intent(self, grant_id, token, *, now):
        claims = self._validated(token, now)
        if claims is None or claims.jti != grant_id or claims.action != 'read':
            return False
        with self._lock:
            self._intents.pop(grant_id, None)
        return True

    def demand(self, robot_id, *, now):
        with self._lock:
            pending = any(value['claims'].robot_id == robot_id and value['expires'] > now
                          for value in self._intents.values())
            active = any(value['claims'].robot_id == robot_id and value['claims'].action == 'read'
                         and value['expires'] > now and not value.get('closing')
                         for value in self._sessions.values())
        return {'active': pending or active, 'robot_id': robot_id,
                'fps': 15, 'target_bitrate': 800000, 'max_bitrate': 1000000}

    def authorize(self, token, action, path, session_id, *, now):
        claims = self._validated(token, now)
        if (claims is None or claims.action != action or claims.path != path
                or not isinstance(session_id, str) or not 1 <= len(session_id) <= 128):
            return False
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                return (not existing.get('closing') and existing['claims'] == claims
                        and existing['expires'] > now)
            if len(self._sessions) >= 128 or any(value['claims'].jti == claims.jti
                                               for value in self._sessions.values()):
                return False
            if action == 'read':
                intent = self._intents.get(claims.jti)
                if intent is None or intent['expires'] <= now:
                    return False
            elif action == 'publish':
                if (not self.demand(claims.robot_id, now=now)['active']
                        or any(value['claims'].robot_id == claims.robot_id
                               and value['claims'].action == 'publish' for value in self._sessions.values())):
                    return False
            else:
                return False
            self._intents.pop(claims.jti, None)
            self._sessions[session_id] = {'claims': claims, 'token': token,
                                          'expires': min(now + 60, claims.exp), 'slow_since': None}
            return True

    def renew(self, session_id, token, *, now):
        claims = self._validated(token, now)
        if claims is None:
            return False
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None or record.get('closing') or record['expires'] <= now:
                return False
            prior = record['claims']
            if ((claims.jti, claims.sub, claims.robot_id, claims.path, claims.action, claims.aud)
                    != (prior.jti, prior.sub, prior.robot_id, prior.path, prior.action, prior.aud)):
                return False
            record.update(claims=claims, token=token, expires=min(now + 60, claims.exp))
            return True

    def _close(self, session_id):
        record = self._sessions.get(session_id)
        if record is None:
            return
        record['closing'] = True
        # A failed kick must remain retryable and fail the supervisor health gate.
        self._kick(session_id)
        self._sessions.pop(session_id, None)

    def tick(self, *, now):
        with self._lock:
            for grant_id, intent in list(self._intents.items()):
                if intent['expires'] <= now or not self._online(intent['token'], intent['claims'], now):
                    self._intents.pop(grant_id, None)
            # Readers first so their removal immediately retracts source demand.
            sessions = sorted(list(self._sessions.items()), key=lambda item: item[1]['claims'].action != 'read')
            for session_id, record in sessions:
                claims = record['claims']
                if (record.get('closing') or record['expires'] <= now or claims.exp <= now
                        or not self._online(record['token'], claims, now)
                        or (claims.action == 'publish' and not self.demand(claims.robot_id, now=now)['active'])):
                    self._close(session_id)

    def report_queue(self, session_id, token, *, queue_ms, now):
        if (isinstance(queue_ms, bool) or not isinstance(queue_ms, (int, float))
                or not math.isfinite(queue_ms) or not 0 <= queue_ms <= 5000):
            return False
        claims = self._validated(token, now)
        with self._lock:
            record = self._sessions.get(session_id)
            if (claims is None or record is None or record['claims'].jti != claims.jti
                    or claims.action != 'read' or record['expires'] <= now):
                return False
            if queue_ms <= 500:
                record['slow_since'] = None
            elif record['slow_since'] is None:
                record['slow_since'] = now
            elif now - record['slow_since'] >= 2:
                self._close(session_id)
            return True

    def source_demand(self, robot_id, token, *, now):
        claims = self._validated(token, now)
        if claims is None or claims.robot_id != robot_id or claims.action != 'publish':
            return None
        return self.demand(robot_id, now=now)

    def close_session(self, session_id, token, *, now):
        claims = self._validated(token, now)
        with self._lock:
            record = self._sessions.get(session_id)
            if (claims is None or record is None or claims.jti != record['claims'].jti
                    or claims.sub != record['claims'].sub):
                return False
            self._close(session_id)
            return True

    def bound_session(self, token, *, now):
        claims = self._validated(token, now)
        if claims is None:
            return None
        with self._lock:
            for session_id, record in self._sessions.items():
                prior = record['claims']
                if (not record.get('closing') and record['expires'] > now
                        and (claims.jti, claims.sub, claims.robot_id, claims.path, claims.action)
                        == (prior.jti, prior.sub, prior.robot_id, prior.path, prior.action)):
                    return {'session_id': session_id, 'expires_at': record['expires']}
        return None


def _unverified_robot(token):
    """Only selects which registered robot to verify a site grant for; the signature decides."""
    try:
        part = token.split('.')[1]
        value = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))['robot_id']
        return value if isinstance(value, str) else None
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None
