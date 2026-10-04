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
        for headers in ({}, {'X-Pinky-Token': workspace['token'], 'Origin': 'https://foreign.example'}):
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
