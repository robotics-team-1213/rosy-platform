"""D-792: the camera page stores immutable references and checks a photo over HTTP."""
import base64
import hashlib
import json
import threading
import urllib.error
import urllib.request

import cv2
import pytest

from review_app import ReviewStore, make_server
from test_camera_setup import HOME, K, LAYOUT, _render, rotate, scene
from test_review_return import fixture_inputs


def _jpeg(frame):
    return base64.b64encode(cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()).decode()


def body(image, method='features', layout=(), **extra):
    return {'image_jpeg': image, 'camera_role': 'front', 'camera_identity': 'omx-front-usb-1', 'fps': 30,
            'intrinsics': K, 'method': method, 'layout': list(layout), 'measured': {}, 'guides': [], 'check_pose': None, **extra}


@pytest.fixture
def app(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    store = ReviewStore(tmp_path / 'state', source, human, images)
    server = make_server(store, 0)
    server.daemon_threads = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        with urllib.request.urlopen(url + '/api/workspace') as response:
            token = json.load(response)['token']

        def call(path, payload=None, token=token):
            data = None if payload is None else json.dumps(payload).encode()
            request = urllib.request.Request(url + path, data, headers={'X-Pinky-Token': token} if data else {})
            with urllib.request.urlopen(request) as response:
                raw = response.read()
                return json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw

        yield call, store
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_features_reference_check_and_still_round_trip(app):
    call, store = app
    assert call('/api/learning/camera/references') == {'references': []}
    assert b'<h1>' in call('/learning/camera') and b'camera.js' in call('/learning/camera')
    image = _jpeg(scene())
    doc = call('/api/learning/camera/reference', body(image))
    assert doc['method'] == 'features' and doc['mount']['estimated'] is None
    assert [r['revision'] for r in call('/api/learning/camera/references')['references']] == [doc['revision']]
    still = call('/api/learning/camera/stills/' + doc['revision'])
    assert hashlib.sha256(still).hexdigest() == doc['reference_still']

    def check(frame):
        return call('/api/learning/camera/check', {'reference_revision': doc['revision'], 'image_jpeg': _jpeg(frame),
                                                   'camera_info_sha256': K['camera_info_sha256'], 'joints': None})
    same = check(scene())
    assert same['check']['verdict'] == 'ok' and len(same['homography']) == 3
    moved = check(rotate(scene(), pan=1.0))
    assert moved['check']['verdict'] == 'adjust'
    assert moved['check']['d_pan_deg'] == pytest.approx(1.0, abs=0.2)

    # A tampered reference file is refused rather than silently used.
    path = store.state / 'camera-setup' / f"{doc['revision']}.json"
    path.write_text(json.dumps({**doc, 'fps': 15}), encoding='utf-8')
    with pytest.raises(urllib.error.HTTPError) as error:
        call('/api/learning/camera/references')
    with error.value:
        assert error.value.code == 400


def test_markers_reference_reports_centimetres(app):
    call, _ = app
    image = _jpeg(_render(**HOME))
    doc = call('/api/learning/camera/reference', body(image, 'markers', LAYOUT))
    assert doc['mount']['estimated']['height_cm'] == pytest.approx(45.0, abs=0.5)
    lower = _jpeg(_render(centre=[0.0, -40.0, 43.0], target=[0.0, 15.0, 0.0]))
    moved = call('/api/learning/camera/check', {'reference_revision': doc['revision'], 'image_jpeg': lower,
                                                'camera_info_sha256': K['camera_info_sha256'], 'joints': None})
    assert moved['check']['verdict'] == 'adjust' and sorted(moved['detected']) == ['0', '1', '2', '3']
    assert moved['check']['d_height_cm'] < -1


def test_reference_write_needs_the_token_and_a_jpeg(app):
    call, _ = app
    image = _jpeg(scene())
    for payload, token, code in [(body(image), 'wrong', 403),
                                 (body(base64.b64encode(b'not a jpeg').decode()), None, 400),
                                 (body(image, measured={'weight_kg': 1}), None, 400),
                                 (body(image, method='sift'), None, 400),
                                 (body(image, layout=LAYOUT), None, 400)]:
        with pytest.raises(urllib.error.HTTPError) as error:
            call('/api/learning/camera/reference', payload, **({'token': token} if token else {}))
        with error.value:
            assert error.value.code == code
