"""D-792 S2: the camera page stores immutable references and checks a photo over HTTP."""
import base64
import hashlib
import json
import threading
import urllib.error
import urllib.request

import cv2
import pytest

from review_app import ReviewStore, make_server
from test_camera_setup import HOME, K, LAYOUT, _render
from test_review_return import fixture_inputs


def _jpeg(frame):
    return base64.b64encode(cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()).decode()


@pytest.fixture
def app(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    store = ReviewStore(tmp_path / 'state', source, human, images)
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    token = json.load(urllib.request.urlopen(url + '/api/workspace'))['token']

    def call(path, body=None, token=token):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url + path, data, headers={'X-Pinky-Token': token} if data else {})
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw

    yield call, store
    server.shutdown()
    server.server_close()
    thread.join()


def test_reference_check_and_still_round_trip(app):
    call, store = app
    assert call('/api/learning/camera/references') == {'references': []}
    assert b'<h1>' in call('/learning/camera') and b'camera.js' in call('/learning/camera')
    image = _jpeg(_render(**HOME))
    doc = call('/api/learning/camera/reference', {
        'image_jpeg': image, 'camera_role': 'front', 'camera_identity': 'omx-front-usb-1', 'fps': 30,
        'intrinsics': K, 'layout': LAYOUT, 'measured': {'height_cm': 45.0}, 'guides': []})
    assert doc['mount']['estimated']['height_cm'] == pytest.approx(45.0, abs=0.5)
    assert [r['revision'] for r in call('/api/learning/camera/references')['references']] == [doc['revision']]
    still = call('/api/learning/camera/stills/' + doc['revision'])
    assert hashlib.sha256(still).hexdigest() == doc['reference_still']

    same = call('/api/learning/camera/check', {'reference_revision': doc['revision'], 'image_jpeg': image,
                                               'camera_info_sha256': K['camera_info_sha256']})
    assert same['check']['verdict'] == 'ok' and sorted(same['detected']) == ['0', '1', '2', '3']
    lower = _jpeg(_render(centre=[0.0, -40.0, 43.0], target=[0.0, 15.0, 0.0]))
    moved = call('/api/learning/camera/check', {'reference_revision': doc['revision'], 'image_jpeg': lower,
                                                'camera_info_sha256': K['camera_info_sha256']})
    assert moved['check']['verdict'] == 'adjust'

    # A tampered reference file is refused rather than silently used.
    path = store.state / 'camera-setup' / f"{doc['revision']}.json"
    path.write_text(json.dumps({**doc, 'fps': 15}), encoding='utf-8')
    with pytest.raises(urllib.error.HTTPError) as error:
        call('/api/learning/camera/references')
    assert error.value.code == 400


def test_reference_write_needs_the_token_and_a_jpeg(app):
    call, _ = app
    body = {'image_jpeg': _jpeg(_render(**HOME)), 'camera_role': 'front', 'camera_identity': 'x', 'fps': 30,
            'intrinsics': K, 'layout': LAYOUT, 'measured': {}, 'guides': []}
    with pytest.raises(urllib.error.HTTPError) as error:
        call('/api/learning/camera/reference', body, token='wrong')
    assert error.value.code == 403
    with pytest.raises(urllib.error.HTTPError) as error:
        call('/api/learning/camera/reference', {**body, 'image_jpeg': base64.b64encode(b'not a jpeg').decode()})
    assert error.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as error:
        call('/api/learning/camera/reference', {**body, 'measured': {'weight_kg': 1}})
    assert error.value.code == 400
