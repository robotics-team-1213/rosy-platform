"""Demo identities, deliberately separate from operational Fleet credentials."""
from http.cookies import SimpleCookie

from response import error, reply

CAPABILITIES = ['accounts.manage', 'fleet.read', 'fleet.operate', 'fleet.policy', 'camera.manage']


class Sessions:
    def __init__(self, epoch, role):
        self.epoch, self.role = epoch, role
        self.active = False
        self.password = 'sample-password'
        self.profile = {'login': 'sample', 'principal_id': 'sample', 'role': role,
                        'display_name': '샘플 운영자', 'email': '', 'account_id': 'sample-account',
                        'grants': [{'resource': 'site:sample', 'capabilities': CAPABILITIES}]}

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
            if body.get('login') != 'sample' or body.get('password') != self.password:
                return error(401, 'INVALID_CREDENTIALS')
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
            return reply(self.profile)
        if (method, path) == ('POST', '/auth/change-password'):
            if body.get('current_password') != self.password:
                return error(403, 'CURRENT_PASSWORD_INCORRECT')
            password = body.get('password')
            if not isinstance(password, str) or len(password) < 8 or password in (self.password, 'sample'):
                return error(422, 'INVALID_REQUEST')
            self.password = password
            self.epoch += 1
            return reply(status=204, headers=self.cookie())
        if (method, path) == ('POST', '/auth/logout'):
            self.active = False
            return reply(status=204, headers=self.cookie(clear=True))
        return None
