"""D-857 §2: --workspace-links lists the center's other review workspaces; the file is a trust boundary."""
import json
import os
import threading

import pytest

from review_app import load_workspace_links, make_server
from test_learning_collaboration import Accounts, request
from test_review_app import open_store

ROW = {'id': 'v13-train', 'label': 'v13 주행 학습', 'url': 'https://learning.example:8443/learning',
       'kind': 'training', 'note': '인식 학습 루프가 묶인 작업 공간'}


def write(tmp_path, workspaces, schema='rosy.learning.workspace-links/1', **extra):
    path = tmp_path / 'workspace-links.json'
    path.write_text(json.dumps({'schema': schema, 'workspaces': workspaces, **extra}), encoding='utf-8')
    return path


def test_valid_file_loads_every_kind(tmp_path):
    rows = [ROW, dict(ROW, id='v13-eval', kind='evaluation', url='http://eval.example/'),
            {'id': 'dataset-937', 'label': '937장 검수', 'url': 'https://review.example', 'kind': 'review'}]
    assert load_workspace_links(write(tmp_path, rows)) == rows


@pytest.mark.parametrize('change, message', [
    ({'schema': 'rosy.learning.workspace-links/2'}, 'schema'),
    ({'extra': 1}, 'schema'),
    ({'workspaces': [dict(ROW, id=f'w{n}') for n in range(21)]}, 'at most 20'),
    ({'workspaces': [ROW, ROW]}, 'unique'),
    ({'workspaces': [dict(ROW, id='Bad_Id')]}, 'unique'),
    ({'workspaces': [dict(ROW, id='a' * 41)]}, 'unique'),
    ({'workspaces': [dict(ROW, label='x' * 61)]}, 'label'),
    ({'workspaces': [dict(ROW, label=' ')]}, 'label'),
    ({'workspaces': [dict(ROW, note='x' * 161)]}, 'note'),
    ({'workspaces': [dict(ROW, kind='deploy')]}, 'kind'),
    ({'workspaces': [dict(ROW, extra='x')]}, 'optional note'),
    ({'workspaces': [{k: v for k, v in ROW.items() if k != 'url'}]}, 'optional note'),
    ({'workspaces': [dict(ROW, label=7)]}, 'optional note'),
    ({'workspaces': [dict(ROW, url='file:///etc/passwd')]}, 'url'),
    ({'workspaces': [dict(ROW, url='javascript:alert(1)')]}, 'url'),
    ({'workspaces': [dict(ROW, url='https:///learning')]}, 'url'),
    ({'workspaces': [dict(ROW, url='https://user:pw@learning.example/')]}, 'url'),
    ({'workspaces': [dict(ROW, url='https://user@learning.example/')]}, 'url'),
    ({'workspaces': [dict(ROW, url='https://learning.example/#top')]}, 'url'),
    ({'workspaces': [dict(ROW, url='https://learning.example:99999/')]}, 'url'),
    ({'workspaces': [dict(ROW, url='https://learning.example/ x')]}, 'url'),
    ({'workspaces': [dict(ROW, url='https://learning.example/' + 'a' * 300)]}, 'url'),
])
def test_each_rejection(tmp_path, change, message):
    value = {'schema': 'rosy.learning.workspace-links/1', 'workspaces': [ROW]} | change
    path = tmp_path / 'links.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError, match=message):
        load_workspace_links(path)


def test_file_must_be_regular_small_utf8_json(tmp_path):
    good = write(tmp_path, [ROW])
    link = tmp_path / 'link.json'
    try:
        os.symlink(good, link)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks unavailable')
    with pytest.raises(ValueError, match='not a link'):
        load_workspace_links(link)
    with pytest.raises(ValueError, match='regular file'):
        load_workspace_links(tmp_path)
    big = tmp_path / 'big.json'
    big.write_bytes(b' ' * (64 * 1024 + 1))
    with pytest.raises(ValueError, match='64 KiB'):
        load_workspace_links(big)
    for raw in (b'\xff{}', b'{not json'):
        big.write_bytes(raw)
        with pytest.raises(ValueError):
            load_workspace_links(big)
    with pytest.raises(OSError):
        load_workspace_links(tmp_path / 'missing.json')


def test_startup_refuses_a_bad_file_with_the_flag_name(tmp_path, monkeypatch, capsys):
    import review_app
    bad = write(tmp_path, [dict(ROW, url='https://learning.example/#x')])
    monkeypatch.setattr('sys.argv', ['review_app.py', '--state', str(tmp_path / 'state'), '--workspace-links', str(bad)])
    with pytest.raises(SystemExit) as exit:
        review_app.main()
    assert exit.value.code == 2 and '--workspace-links: workspace v13-train: url' in capsys.readouterr().err


def serving(store, **options):
    server = make_server(store, 0, **options)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f'http://127.0.0.1:{server.server_port}'


class NoView(Accounts):
    def authenticate(self, session):
        if session == 'guest':
            return dict(user_id='guest', project_id='alpha', capabilities=[])
        return super().authenticate(session)


@pytest.mark.parametrize('accounts', [None, NoView()])
def test_http_list_is_empty_without_the_flag_and_needs_view(tmp_path, accounts):
    for links, expected in [(None, {'configured': False, 'workspaces': []}),
                            ([ROW], {'configured': True, 'workspaces': [ROW]})]:
        folder = tmp_path / str(bool(links))
        folder.mkdir()
        server, thread, base = serving(open_store(folder), accounts=accounts, workspace_links=links)
        try:
            if accounts:
                assert request(base, '/api/learning/workspaces')[0] == 401
                assert request(base, '/api/learning/workspaces', 'guest')[0] == 403
            assert request(base, '/api/learning/workspaces', 'reader' if accounts else None) == (200, expected)
        finally:
            server.shutdown(); server.server_close(); thread.join()


def test_make_server_rechecks_links(tmp_path):
    with pytest.raises(ValueError, match='url'):
        make_server(open_store(tmp_path), 0, workspace_links=[dict(ROW, url='ftp://x/')])
