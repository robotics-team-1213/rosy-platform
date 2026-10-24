"""Account boundary for the unchanged 937 dataset server.

Run: python -m learning.curation.perception.legacy_review_account --config PRIVATE_JSON
The TLS terminator forwards only to this loopback listener; the legacy server must
separately bind 127.0.0.1:18770. No data files are read or changed by this wrapper.
"""
import argparse
from hashlib import sha256
from html import escape
from http.client import HTTPConnection, HTTPException
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import parse_qs, urlsplit

from core_common.protocol.account_client import AccountUnavailable, load_account_client


BACKEND = ('127.0.0.1', 18770)
READ_PATH = re.compile(r'/(?:image|mask|rawmask|info)/[0-9]+/[A-Za-z0-9_.-]+\Z')
MAX_RESPONSE = 32 * 1024 * 1024


def private_file(path, bounded=True):
    path = Path(path)
    if (path.is_symlink() or not path.is_file()
            or (os.name == 'posix' and path.stat().st_mode & 0o077)
            or (bounded and path.stat().st_size > 65536)):
        raise ValueError('Configuration must be a private regular file')
    return path


def private_directory(path):
    path = Path(path)
    if (path.is_symlink() or not path.is_dir()
            or (os.name == 'posix' and path.stat().st_mode & 0o077)):
        raise ValueError('State directory must be private')
    return path


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, *, origin, account, audit_db):
        parsed = urlsplit(origin)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment
                or account.callback != origin + '/api/account/callback'
                or not re.fullmatch(r'project:[A-Za-z0-9._-]{1,96}', account.resource)):
            raise ValueError('Fixed HTTPS origin and project receiver required')
        self.origin, self.host, self.account = origin, parsed.netloc, account
        suffix = sha256((origin + '/' + account.resource).encode()).hexdigest()[:20]
        self.session_cookie, self.flow_cookie = '__Host-937-' + suffix, '__Host-937-flow-' + suffix
        self.audit_db = Path(audit_db)
        private_directory(self.audit_db.parent)
        if self.audit_db.exists():
            private_file(self.audit_db, bounded=False)
        else:
            fd = os.open(self.audit_db, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        with sqlite3.connect(self.audit_db) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS review_audit (
                id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, resource TEXT NOT NULL,
                body_sha256 TEXT NOT NULL, created REAL NOT NULL, outcome TEXT NOT NULL)''')
            # A crashed process cannot know whether its last upstream write committed.
            db.execute("UPDATE review_audit SET outcome='unknown' WHERE outcome='intent'")
        super().__init__(('127.0.0.1', port), ReviewHandler)

    def service_actions(self):
        try:
            self.account.retry_revocations()
        except (AccountUnavailable, ValueError):
            pass


class ReviewHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        pass  # Authorization callback query strings must never enter access logs.

    def reply(self, status, body=b'', content_type='application/json', *, location=None, cookies=()):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        if location:
            self.send_header('Location', location)
        for cookie in cookies:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def cookie(self, name, value='', clear=False):
        return f'{name}={value}; Path=/; Secure; HttpOnly; SameSite=Lax' + ('; Max-Age=0' if clear else '')

    def cookies(self):
        values = self.headers.get_all('Cookie', [])
        if len(values) > 1 or (values and len(values[0]) > 8192):
            raise ValueError('Invalid cookies')
        parsed = SimpleCookie()
        try:
            parsed.load(values[0] if values else '')
        except CookieError:
            raise ValueError('Invalid cookies') from None
        return parsed

    def boundary(self, unsafe=False):
        if self.headers.get_all('Host') != [self.server.host]:
            self.reply(421)
            return False
        if unsafe and self.headers.get_all('Origin') != [self.server.origin]:
            self.reply(403)
            return False
        if len(self.path) > 2048 or not self.path.startswith('/') or self.path.startswith('//'):
            self.reply(400)
            return False
        return True

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, unsafe):
        if not self.boundary(unsafe):
            return
        try:
            self.handle_request(unsafe)
        except AccountUnavailable:
            self.reply(503)
        except (ValueError, UnicodeDecodeError):
            self.reply(400)
        except sqlite3.Error:
            self.reply(503)

    def handle_request(self, unsafe):
        account = self.server.account
        cookies = self.cookies()
        session = cookies.get(self.server.session_cookie)
        session = session.value if session else ''
        if not unsafe and self.path == '/api/account/login':
            flow, destination = account.start('/')
            self.reply(303, location=destination,
                       cookies=[self.cookie(self.server.flow_cookie, flow)])
            return
        parsed = urlsplit(self.path)
        if not unsafe and parsed.path == '/api/account/callback':
            if parsed.fragment:
                raise ValueError('Invalid callback')
            query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
            if set(query) != {'code', 'state'} or any(len(v) != 1 or not v[0] for v in query.values()):
                raise ValueError('Invalid callback')
            flow = cookies.get(self.server.flow_cookie)
            session, target = account.finish(flow.value if flow else '', query['state'][0], query['code'][0])
            if target != '/':
                raise ValueError('Invalid destination')
            self.reply(303, location='/', cookies=[self.cookie(self.server.session_cookie, session),
                       self.cookie(self.server.flow_cookie, clear=True)])
            return
        if unsafe and self.path == '/api/account/logout':
            try:
                account.logout(session)
            except AccountUnavailable:
                pass  # AccountClient already removed local session and persisted pending revoke.
            self.reply(303, location='/', cookies=[self.cookie(self.server.session_cookie, clear=True),
                       self.cookie(self.server.flow_cookie, clear=True)])
            return
        if unsafe:
            allowed = self.path == '/api/review'
        else:
            allowed = self.path in {'/', '/api/data', '/reviews.csv', '/api/account/session'} or bool(READ_PATH.fullmatch(self.path))
            if any(component in {'.', '..'} for component in self.path.split('/')):
                allowed = False
        if not allowed:
            self.reply(404)
            return
        claims = account.resolve(session)
        if claims is None:
            self.reply(303 if self.path == '/' else 401,
                       location='/api/account/login' if self.path == '/' else None)
            return
        if not claims.permits(account.resource, 'learning.view'):
            self.reply(403)
            return
        if self.path == '/api/account/session':
            profile = account.profile(session)
            self.reply(200, json.dumps({'account_id': claims.sub, 'profile': profile,
                                       'profile_url': account.profile_url}).encode())
            return
        body, audit_id = None, None
        if unsafe:
            if (self.headers.get_all('Transfer-Encoding')
                    or self.headers.get_all('Content-Type') != ['application/json']
                    or len(self.headers.get_all('Content-Length', [])) != 1):
                raise ValueError('Invalid request framing')
            size = int(self.headers['Content-Length'])
            if not 0 < size <= 20000:
                self.reply(413)
                return
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError('Incomplete body')
            data = json.loads(body)
            if (not isinstance(data, dict) or set(data) != {'index', 'status', 'note'}
                    or type(data['index']) is not int or data['index'] < 0
                    or data['status'] not in ('pending', 'ok', 'fix', 'hold')
                    or not isinstance(data['note'], str) or len(data['note']) > 4000):
                raise ValueError('Invalid review')
            capability = 'learning.approve' if data['status'] == 'ok' else 'learning.edit'
            if not claims.permits(account.resource, capability):
                self.reply(403)
                return
            with sqlite3.connect(self.server.audit_db) as db:
                audit_id = db.execute('INSERT INTO review_audit(account_id,resource,body_sha256,created,outcome) '
                    'VALUES(?,?,?,?,?)', (claims.sub, account.resource, sha256(body).hexdigest(), time.time(), 'intent')).lastrowid
        self.proxy(body, audit_id)

    def proxy(self, body, audit_id):
        connection = HTTPConnection(*BACKEND, timeout=5)
        try:
            headers = {'Host': f'{BACKEND[0]}:{BACKEND[1]}', 'Origin': f'http://{BACKEND[0]}:{BACKEND[1]}'}
            if body is not None:
                headers['Content-Type'] = 'application/json'
            connection.request('POST' if body is not None else 'GET', self.path, body=body, headers=headers)
            response = connection.getresponse()
            result = response.read(MAX_RESPONSE + 1)
            if len(result) > MAX_RESPONSE or 300 <= response.status < 400:
                raise OSError('Invalid backend response')
            if audit_id:
                self.outcome(audit_id, 'success' if 200 <= response.status < 300 else 'upstream_error')
            content_type = response.getheader('Content-Type', 'application/octet-stream')
            if self.path == '/' and response.status == 200:
                bar = ('<nav aria-label="Rosy Account"><a href="' + escape(self.server.account.profile_url, quote=True)
                       + '">Rosy Account profile</a> <form method="post" action="/api/account/logout" style="display:inline">'
                       '<button>Log out</button></form></nav>')
                result = result.replace(b'<body>', b'<body>' + bar.encode(), 1)
            self.reply(response.status, result, content_type)
        except (OSError, HTTPException):
            if audit_id:
                self.outcome(audit_id, 'unknown')
            self.reply(502)
        finally:
            connection.close()

    def outcome(self, audit_id, value):
        with sqlite3.connect(self.server.audit_db) as db:
            db.execute('UPDATE review_audit SET outcome=? WHERE id=?', (value, audit_id))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = private_file(args.config)
    settings = json.loads(config.read_bytes())
    if not isinstance(settings, dict) or set(settings) != {'origin', 'port', 'receiver_config', 'audit_db'}:
        raise ValueError('Invalid wrapper configuration')
    if type(settings['port']) is not int or not 1024 <= settings['port'] <= 65535 or settings['port'] == BACKEND[1]:
        raise ValueError('Invalid wrapper port')
    base = config.resolve().parent
    receiver = private_file(base / settings['receiver_config'])
    receiver_settings = json.loads(receiver.read_bytes())
    state = base / settings['audit_db']
    private_directory(state.parent)
    session_db = receiver.parent / receiver_settings['session_db']
    private_directory(session_db.parent)
    if session_db.exists():
        private_file(session_db, bounded=False)
    os.umask(0o077)
    account = load_account_client(receiver, destinations=('/',))
    ReviewServer(settings['port'], origin=settings['origin'], account=account, audit_db=state).serve_forever()


if __name__ == '__main__':
    main()
