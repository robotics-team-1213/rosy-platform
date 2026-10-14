"""Private dataset and model repositories for one stored Hugging Face connection.

The caller supplies the transport. The default transport allows only fixed Hub
API paths and does not read HF_TOKEN or a CLI login.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, build_opener

from learning_accounts import AccountError, _NoRedirect

API = 'https://huggingface.co/api/'
REPO_ID = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
NAME = re.compile(r'^[A-Za-z0-9_.-]+$')
SHA = re.compile(r'^[0-9a-f]{40}$')
HUB_FAILURE = 'Hugging Face 저장소 요청에 실패했습니다.'


def _fail():
    raise ValueError(HUB_FAILURE)


def _allowed(method, url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'huggingface.co' or parsed.username
            or parsed.password or parsed.fragment or parsed.port not in (None, 443)):
        return False
    if method == 'POST' and parsed.path == '/api/repos/create' and not parsed.query:
        return True
    if method == 'DELETE' and parsed.path == '/api/repos/delete' and not parsed.query:
        return True
    if method != 'GET':
        return False
    if parsed.path in ('/api/datasets', '/api/models'):
        try:
            fields = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
        except ValueError:
            return False
        author = fields.get('author', [])
        return (set(fields) == {'author', 'limit'} and fields.get('limit') == ['50']
                and len(author) == 1 and bool(NAME.fullmatch(author[0])))
    for kind in ('datasets', 'models'):
        prefix = '/api/' + kind + '/'
        if parsed.path.startswith(prefix) and not parsed.query:
            return bool(REPO_ID.fullmatch(parsed.path[len(prefix):]))
    return False


def hub_transport(method, url, token, body=None):
    if (not _allowed(method, url) or not isinstance(token, str) or not 1 <= len(token) <= 8192
            or any(c.isspace() for c in token) or token in url):
        _fail()
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
    data = None
    if body is not None:
        data = json.dumps(body, separators=(',', ':'), allow_nan=False).encode()
        headers['Content-Type'] = 'application/json'
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(1024 * 1024 + 1)
            status = response.status
        if len(raw) > 1024 * 1024:
            _fail()
        return status, json.loads(raw) if raw else None
    except HTTPError as exc:
        try:
            exc.read(1024)
        except Exception:
            pass
        return exc.code, None
    except Exception:
        _fail()


def _split(repo_id):
    if not isinstance(repo_id, str) or not REPO_ID.fullmatch(repo_id):
        raise ValueError('저장소 이름은 조직/이름 형식이어야 합니다.')
    return repo_id.split('/', 1)


def _kind(repo_type):
    if repo_type not in ('dataset', 'model'):
        raise ValueError('저장소 종류는 데이터셋 또는 모델만 가능합니다.')
    return 'datasets' if repo_type == 'dataset' else 'models'


def _credential(accounts, principal, connection_id, scope, resource):
    try:
        return accounts.management_credential(principal, connection_id, scope=scope, resource=resource)
    except AccountError as exc:
        reason = str(exc)
        if reason == 'connection scope denied':
            raise ValueError('이 연결에는 필요한 저장소 권한이 없습니다.') from None
        if reason == 'repository not allowed for project connection':
            raise ValueError('프로젝트 연결에 허용된 저장소만 관리합니다.') from None
        raise


def _call(transport, method, url, token, body=None):
    try:
        status, document = transport(method, url, token, body)
    except ValueError:
        raise
    except Exception:
        _fail()
    if not isinstance(status, int):
        _fail()
    return status, document


def _read(transport, token, repo_type, repo_id):
    status, document = _call(transport, 'GET', API + _kind(repo_type) + '/' + quote(repo_id, safe='/'), token)
    if status == 404:
        return None
    if status != 200 or not isinstance(document, dict) or document.get('id') not in (None, repo_id):
        _fail()
    return document


def _item(document, repo_id):
    if not isinstance(document, dict):
        return None
    private = document.get('private')
    if private is not True and private is not False:
        return None
    sha = document.get('sha')
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        sha = ''
    return {'repo_id': repo_id, 'private': private, 'sha': sha}


def create_private(accounts, principal, connection_id, repo_type, repo_id, *, transport=None):
    transport = transport or hub_transport
    namespace, name = _split(repo_id)
    _kind(repo_type)
    resource = repo_type + ':' + repo_id
    cred = _credential(accounts, principal, connection_id, 'write-repos', resource)
    if cred['sharing'] == 'personal' and namespace != cred['username']:
        raise ValueError('개인 연결은 그 계정의 저장소만 만듭니다.')
    status, _document = _call(transport, 'POST', API + 'repos/create', cred['token'],
                              {'name': name, 'organization': namespace, 'visibility': 'private', 'type': repo_type})
    if status == 409:
        raise ValueError('같은 저장소가 이미 있습니다. 공개 상태를 바꾸지 않습니다.')
    if status not in (200, 201):
        _fail()
    document = _read(transport, cred['token'], repo_type, repo_id)
    # A create response is not proof of privacy. Do not change visibility or delete it here.
    if not document or document.get('private') is not True:
        raise ValueError('만든 저장소가 비공개로 확인되지 않았습니다.')
    item = _item(document, repo_id)
    if not item:
        raise ValueError('만든 저장소가 비공개로 확인되지 않았습니다.')
    accounts.audit_publish(principal, 'repo_create', resource)
    return item


def delete_private(accounts, principal, connection_id, repo_type, repo_id, confirm, *, transport=None):
    transport = transport or hub_transport
    if confirm != repo_id:
        raise ValueError('삭제 확인은 저장소 이름과 같아야 합니다.')
    namespace, name = _split(repo_id)
    _kind(repo_type)
    resource = repo_type + ':' + repo_id
    cred = _credential(accounts, principal, connection_id, 'manage-repos', resource)
    if cred['sharing'] == 'personal' and namespace != cred['username']:
        raise ValueError('개인 연결은 그 계정의 저장소만 지웁니다.')
    document = _read(transport, cred['token'], repo_type, repo_id)
    if document is None:
        raise ValueError('저장소를 찾을 수 없습니다.')
    if document.get('private') is not True:
        raise ValueError('공개 저장소는 삭제하지 않습니다.')
    status, _document = _call(transport, 'DELETE', API + 'repos/delete', cred['token'],
                              {'name': name, 'organization': namespace, 'type': repo_type})
    if status not in (200, 204):
        _fail()
    accounts.audit_publish(principal, 'repo_delete', resource)
    return {'ok': True, 'repo_type': repo_type, 'repo_id': repo_id}


def list_repos(accounts, principal, connection_id, repo_type, *, transport=None):
    transport = transport or hub_transport
    _kind(repo_type)
    cred = _credential(accounts, principal, connection_id, 'read-repos', None)
    if cred['sharing'] == 'project':
        repos = []
        prefix = repo_type + ':'
        for resource in cred['resources']:
            if not isinstance(resource, str) or not resource.startswith(prefix):
                continue
            repo_id = resource[len(prefix):]
            if not REPO_ID.fullmatch(repo_id):
                continue
            document = _read(transport, cred['token'], repo_type, repo_id)
            if document is None:
                repos.append({'repo_id': repo_id, 'missing': True, 'private': False, 'sha': ''})
            else:
                item = _item(document, repo_id)
                if item:
                    repos.append(item)
            if len(repos) == 50:
                break
        return {'repos': repos}
    if not isinstance(cred['username'], str) or not NAME.fullmatch(cred['username']):
        _fail()
    url = API + _kind(repo_type) + '?author=' + quote(cred['username']) + '&limit=50'
    status, document = _call(transport, 'GET', url, cred['token'])
    if status != 200 or not isinstance(document, list):
        _fail()
    repos = []
    for entry in document:
        repo_id = entry.get('id') if isinstance(entry, dict) else None
        item = _item(entry, repo_id) if isinstance(repo_id, str) else None
        if item and repo_id.split('/', 1)[0] == cred['username']:
            repos.append(item)
        if len(repos) == 50:
            break
    return {'repos': repos}
