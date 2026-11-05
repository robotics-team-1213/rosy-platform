"""Client-owned image bytes are imported without server filesystem authority."""
import base64
import json
import struct
import zlib

import cv2
import numpy as np
import pytest

import review_masks
import review_upload
import review_ingest
from test_review_app import open_store
from test_learning_collaboration import running, request
from test_review_cycle import CLASSES


def payload(name='photo.png'):
    raw = cv2.imencode('.png', np.full((24, 32, 3), 90, np.uint8))[1].tobytes()
    return {'name': name, 'data': base64.b64encode(raw).decode()}


def test_upload_preserves_decisions_and_retries_without_duplicates(tmp_path):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    before = store.get(0)
    result = review_upload.import_image(store, payload(), 'alice')
    assert result['added'] == 1
    frame = store.get(result['indices'][0])
    assert frame['status'] == 'pending'
    assert frame['source']['source_kind'] == 'browser_upload'
    assert frame['source']['upstream']['registered_by'] == 'alice'
    assert frame['source']['original_video_verified'] is False
    assert frame['source'].get('source_video_sha256') is None
    assert review_masks.get(store, result['indices'][0])['status'] == 'pending'
    assert review_upload.import_image(store, payload(), 'alice')['added'] == 0
    assert store.get(0) == before


@pytest.mark.parametrize('extension', ['.png', '.jpg'])
@pytest.mark.parametrize('damage', ['oversized', 'corrupt', 'truncated'])
def test_image_headers_rejected_before_any_pixel_decode(tmp_path, monkeypatch, extension, damage):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    raw = bytearray(cv2.imencode(extension, np.full((24, 32, 3), 90, np.uint8))[1].tobytes())
    if extension == '.png':
        if damage == 'oversized':
            raw[16:20] = (4097).to_bytes(4, 'big')
            raw[29:33] = zlib.crc32(raw[12:29]).to_bytes(4, 'big')
        elif damage == 'corrupt':
            raw[29] ^= 1
        else:
            raw = raw[:25]
    else:
        frame = raw.index(b'\xff\xc0')
        if damage == 'oversized':
            raw[frame + 7:frame + 9] = (4097).to_bytes(2, 'big')
        elif damage == 'corrupt':
            raw[frame + 2:frame + 4] = b'\0\1'
        else:
            raw = raw[:frame + 7]
    raw = bytes(raw)
    assert len(raw) < 4096
    before = store.list_frames()
    monkeypatch.setattr(cv2, 'imdecode', lambda *_: pytest.fail('untrusted dimensions reached pixel decoder'))
    with pytest.raises(ValueError):
        review_ingest.image(raw, review_masks.sha(raw), 32, 24)
    with pytest.raises(ValueError):
        review_upload.import_image(store, {'name': 'photo' + extension, 'data': base64.b64encode(raw).decode()}, 'alice')
    incoming = tmp_path / ('incoming' + extension)
    incoming.write_bytes(raw)
    entry = {'path': incoming.name, 'sha256': review_masks.sha(raw)}
    with pytest.raises(ValueError):
        review_ingest.import_hf(store, {'repo_type': 'dataset', 'repo_id': 'team/images', 'revision': 'a' * 40,
                                      'files': [entry]}, {incoming.name: incoming}, 'alice')
    assert store.list_frames() == before


@pytest.mark.parametrize('extension,options', [('.png', []), ('.jpg', []), ('.jpg', [cv2.IMWRITE_JPEG_PROGRESSIVE, 1])])
def test_bounded_png_and_jpeg_headers_preserve_valid_uploads(tmp_path, extension, options):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    raw = cv2.imencode(extension, np.full((24, 32, 3), 90, np.uint8), options)[1].tobytes()
    assert review_ingest.image_dimensions(raw) == (32, 24)
    review_ingest.image(raw, review_masks.sha(raw), 32, 24)
    result = review_upload.import_image(store, {'name': 'photo' + extension, 'data': base64.b64encode(raw).decode()}, 'alice')
    assert result['added'] == 1
    assert store.get(result['indices'][0])['source']['width'] == 32


