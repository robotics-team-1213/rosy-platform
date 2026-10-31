"""D-943 §4: a finished center model goes to a private HF repo only after a preview and an explicit upload."""
import io
import shutil
import sys
import time
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parents[1] / 'curation' / 'perception'))
TOKEN = 'hf_secret_token_value'


def archive():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as zf:
        for name, data in {'result.json': b'{"ok": true}', 'evaluation.json': b'{}',
                           'request.json': b'{"dataset_root": "/home/rosy/data"}',
                           'policy/config.json': b'{}', 'policy/model.safetensors': b'weights'}.items():
            zf.writestr(name, data)
    return stream.getvalue()


def center(tmp_path):
    import experiment_center
    c = experiment_center.Center({'schema': 'rosy.omx.center-config/1', 'root': str(tmp_path / 'center'),
                                  'python': {'act': sys.executable, 'hilserl': sys.executable}})
    c.artifact = lambda rid: archive()
    return c


class FakeHub:
    def __init__(self, private=True):
        self.private, self.commits = private, []

    def repo_info(self, repo_id, repo_type):
        return SimpleNamespace(private=self.private, sha='a' * 40)

    def create_commit(self, operations, **kwargs):
        self.commits.append(operations)
        return SimpleNamespace(oid='b' * 40)


def wait(hub, bid):
    for _ in range(200):
        state = hub.status(bid)
        if state['state'] != 'uploading':
            return state
        time.sleep(0.02)
    raise AssertionError('upload did not finish')


def test_preview_excludes_host_request_and_is_idempotent(tmp_path):
    hub = center(tmp_path).hub
    body = dict(run_id=str(uuid.uuid4()), repo_id='team/omx-act', request_id=str(uuid.uuid4()))
    state = hub.prepare(body)
    assert state['state'] == 'prepared' and state['repo_type'] == 'model'
    assert set(state['files']) == {'result.json', 'evaluation.json', 'policy/config.json', 'policy/model.safetensors'}
    assert hub.prepare(body)['bundle_id'] == state['bundle_id']
    with pytest.raises(ValueError):
        hub.prepare(dict(body, repo_id='team/other'))
    assert [b['bundle_id'] for b in hub.bundles()] == [body['request_id']]


def test_upload_reads_back_the_commit_and_never_stores_the_token(tmp_path):
    hub = center(tmp_path).hub
    bid = hub.prepare(dict(run_id=str(uuid.uuid4()), repo_id='team/omx-act', request_id=str(uuid.uuid4())))['bundle_id']
    payload = hub.root / bid / 'payload'
    fake = FakeHub()
    hub.upload(bid, TOKEN, api=fake, operation=lambda path_in_repo, path_or_fileobj: path_in_repo,
               downloader=lambda local_dir, **k: shutil.copytree(payload, local_dir))
    state = wait(hub, bid)
    assert state['state'] == 'uploaded' and state['receipt']['revision'] == 'b' * 40
    assert sorted(fake.commits[0]) == sorted(state['files'])
    assert hub.upload(bid, TOKEN, api=fake)['state'] == 'uploaded' and len(fake.commits) == 1
    assert not any(TOKEN.encode() in p.read_bytes() for p in hub.root.rglob('*') if p.is_file())


def test_public_destination_fails_with_a_reason_and_can_retry(tmp_path):
    hub = center(tmp_path).hub
    bid = hub.prepare(dict(run_id=str(uuid.uuid4()), repo_id='team/omx-act', request_id=str(uuid.uuid4())))['bundle_id']
    state = wait(hub, hub.upload(bid, TOKEN, api=FakeHub(private=False), operation=None, downloader=None)['bundle_id'])
    assert state['state'] == 'failed' and 'private' in state['error']


def test_upload_route_requires_a_project_hf_connection(tmp_path):
    import omx_center_web
    c = center(tmp_path)
    handler = SimpleNamespace(send=lambda value: None)
    with pytest.raises(ValueError, match='HF'):
        omx_center_web.post(handler, omx_center_web.PREFIX + '/hub-upload',
                            {'bundle_id': str(uuid.uuid4()), 'connection_id': 'c'}, c, None, None)
