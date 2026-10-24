"""/learning/vlm routes for review_app.py: human VLM question truth, its small queue and evaluation; never approves.

Collaboration: labels need `edit` and actor is the signed-in user; the export (it carries provisional answers)
and unpause need `manage`; import reads server paths, so like `/api/import` it is refused there (use the CLI on
the server). Local mode keeps the app's unidentified editor (actor null, D-478).
"""
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import vlm_judge

STATIC = Path(__file__).with_name('review_app_web')
PREFIX = '/api/learning/vlm/'
PAGES = {'/learning/vlm': ('vlm.html', 'text/html; charset=utf-8'),
         '/vlm.js': ('vlm.js', 'text/javascript; charset=utf-8'),
         '/vlm.css': ('vlm.css', 'text/css; charset=utf-8')}


def get(handler, path, store, token, collaboration=None):
    if path in PAGES:
        name, mime = PAGES[path]
        handler.send((STATIC / name).read_bytes(), mime=mime)
    elif not path.startswith(PREFIX):
        return False
    elif path == PREFIX + 'summary':
        handler.send(dict(vlm_judge.summary(store), token=token))
    elif path == PREFIX + 'items':
        query = parse_qs(urlparse(handler.path).query, keep_blank_values=True)
        if set(query) - {'view', 'status'} or any(len(v) != 1 for v in query.values()):
            raise ValueError('items accepts one view and one status filter')
        view, status = query.get('view', [''])[0], query.get('status', [''])[0]
        if (view and not vlm_judge.NAME.fullmatch(view)) or (status and status not in vlm_judge.STATUSES):
            raise ValueError('unknown view or status filter')
        handler.send({'items': vlm_judge.items(store, view or None, status or None)})
    elif path == PREFIX + 'queue':
        query = parse_qs(urlparse(handler.path).query, keep_blank_values=True)
        if set(query) - {'view'} or any(len(v) != 1 for v in query.values()):
            raise ValueError('queue accepts one view filter')
        view = query.get('view', [''])[0]
        if view and not vlm_judge.NAME.fullmatch(view):
            raise ValueError('unknown view filter')
        handler.send(vlm_judge.queue(store, view or None))
    elif match := re.fullmatch(PREFIX + r'items/(\d{1,9})', path):
        handler.send(vlm_judge.item(store, int(match[1])))
    elif match := re.fullmatch(PREFIX + r'images/(\d{1,9})', path):
        data, mime, digest = vlm_judge.image(store, int(match[1]))
        etag = '"' + digest + '"'
        if handler.headers.get('If-None-Match') == etag:  # bytes were re-hashed above; only the transfer is skipped
            handler.send(b'', 304, etag=etag, cache='no-cache')
        else:
            handler.send(data, mime=mime, etag=etag, cache='no-cache')
    elif path == PREFIX + 'evaluation':
        handler.send(vlm_judge.evaluation(store))
    elif path == PREFIX + 'export':
        if collaboration:
            collaboration.accounts.require(handler.learning_principal, 'manage')
        handler.send(vlm_judge.export(store))
    else:
        handler.send({'error': 'VLM 경로를 확인하세요.'}, 404)
    return True


def post(handler, path, body, store, collaboration, conflict):
    if not path.startswith(PREFIX):
        return False
    principal = handler.learning_principal if collaboration else None
    if path == PREFIX + 'import':
        if collaboration:  # authorize_write refuses it first; kept so the plugin never depends on that order
            raise PermissionError('project users cannot import arbitrary server filesystem paths')
        handler.send(vlm_judge.import_rows(store, body))
    elif path == PREFIX + 'unpause':
        if collaboration:  # authorize_write already asks manage for /api/learning/; kept explicit here
            collaboration.accounts.require(principal, 'manage')
        if set(body) != {'question'}:
            raise ValueError('unpause accepts one question id')
        handler.send(vlm_judge.unpause(store, body['question'], actor=principal['user_id'] if principal else None))
    elif match := re.fullmatch(PREFIX + r'items/(\d{1,9})', path):
        if collaboration:
            collaboration.accounts.require(principal, 'edit')
        handler.send(vlm_judge.save(store, int(match[1]), body, conflict,
                                    actor=principal['user_id'] if principal else None))
    else:
        handler.send({'error': 'VLM 경로를 확인하세요.'}, 404)
    return True
