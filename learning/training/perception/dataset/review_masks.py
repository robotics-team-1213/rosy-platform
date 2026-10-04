"""Independent, versioned pixel reviews. Never derive human truth from CAD/boxes."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import build


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(pixels):
    ok, data = cv2.imencode('.png', pixels)
    if not ok:
        raise ValueError('mask encoding failed')
    return data.tobytes()


def configure(store):
    with store.connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS masks (
            frame INTEGER PRIMARY KEY, version INTEGER NOT NULL, status TEXT NOT NULL,
            path TEXT, sha256 TEXT, complete INTEGER DEFAULT 0, background INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS pixel_events (
            id INTEGER PRIMARY KEY, ts TEXT DEFAULT CURRENT_TIMESTAMP,
            frame INTEGER, version INTEGER, action TEXT, review TEXT);''')
        if 'approval' not in {r['name'] for r in db.execute('PRAGMA table_info(masks)')}:
            db.execute('ALTER TABLE masks ADD COLUMN approval TEXT')


def classes(store):
    with store.connect() as db:
        row = db.execute("SELECT value FROM metadata WHERE key='pixel_classes'").fetchone()
    return json.loads(row[0]) if row else None


def bind_classes(store, raw):
    values = build.load_classes(Path('classes.yaml'), source_bytes=raw)
    indices = [c['index'] for c in values]
    if len(set(indices)) != len(indices) or any(not 0 <= index < 255 for index in indices):
        raise ValueError('unique pixel class indices in 0..254 required')
    binding = {'classes': values, 'sha256': sha(raw), 'ignore_index': 255,
               'classes_signature': sha(json.dumps(values, sort_keys=True).encode())}
    folder = store.state / 'pixel'
    folder.mkdir(exist_ok=True)
    path = folder / (binding['sha256'] + '.yaml')
    if not path.exists():
        path.write_bytes(raw)
    if path.read_bytes() != raw:
        raise ValueError('pixel class file changed')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute("SELECT value FROM metadata WHERE key='pixel_classes'").fetchone()
        if existing and json.loads(existing[0])['sha256'] != binding['sha256']:
            raise ValueError('workspace pixel classes differ; do not reinterpret masks')
        if not existing:
            db.execute("INSERT INTO metadata VALUES ('pixel_classes',?)", (json.dumps(binding),))
            db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
    return binding


def freeze(store, raw):
    folder = store.state / 'pixel'
    folder.mkdir(exist_ok=True)
    path = folder / (sha(raw) + '.png')
    if not path.exists():
        path.write_bytes(raw)
    elif path.read_bytes() != raw:
        raise ValueError('mask hash collision')
    return path.relative_to(store.state).as_posix(), sha(raw)


def get(store, index):
    frame = store.get(index)
    with store.connect() as db:
        row = db.execute('SELECT * FROM masks WHERE frame=?', (index,)).fetchone()
    result = dict(row) if row else {'frame': index, 'version': 0, 'status': 'pending',
                                   'path': None, 'sha256': None, 'complete': 0, 'background': 0}
    result.update(width=frame['source']['width'], height=frame['source']['height'], classes=classes(store))
    result['approval'] = json.loads(result['approval']) if result.get('approval') else None
    return result


def pixels(store, review):
    if review['path'] is None:
        return np.full((review['height'], review['width']), 255, dtype=np.uint8)
    path = (store.state / review['path']).resolve()
    if not path.is_relative_to(store.state):
        raise ValueError('mask outside workspace')
    data = path.read_bytes()
    if sha(data) != review['sha256']:
        raise ValueError('mask hash mismatch')
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or image.shape != (review['height'], review['width']) or image.dtype != np.uint8:
        raise ValueError('mask shape or index format differs')
    return image


def from_color(raw, width, height, labelmap_raw, binding):
    mapping = build.parse_labelmap(Path('labelmap.txt'), binding['classes'], source_bytes=labelmap_raw)
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape != (height, width, 3):
        raise ValueError('draft mask dimensions differ')
    rgb = image[..., ::-1]
    result = np.full((height, width), 255, dtype=np.uint8)
    known = np.zeros((height, width), dtype=bool)
    for color, index in mapping.items():
        selected = np.all(rgb == color, axis=2)
        result[selected] = index
        known |= selected
    if not known.all():
        raise ValueError('unknown draft mask color')
    return encode(result)


def flood_region(store, index, review, seed, tolerance):
    """4-connected photo region around `seed` within RGB distance `tolerance`.

    The mask follows the photo's own colour boundary: only the connected area
    of similar pixels is selected, so a wall click does not spill onto the
    floor. Pure photo similarity, never a training label by itself; the
    reviewer's explicit approve still claims the result.
    """
    raw = store.image(index).read_bytes()
    photo = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if photo is None or (photo.shape[1], photo.shape[0]) != (review['width'], review['height']):
        raise ValueError('source image dimensions differ')
    target = photo[seed[1], seed[0]].astype(np.int16)
    inside = (np.sqrt(((photo.astype(np.int16) - target) ** 2).sum(axis=2)) <= float(tolerance))
    _, labels = cv2.connectedComponents(inside.astype(np.uint8), connectivity=4)
    return labels == labels[seed[1], seed[0]]


def update(store, index, body, conflict):
    with store.lock, store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        frame, review = store.get(index), get(store, index)
        if type(body.get('version')) is not int or body['version'] != review['version']:
            raise conflict('픽셀 검수가 다른 탭에서 변경됐습니다. 다시 불러오세요.')
        if frame['status'] == 'excluded':
            raise ValueError('제외 사진은 객체 재검수로 돌린 후 픽셀 검수하세요.')
        binding = review['classes']
        if not binding:
            raise ValueError('검증된 classes.yaml을 포함한 자료를 먼저 등록하세요.')
        image = pixels(store, review)
        allowed = {c['index'] for c in binding['classes']} | {255}
        action = body.get('action')
        complete = background = 0
        status = 'pending'
        if action in ('paint', 'fill', 'flood'):
            value = body.get('label')
            if type(value) is not int or value not in allowed:
                raise ValueError('known mask index required')
            if action == 'fill':
                image[:] = value
            elif action == 'flood':
                seed = body.get('seed')
                if (not isinstance(seed, list) or len(seed) != 2
                        or any(type(v) is not int for v in seed)
                        or not 0 <= seed[0] < review['width']
                        or not 0 <= seed[1] < review['height']):
                    raise ValueError('flood seed outside original image')
                tolerance = body.get('tolerance', 16)
                if type(tolerance) is not int or not 0 <= tolerance <= 100:
                    raise ValueError('bounded flood tolerance required')
                image[flood_region(store, index, review, seed, tolerance)] = value
            else:
                points, radius = body.get('points'), body.get('radius')
                if type(radius) is not int or not 1 <= radius <= 128:
                    raise ValueError('bounded brush radius required')
                if not isinstance(points, list) or not 1 <= len(points) <= 2048:
                    raise ValueError('bounded brush points required')
                checked = []
                for point in points:
                    if (not isinstance(point, list) or len(point) != 2 or
                        any(type(v) is not int for v in point) or
                        not 0 <= point[0] < review['width'] or not 0 <= point[1] < review['height']):
                        raise ValueError('brush point outside original image')
                    checked.append(tuple(point))
                for point in checked:
                    cv2.circle(image, point, radius, value, -1)
                for first, second in zip(checked, checked[1:]):
                    cv2.line(image, first, second, value, radius * 2)
        elif action == 'undo':
            # Walk back one edit per undo: after an undo, the next target is the
            # edit that produced the version that undo restored.
            last = db.execute('SELECT action, review FROM pixel_events WHERE frame=? ORDER BY id DESC LIMIT 1', (index,)).fetchone()
            target = None
            if last and review['status'] == 'pending' and json.loads(last[1]).get('saved_version') == review['version']:
                want = review['version'] if last[0] in ('paint', 'fill', 'flood') else json.loads(last[1]).get('restored_version')
                target = db.execute("SELECT review FROM pixel_events WHERE frame=? AND version=? AND action IN ('paint','fill','flood')", (index, want)).fetchone()
            if not target:
                raise ValueError('되돌릴 픽셀 수정이 없습니다.')
            prior = json.loads(target[0])
            image = pixels(store, dict(review, path=prior['path'], sha256=prior['sha256']))
        elif action == 'approve':
            if body.get('complete_frame_review') is not True or body.get('background_reviewed') is not True:
                raise ValueError('사진 전체와 기본 배경을 각각 확인하세요.')
            if np.any(image == 255):
                raise ValueError('미검수 픽셀이 남아 있습니다.')
            if frame['source'].get('fixed_eval_overlap'):
                raise ValueError('고정 평가와 겹치는 자료는 학습 승인할 수 없습니다.')
            store.image(index)
            complete = background = 1
            status = 'approved'
        elif action == 'exclude':
            status = 'excluded'
        elif action != 'reopen':
            raise ValueError('unknown pixel review action')
        path, digest = freeze(store, encode(image))
        version = review['version'] + 1
        approval = None
        if status == 'approved':
            approval = {'image_sha256': frame['source']['image_sha256'], 'mask_sha256': digest,
                        'mask_version': version, 'classes_sha256': binding['sha256'],
                        'classes_signature': sha(json.dumps(binding['classes'], sort_keys=True).encode()),
                        'ignore_index': binding['ignore_index'], 'width': review['width'],
                        'height': review['height'], 'complete_frame_review': True,
                        'background_reviewed': True}
        db.execute('INSERT OR REPLACE INTO masks(frame,version,status,path,sha256,complete,background,approval) VALUES (?,?,?,?,?,?,?,?)',
                   (index, version, status, path, digest, complete, background,
                    json.dumps(approval) if approval else None))
        previous = {key: review[key] for key in ('path', 'sha256', 'version')}
        previous['saved_version'] = version
        if action == 'undo':
            previous['restored_version'] = prior['version']
        db.execute('INSERT INTO pixel_events(frame,version,action,review) VALUES (?,?,?,?)',
                   (index, version, action, json.dumps(previous)))
        db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
    return get(store, index)
