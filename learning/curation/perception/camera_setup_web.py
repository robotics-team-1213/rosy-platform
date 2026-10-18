"""D-792 S2 camera setup HTTP helpers: immutable references under the review state; advice only."""
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import cv2
import numpy as np

import camera_setup
from rosy.contracts.learning.camera_setup import MOUNT, validate_reference


def _root(state):
    return Path(state) / 'camera-setup'


def _fields(body, fields):
    if set(body) != set(fields.split()):
        raise ValueError(f'exact fields required: {fields}')


def _image(body):
    try:
        raw = base64.b64decode(body['image_jpeg'], validate=True)
    except (binascii.Error, TypeError) as exc:
        raise ValueError('base64 JPEG image required') from exc
    if not raw.startswith(b'\xff\xd8'):
        raise ValueError('JPEG image required')
    frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError('JPEG image could not be decoded')
    return raw, frame


def load(state, revision):
    if not re.fullmatch('[0-9a-f]{64}', revision or ''):
        raise ValueError('reference revision required')
    doc = validate_reference(json.loads((_root(state) / f'{revision}.json').read_text(encoding='utf-8')))
    if doc['revision'] != revision:
        raise ValueError('reference file does not match its revision')
    return doc


def references(state):
    root = _root(state)
    docs = [load(state, path.stem) for path in root.glob('*.json')] if root.is_dir() else []
    return sorted(docs, key=lambda doc: doc['created_at'], reverse=True)


def still(state, revision):
    doc = load(state, revision)
    raw = (_root(state) / f'{revision}.jpg').read_bytes()
    if hashlib.sha256(raw).hexdigest() != doc['reference_still']:
        raise ValueError('reference still does not match its reference')
    return raw


def create(state, body, actor):
    _fields(body, 'image_jpeg camera_role camera_identity fps intrinsics method layout measured guides check_pose')
    if body['method'] not in ('features', 'markers'):
        raise ValueError('method must be features or markers')
    if not isinstance(body['measured'], dict) or not set(body['measured']) <= set(MOUNT):
        raise ValueError('measured accepts only ' + ' '.join(MOUNT))
    raw, frame = _image(body)
    doc = camera_setup.make_reference(
        frame, camera_role=body['camera_role'], camera_identity=body['camera_identity'], fps=body['fps'],
        intrinsics=body['intrinsics'], method=body['method'], layout=body['layout'], measured=body['measured'],
        guides=body['guides'], check_pose=body['check_pose'],
        reference_still=hashlib.sha256(raw).hexdigest(),
        created_at=datetime.now(timezone.utc).isoformat(timespec='seconds'), created_by=actor or 'local-unidentified')
    root = _root(state)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / f"{doc['revision']}.jpg", 'xb') as out:  # never overwrite an existing reference
        out.write(raw)
    with open(root / f"{doc['revision']}.json", 'x', encoding='utf-8') as out:
        json.dump(doc, out, ensure_ascii=False, indent=1)
    return doc


def check(state, body):
    _fields(body, 'reference_revision image_jpeg camera_info_sha256 joints')
    reference = load(state, body['reference_revision'])
    _, frame = _image(body)
    reference_still = cv2.imdecode(np.frombuffer(still(state, reference['revision']), np.uint8), cv2.IMREAD_COLOR)
    record, overlay = camera_setup.measure(frame, reference, body['camera_info_sha256'], reference_still, body['joints'])
    return {'check': record, **overlay}


STATIC = Path(__file__).with_name('review_app_web')
PAGES = {'/learning/camera': ('camera.html', 'text/html; charset=utf-8'),
         '/camera.js': ('camera.js', 'text/javascript; charset=utf-8')}


def get(handler, path, state):
    """Serve the camera page and its reads; False leaves the path to review_app."""
    if path in PAGES:
        name, mime = PAGES[path]
        handler.send((STATIC / name).read_bytes(), mime=mime)
    elif path == '/api/learning/camera/references':
        handler.send({'references': references(state)})
    elif path.startswith('/api/learning/camera/stills/'):
        handler.send(still(state, path.rsplit('/', 1)[1]), mime='image/jpeg', cache='no-cache')
    else:
        return False
    return True


def post(handler, path, body, state, collaboration):
    """Camera writes after review_app's token, origin and (collaboration) manage checks; False passes on."""
    if path == '/api/learning/camera/reference':
        handler.send(create(state, body, handler.learning_principal['user_id'] if collaboration else None))
    elif path == '/api/learning/camera/check':
        handler.send(check(state, body))
    else:
        return False
    return True
