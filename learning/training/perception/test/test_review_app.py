"""Persistent review, stale writes and explicit object-only approvals."""
import json

import pytest

from test_review_return import fixture_inputs
from review_app import ReviewStore, Conflict


def open_store(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    rows = [json.loads(s) for s in human.read_text().splitlines()]
    rows[1].update(review_status='pending_human', complete_frame_review=False,
                   disposition='excluded_by_user')
    human.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    return ReviewStore(tmp_path / 'state', source, human, images)


def test_restart_preserves_approval_exclusion_and_unknown(tmp_path):
    store = open_store(tmp_path)
    assert [r['status'] for r in store.list_frames()] == ['approved', 'excluded']
    assert ReviewStore(tmp_path / 'state').get(0)['review']['boxes'][0]['signal_state'] == 'unknown'
    result = store.prepare()
    assert result['exported_frames'] == 1
    assert result['queued_frames'] == 1
    assert result['training_dataset_qualified'] is False
    assert not list((store.state / 'exports').rglob('000001.txt'))


def test_edit_demotes_and_stale_tab_cannot_overwrite(tmp_path):
    store = open_store(tmp_path)
    frame = store.get(0)
    boxes = frame['review']['boxes']
    boxes[0]['bbox_xyxy'][0] = 2
    updated = store.update(0, {'version': frame['version'], 'action': 'save', 'boxes': boxes})
    assert updated['status'] == 'pending'
    assert updated['review']['complete_frame_review'] is False
    with pytest.raises(Conflict):
        store.update(0, {'version': frame['version'], 'action': 'exclude'})
    with pytest.raises(ValueError):
        store.update(0, {'version': updated['version'], 'action': 'approve', 'complete_frame_review': False})
    approved = store.update(0, {'version': updated['version'], 'action': 'approve', 'complete_frame_review': True})
    assert approved['status'] == 'approved'
    assert ReviewStore(store.state).get(0)['version'] == approved['version']


def test_bounds_hash_and_exclusion_guard(tmp_path):
    store = open_store(tmp_path)
    frame = store.get(0)
    boxes = frame['review']['boxes']
    boxes[0]['bbox_xyxy'][2] = 500
    with pytest.raises(ValueError):
        store.update(0, {'version': frame['version'], 'action': 'save', 'boxes': boxes})
    with pytest.raises(ValueError):
        store.update(1, {'version': 1, 'action': 'approve', 'complete_frame_review': True})
    store.image(0).write_bytes(b'changed')
    with pytest.raises(ValueError):
        store.prepare()


def test_candidates_are_pending_and_require_classification(tmp_path):
    store = open_store(tmp_path)
    frame = store.update(0, {'version': 1, 'action': 'candidates'})
    assert frame['status'] == 'pending'
    assert frame['review']['complete_frame_review'] is False
    boxes = [{'label': None, 'bbox_xyxy': [1, 2, 12, 14]}]
    frame = store.update(0, {'version': frame['version'], 'action': 'save', 'boxes': boxes})
    with pytest.raises(ValueError):
        store.update(0, {'version': frame['version'], 'action': 'approve', 'complete_frame_review': True})
    assert store.prepare()['exported_frames'] == 0


def test_http_images_revalidate_with_etag_and_tamper_guard(tmp_path):
    import threading
    import urllib.request
    import urllib.error
    from review_app import make_server
    store = open_store(tmp_path)
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        etag = '"' + store.get(0)['source']['image_sha256'] + '"'
        with urllib.request.urlopen(url + '/api/images/0') as response:
            assert response.headers['Cache-Control'] == 'no-cache'
            assert response.headers['ETag'] == etag
            assert response.read()
        request = urllib.request.Request(url + '/api/images/0', headers={'If-None-Match': etag})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 304
        request = urllib.request.Request(url + '/api/images/0', headers={'If-None-Match': '"stale"'})
        with urllib.request.urlopen(request) as response:
            assert response.status == 200 and response.read()
        with urllib.request.urlopen(url + '/api/mask-images/0') as response:
            mask_etag = response.headers['ETag']
            assert response.headers['Cache-Control'] == 'no-cache'
            assert response.read()
        request = urllib.request.Request(url + '/api/mask-images/0', headers={'If-None-Match': mask_etag})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 304
        # Revalidation never skips the on-disk hash check: a tampered file is refused even with a matching ETag.
        store.image(0).write_bytes(b'tampered')
        request = urllib.request.Request(url + '/api/images/0', headers={'If-None-Match': etag})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_http_blocks_foreign_hosts_and_tokenless_writes(tmp_path):
    import threading
    import urllib.request
    import urllib.error
    from review_app import make_server
    store = open_store(tmp_path)
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        workspace = json.load(urllib.request.urlopen(url + '/api/workspace'))
        assert len(json.load(urllib.request.urlopen(url + '/api/learning'))['workflows']) == 8
        with urllib.request.urlopen(url + '/learning') as response:
            assert response.headers.get_content_type() == 'text/html'
        report = tmp_path / 'state.json'
        report.write_text('{"outcome":"running"}')
        request = urllib.request.Request(url + '/api/learning/register', json.dumps(
            {'kind': 'perception', 'name': 'HTTP job', 'path': str(tmp_path)}).encode(),
            headers={'X-Pinky-Token': workspace['token']})
        item = json.load(urllib.request.urlopen(request))
        request = urllib.request.Request(url + '/api/learning/remove', json.dumps(
            {'id': item['id'], 'version': 999}).encode(), headers={'X-Pinky-Token': workspace['token']})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 409
        with urllib.request.urlopen(url + '/box-geometry.mjs') as response:
            assert response.headers.get_content_type() == 'text/javascript'
        for headers in ({}, {'X-Pinky-Token': workspace['token'], 'Origin': 'https://foreign.example'}) * 5:
            request = urllib.request.Request(url + '/api/prepare', b'{}', headers=headers)
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            assert error.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(url + '/api/workspace', headers={'Host': 'foreign.example'}))
        assert error.value.code == 403
        request = urllib.request.Request(url + '/api/frames/0', json.dumps({'version': 1, 'action': 'reopen'}).encode(), headers={'X-Pinky-Token': workspace['token']})
        assert json.load(urllib.request.urlopen(request))['status'] == 'pending'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def serve_as(monkeypatch, store, host):
    """Bind loopback but advertise `host`, so the tailnet Host/Origin rules run without that interface."""
    import threading
    import review_app
    real = review_app.ThreadingHTTPServer
    monkeypatch.setattr(review_app, 'ThreadingHTTPServer', lambda addr, handler: real(('127.0.0.1', addr[1]), handler))
    server = review_app.make_server(store, 0, host)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def status(url, path, headers, data=None):
    import urllib.error
    import urllib.request
    try:
        return urllib.request.urlopen(urllib.request.Request(url + path, data, headers=headers)).status
    except urllib.error.HTTPError as error:
        return error.code


