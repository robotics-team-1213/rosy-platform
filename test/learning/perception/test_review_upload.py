"""Client-owned image bytes are imported without server filesystem authority."""
import base64

import cv2
import numpy as np
import pytest

import review_masks
import review_upload
from test_review_app import open_store
from test_learning_collaboration import running, request


def payload(name='photo.png'):
    raw = cv2.imencode('.png', np.full((24, 32, 3), 90, np.uint8))[1].tobytes()
    return {'name': name, 'data': base64.b64encode(raw).decode()}


def test_upload_preserves_decisions_and_retries_without_duplicates(tmp_path):
    store = open_store(tmp_path)
    before = store.get(0)
    result = review_upload.import_image(store, payload(), 'alice')
    assert result['added'] == 1
    frame = store.get(result['indices'][0])
    assert frame['status'] == 'pending'
    assert frame['source']['source_kind'] == 'browser_upload'
    assert frame['source']['upstream']['registered_by'] == 'alice'
    assert frame['source']['original_video_verified'] is False
    assert frame['source'].get('source_video_sha256') is None
    assert review_masks.get(store, frame['index'])['status'] == 'pending'
    assert review_upload.import_image(store, payload(), 'alice')['added'] == 0
    assert store.get(0) == before


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
        _, state = request(url, '/api/workspace', 'reviewer')
        body = payload()
        assert request(url, '/api/catalog/upload', 'reader', body, state['token'])[0] == 403
        assert request(url, '/api/catalog/upload', 'reviewer', body)[0] == 403
        code, result = request(url, '/api/catalog/upload', 'reviewer', body, state['token'])
        assert code == 200 and result['added'] == 1
