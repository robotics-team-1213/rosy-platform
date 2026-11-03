"""Configured review folders narrow one bound state without revealing server paths."""
import json
import hashlib
import threading
import urllib.error
import urllib.request

import pytest

from review_app import make_server
from test_review_pagination import large_store


def configured_store(tmp_path):
    store = large_store(tmp_path)
    with store.connect() as db:
        db.execute('INSERT INTO metadata VALUES (?,?)', ('image_folders', json.dumps([
            {'id': 'geg6-1102', 'label': '11월 2일', 'path': '/private/capture'},
            {'id': 'second', 'label': '다른 자료', 'path': '/private/second'}])))
        db.execute('UPDATE frames SET source=json_set(source,\'$.source_session\',?) WHERE id>=1637',
                   ('folder:second:run',))
    return store


def test_registered_folder_default_pagination_and_exact_session_intersection(tmp_path):
    store = configured_store(tmp_path)
    page = store.frame_page(offset=60)
    assert page['page']['total'] == 1637
    assert page['frames'][0]['index'] == 60
    assert page['context']['folder_id'] == 'geg6-1102'
    second = store.frame_page(folder_id='second', around=1697)
    assert second['frames'][0]['index'] == 1697
    assert second['page']['total'] == 4363
    assert store.frame_page(folder_id='all')['page']['total'] == 6000
    assert store.frame_page(folder_id='second', source_session='folder:geg6-1102:run')['page']['total'] == 0
    assert store.frame_page(folder_id='second', source_session='folder:second:run')['page']['total'] == 4363
    assert '/private/' not in json.dumps(second['context'])


def test_uploaded_groups_are_exact_server_derived_scopes_without_changing_default(tmp_path):
    store = configured_store(tmp_path)
    with store.connect() as db:
        for index, session, kind in [(5995, 'upload:photos/day-one', 'browser_upload'),
                                     (5996, 'upload:photos/day-one', 'browser_upload'),
                                     (5997, 'upload:photos/day-one-extra', 'browser_upload'),
                                     (5998, 'upload:files', 'browser_upload'),
                                     (5999, 'upload:photos/day-one', 'folder_import')]:
            db.execute("UPDATE frames SET source=json_set(source,'$.source_session',?,'$.source_kind',?) WHERE id=?", (session, kind, index))
    key = 'upload-' + hashlib.sha256(b'upload:photos/day-one').hexdigest()[:16]
    loose = 'upload-' + hashlib.sha256(b'upload:files').hexdigest()[:16]
    default = store.frame_page()
    assert default['context']['folder_id'] == 'geg6-1102'
    assert default['page']['total'] == 1637
    folders = {item['id']: item['label'] for item in default['context']['folders']}
    assert folders[key] == '업로드 · day-one' and folders[loose] == '개별 업로드'
    assert len(folders) == 5
    uploaded = store.frame_page(folder_id=key)
    assert [row['index'] for row in uploaded['frames']] == [5995, 5996]
    assert uploaded['context']['total'] == 2 and uploaded['context']['folder_id'] == key
    assert store.frame_page(folder_id=loose)['page']['total'] == 1
    assert store.frame_page(folder_id=key, source_session='upload:photos/day-one-extra')['page']['total'] == 0
    assert store.frame_page(folder_id=key, source_session='upload:photos/day-one')['page']['total'] == 2
    assert store.frame_page(folder_id='second')['page']['total'] == 4358
    assert store.frame_page(folder_id='all')['page']['total'] == 6000
    assert '/private/' not in json.dumps(default['context'])
    assert 'photos/' not in json.dumps(default['context'])
    with pytest.raises(ValueError, match='unknown review folder'):
        store.frame_page(folder_id='upload-0000000000000000')


def test_context_http_rejects_unknown_folder_and_preserves_bound_identity(tmp_path):
    store = configured_store(tmp_path)
    with store.connect() as db:
        db.execute("UPDATE frames SET source=json_set(source,'$.source_kind','browser_upload','$.source_session','upload:files') WHERE id=5999")
    links = [{'id': 'other', 'label': '다른 작업공간', 'url': 'https://review.example/pixels', 'kind': 'review'}]
    server = make_server(store, 0, workspace_links=links)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        with urllib.request.urlopen(url + '/api/workspace') as response:
            data = json.load(response)
        assert len(data['frames']) == 60
        assert data['context']['workspaces'] == links
        assert data['context']['workspace']['id']
        assert '/private/' not in json.dumps(data)
        uploaded_id = next(item['id'] for item in data['context']['folders'] if item['label'] == '개별 업로드')
        with urllib.request.urlopen(url + '/api/workspace?folder_id=' + uploaded_id) as response:
            uploaded = json.load(response)
        assert uploaded['page']['total'] == 1 and uploaded['frames'][0]['index'] == 5999
        for query in ('folder_id=unknown', 'folder_id=upload-0000000000000000', 'folder_id=../second', 'folder_id=second&project_id=other'):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(url + '/api/workspace?' + query)
            assert error.value.code == 400
        with urllib.request.urlopen(url + '/review-context.js') as response:
            assert response.headers['Content-Type'].startswith('text/javascript')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
