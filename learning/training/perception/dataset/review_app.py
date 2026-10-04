"""Pinky local persistent object review application (no robot or model access).

Run: python review_app.py --state <persistent-directory> --source source.jsonl
     --human human.jsonl --images <image-root> [--port 8767]
Restart with the same --state only. Local HTTP contract: review_app.md.
"""
from __future__ import annotations

import argparse
import hashlib
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

import review_return

STATIC = Path(__file__).with_name('review_app_web')
COMMON = Path(__file__).resolve().parents[4] / 'shared' / 'web'
SHARED_ASSETS = json.loads((COMMON / 'shared-assets.json').read_text(encoding='utf-8'))['shared_assets']


class Conflict(ValueError):
    """The client must reload rather than overwrite a newer review."""


class ReviewStore:
    def __init__(self, state, source=None, human=None, images=None):
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
                return
            if source is None or human is None or images is None:
                raise ValueError('first start requires source, human and images')
            # Existing receiver validates hashes, dimensions, boxes and the complete import.
            validation = self.state / ('import-' + uuid.uuid4().hex)
            review_return.receive_review(source, human, images, validation)
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
                self.validate_boxes(row, review['boxes'])
                db.execute('INSERT INTO frames VALUES (?,?,?,?,1)',
                           (index, json.dumps(row), json.dumps(review), status))
                db.execute('INSERT INTO events(frame,action,version,review) VALUES (?,?,?,?)',
                           (index, 'import', 1, json.dumps(review)))
            db.execute("INSERT INTO metadata VALUES ('initialized','true')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def validate_boxes(source, boxes, *, approved=False):
        if not isinstance(boxes, list):
            raise ValueError('boxes must be a list')
        for box in boxes:
            review_return.exporter._check_human_box(box)
            allowed = review_return.exporter.OBJECT_CLASSES + (() if approved else (None,))
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
                self.validate_boxes(frame['source'], boxes)
                review.update(boxes=boxes, review_status='pending_human', complete_frame_review=False,
                              review_origin='pinky_web_edit')
                review.pop('disposition', None)
                status = 'pending'
            elif action == 'approve':
                if status == 'excluded' or body.get('complete_frame_review') is not True:
                    raise ValueError('전체 프레임 확인과 재검수 상태가 필요합니다.')
                self.image(index)
                self.validate_boxes(frame['source'], review['boxes'], approved=True)
                review.update(review_status='approved', complete_frame_review=True,
                              review_origin='pinky_web_explicit_review')
                status = 'approved'
            elif action == 'candidates':
                if status == 'excluded':
                    raise ValueError('제외 사진은 재검수로 돌린 후 초안을 가져오세요.')
                boxes = frame['source'].get('objects', frame['source'].get('boxes', []))
                self.validate_boxes(frame['source'], boxes)
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
        return self.get(index)

    def prepare(self):
        with self.lock:
            frames = self.list_frames()
            export_id = uuid.uuid4().hex
            inputs = self.state / 'exports' / (export_id + '-inputs')
            inputs.mkdir(parents=True)
            source, human = inputs / 'source.jsonl', inputs / 'human.jsonl'
            source.write_bytes(review_return._jsonl(f['source'] for f in frames))
            # Unclassified candidates are not valid human labels. Keep the complete
            # app snapshot; omit their pending human row from the training receiver.
            unclassified = [f['index'] for f in frames
                            if any(b.get('label') is None for b in f['review']['boxes'])]
            human.write_bytes(review_return._jsonl(f['review'] for f in frames if f['index'] not in unclassified))
            (inputs / 'application-snapshot.json').write_text(json.dumps(frames, ensure_ascii=False, indent=2), encoding='utf-8')
            out = self.state / 'exports' / export_id
            receipt = review_return.receive_review(source, human, self.state, out)
            receipt.update(export_id=export_id, path=str(out),
                           frame_versions={str(f['index']): f['version'] for f in frames},
                           excluded_indices=[f['index'] for f in frames if f['status'] == 'excluded'],
                           unclassified_indices=unclassified,
                           segmentation_approved=False,
                           qualification='HOLD: learning owner must establish session mapping, session-disjoint splits and exclude every fixed eval set before training')
            (out / 'pinky-review-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
            with self.connect() as db:
                db.execute('INSERT INTO exports VALUES (?,?)', (export_id, json.dumps(receipt)))
            return receipt

    def exports(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT receipt FROM exports ORDER BY rowid DESC LIMIT 10')]


def make_server(store, port=8767):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def send(self, data, code=200, mime='application/json; charset=utf-8'):
            if isinstance(data, (dict, list)):
                data = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def allowed_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.allowed_host():
                return self.send({'error': 'local host required'}, 403)
            path = urlparse(self.path).path
            try:
                if path == '/api/workspace':
                    return self.send({'frames': store.list_frames(), 'classes': list(review_return.exporter.OBJECT_CLASSES),
                                      'token': token, 'exports': store.exports(), 'segmentation_supported': False})
                if path.startswith('/api/images/'):
                    image = store.image(int(path.rsplit('/', 1)[1]))
                    return self.send(image.read_bytes(), mime=mimetypes.guess_type(image.name)[0])
                files = {'/': 'index.html', '/app.js': 'app.js', '/app.css': 'app.css',
                         '/box-geometry.mjs': 'box-geometry.mjs'}
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
            if not self.allowed_host() or self.headers.get('X-Pinky-Token') != token:
                return self.send({'error': 'local workspace token required'}, 403)
            origin = self.headers.get('Origin')
            if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
                return self.send({'error': 'same origin required'}, 403)
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
                if path.startswith('/api/frames/'):
                    return self.send(store.update(int(path.rsplit('/', 1)[1]), body))
                self.send({'error': 'not found'}, 404)
            except Conflict as exc:
                self.send({'error': str(exc)}, 409)
            except (ValueError, KeyError, OSError) as exc:
                self.send({'error': str(exc)}, 400)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--human', type=Path)
    parser.add_argument('--images', type=Path)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    store = ReviewStore(args.state, args.source, args.human, args.images)
    server = make_server(store, args.port)
    print(f'Pinky review: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
