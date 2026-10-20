"""Demo identities, deliberately separate from operational Fleet credentials."""
from http.cookies import SimpleCookie
import re

from response import error, reply

CAPABILITIES = ['accounts.manage', 'fleet.read', 'fleet.operate', 'fleet.policy', 'camera.manage']


class Sessions:
    def __init__(self, epoch, role):
        self.epoch, self.role = epoch, role
        self.active = False
        password = 'CHANGE_ME'
        self.profile = {'login': 'sample', 'principal_id': 'sample', 'role': role,
                        'display_name': '샘플 운영자', 'email': '', 'account_id': 'sample-account',
                        'grants': [{'resource': 'site:sample', 'capabilities': CAPABILITIES if role == 'operator' else ['fleet.read']}]}
        self.accounts = {'sample-account': {**self.profile, 'revision': 1, 'enabled': True}}
        self.accounts['sample-reviewer-account'] = {**self.profile, 'login': 'sample-reviewer',
            'principal_id': 'sample-reviewer', 'account_id': 'sample-reviewer-account', 'display_name': '샘플 검토자',
            'revision': 1, 'enabled': True}
        self.logins = 0
        self.passwords = dict.fromkeys(self.accounts, password)

    def authorized(self, headers):
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get('cookie', ''))
        except Exception:
            return False
        return self.active and cookie.get('rosy_sample_session') is not None and (
            cookie['rosy_sample_session'].value == f'sample-{self.epoch}')

    def identity(self):
        return {**self.profile, 'via': 'cookie', 'expires_at': None, 'password_change_required': False,
                'site_resource': 'site:sample', 'session_family': 'sample-family', 'revision': self.epoch}

    def cookie(self, clear=False):
        value = '' if clear else f'sample-{self.epoch}'
        return [('Set-Cookie', f'rosy_sample_session={value}; Path=/; HttpOnly; SameSite=Strict'
                 + ('; Max-Age=0' if clear else ''))]

    def handle(self, method, path, body, headers):
        if (method, path) == ('GET', '/auth/connection'):
            return reply({'mode': 'paired', 'password_login': True})
        if (method, path) == ('POST', '/auth/login'):
            login = body.get('login')
            account = next((row for row in self.accounts.values() if row['login'] == login), None)
            if (account is None or body.get('password') != self.passwords.get(account['account_id'])
                    or not account['enabled']):
                return error(401, 'INVALID_CREDENTIALS')
            if self.logins:
                self.epoch += 1
            self.logins += 1
            self.profile = {k: v for k, v in account.items() if k not in ('revision', 'enabled')}
            self.role = self.profile['role']
            self.active = True
            return reply(status=204, headers=self.cookie())
        if not self.authorized(headers):
            return error(401, 'UNAUTHORIZED')
        if method == 'GET' and path in ('/session', '/auth/session'):
            return reply(self.identity())
        if (method, path) == ('GET', '/auth/profile'):
            return reply(self.profile)
        if (method, path) == ('PATCH', '/auth/profile'):
            name = body.get('display_name')
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
                return error(422, 'INVALID_REQUEST')
            self.profile['display_name'] = name.strip()
            self.accounts[self.profile['account_id']]['display_name'] = name.strip()
            return reply(self.profile)
        if (method, path) == ('POST', '/auth/change-password'):
            current = self.passwords[self.profile['account_id']]
            if body.get('current_password') != current:
                return error(403, 'CURRENT_PASSWORD_INCORRECT')
            password = body.get('password')
            if not isinstance(password, str) or len(password) < 8 or password in (current, 'sample'):
                return error(422, 'INVALID_REQUEST')
            self.passwords[self.profile['account_id']] = password
            self.epoch += 1
            return reply(status=204, headers=self.cookie())
        if (method, path) == ('POST', '/auth/logout'):
            self.active = False
            return reply(status=204, headers=self.cookie(clear=True))
        if path.startswith('/auth/accounts'):
            if self.role != 'operator':
                return error(403, 'ACCOUNT_ADMIN_REQUIRED')
            if (method, path) == ('GET', '/auth/accounts'):
                return reply(list(self.accounts.values()))
            if (method, path) == ('POST', '/auth/accounts'):
                if not all(body.get(key) for key in ('login', 'principal_id', 'password', 'role')):
                    return error(422, 'INVALID_REQUEST')
                if any(row['login'] == body['login'] for row in self.accounts.values()):
                    return error(409, 'ACCOUNT_ALREADY_EXISTS')
                identifier = f'sample-account-{len(self.accounts) + 1}'
                self.accounts[identifier] = {k: v for k, v in body.items() if k != 'password'}
                self.accounts[identifier].update(account_id=identifier, revision=1, enabled=True)
                self.passwords[identifier] = body['password']
                return reply(self.accounts[identifier], 201)
            match = re.fullmatch(r'/auth/accounts/([^/]+)(?:/(reset-password|revoke-sessions))?', path)
            if match and method in ('PATCH', 'POST'):
                row = self.accounts.get(match[1])
                if row is None:
                    return error(404, 'ACCOUNT_NOT_FOUND')
                if row['revision'] != body.get('revision'):
                    return error(409, 'ACCOUNT_REVISION_CONFLICT')
                if method == 'PATCH' and match[2] is None:
                    row.update({k: v for k, v in body.items() if k in ('role', 'grants', 'enabled')})
                elif method == 'POST' and match[2] == 'reset-password':
                    if not isinstance(body.get('password'), str) or len(body['password']) < 8:
                        return error(422, 'INVALID_REQUEST')
                    self.passwords[row['account_id']] = body['password']
                elif method != 'POST' or match[2] is None:
                    return None
                row['revision'] += 1
                if row['account_id'] == self.profile['account_id']:
                    self.active = False
                return reply(row)
        return None
