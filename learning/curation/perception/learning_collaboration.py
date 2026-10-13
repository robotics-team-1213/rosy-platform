"""Optional project authorization and account/import HTTP routes for the review app."""
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
import threading
from urllib.parse import parse_qs, urlparse


COOKIE = 'rosy_learning_session'
BINDING = 'rosy_learning_oauth'


def cookie(handler, name):
    try:
        values = SimpleCookie(handler.headers.get('Cookie', ''))
        return values[name].value if name in values else ''
    except Exception:
        return ''


class Collaboration:
    def __init__(self, accounts, store, *, oauth=None, imports=None):
        self.accounts, self.oauth, self.imports = accounts, oauth, imports
        self.origin = (accounts.config().get('public_origin') if hasattr(accounts, 'config')
                       else getattr(accounts, 'public_origin', None))
        self.authority = urlparse(self.origin).netloc if self.origin else None
        if self.origin:
            parsed = urlparse(self.origin)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.path or parsed.query or parsed.fragment):
                raise ValueError('public_origin must be an HTTPS origin without path')
        with store.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='collaboration_project'").fetchone()
            if row and row[0] != accounts.project_id:
                raise ValueError('workspace already belongs to another collaboration project')
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('collaboration_project',?)", (accounts.project_id,))
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='learning-import') if imports else None
        self.slots = threading.BoundedSemaphore(4)
        self.tasks = {}
        self.lock = threading.Lock()

    def shutdown(self):
        if self.pool:
            self.pool.shutdown(wait=True, cancel_futures=True)

    def set_cookie(self, handler, name, value, *, clear=False):
        suffix = '; Secure' if self.origin else ''
        handler.extra_headers.append(('Set-Cookie', f'{name}={value}; Path=/; HttpOnly; SameSite=Lax'
                                     + ('; Max-Age=0' if clear else '') + suffix))

    def identity(self, handler):
        principal = self.accounts.authenticate(cookie(handler, COOKIE))
        self.accounts.require(principal, 'view')
        handler.learning_principal = principal
        return principal

    def get(self, handler, path, token):
        if path in ('/accounts', '/accounts.js') or path.startswith('/common/') or path == '/app.css':
            return False
        if path == '/api/accounts/options':
            handler.send({'enabled': True, 'oauth': self.oauth is not None,
                          'project_id': self.accounts.project_id})
            return True
        if path == '/oauth/huggingface/callback':
            if not self.oauth:
                raise ValueError('Hugging Face OAuth is not configured')
            query = parse_qs(urlparse(handler.path).query, strict_parsing=True)
            if any(len(v) != 1 for v in query.values()):
                raise ValueError('duplicate OAuth callback parameters')
            session, _ = self.oauth.complete({k: v[0] for k, v in query.items()},
                                             cookie(handler, BINDING), session=cookie(handler, COOKIE) or None)
            self.set_cookie(handler, BINDING, '', clear=True)
            if session:
                self.set_cookie(handler, COOKIE, session)
            handler.extra_headers.append(('Location', '/accounts'))
            handler.send(b'', 303)
            return True
        try:
            principal = self.identity(handler)
        except PermissionError:
            if not path.startswith('/api/'):
                handler.extra_headers.append(('Location', '/accounts'))
                handler.send(b'', 303)
            else:
                handler.send({'error': '로그인이 필요합니다.'}, 401)
            return True
        if path == '/api/accounts/session':
            public = {key: principal[key] for key in ('user_id', 'project_id', 'capabilities')}
            handler.send(dict(public, token=token, connections=self.accounts.connections(principal)))
            return True
        if path == '/api/learning/imports':
            handler.send({'jobs': self.imports.list(principal, self.accounts.project_id) if self.imports else []})
            return True
        return False

    def authorize_write(self, handler, path, body):
        principal = self.identity(handler)
        if path in ('/api/import', '/api/cad', '/api/learning/register'):
            raise PermissionError('project users cannot import arbitrary server filesystem paths')
        if path.startswith(('/api/frames/', '/api/masks/', '/api/mask-preview/')):
            capability = 'approve' if body.get('action') == 'approve' else 'edit'
        elif path == '/api/prepare':
            capability = 'approve'
        elif path.startswith('/api/learning/imports/'):
            capability = 'import'
        elif path.startswith('/api/accounts/'):
            capability = 'view'
        elif path.startswith('/api/learning/'):
            capability = 'manage'
        else:
            capability = 'manage'
        self.accounts.require(principal, capability)
        body.pop('reviewer', None)
        body.pop('author', None)
        return principal

    def submit(self, job, principal):
        if job['status'] != 'queued':
            return
        with self.lock:
            if job['id'] in self.tasks:
                return
            if not self.slots.acquire(blocking=False):
                raise ValueError('가져오기 대기열이 가득 찼습니다. 잠시 후 재시도하세요.')
            future = self.pool.submit(self.imports.run, job['id'], principal)
            self.tasks[job['id']] = future

        def done(_):
            with self.lock:
                self.tasks.pop(job['id'], None)
                self.slots.release()
        future.add_done_callback(done)

    def post(self, handler, path, body, token):
        if path == '/api/accounts/login':
            session, _ = self.accounts.login(body.get('username'), body.get('password'),
                                              address=handler.client_address[0])
            self.set_cookie(handler, COOKIE, session)
            handler.send({'ok': True})
            return True
        if path == '/api/accounts/oauth' and body.get('purpose') == 'login':
            if not self.oauth:
                raise ValueError('Hugging Face OAuth is not configured')
            url, binding = self.oauth.begin('login')
            self.set_cookie(handler, BINDING, binding)
            handler.send({'url': url})
            return True
        principal = self.authorize_write(handler, path, body)
        if path == '/api/accounts/logout':
            self.accounts.logout(cookie(handler, COOKIE))
            self.set_cookie(handler, COOKIE, '', clear=True)
            handler.send({'ok': True})
        elif path == '/api/accounts/oauth':
            if not self.oauth or body.get('purpose') != 'link':
                raise ValueError('Hugging Face account linking is unavailable')
            url, binding = self.oauth.begin('link', session=cookie(handler, COOKIE))
            self.set_cookie(handler, BINDING, binding)
            handler.send({'url': url})
        elif path == '/api/accounts/connect':
            handler.send(self.accounts.connect_token(principal, body.get('token'),
                         sharing=body.get('sharing', 'personal'), resources=body.get('resources', [])))
        elif path == '/api/accounts/disconnect':
            self.accounts.disconnect(principal, body.get('connection_id'))
            handler.send({'ok': True})
        elif path.startswith('/api/learning/imports/'):
            if not self.imports:
                raise ValueError('자료 가져오기가 설정되지 않았습니다.')
            if path.endswith('/create'):
                job = self.imports.create(principal, self.accounts.project_id,
                    body.get('connection_id'), body.get('repo_type'), body.get('repo_id'),
                    body.get('revision'), body.get('files'), body.get('rights'))
            elif path.endswith('/retry'):
                job = self.imports.retry(principal, self.accounts.project_id, body.get('id'))
            elif path.endswith('/cancel'):
                job = self.imports.cancel(principal, self.accounts.project_id, body.get('id'))
            else:
                raise ValueError('unknown import action')
            self.submit(job, principal)
            handler.send(job)
        else:
            return False
        return True


def load(config_path, store):
    """Private configuration is opened only when explicitly enabled by the operator."""
    import json
    from pathlib import Path
    from learning_accounts import Accounts
    from learning_imports import LearningImports
    from learning_oauth import OAuth
    path = Path(config_path).resolve()
    config = json.loads(path.read_text(encoding='utf-8'))

    def private_path(name):
        value = Path(config[name])
        if not value.is_absolute():
            raise ValueError(f'{name} must be an absolute private path')
        return value

    accounts = Accounts(private_path('accounts_db'), private_path('key_file'), path)
    oauth = OAuth(accounts) if config.get('oauth') else None

    def credential(actor, project, connection, generation=None, resource=None):
        accounts.authorize(actor, project, 'import')
        return accounts.credential(actor, connection, generation=generation, resource=resource)

    imports = LearningImports(private_path('imports_root'), accounts.authorize, credential)
    return accounts, oauth, imports