def test_default_rejects_tailnet_host(tmp_path, monkeypatch):
    server = serve_as(monkeypatch, open_store(tmp_path), '127.0.0.1')
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        assert status(url, '/api/workspace', {'Host': f'100.98.162.71:{server.server_port}'}) == 403
    finally:
        server.shutdown()
        server.server_close()


def test_explicit_host_accepts_host_and_origin_but_keeps_token_and_foreign_origin(tmp_path, monkeypatch):
    import urllib.request
    server = serve_as(monkeypatch, open_store(tmp_path), '100.98.162.71')
    try:
        port = server.server_port
        url = f'http://127.0.0.1:{port}'
        host = {'Host': f'100.98.162.71:{port}'}
        assert status(url, '/api/workspace', host) == 200
        assert status(url, '/api/workspace', {}) == 200  # loopback forms stay allowed
        token = json.load(urllib.request.urlopen(urllib.request.Request(url + '/api/workspace', headers=host)))['token']
        origin = f'http://100.98.162.71:{port}'
        assert status(url, '/api/prepare', dict(host, Origin=origin), b'{}') == 403  # no token
        assert status(url, '/api/prepare', dict(host, Origin='https://foreign.example', **{'X-Pinky-Token': token}), b'{}') == 403
        assert status(url, '/api/prepare', dict(host, Origin=origin, **{'X-Pinky-Token': token}), b'{}') == 200
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('host', ['0.0.0.0', '::', '8.8.8.8', '100.128.0.1', 'localhost', 'example.com', '2001:db8::1'])
def test_unsafe_bind_host_fails_at_startup(tmp_path, host):
    from review_app import make_server
    with pytest.raises(ValueError):
        make_server(open_store(tmp_path), 0, host)
