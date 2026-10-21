"""Rosy Account browser session for the optional HTTPS match board."""
import json
from http.cookies import SimpleCookie, CookieError
from urllib.parse import parse_qs, urlsplit

from core_common.protocol.account_client import AccountUnavailable


def cookie(handler, name):
    jar = SimpleCookie()
    try:
        jar.load(handler.headers.get('Cookie', ''))
        return jar[name].value if name in jar else ''
    except CookieError:
        return ''


def set_cookie(name, value, age):
    return ('Set-Cookie', f'{name}={value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={age}')


def same_origin(handler):
    if not handler.account:
        return False
    url = urlsplit(handler.account.callback)
    return handler.headers.get('Origin') == f'{url.scheme}://{url.netloc}'


def route(handler, method):
    url = urlsplit(handler.path)
    if not url.path.startswith('/api/account/'):
        return False
    account = handler.account
    headers = []
    status, body = 200, {}
    try:
        if method == 'GET' and url.path == '/api/account/session':
            body, claims = (account.browser_session(cookie(handler, 'rosy_app_account')) if account else
                            ({'enabled': False, 'authenticated': False, 'profile': None, 'profile_url': None}, None))
            body['can_operate'] = bool(claims and claims.permits(account.resource, 'games.operate'))
        elif method == 'GET' and url.path == '/api/account/login' and account:
            flow, target = account.start('/')
            headers = [set_cookie('rosy_account_flow', flow, 600), ('Location', target)]
            status = 303
        elif method == 'GET' and url.path == '/api/account/callback' and account:
            query = parse_qs(url.query, max_num_fields=8)
            if set(query) != {'state', 'code'} or any(len(v) != 1 for v in query.values()):
                raise ValueError('Invalid callback')
            session, target = account.finish(cookie(handler, 'rosy_account_flow'), query['state'][0], query['code'][0])
            headers = [set_cookie('rosy_app_account', session, 2592000),
                       set_cookie('rosy_account_flow', '', 0), ('Location', target)]
            status = 303
        elif method == 'POST' and url.path == '/api/account/logout' and same_origin(handler):
            headers = [set_cookie('rosy_app_account', '', 0)]
            account.logout(cookie(handler, 'rosy_app_account'))
        else:
            status, body = 403, {'error': 'Account access refused'}
    except AccountUnavailable:
        status, body = 503, {'error': 'Account service unavailable'}
    except ValueError:
        status, body = 401, {'error': 'Account session refused'}
    handler._send(status, 'application/json', json.dumps(body).encode(), headers=headers)
    return True
