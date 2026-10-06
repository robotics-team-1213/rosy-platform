"""Pinky local persistent object review application (no robot or model access).

Run: python review_app.py --state <persistent-directory> --source source.jsonl
     --human human.jsonl --images <image-root> [--port 8767]
Restart with the same --state only. Local HTTP contract: docs/review-app.md.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import mimetypes
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import class_sets
import review_return
from learning_workspace import Workspace, WORKFLOWS
import review_evidence
import review_ingest
import review_masks

STATIC = Path(__file__).with_name('review_app_web')
COMMON = Path(__file__).resolve().parents[4] / 'shared' / 'web'
SHARED_ASSETS = json.loads((COMMON / 'shared-assets.json').read_text(encoding='utf-8'))['shared_assets']


class Conflict(ValueError):
    """The client must reload rather than overwrite a newer review."""


class ReviewStore:
    def __init__(self, state, source=None, human=None, images=None, object_classes=None):
        self.state = Path(state).resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = self.state / 'reviews.sqlite3'
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS frames (
                id INTEGER PRIMARY KEY, source TEXT NOT NULL, review TEXT NOT NULL,
                status TEXT NOT NULL, version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, ts TEXT DEFAULT CURRENT_TIMESTAMP,
                frame INTEGER, action TEXT, version INTEGER, review TEXT);
                CREATE TABLE IF NOT EXISTS exports (id TEXT PRIMARY KEY, receipt TEXT);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);''')
            initialized = db.execute("SELECT value FROM metadata WHERE key='initialized'").fetchone()
            if initialized:
                if any(x is not None for x in (source, human, images)):
                    raise ValueError('existing workspace: restart with --state only; imports never overwrite reviews')
                if object_classes is not None and object_classes.get('sha256') != class_sets.object_set(self)['sha256']:
                    raise ValueError('workspace object classes differ; do not reinterpret labels')
                review_masks.configure(self)
                review_evidence.configure(self)
                return
            if source is None or human is None or images is None:
                raise ValueError('first start requires source, human and images')
            # Existing receiver validates hashes, dimensions, boxes and the complete import.
            validation = self.state / ('import-' + uuid.uuid4().hex)
            record = object_classes or class_sets.legacy_object_set()
            classes = tuple(c['name'] for c in record['classes'])
            review_return.receive_review(source, human, images, validation, classes=classes)
            # One transaction: the binding commits or rolls back with the frame rows.
            db.execute('BEGIN IMMEDIATE')
            class_sets.bind_object_set(self, record, db)
            originals = review_return._parse(Path(source).read_bytes())
            reviews = review_return._parse(Path(human).read_bytes())
            for index, row in originals.items():
                review = reviews.get(index, {'index': index, 'image_sha256': row['image_sha256'],
                    'boxes': row.get('objects', row.get('boxes', [])),
                    'review_status': 'pending_human', 'complete_frame_review': False})
                status = ('excluded' if review.get('disposition') == 'excluded_by_user' else
                          'approved' if review['review_status'] == 'approved' and
                          review['complete_frame_review'] is True else 'pending')
                if status == 'excluded':
                    review.update(review_status='pending_human', complete_frame_review=False)
                suffix = Path(row['image']).suffix.lower()
                frozen = validation / 'inputs' / 'images' / f'{index:06d}{suffix}'
                row = dict(row, image=frozen.relative_to(self.state).as_posix())
                self.validate_boxes(row, review['boxes'], classes=classes)
                db.execute('INSERT INTO frames VALUES (?,?,?,?,1)',
                           (index, json.dumps(row), json.dumps(review), status))
                db.execute('INSERT INTO events(frame,action,version,review) VALUES (?,?,?,?)',
                           (index, 'import', 1, json.dumps(review)))
            db.execute("INSERT INTO metadata VALUES ('initialized','true')")
        review_masks.configure(self)
        review_evidence.configure(self)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def object_classes(self):
        return tuple(c['name'] for c in class_sets.object_set(self)['classes'])

    @staticmethod
    def validate_boxes(source, boxes, *, classes, approved=False):
        if not isinstance(boxes, list):
            raise ValueError('boxes must be a list')
        for box in boxes:
            review_return.exporter._check_human_box(box)
            allowed = classes + (() if approved else (None,))
            if box.get('label') not in allowed:
                raise ValueError('known object class required')
            x0, y0, x1, y1 = box['bbox_xyxy']
            if not (0 <= x0 < x1 <= source['width'] and 0 <= y0 < y1 <= source['height']):
                raise ValueError('box outside original image')
            if box.get('signal_state', 'unknown') not in ('unknown', 'red', 'yellow', 'green', 'off'):
                raise ValueError('unknown signal state')

    @staticmethod
    def decoded(row):
        return {'index': row['id'], 'source': json.loads(row['source']),
                'review': json.loads(row['review']), 'status': row['status'], 'version': row['version']}

    def get(self, index):
        with self.connect() as db:
            row = db.execute('SELECT * FROM frames WHERE id=?', (index,)).fetchone()
        if row is None:
            raise KeyError(index)
        return self.decoded(row)

    def list_frames(self):
        with self.connect() as db:
            return [self.decoded(row) for row in db.execute('SELECT * FROM frames ORDER BY id')]

    def image(self, index):
        row = self.get(index)['source']
        path = (self.state / row['image']).resolve()
        if not path.is_relative_to(self.state):
            raise ValueError('image outside workspace')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row['image_sha256']:
            raise ValueError('image hash mismatch')
        return path

    def update(self, index, body):
        classes = self.object_classes()
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            frame = self.get(index)
            if type(body.get('version')) is not int or body['version'] != frame['version']:
                raise Conflict('다른 탭에서 변경됐습니다. 최신 내용을 다시 불러오세요.')
            action = body.get('action')
            review, status = frame['review'], frame['status']
            if action == 'save':
                if status == 'excluded':
                    raise ValueError('제외 사진은 재검수로 돌린 후 수정하세요.')
                boxes = body.get('boxes')
                self.validate_boxes(frame['source'], boxes, classes=classes)
                review.update(boxes=boxes, review_status='pending_human', complete_frame_review=False,
                              review_origin='pinky_web_edit')
                review.pop('disposition', None)
                status = 'pending'
            elif action == 'approve':
                if status == 'excluded' or body.get('complete_frame_review') is not True:
                    raise ValueError('전체 프레임 확인과 재검수 상태가 필요합니다.')
                self.image(index)
                self.validate_boxes(frame['source'], review['boxes'], classes=classes, approved=True)
                review.update(review_status='approved', complete_frame_review=True,
                              review_origin='pinky_web_explicit_review')
                status = 'approved'
            elif action == 'candidates':
                if status == 'excluded':
                    raise ValueError('제외 사진은 재검수로 돌린 후 초안을 가져오세요.')
                boxes = frame['source'].get('objects', frame['source'].get('boxes', []))
                self.validate_boxes(frame['source'], boxes, classes=classes)
                review.update(boxes=boxes, review_status='pending_human', complete_frame_review=False,
                              review_origin='pinky_web_candidate_import')
                review.pop('disposition', None)
                status = 'pending'
            elif action in ('exclude', 'reopen'):
                status = 'excluded' if action == 'exclude' else 'pending'
                review.update(review_status='pending_human', complete_frame_review=False,
                              review_origin='pinky_web_explicit_review')
                if action == 'exclude':
                    review['disposition'] = 'excluded_by_user'
                else:
                    review.pop('disposition', None)
            else:
                raise ValueError('unknown review action')
            version = frame['version'] + 1
            db.execute('UPDATE frames SET review=?,status=?,version=? WHERE id=?',
                       (json.dumps(review), status, version, index))
            db.execute('INSERT INTO events(frame,action,version,review) VALUES (?,?,?,?)',
                       (index, action, version, json.dumps(review)))
            db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
        return self.get(index)

    def prepare(self):
        with self.lock:
            captured = review_evidence.snapshot(self)
            frames = captured['frames']
            export_id = uuid.uuid4().hex
            inputs = self.state / 'exports' / (export_id + '-inputs')
            inputs.mkdir(parents=True)
            source, human = inputs / 'source.jsonl', inputs / 'human.jsonl'
            source.write_bytes(review_return._jsonl(f['source'] for f in frames))
            # Unclassified candidates are not valid human labels. Keep the complete
            # app snapshot; omit their pending human row from the training receiver.
            unclassified = [f['index'] for f in frames
                            if any(b.get('label') is None for b in f['review']['boxes'])]
            human.write_bytes(review_return._jsonl(review_evidence.human_review(f) for f in frames if f['index'] not in unclassified))
            (inputs / 'application-snapshot.json').write_text(json.dumps(frames, ensure_ascii=False, indent=2), encoding='utf-8')
            out = self.state / 'exports' / export_id
            receipt = review_return.receive_review(source, human, self.state, out, classes=self.object_classes())
            receipt.update(export_id=export_id, path=str(out),
                           frame_versions={str(f['index']): f['version'] for f in frames},
                           excluded_indices=[f['index'] for f in frames if f['status'] == 'excluded'],
                           unclassified_indices=unclassified,
                           segmentation_approved=False,
                           qualification='HOLD: learning owner must establish session mapping, session-disjoint splits and exclude every fixed eval set before training')
            receipt.update(review_contract_schema='rosy.pinky-review-export/2',
                           authority=captured['authority'],
                           current_decisions_required=True)
            (out / 'pinky-review-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
            contract = review_evidence.seal_export(self, out, receipt, captured)
            receipt['pixel_approved_frames'] = contract['pixel_approved_frames']
            with self.connect() as db:
                db.execute('INSERT INTO exports VALUES (?,?)', (export_id, json.dumps(receipt)))
            return receipt

    def exports(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT receipt FROM exports ORDER BY rowid DESC LIMIT 10')]


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


def make_server(store, port=8767, host='127.0.0.1'):
    check_bind_host(host)
    token = secrets.token_urlsafe(32)
    learning = Workspace(store.db)

    class Handler(BaseHTTPRequestHandler):
        def send(self, data, code=200, mime='application/json; charset=utf-8', etag=None, cache='no-store'):
            if isinstance(data, (dict, list)):
                data = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', cache)
            if etag:
                self.send_header('ETag', etag)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def allowed_host(self):
            port = self.server.server_port
            return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}', f'{host}:{port}')

        def do_GET(self):
            if not self.allowed_host():
                return self.send({'error': 'local host required'}, 403)
            path = urlparse(self.path).path
            try:
                if path == '/api/workspace':
                    frames = [dict(row, pixel_status=review_masks.get(store, row['index'])['status'])
                              for row in store.list_frames()]
                    object_set = class_sets.object_set(store)
                    return self.send({'frames': frames, 'classes': [c['name'] for c in object_set['classes']],
                                      'object_class_set': object_set,
                                      'token': token, 'exports': store.exports(), 'segmentation_supported': True,
                                      'pixel_classes': review_masks.classes(store),
                                      'map_reference': review_evidence.map_reference(store)})
                if path == '/api/decisions':
                    value = review_evidence.decisions(store)
                    tag = '"' + value['decision_sha256'] + '"'
                    if self.headers.get('If-None-Match') == tag:
                        return self.send(b'', 304, etag=tag)
                    return self.send(value, etag=tag)
                if path == '/api/catalog':
                    return self.send({'catalog': review_evidence.metadata(store, 'import_catalog'),
                                      'cad_catalog': review_evidence.metadata(store, 'cad_catalog'),
                                      'map_reference': review_evidence.map_reference(store), 'token': token})
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
                if path.startswith('/api/masks/'):
                    return self.send(review_masks.get(store, int(path.rsplit('/', 1)[1])))
                if path == '/api/learning':
                    return self.send({'workflows': WORKFLOWS, 'items': learning.list(), 'token': token,
                                      'counts': {state: sum(f['status'] == state for f in store.list_frames())
                                                 for state in ('approved', 'pending', 'excluded')}})
                if path.startswith('/api/images/'):
                    index = int(path.rsplit('/', 1)[1])
                    image = store.image(index)
                    etag = '"' + store.get(index)['source']['image_sha256'] + '"'
                    if self.headers.get('If-None-Match') == etag:
                        return self.send(b'', 304, etag=etag, cache='no-cache')
                    return self.send(image.read_bytes(), mime=mimetypes.guess_type(image.name)[0],
                                     etag=etag, cache='no-cache')
                files = {'/': 'index.html', '/app.js': 'app.js', '/app.css': 'app.css',
                         '/box-geometry.mjs': 'box-geometry.mjs', '/learning': 'learning.html',
                         '/learning.js': 'learning.js', '/pixels': 'pixels.html', '/pixels.js': 'pixels.js',
                         '/catalog': 'catalog.html', '/catalog.js': 'catalog.js'}
                name = path.removeprefix('/common/')
                if path.startswith('/common/') and name in SHARED_ASSETS:
                    file = COMMON / name
                    return self.send(file.read_bytes(), mime=SHARED_ASSETS[name])
                if path in files:
                    file = STATIC / files[path]
                    types = {'.html': 'text/html', '.css': 'text/css',
                             '.js': 'text/javascript', '.mjs': 'text/javascript'}
                    return self.send(file.read_bytes(), mime=types[file.suffix] + '; charset=utf-8')
                self.send({'error': 'not found'}, 404)
            except (KeyError, ValueError, OSError) as exc:
                self.send({'error': str(exc)}, 400)

        def do_POST(self):
            # Consume bounded rejected bodies before responding; Windows may otherwise
            # reset the connection while the client is still transmitting its request.
            def deny():
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if 0 < length <= 1048576:
                        self.connection.settimeout(5)
                        self.rfile.read(length)
                except (ValueError, OSError):
                    pass
                return self.send({'error': 'local workspace authorization required'}, 403)
            if not self.allowed_host() or self.headers.get('X-Pinky-Token') != token:
                return deny()
            origin = self.headers.get('Origin')
            port = self.server.server_port
            if origin and origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}', f'http://{host}:{port}'):
                return deny()
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1048576:
                    raise ValueError('bounded JSON body required')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('JSON object required')
                path = urlparse(self.path).path
                if path == '/api/prepare':
                    return self.send(store.prepare())
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
                if path.startswith('/api/masks/'):
                    return self.send(review_masks.update(store, int(path.rsplit('/', 1)[1]), body, Conflict))
                if path == '/api/learning/register':
                    return self.send(learning.register(body))
                if path == '/api/learning/remove':
                    try:
                        return self.send(learning.remove(body))
                    except ValueError as exc:
                        raise Conflict(str(exc)) from exc
                if path.startswith('/api/frames/'):
                    return self.send(store.update(int(path.rsplit('/', 1)[1]), body))
                self.send({'error': 'not found'}, 404)
            except Conflict as exc:
                self.send({'error': str(exc)}, 409)
            except (ValueError, KeyError, OSError) as exc:
                self.send({'error': str(exc)}, 400)

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--human', type=Path)
    parser.add_argument('--images', type=Path)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--host', default='127.0.0.1', help='bind address; default loopback (D-478)')
    parser.add_argument('--catalog', type=Path, help='prepared verified-inputs folder shown in app')
    parser.add_argument('--object-classes', type=Path,
                        help='Ultralytics data.yaml naming the object classes; first start binds it (D-485)')
    parser.add_argument('--cad-catalog', type=Path, help='verified CAD reference catalog shown in app')
    args = parser.parse_args()
    object_classes = None
    if args.object_classes:
        try:
            object_classes = class_sets.from_data_yaml(args.object_classes.read_bytes(), 'detect')
        except (OSError, ValueError) as exc:
            parser.error(f'--object-classes: {exc}')
    store = ReviewStore(args.state, args.source, args.human, args.images, object_classes)
    with store.connect() as db:
        for key, path in [('import_catalog', args.catalog), ('cad_catalog', args.cad_catalog)]:
            if path:
                db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, str(path.resolve())))
    server = make_server(store, args.port, args.host)
    print(f'Pinky review: http://{args.host}:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
