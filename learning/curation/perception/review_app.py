"""Pinky persistent review with optional model-PC draft jobs; no robot control.

Restart with the same --state only. Local HTTP contract: docs/review-app.md.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import mimetypes
import re
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlsplit

import cv2
import numpy as np

import class_sets, review_return
from learning_workspace import Workspace, WORKFLOWS
import review_evidence, review_ingest, review_masks, vlm_mask_feedback, camera_setup_web, omx_web, sim_web, ladder_web, vlm_judge_web
import review_classes, review_context, review_versions, omx_center_web, review_upload
import learning_domains, learning_pipeline, promotion_request
import review_static
import learning_tasks_web
import learning_recording_web
from workspace_links import WORKSPACE_LINKS_SCHEMA, check_workspace_links, load_workspace_links
from learning_tasks import Tasks
from review_ai_jobs import Jobs
from review_store import Conflict, ReviewStore
from review_decisions import make_decisions_server, serve_review
from storage_web import StorageWeb
from learning_control import Control, ControlConflict




def detail_preview(store, index):
    frame = store.get(index)
    photo = cv2.imdecode(np.frombuffer(store.image(index).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if photo is None or photo.shape[:2] != (frame['source']['height'], frame['source']['width']):
        raise ValueError('source image dimensions differ')
    light, a, b = cv2.split(cv2.cvtColor(photo, cv2.COLOR_BGR2LAB))
    # Preserve flat areas: local sharpening must not invent texture in clipped regions.
    blurred = cv2.GaussianBlur(light, (0, 0), 3)
    light = cv2.addWeighted(light, 1.6, blurred, -0.6, 0)
    curve = np.rint(255 * (np.arange(256) / 255) ** 1.5).astype(np.uint8)
    light = cv2.LUT(light, curve)
    enhanced = cv2.cvtColor(cv2.merge((light, a, b)), cv2.COLOR_LAB2BGR)
    ok, data = cv2.imencode('.png', enhanced)
    if not ok:
        raise ValueError('preview encoding failed')
    return data.tobytes()


# D-478: loopback, RFC1918, link-local and Tailscale only; never wildcard or public.
BIND_NETWORKS = [ipaddress.ip_network(n) for n in (
    '127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16', '100.64.0.0/10')]


def check_bind_host(host):
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError:
        raise ValueError(f'--host must be a literal IPv4 address, got {host!r}') from None
    if not any(address in net for net in BIND_NETWORKS):
        raise ValueError(f'--host {host} is not loopback, private, link-local or Tailscale 100.64.0.0/10')
    return host


def check_link(url):
    """--vlm-eval-url: an http(s) address without credentials, shown as a link only (D-857 §2)."""
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or len(url) > 300:
        raise ValueError('--vlm-eval-url must be an http(s) address without credentials')
    return url


def make_server(store, port=8767, host='127.0.0.1', *, control=None, accounts=None, oauth=None, imports=None, storage=None, storage_jobs=None, ai_jobs=None, repos=None, omx_center=None, sim_runs=None, vlm_eval_url=None, workspace_links=None, owners=None, recordings=None, recording_config=None, ladder=None):
    check_bind_host(host)
    if workspace_links is not None:
        workspace_links = check_workspace_links({'schema': WORKSPACE_LINKS_SCHEMA, 'workspaces': workspace_links})
    if vlm_eval_url is not None:
        check_link(vlm_eval_url)
    if ai_jobs is not None and ai_jobs.store.db != store.db:
        raise ValueError('AI jobs must belong to the review workspace')
    collaboration = None
    with store.connect() as db:
        bound = db.execute("SELECT value FROM metadata WHERE key='collaboration_project'").fetchone()
    if bound and not accounts:
        raise ValueError('collaboration-bound workspace requires its account configuration')
    project = accounts.project_id if accounts else review_evidence.metadata(store, 'workspace_id')
    tasks = Tasks(store.db, project)
    if omx_center is not None:
        omx_center.bind_workspace(project)
        omx_center.tasks = tasks
    if recordings is None:
        recordings = learning_recording_web.create(store, omx_center, recording_config)
    if storage and storage.project_id != project:
        raise ValueError('storage project must match workspace project')
    storage_web = StorageWeb(storage, accounts, storage_jobs, store.db, sim_runs=sim_runs, omx_center=omx_center)
    if accounts:
        from learning_collaboration import Collaboration
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError('collaboration requires loopback behind an HTTPS reverse proxy')
        collaboration = Collaboration(accounts, store, oauth=oauth, imports=imports, repos=repos)
    token = secrets.token_urlsafe(32)
    learning = Workspace(store.db)
    native_workflow_cache = {}
    ai_jobs = ai_jobs if ai_jobs is not None else Jobs(store)
    sim_seen = {}

    def sim_status():
        # shortcut: the home row reads the SIM list at most once a minute; the SIM page itself reads live.
        if sim_runs is None:
            return None
        if time.monotonic() - sim_seen.get('at', -60.0) >= 60:
            try:
                value = {'runs': [sim_web.public(row) for row in sim_runs.call({'action': 'list'})]}
            except (ValueError, KeyError, TypeError):  # one malformed row must not break the home page
                value = {'error': 'unavailable'}
            sim_seen.update(at=time.monotonic(), value=value)
        return sim_seen['value']

    class Handler(BaseHTTPRequestHandler):
        def send(self, data, code=200, mime='application/json; charset=utf-8', etag=None, cache='no-store'):
            if collaboration and isinstance(data, dict) and 'token' in data:
                data = dict(data, token=collaboration.csrf(self, token))
            if isinstance(data, (dict, list)):
                data = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', cache)
            for name, value in getattr(self, 'extra_headers', []):
                self.send_header(name, value)
            if etag:
                self.send_header('ETag', etag)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def allowed_host(self):
            port = self.server.server_port
            allowed = [f'127.0.0.1:{port}', f'localhost:{port}', f'{host}:{port}']
            if collaboration and collaboration.authority:
                allowed.append(collaboration.authority)
            return self.headers.get('Host') in allowed

        def log_message(self, fmt, *args):
            if not collaboration:
                super().log_message(fmt, *args)
            # OAuth authorization codes and errors must not enter access logs.

        def do_GET(self):
            self.extra_headers = []
            if not self.allowed_host():
                return self.send({'error': 'local host required'}, 403)
            path = urlparse(self.path).path
            try:
                if collaboration and collaboration.get(self, path, token):
                    return
                if storage_web.get(self, path): return
                if learning_recording_web.get(self, path, recordings):
                    return
                if learning_tasks_web.get(self, path, tasks, omx_center, token, learning, native_workflow_cache, sim_runs=sim_runs, owners=owners):
                    return
                if omx_center_web.get(self, path, omx_center, learning) or camera_setup_web.get(self, path, store.state) or omx_web.get(self, path, learning, omx_center, store.state) or sim_web.get(self, path, sim_runs) or ladder_web.get(self, path, ladder) or vlm_judge_web.get(self, path, store, token, collaboration):
                    return
                if path == '/api/accounts/options':
                    return self.send({'enabled': False, 'oauth': False})
                if path.startswith('/api/review-ai/'):
                    match = re.fullmatch(r'/api/review-ai/(\d+)', path)
                    if not match:
                        raise ValueError('invalid AI frame path')
                    value = ai_jobs.status(int(match[1]))
                    value['can_request'] = not collaboration or 'edit' in self.learning_principal['capabilities']
                    return self.send(value)
                if path.startswith('/api/review-history/'):
                    match = re.fullmatch(r'/api/review-history/(object|pixel)/(\d+)', path)
                    query = parse_qs(urlparse(self.path).query, strict_parsing=True, keep_blank_values=True)
                    if (not match or set(query) - {'before', 'limit'}
                            or any(len(values) != 1 for values in query.values())):
                        raise ValueError('invalid review history request')
                    return self.send(review_versions.page(store, match[1], int(match[2]),
                        before=int(query['before'][0]) if 'before' in query else None,
                        limit=int(query.get('limit', ['20'])[0])))
                if path.startswith('/api/review-versions/'):
                    match = re.fullmatch(r'/api/review-versions/(object|pixel)/(\d+)/(\d+)', path)
                    if not match:
                        raise ValueError('invalid review version path')
                    return self.send(review_versions.version(store, match[1], int(match[2]), int(match[3])))
                if path.startswith('/api/review-version-images/'):
                    match = re.fullmatch(r'/api/review-version-images/(\d+)/(\d+)', path)
                    if not match:
                        raise ValueError('invalid review version image path')
                    return self.send(review_versions.image(store, int(match[1]), int(match[2])), mime='image/png')
                if path == '/api/learning/workspaces':
                    return self.send({'configured': workspace_links is not None, 'workspaces': workspace_links or []})
                if path == '/api/learning/storage':
                    return self.send(storage_web.inventory.snapshot() if storage_web.inventory else {'status': 'not_configured', 'roots': []})
                if path == '/api/workspace':
                    return self.send(review_context.workspace(store, self.path, project, workspace_links, token))
                if path == '/api/classes':
                    if collaboration:
                        accounts.require(self.learning_principal, 'manage')
                    query = parse_qs(urlparse(self.path).query, strict_parsing=True)
                    if set(query) != {'kind'} or len(query['kind']) != 1:
                        raise ValueError('one class kind required')
                    return self.send(dict(review_classes.snapshot(store, query['kind'][0]), token=token,
                        workspace_id=project, workspace_label=review_evidence.metadata(store, 'workspace_label') or '현재 작업공간'))
                if path == '/api/decisions':
                    value = review_evidence.decisions(store)
                    tag = '"' + value['decision_sha256'] + '"'
                    if self.headers.get('If-None-Match') == tag:
                        return self.send(b'', 304, etag=tag)
                    return self.send(value, etag=tag)
                if path.startswith('/api/history/'):
                    return self.send(store.history(int(path.rsplit('/', 1)[1])))
                if path.startswith('/api/vlm-feedback/'):
                    return self.send(vlm_mask_feedback.read_current_feedback(store.state, int(path.rsplit('/', 1)[1])))
                if path == '/api/catalog':
                    return self.send({'catalog': review_evidence.metadata(store, 'import_catalog'),
                                      'cad_catalog': review_evidence.metadata(store, 'cad_catalog'),
                                      'map_reference': review_evidence.map_reference(store), 'token': token,
                                      'folders': review_upload.folders(store), 'local_import': not bool(collaboration),
                                      'imports': bool(collaboration)})  # HF imports exist only in collaboration mode
                if path.startswith('/api/mask-images/'):
                    review = review_masks.get(store, int(path.rsplit('/', 1)[1]))
                    pixels = review_masks.encode(review_masks.pixels(store, review))
                    # Store-and-revalidate (D-469): every request still decodes and the
                    # image endpoints below re-read and re-hash the bytes on disk, so a
                    # matching If-None-Match only skips the transfer, never the check.
                    etag = '"' + hashlib.sha256(pixels).hexdigest() + '"'
                    if self.headers.get('If-None-Match') == etag:
                        return self.send(b'', 304, etag=etag, cache='no-cache')
                    return self.send(pixels, mime='image/png', etag=etag, cache='no-cache')
                if path.startswith('/api/draft-images/'):
                    _, _, frame_id, digest = path.rsplit('/', 3)
                    return self.send(review_masks.draft_image(store, int(frame_id), digest),
                                     mime='image/png', cache='no-cache')
                if path.startswith(('/api/draft-preview/', '/api/draft-merge-preview/')):
                    _, _, frame_id, digest = path.rsplit('/', 3)
                    merged = path.startswith('/api/draft-merge-preview/')
                    return self.send(review_masks.draft_preview(store, int(frame_id), digest, merge=merged),
                                     mime='image/png', cache='no-cache')
                if path.startswith('/api/masks/'):
                    return self.send(review_masks.get(store, int(path.rsplit('/', 1)[1])))
                if path.startswith('/api/object-drafts/'):
                    return self.send({'drafts': store.object_drafts(int(path.rsplit('/', 1)[1]))})
                if path == '/api/learning/control':
                    return self.send(control.status() if control else {'available': False})
                if path == '/api/learning/promotion-requests':
                    return self.send(promotion_request.listing(store.state, learning.list(), control))
                if path == '/api/learning':
                    frames = store.list_frames()
                    pixel_reviews = review_masks.get_many(store, [f for f in frames if f['status'] != 'excluded'])
                    pixel_statuses = [row['status'] for row in pixel_reviews]
                    with store.connect() as db:
                        queued_objects = {row[0] for row in db.execute('SELECT DISTINCT frame FROM object_drafts d WHERE NOT EXISTS (SELECT 1 FROM object_draft_quarantine q WHERE q.frame=d.frame AND q.sha256=d.sha256)')}
                    object_draft_indices = [f['index'] for f in frames if f['status'] == 'pending'
                                            and (f['index'] in queued_objects or f['source'].get('objects')
                                                 or f['source'].get('boxes'))]
                    pixel_draft_indices = [row['frame'] for row in pixel_reviews
                                           if row['status'] == 'pending' and row['path'] is not None and
                                           bool((review_masks.pixels(store, row) != 255).any())]
                    pixel_candidate_indices = [row['frame'] for row in pixel_reviews if row['status'] == 'pending'
                                               and row['draft_candidates']]
                    latest = next(iter(store.exports()), None)
                    preparation = None
                    current = review_evidence.decisions(store)
                    if latest:
                        authority = latest.get('authority', {})
                        preparation = {'object_frames': latest['exported_frames'],
                                       'pixel_frames': latest.get('pixel_approved_frames', 0),
                                       'current_decisions_match':
                                       authority.get('workspace_id') == current['workspace_id'] and
                                       authority.get('generation') == current['generation'] and
                                       authority.get('decision_sha256') == current['decision_sha256']}
                    control_status = control.status() if control else None
                    counts = {state: sum(row['object_decision'] == state for row in current['frames'])
                              for state in ('approved', 'pending', 'excluded')}
                    pixel_counts = {state: sum(row['mask_decision'] == state and not row['frame_excluded']
                                               for row in current['frames'])
                                    for state in ('approved', 'pending', 'excluded')}
                    pipeline = learning_pipeline.project(current, counts=counts, pixel_counts=pixel_counts,
                                                         preparation=preparation, control=control_status)
                    items = learning.list()
                    with store.connect() as db:
                        omx_reviewed, vlm_counts, task_count = learning_domains.stored(db)
                    domains = learning_domains.domains(
                        pipeline=pipeline, counts=counts, preparation=preparation, items=items,
                        omx_reviewed=omx_reviewed, sim_runs=sim_status(), ladder=ladder_web.status(ladder), vlm_counts=vlm_counts,
                        vlm_eval_url=vlm_eval_url, tasks=task_count, pixel_counts=pixel_counts,
                        drafts={'object': object_draft_indices, 'pixel': pixel_candidate_indices})
                    return self.send({'workflows': WORKFLOWS, 'items': items, 'token': token,
                                      'pipeline': pipeline, 'domains': domains, 'vlm_eval_url': vlm_eval_url,
                                      'preparation': preparation,
                                      'control': control_status,
                                      'counts': counts,
                                      'object_drafts': len(object_draft_indices),
                                      'source_video_unverified': sum(
                                          f['status'] != 'excluded'
                                          and bool(f['source'].get('source_video_sha256'))
                                          and f['source'].get('original_video_verified') is not True
                                          for f in frames),
                                      'object_draft_first': object_draft_indices[0] if object_draft_indices else None,
                                      'pixel_draft_first': pixel_candidate_indices[0] if pixel_candidate_indices else None,
                                      'pixel_counts': pixel_counts | {'drafted': len(pixel_draft_indices),
                                                         'candidates': len(pixel_candidate_indices),
                                                         'blank': pixel_statuses.count('pending') - len(pixel_draft_indices)}})
                if path.startswith('/api/learning/images/'):
                    prefix, identifier, name = path.rsplit('/', 2)
                    if prefix != '/api/learning/images':
                        raise ValueError('invalid JPG evidence path')
                    raw, digest = learning.image(identifier, name)
                    return self.send(raw, mime='image/jpeg', etag='"' + digest + '"', cache='no-cache')
                if path.startswith('/api/images/'):
                    index = int(path.rsplit('/', 1)[1])
                    image = store.image(index)
                    etag = '"' + store.get(index)['source']['image_sha256'] + '"'
                    if self.headers.get('If-None-Match') == etag:
                        return self.send(b'', 304, etag=etag, cache='no-cache')
                    return self.send(image.read_bytes(), mime=mimetypes.guess_type(image.name)[0],
                                     etag=etag, cache='no-cache')
                if path.startswith('/api/view-images/'):
                    return self.send(detail_preview(store, int(path.rsplit('/', 1)[1])),
                                     mime='image/png')
                if review_static.get(self, path):
                    return
                self.send({'error': 'not found'}, 404)
            except PermissionError:
                self.send({'error': '프로젝트 접근 권한이 없습니다.'}, 403)
            except (KeyError, ValueError, OSError) as exc:
                self.send({'error': str(exc)}, 400)

        def do_POST(self):
            self.extra_headers = []
            path = urlparse(self.path).path
            body_limit = (review_upload.BODY_LIMIT if path == '/api/catalog/upload' else
                          4*1048576 if path == '/api/learning/omx/center/lerobot-study' else 1048576)
            # Consume bounded rejected bodies before responding; Windows may otherwise
            # reset the connection while the client is still transmitting its request.
            def deny():
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if 0 < length <= body_limit:
                        self.connection.settimeout(5)
                        self.rfile.read(length)
                except (ValueError, OSError):
                    pass
                return self.send({'error': 'local workspace authorization required'}, 403)
            login_request = collaboration and path == '/api/accounts/logout'
            expected_token = collaboration.csrf(self, token) if collaboration else token
            if not self.allowed_host() or (not login_request and self.headers.get('X-Pinky-Token') != expected_token):
                return deny()
            origin = self.headers.get('Origin')
            port = self.server.server_port
            origins = [f'http://127.0.0.1:{port}', f'http://localhost:{port}', f'http://{host}:{port}']
            if collaboration and collaboration.origin:
                origins = [collaboration.origin]
            if (collaboration and not origin) or (origin and origin not in origins):
                return deny()
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= body_limit:
                    raise ValueError('bounded JSON body required')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('JSON object required')
                path = urlparse(self.path).path
                if path.startswith('/api/review-ai/'):
                    expected = {'action', 'version', 'label', 'points'} if body.get('action') == 'sam_points' else {'action', 'version'}
                    if set(body) != expected:
                        raise ValueError('AI request fields do not match its action')
                if path.startswith('/api/review-ai-cancel/') and body:
                    raise ValueError('AI cancellation accepts an empty object only')
                if collaboration and collaboration.post(self, path, body, token):
                    return
                if storage_web.post(self, path, body): return
                if learning_recording_web.post(self, path, body, recordings):
                    return
                if learning_tasks_web.post(self, path, body, tasks, omx_center, collaboration, learning, sim_runs=sim_runs, owners=owners):
                    return
                if omx_center_web.post(self, path, body, omx_center, learning,
                                       collaboration.accounts if collaboration else None):
                    return
                if camera_setup_web.post(self, path, body, store.state, collaboration):
                    return
                if sim_web.post(self, path, body, sim_runs, collaboration) or ladder_web.post(self, path, body, ladder, collaboration):
                    return
                if vlm_judge_web.post(self, path, body, store, collaboration, Conflict):
                    return
                actor = self.learning_principal['user_id'] if collaboration else None
                if path == '/api/classes/revisions':
                    if collaboration:
                        accounts.require(self.learning_principal, 'manage')
                    return self.send(review_classes.revise(store, body, actor or 'local-unidentified', Conflict))
                if omx_web.post(self, path, body, learning, Conflict):
                    return
                if path.startswith('/api/review-ai/'):
                    match = re.fullmatch(r'/api/review-ai/(\d+)', path)
                    if not match or body['action'] not in ('object_draft', 'pixel_draft', 'mask_check', 'sam_points') or type(body['version']) is not int:
                        raise ValueError('invalid AI request')
                    index = int(match[1])
                    principal = self.learning_principal if collaboration else None
                    authorize = (lambda _: accounts.require(principal, 'edit')) if collaboration else None
                    with ai_jobs.guard, store.lock:
                        current = store.get(index) if body['action'] == 'object_draft' else review_masks.get(store, index)
                        if current['version'] != body['version']:
                            raise Conflict('검수 버전이 바뀌었습니다. 사진을 다시 불러오세요.')
                        prompt = {'label': body['label'], 'points': body['points']} if body['action'] == 'sam_points' else None
                        job = ai_jobs.create(index, body['action'], body['version'],
                                             actor or 'local-unidentified', authorize=authorize, prompt=prompt)
                    return self.send(job)
                if path.startswith('/api/review-ai-cancel/'):
                    match = re.fullmatch(r'/api/review-ai-cancel/([a-f0-9]{32})', path)
                    if not match:
                        raise ValueError('invalid AI job identifier')
                    with ai_jobs.guard, store.lock:
                        with store.connect() as db:
                            row = db.execute('SELECT document FROM review_ai_jobs WHERE id=?', (match[1],)).fetchone()
                        if row is None:
                            raise ValueError('AI job not found')
                        job = json.loads(row[0])
                        if collaboration and job['actor'] != actor:
                            accounts.require(self.learning_principal, 'manage')
                        return self.send(ai_jobs.cancel(match[1], actor or 'local-unidentified'))
                if path == '/api/learning/storage/preflight':
                    if not storage_web.inventory:
                        raise ValueError('storage is not configured')
                    return self.send(storage_web.inventory.preflight(body))
                if path == '/api/prepare':
                    return self.send(store.prepare())
                if path == '/api/catalog/upload':
                    return self.send(review_upload.import_image(store, body, actor))
                if path == '/api/catalog/folder':
                    return self.send(review_upload.import_folder(store, body, actor))
                if path == '/api/import':
                    if not body.get('path'):
                        body['path'] = review_evidence.metadata(store, 'import_catalog')
                    if not body.get('path'):
                        raise ValueError('등록할 검증 입력 폴더가 필요합니다.')
                    return self.send(review_ingest.import_frames(store, body))
                if path == '/api/cad':
                    path = body.get('path') or review_evidence.metadata(store, 'cad_catalog')
                    if not path:
                        raise ValueError('CAD 검증 자료 경로가 필요합니다.')
                    return self.send(review_evidence.register_map(store, path))
                if path.startswith('/api/mask-preview/'):
                    png, count, tolerance = review_masks.preview(
                        store, int(path.rsplit('/', 1)[1]), body, Conflict)
                    return self.send({'mask_png': base64.b64encode(png).decode('ascii'),
                                      'selected_pixels': count, 'tolerance': tolerance})
                if path.startswith('/api/masks/'):
                    return self.send(review_masks.update(store, int(path.rsplit('/', 1)[1]), body, Conflict,
                                                         actor=actor))
                if path == '/api/learning/promotion-requests':
                    # `manage` via authorize_write: a project action, not truth approval (`approve`) nor Fleet's.
                    item = next((row for row in learning.list() if row['kind'] == 'perception'
                                 and set(body) == {'id'} and row['id'] == body['id']), None)
                    if item is None:
                        raise ValueError('승격 요청은 등록된 인식 학습 결과의 id 하나만 받습니다.')
                    bundle = promotion_request.build(item['path'], actor or 'local-unidentified', control)
                    return self.send(promotion_request.write(store.state, bundle))
                if path in ('/api/learning/register', '/api/learning/remove', '/api/learning/control'):
                    return self.send(learning.action(path, body, control, Conflict))
                if path.startswith('/api/frames/'):
                    return self.send(store.update(int(path.rsplit('/', 1)[1]), body, actor=actor))
                self.send({'error': 'not found'}, 404)
            except (Conflict, ControlConflict) as exc:
                self.send({'error': str(exc)}, 409)
            except PermissionError:
                self.send({'error': '로그인 또는 프로젝트 권한을 확인하세요.'}, 403)
            except (ValueError, KeyError, OSError) as exc:
                self.send({'error': str(exc)}, 400)

    class Server(ThreadingHTTPServer):
        def server_close(self):
            recordings.close()
            storage_web.close()
            ai_jobs.close()
            if collaboration:
                collaboration.shutdown()
            super().server_close()

    try:
        return Server((host, port), Handler)
    except Exception:
        recordings.close()
        storage_web.close()
        ai_jobs.close()
        if collaboration:
            collaboration.shutdown()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--human', type=Path)
    parser.add_argument('--images', type=Path)
    parser.add_argument('--empty-eval', action='store_true', help='initialize a separate empty evaluation workspace once')
    parser.add_argument('--empty-training', action='store_true', help='initialize a separate verified-import review workspace once')
    parser.add_argument('--init-only', action='store_true', help='initialize the requested workspace and exit without serving')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--decisions-port', type=int, help='optional loopback-only current-decisions readback')
    parser.add_argument('--learning-control', type=Path, help='private binding for owned signed pipeline controls')
    parser.add_argument('--collaboration', type=Path, help='private project account/OAuth configuration')
    parser.add_argument('--storage-config', type=Path, help='private registered project storage roots and quota estimates')
    parser.add_argument('--review-ai-config', type=Path, help='private workspace-bound model-PC AI execution configuration')
    parser.add_argument('--omx-center-config', type=Path, help='private isolated OMX learning root and pinned host learner interpreters')
    parser.add_argument('--recording-config', type=Path, help='private local observer recording sources and exporter configuration')
    parser.add_argument('--sim-config', type=Path, help='private workspace-bound local SIM subprocess configuration')
    parser.add_argument('--ladder-config', type=Path, help='private OMX ladder root, cell and interpreter paths')
    parser.add_argument('--fleet-owner-config', type=Path, help='private Fleet url, Viewer token file and CA for the read-only robot list')
    parser.add_argument('--vlm-eval-url', help='link from 평가·승격 to a separate VLM evaluation state instance (D-857)')
    parser.add_argument('--workspace-links', type=Path, help='private JSON listing the center\'s other review workspaces (D-857 §2)')
    parser.add_argument('--host', default='127.0.0.1', help='bind address; default loopback (D-478)')
    parser.add_argument('--catalog', type=Path, help='prepared verified-inputs folder shown in app')
    parser.add_argument('--object-classes', type=Path, help='Ultralytics data.yaml naming the object classes; first start binds it (D-485)')
    parser.add_argument('--cad-catalog', type=Path, help='verified CAD reference catalog shown in app')
    args = parser.parse_args()
    if args.empty_eval and args.empty_training:
        parser.error('choose one empty workspace kind')
    if args.vlm_eval_url:
        try:
            check_link(args.vlm_eval_url)
        except ValueError as exc:
            parser.error(str(exc))
    workspace_links = None
    if args.workspace_links:
        try:
            workspace_links = load_workspace_links(args.workspace_links)
        except (OSError, ValueError) as exc:
            parser.error(f'--workspace-links: {exc}')
    object_classes = None
    if args.object_classes:
        try:
            object_classes = class_sets.from_data_yaml(args.object_classes.read_bytes(), 'detect')
        except (OSError, ValueError) as exc:
            parser.error(f'--object-classes: {exc}')
    try:
        store = ReviewStore(args.state, args.source, args.human, args.images, object_classes,
                            empty_eval=args.empty_eval, empty_training=args.empty_training)
    except (OSError, ValueError) as exc:   # startup refusals are usage errors, not crashes
        parser.error(str(exc))
    if args.init_only:
        return
    with store.connect() as db:
        for key, path in [('import_catalog', args.catalog), ('cad_catalog', args.cad_catalog)]:
            if path:
                db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, str(path.resolve())))
    control = Control(args.learning_control, review_evidence.metadata(store, 'workspace_id')) if args.learning_control else None
    accounts = oauth = imports = None
    if args.collaboration:
        if args.decisions_port:
            parser.error('collaboration cannot expose unauthenticated decisions-port')
        from learning_collaboration import load
        accounts, oauth, imports = load(args.collaboration, store)
    storage = None
    if args.storage_config:
        from storage_inventory import StorageInventory
        try:
            storage = StorageInventory(store.db, json.loads(args.storage_config.read_text(encoding='utf-8')),
                accounts.project_id if accounts else review_evidence.metadata(store, 'workspace_id'))
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    ai_jobs = Jobs(store, args.review_ai_config)
    omx_center = None
    if args.omx_center_config:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'training' / 'omx'))
        from experiment_center import Center
        omx_center = Center(json.loads(args.omx_center_config.read_text(encoding='utf-8')))
    sim_runs = sim_web.LocalRuns(args.sim_config, review_evidence.metadata(store, 'workspace_id')) if args.sim_config else None
    try:
        from owner_robots import FleetOwners
        owners = FleetOwners(json.loads(args.fleet_owner_config.read_text(encoding='utf-8'))) if args.fleet_owner_config else None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f'--fleet-owner-config: {exc}')
    recording_config = learning_recording_web.load_config(args.recording_config, parser)
    ladder = ladder_web.load(args.ladder_config, parser)
    server = make_server(store, args.port, args.host, control=control, accounts=accounts, oauth=oauth, imports=imports,
                         storage=storage, ai_jobs=ai_jobs, omx_center=omx_center, sim_runs=sim_runs,
                         vlm_eval_url=args.vlm_eval_url, workspace_links=workspace_links, owners=owners,
                         recording_config=recording_config, ladder=ladder)
    print(f'Pinky review: http://{args.host}:{server.server_port}', flush=True)
    serve_review(server, store, args.decisions_port)


if __name__ == '__main__':
    main()
