"""Optional project authorization and account/import HTTP routes for the review app."""
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
import hashlib
import hmac
import threading
import time
from urllib.parse import parse_qs, urlparse

from learning_repos import create_private, delete_private, list_repos


COOKIE = 'rosy_learning_session'
BINDING = 'rosy_learning_oauth'


def cookie(handler, name):
    try:
        values = SimpleCookie(handler.headers.get('Cookie', ''))
        return values[name].value if name in values else ''
    except Exception:
        return ''


class Collaboration:
    def __init__(self, accounts, store, *, oauth=None, imports=None, repos=None):
        self.accounts, self.oauth, self.imports, self.repos = accounts, oauth, imports, repos
        self.store = store
        self.receiver = getattr(accounts, 'receiver', None)
        self.unavailable = ()
        if self.receiver:
            from core_common.protocol.account_client import AccountUnavailable
            self.unavailable = (AccountUnavailable,)
        self.origin = (accounts.config().get('public_origin') if hasattr(accounts, 'config')
                       else getattr(accounts, 'public_origin', None))
        self.authority = urlparse(self.origin).netloc if self.origin else None
        if self.origin:
            parsed = urlparse(self.origin)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.path or parsed.query or parsed.fragment):
                raise ValueError('public_origin must be an HTTPS origin without path')
        # Cookies share a host across ports; each trusted project origin needs its own flow.
        self.cookie_suffix = ('_' + hashlib.sha256((accounts.project_id + '\0' + (self.origin or '')).encode()).hexdigest()[:24]
                              if self.receiver else '')
        if oauth:
            oauth.validate_origin(self.origin)
        with store.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='collaboration_project'").fetchone()
            if row and row[0] != accounts.project_id:
                raise ValueError('workspace already belongs to another collaboration project')
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('collaboration_project',?)", (accounts.project_id,))
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='learning-import') if imports else None
        self.slots = threading.BoundedSemaphore(4)
        self.tasks = {}
        self.retries = {}
        self.closing = False
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        if self.receiver:
            def retry():
                while not self.stopping.is_set():
                    try:
                        self.receiver.retry_revocations()
                    except (ValueError, *self.unavailable):
                        pass
                    self.stopping.wait(20)
            self.revocations = threading.Thread(target=retry, daemon=True, name='account-revocations')
            self.revocations.start()

    def shutdown(self):
        with self.lock:
            self.closing = True
        self.stopping.set()
        if self.receiver:
            self.revocations.join(timeout=4)
        if self.pool:
            self.pool.shutdown(wait=True, cancel_futures=True)

    def set_cookie(self, handler, name, value, *, clear=False):
        name += self.cookie_suffix
        suffix = '; Secure' if self.origin else ''
        handler.extra_headers.append(('Set-Cookie', f'{name}={value}; Path=/; HttpOnly; SameSite=Lax'
                                     + ('; Max-Age=0' if clear else '') + suffix))

    def cookie(self, handler, name):
        return cookie(handler, name + self.cookie_suffix)

    def identity(self, handler):
        handler.learning_signed_in = False
        principal = self.accounts.authenticate(self.cookie(handler, COOKIE))
        handler.learning_signed_in = True
        self.accounts.require(principal, 'view')
        handler.learning_principal = principal
        return principal

    def signed_in(self, handler):
        try:
            self.accounts.authenticate(self.cookie(handler, COOKIE))
            return True
        except PermissionError:
            return False

    def csrf(self, handler, token):
        return hmac.new(token.encode(), self.cookie(handler, COOKIE).encode(), hashlib.sha256).hexdigest() if self.receiver else token

    def get(self, handler, path, token):
        try:
            return self._get(handler, path, token)
        except self.unavailable:
            if path == '/api/account/callback':
                return self.callback_failure(handler, 'account_unavailable')
            handler.send({'error':'Rosy Account 연결을 확인하세요.'}, 503)
            return True
        except ValueError:
            if self.receiver and path == '/api/account/callback':
                return self.callback_failure(handler, 'account_callback_failed')
            raise

    def callback_failure(self, handler, error):
        self.set_cookie(handler, 'rosy_account_flow', '', clear=True)
        handler.extra_headers.append(('Location', '/accounts?error=' + error))
        handler.send(b'', 303)
        return True

    def _get(self, handler, path, token):
        if self.receiver and path == '/api/account/login':
            query = parse_qs(urlparse(handler.path).query)
            target = query.get('return', ['/accounts'])[0]
            binding, url = self.receiver.start(target)
            self.set_cookie(handler, 'rosy_account_flow', binding)
            handler.extra_headers.append(('Location', url))
            handler.send(b'', 303)
            return True
        if self.receiver and path == '/api/account/callback':
            query = parse_qs(urlparse(handler.path).query, strict_parsing=True)
            if set(query) != {'code','state'} or any(len(v) != 1 for v in query.values()):
                raise ValueError('invalid Account callback')
            session, target = self.receiver.finish(self.cookie(handler, 'rosy_account_flow'), query['state'][0], query['code'][0])
            self.set_cookie(handler, 'rosy_account_flow', '', clear=True)
            self.set_cookie(handler, COOKIE, session)
            handler.extra_headers.append(('Location', target))
            handler.send(b'',303)
            return True
        if path in ('/accounts', '/accounts.js', '/account-session.js', '/commands.js', '/app.css') or path.startswith('/common/'):
            return False
        if path == '/api/accounts/options':
            handler.send({'enabled': True, 'oauth': self.oauth is not None,
                          'rosy_account': self.receiver is not None,
                          'project_id': self.accounts.project_id})
            return True
        if path == '/oauth/huggingface/callback':
            if not self.oauth:
                raise ValueError('Hugging Face OAuth is not configured')
            query = parse_qs(urlparse(handler.path).query, strict_parsing=True)
            if any(len(v) != 1 for v in query.values()):
                raise ValueError('duplicate OAuth callback parameters')
            session, _ = self.oauth.complete({k: v[0] for k, v in query.items()},
                                             self.cookie(handler, BINDING), session=self.cookie(handler, COOKIE) or None)
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
            elif self.signed_in(handler):
                # 401 would send a signed-in Account user back to login in a loop.
                handler.send({'error': '이 프로젝트의 학습 권한이 없습니다. 계정 관리자에게 권한을 요청하세요.'}, 403)
            else:
                signed_in = handler.learning_signed_in
                handler.send({'error': '프로젝트 열람 권한이 필요합니다. 다른 계정으로 로그인하거나 관리자에게 권한을 요청하세요.'
                              if signed_in else '로그인이 필요합니다.'}, 403 if signed_in else 401)
            return True
        if path == '/api/accounts/session':
            public = {key: principal[key] for key in ('user_id', 'project_id', 'capabilities')}
            if self.receiver:
                public['account_session'] = principal['_session_id']
                public['account_id'] = principal['account_id']
                profile = self.receiver.profile_session_id(principal['_session_id'])
                public['profile'] = profile if profile and profile['account_id'] == principal['account_id'] else None
                public['profile_url'] = self.receiver.profile_url
            handler.send(dict(public, token=token, connections=self.accounts.connections(principal)))
            return True
        if path == '/api/learning/imports':
            handler.send({'jobs': self.imports.list(principal, self.accounts.project_id) if self.imports else []})
            return True
        if path == '/api/accounts/repos':
            query = parse_qs(urlparse(handler.path).query, strict_parsing=True, keep_blank_values=True)
            if (set(query) != {'connection_id', 'repo_type'}
                    or any(len(values) != 1 or not values[0] for values in query.values())):
                raise ValueError('저장소 목록 요청이 올바르지 않습니다.')
            handler.send(list_repos(self.accounts, principal, query['connection_id'][0], query['repo_type'][0],
                                    transport=self.repos))
            return True
        return False

    def authorize_write(self, handler, path, body):
        principal = self.identity(handler)
        if path in ('/api/import', '/api/cad', '/api/learning/register', '/api/learning/vlm/import'):
            raise PermissionError('project users cannot import arbitrary server filesystem paths')
        if path.startswith(('/api/review-ai/', '/api/review-ai-cancel/')):
            capability = 'edit'
        elif path.startswith(('/api/frames/', '/api/masks/', '/api/mask-preview/')):
            capability = 'approve' if body.get('action') == 'approve' else 'edit'
        elif path.startswith('/api/learning/vlm/items/'):
            capability = 'edit'
        elif path == '/api/prepare':
            capability = 'approve'
        elif path == '/api/learning/storage/preflight':
            capability = 'view'
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
            if self.closing:
                raise ValueError('import service is stopping')
            if job['id'] in self.tasks:
                self.retries[job['id']] = (job, principal)
                return
            if not self.slots.acquire(blocking=False):
                raise ValueError('가져오기 대기열이 가득 찼습니다. 잠시 후 재시도하세요.')
            future = self.pool.submit(self.imports.run, job['id'], principal)
            self.tasks[job['id']] = future

        def done(_):
            following = None
            with self.lock:
                retry = self.retries.pop(job['id'], None)
                if retry and not self.closing:
                    # Keep the same queue slot until the requested retry finishes.
                    following = self.pool.submit(self.imports.run, job['id'], retry[1])
                    self.tasks[job['id']] = following
                else:
                    self.tasks.pop(job['id'], None)
                    self.slots.release()
            if following:
                following.add_done_callback(done)
        future.add_done_callback(done)

    def post(self, handler, path, body, token):
        try:
            return self._post(handler, path, body, token)
        except self.unavailable:
            handler.send({'error':'이 앱의 로그아웃 요청은 보존되었습니다. 계정 연결 복구 후 회수를 완료합니다.'
                          if path == '/api/accounts/logout' else 'Rosy Account 연결을 확인하세요.'},503)
            return True

    def _post(self, handler, path, body, token):
        if self.receiver and path == '/api/accounts/oauth' and handler.headers.get('X-Pinky-Token') != self.csrf(handler, token):
            raise PermissionError('Account session changed')
        if self.receiver and path == '/api/accounts/logout':
            self.set_cookie(handler, COOKIE, '', clear=True)
            self.accounts.logout(self.cookie(handler, COOKIE))
            handler.send({'ok':True})
            return True
        principal = self.authorize_write(handler, path, body)
        if path == '/api/accounts/logout':
            self.accounts.logout(self.cookie(handler, COOKIE))
            self.set_cookie(handler, COOKIE, '', clear=True)
            handler.send({'ok': True})
        elif path == '/api/accounts/oauth':
            purpose = body.get('purpose')
            if not self.oauth or purpose not in ('link', 'manage'):
                raise ValueError('Hugging Face account linking is unavailable')
            url, binding = self.oauth.begin(purpose, session=self.cookie(handler, COOKIE))
            self.set_cookie(handler, BINDING, binding)
            handler.send({'url': url})
        elif path == '/api/accounts/connect':
            handler.send(self.accounts.connect_token(principal, body.get('token'),
                         sharing=body.get('sharing', 'personal'), resources=body.get('resources', [])))
        elif path == '/api/accounts/disconnect':
            self.accounts.disconnect(principal, body.get('connection_id'))
            handler.send({'ok': True})
        elif path == '/api/accounts/repos/create':
            if set(body) != {'connection_id', 'repo_type', 'repo_id'}:
                raise ValueError('저장소 만들기 요청이 올바르지 않습니다.')
            handler.send(create_private(self.accounts, principal, body['connection_id'], body['repo_type'],
                                        body['repo_id'], transport=self.repos))
        elif path == '/api/accounts/repos/delete':
            if set(body) != {'connection_id', 'repo_type', 'repo_id', 'confirm'}:
                raise ValueError('저장소 삭제 요청이 올바르지 않습니다.')
            handler.send(delete_private(self.accounts, principal, body['connection_id'], body['repo_type'],
                                        body['repo_id'], body['confirm'], transport=self.repos))
        elif path.startswith('/api/learning/imports/'):
            if not self.imports:
                raise ValueError('자료 가져오기가 설정되지 않았습니다.')
            if path == '/api/learning/imports/review':
                # `import` (not `edit`/`approve`): this only queues verified bytes as pending, never a decision.
                import review_ingest
                job, files = self.imports.verified(principal, self.accounts.project_id, body.get('id'))
                if not job.get('review'):
                    result = review_ingest.import_hf(self.store, job, files, principal['user_id'])
                    job = self.imports.record_review(principal, self.accounts.project_id, job['id'], dict(
                        registered_by=principal['user_id'], registered_at=time.time(), status='pending_human',
                        added=result['added'], indices=result['indices'],
                        pixel_reviews_pending=result['pixel_reviews_pending'],
                        catalog_sha256=result['catalog_sha256']))
                handler.send(job)
                return True
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
    from learning_imports import LearningImports
    from learning_oauth import OAuth
    path = Path(config_path).resolve()
    config = json.loads(path.read_text(encoding='utf-8'))

    def private_path(name):
        value = Path(config[name])
        if not value.is_absolute():
            raise ValueError(f'{name} must be an absolute private path')
        return value

    # D-757: people sign in only through Rosy Account; app-local passwords are not served.
    if not config.get('account_client_file'):
        raise ValueError('collaboration requires account_client_file (Rosy Account sign-in)')
    from core_common.protocol.account_client import load_account_client
    from learning_rosy_accounts import RosyAccounts
    receiver = load_account_client(private_path('account_client_file'), destinations=('/accounts','/'))
    if receiver.callback != config.get('public_origin', '') + '/api/account/callback':
        raise ValueError('Account callback must match public_origin')
    accounts = RosyAccounts(private_path('accounts_db'), private_path('key_file'), path, receiver=receiver)
    oauth = OAuth(accounts) if config.get('oauth') else None

    def credential(actor, project, connection, generation=None, resource=None):
        accounts.authorize(actor, project, 'import')
        return accounts.credential(actor, connection, generation=generation, resource=resource)

    imports = LearningImports(private_path('imports_root'), accounts.authorize, credential,
                              limits=config.get('import_limits'))
    return accounts, oauth, imports
