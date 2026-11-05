"""Bounded review pages retain queue counts, source scope and deep-link navigation."""
import json

import pytest

from review_store import ReviewStore


def large_store(tmp_path):
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    with store.connect() as db:
        db.executemany('INSERT INTO frames VALUES (?,?,?,?,1)', (
            (index, json.dumps({'source_session': 'folder:geg6-1102:run' if index < 1637 else 'old',
                               'width': 32, 'height': 24, 'image': 'not-read.jpg',
                               'image_sha256': 'a' * 64}),
             json.dumps({'boxes': [], 'review_status': 'pending_human'}),
             'excluded' if index == 1 else 'pending') for index in range(6000)))
        db.execute("INSERT INTO masks(frame,version,status) VALUES (0,1,'approved')")
    return store


def test_page_decodes_only_sixty_of_six_thousand_frames(tmp_path, monkeypatch):
    store = large_store(tmp_path)
    decoded = []
    original = store.decoded
    monkeypatch.setattr(store, 'decoded', lambda row: (decoded.append(row['id']), original(row))[1])
    page = store.frame_page(offset=60)
    assert decoded == list(range(60, 120))
    assert page['page'] == {'offset': 60, 'limit': 60, 'total': 6000, 'target': None}
    assert page['counts'] == {'pending': 5999, 'excluded': 1, 'approved': 0}
    assert page['pixel_counts'] == {'pending': 5998, 'excluded': 0, 'approved': 1}
    assert len(json.dumps(page['frames'])) * 50 < len(json.dumps(store.list_frames()))


def test_page_filters_pixels_and_finds_next_pending_across_page_boundary(tmp_path):
    store = large_store(tmp_path)
    page = store.frame_page(lane='pixel', status='pending', after=59)
    assert page['page']['target'] == 60
    assert any(row['index'] == 60 for row in page['frames'])
    assert all(row['status'] != 'excluded' and row['pixel_status'] == 'pending' for row in page['frames'])
    wrapped = store.frame_page(lane='pixel', status='pending', after=5999)
    assert wrapped['frames'][0]['index'] == 2
    assert store.frame_page(around=5999)['frames'][-1]['index'] == 5999
    assert store.frame_page(offset=99999)['page']['offset'] == 5940


def test_default_prefix_scope_is_literal_and_explicit_session_can_override(tmp_path):
    store = large_store(tmp_path)
    with store.connect() as db:
        db.execute('INSERT INTO metadata VALUES (?,?)', ('review_source_prefix', json.dumps('folder:geg6-1102:')))
    scoped = store.frame_page(around=5999)
    assert scoped['page']['total'] == 1637
    assert scoped['counts']['pending'] == 1636
    assert scoped['frames'][-1]['index'] == 1636
    assert store.frame_page(source_session='old')['page']['total'] == 4363
    with store.connect() as db:
        db.execute("UPDATE metadata SET value=? WHERE key='review_source_prefix'", (json.dumps('folder:%'),))
    assert store.frame_page()['page']['total'] == 0


@pytest.mark.parametrize('options', [{'limit': 61}, {'limit': 0}, {'offset': -1},
                                    {'around': -1}, {'after': -1}, {'lane': 'other'}, {'status': 'other'}])
def test_page_rejects_invalid_bounds_before_reading(tmp_path, options):
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    with pytest.raises(ValueError):
        store.frame_page(**options)


def test_workspace_http_page_never_uses_unbounded_list(tmp_path, monkeypatch):
    import threading
    import urllib.error
    import urllib.request
    from review_app import make_server

    store = large_store(tmp_path)
    server = make_server(store, 0)
    monkeypatch.setattr(store, 'list_frames', lambda: pytest.fail('unbounded frame read'))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/api/workspace'
    try:
        with urllib.request.urlopen(url + '?limit=60&around=120') as response:
            page = json.load(response)
        assert len(page['frames']) == 60
        assert page['frames'][0]['index'] == 120
        assert page['page']['total'] == 6000
        for query in ('limit=61', 'limit=60&limit=60', 'offset=-1', 'lane=wrong', 'unknown=1'):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(url + '?' + query)
            assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
