"""Persistent review, stale writes and explicit object-only approvals."""
import json

import pytest

from test_review_return import fixture_inputs
import class_sets
from review_app import ReviewStore, Conflict


def open_store(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    rows = [json.loads(s) for s in human.read_text().splitlines()]
    rows[1].update(review_status='pending_human', complete_frame_review=False,
                   disposition='excluded_by_user')
    human.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    return ReviewStore(tmp_path / 'state', source, human, images)


def test_learning_counts_unverified_source_video(tmp_path):
    import threading
    import urllib.request
    from review_app import make_server

    source, human, images = fixture_inputs(tmp_path)
    rows = [json.loads(line) for line in source.read_text(encoding='utf-8').splitlines()]
    rows[0].update(source_video_sha256='1' * 64, original_video_verified=False)
    source.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
    store = ReviewStore(tmp_path / 'state', source, human, images)
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}/api/learning'
        assert json.load(urllib.request.urlopen(url))['source_video_unverified'] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_empty_training_workspace_reopens_without_initial_labels(tmp_path):
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    assert store.list_frames() == []
    assert ReviewStore(store.state).list_frames() == []
    with pytest.raises(ValueError, match='reopen'):
        ReviewStore(store.state, empty_training=True)


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
        legacy = class_sets.legacy_object_set()
        assert workspace['object_class_set'] == legacy
        assert workspace['classes'] == [c['name'] for c in legacy['classes']]
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


CAR_LIGHT = b'names: [car, traffic_light]\n'


def test_workspace_with_a_new_class_set_saves_and_exports_its_labels(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    record = class_sets.from_data_yaml(CAR_LIGHT, 'detect')
    store = ReviewStore(tmp_path / 'state', source, human, images, object_classes=record)
    frame = store.get(0)
    boxes = [dict(frame['review']['boxes'][0], label='car')]
    saved = store.update(0, {'version': frame['version'], 'action': 'save', 'boxes': boxes})
    with pytest.raises(ValueError, match='known object class'):
        store.update(0, {'version': saved['version'], 'action': 'save',
                         'boxes': [dict(boxes[0], label='cone')]})
    assert class_sets.object_set(store)['sha256'] == record['sha256']
    store.update(0, {'version': saved['version'], 'action': 'approve', 'complete_frame_review': True})
    receipt = store.prepare()
    out = store.state / 'exports' / receipt['export_id']
    assert receipt['classes'] == ['car', 'traffic_light']
    assert (out / 'groups/32x24/000000.txt').read_text().startswith('0 ')    # car is index 0 here
    assert (out / 'groups/64x48/000001.txt').read_text().startswith('1 ')    # traffic_light is 1, not 3
    contract = json.loads((out / 'review-contract.json').read_bytes())
    assert contract['object_class_set_sha256'] == record['sha256']
    # Decision authority stays byte-compatible: the class set is not part of decision_sha256.
    assert 'object_class_set_sha256' not in contract['authority']


def test_first_start_refuses_labels_outside_the_class_set_and_binds_nothing(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    record = class_sets.from_data_yaml(b'names: [car, robot]\n', 'detect')
    with pytest.raises(ValueError, match='object class'):
        ReviewStore(tmp_path / 'state', source, human, images, object_classes=record)
    store = ReviewStore(tmp_path / 'state', source, human, images)   # a failed start locks nothing
    assert class_sets.object_set(store)['sha256'] == class_sets.legacy_object_set()['sha256']


def test_restart_keeps_the_bound_set_and_refuses_another(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    record = class_sets.from_data_yaml(CAR_LIGHT, 'detect')
    ReviewStore(tmp_path / 'state', source, human, images, object_classes=record)
    assert class_sets.object_set(ReviewStore(tmp_path / 'state'))['sha256'] == record['sha256']
    ReviewStore(tmp_path / 'state', object_classes=record)
    with pytest.raises(ValueError, match='object classes differ'):
        ReviewStore(tmp_path / 'state', object_classes=class_sets.legacy_object_set())


def test_a_failed_import_after_binding_leaves_no_orphan_set(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    rows = [json.loads(line) for line in human.read_text().splitlines()]
    rows[1]['boxes'][0]['label'] = 'none'   # the receiver accepts REJECT; the store refuses it
    human.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    record = class_sets.from_data_yaml(CAR_LIGHT, 'detect')
    with pytest.raises(ValueError, match='known object class'):
        ReviewStore(tmp_path / 'state', source, human, images, object_classes=record)
    (tmp_path / 'again').mkdir()
    source, human, images = fixture_inputs(tmp_path / 'again')
    other = class_sets.from_data_yaml(b'names: [traffic_light]\n', 'detect')
    store = ReviewStore(tmp_path / 'state', source, human, images, object_classes=other)
    assert class_sets.object_set(store)['sha256'] == other['sha256']


def test_restart_with_the_same_names_but_new_display_is_accepted(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    record = class_sets.from_data_yaml(CAR_LIGHT, 'detect')
    ReviewStore(tmp_path / 'state', source, human, images, object_classes=record)
    shown = class_sets.from_data_yaml(
        'names: [car, traffic_light]\ndisplay: {car: "자동차"}\n'.encode('utf-8'), 'detect')
    ReviewStore(tmp_path / 'state', object_classes=shown)


def test_legacy_decision_authority_is_unchanged_by_the_binding(tmp_path):
    import review_evidence
    store = open_store(tmp_path)
    bound = review_evidence.decisions(store)
    assert set(bound) == {'schema', 'workspace_id', 'generation', 'frames', 'pixel_classes_sha256',
                          'classes_signature', 'ignore_index', 'map_reference_sha256', 'decision_sha256'}
    with store.connect() as db:   # the same workspace as made before D-485
        db.execute("DELETE FROM metadata WHERE key='object_class_set'")
    assert review_evidence.decisions(store) == bound


@pytest.mark.parametrize('content', [None, b'names: [a\n'])
def test_bad_object_classes_file_is_a_usage_error(tmp_path, monkeypatch, capsys, content):
    import sys
    import review_app
    path = tmp_path / 'data.yaml'
    if content is not None:
        path.write_bytes(content)
    monkeypatch.setattr(sys, 'argv', ['review_app.py', '--state', str(tmp_path / 'state'),
                                      '--object-classes', str(path)])
    with pytest.raises(SystemExit) as stop:
        review_app.main()
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert '--object-classes' in err and 'Traceback' not in err