def test_phone_jpeg_exif_rotation_preserves_decoded_catalog_dimensions(tmp_path):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    raw = cv2.imencode('.jpg', np.full((24, 32, 3), 90, np.uint8))[1].tobytes()
    # A single little-endian TIFF orientation entry (6 = rotate 90 degrees clockwise).
    exif = b'Exif\0\0II' + struct.pack('<HIH', 42, 8, 1)
    exif += struct.pack('<HHIHHI', 0x0112, 3, 1, 6, 0, 0)
    raw = raw[:2] + b'\xff\xe1' + struct.pack('>H', len(exif) + 2) + exif + raw[2:]
    assert review_ingest.image_dimensions(raw) == (32, 24)
    assert cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR).shape[:2] == (32, 24)
    review_ingest.image(raw, review_masks.sha(raw), 24, 32)
    with pytest.raises(ValueError, match='source image dimensions differ'):
        review_ingest.image(raw, review_masks.sha(raw), 32, 24)
    result = review_upload.import_image(store, {'name': 'phone.jpg', 'data': base64.b64encode(raw).decode()}, 'alice')
    source = store.get(result['indices'][0])['source']
    assert (source['width'], source['height']) == (24, 32)


@pytest.mark.parametrize('body', [payload('../secret.png'), {'name': 'x.png', 'data': 'invalid'},
                                {'name': 'x.txt', 'data': 'YQ=='},
                                {**payload(), 'path': '/home/another-user/private'}])
def test_upload_rejects_invalid_input_without_adding_frames(tmp_path, body):
    store = open_store(tmp_path)
    before = store.list_frames()
    with pytest.raises(ValueError):
        review_upload.import_image(store, body, 'alice')
    assert store.list_frames() == before


def test_project_upload_requires_import_permission_and_csrf(tmp_path):
    with running(tmp_path) as (url, _, store):
        review_masks.bind_classes(store, CLASSES)
        _, state = request(url, '/api/workspace', 'reviewer')
        body = payload()
        assert request(url, '/api/catalog/upload', 'reader', body, state['token'])[0] == 403
        assert request(url, '/api/catalog/upload', 'reviewer', body)[0] == 403
        code, result = request(url, '/api/catalog/upload', 'reviewer', body, state['token'])
        assert code == 200 and result['added'] == 1


def test_configured_folder_imports_only_selected_date_originals(tmp_path):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    root = tmp_path / 'capture'
    run = root / 'run_20261102_190726'
    run.mkdir(parents=True)
    raw = base64.b64decode(payload()['data'])
    (run / 'original.png').write_bytes(raw)
    (run / 'corrected').mkdir()
    (run / 'corrected' / 'derived.png').write_bytes(raw)
    (root / 'run_20261031_190726').mkdir()
    (root / 'run_20261031_190726' / 'other.png').write_bytes(raw)
    config = [{'id': 'geg6-1102', 'label': '11월 2일', 'path': str(root), 'pattern': 'run_20261102_*'}]
    with store.connect() as db:
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('image_folders', json.dumps(config)))
    assert review_upload.folders(store) == [{'id': 'geg6-1102', 'label': '11월 2일'}]
    with pytest.raises(ValueError):
        review_upload.import_folder(store, {'id': 'geg6-1102', 'path': '/home/other'}, 'alice')
    result = review_upload.import_folder(store, {'id': 'geg6-1102'}, 'alice')
    assert result['added'] == 1
    frame = store.get(result['indices'][0])
    assert frame['source']['source_session'] == 'folder:geg6-1102:run_20261102_190726'
    assert frame['source']['source_kind'] == 'local_folder'
    assert review_upload.import_folder(store, {'id': 'geg6-1102'}, 'alice')['added'] == 0


def test_upload_http_accepts_image_larger_than_default_json_limit(tmp_path):
    raw = cv2.imencode('.png', np.random.default_rng(0).integers(0, 256, (768, 768, 3), dtype=np.uint8))[1].tobytes()
    body = {'name': 'large.png', 'data': base64.b64encode(raw).decode()}
    assert len(json.dumps(body)) > 1048576
    with running(tmp_path) as (url, _, store):
        review_masks.bind_classes(store, CLASSES)
        _, state = request(url, '/api/workspace', 'reviewer')
        code, result = request(url, '/api/catalog/upload', 'reviewer', body, state['token'])
        assert code == 200 and result['added'] == 1
