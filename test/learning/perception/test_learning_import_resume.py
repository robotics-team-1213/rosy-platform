"""Persistent partial downloads, worker ownership and fail-closed HTTP ranges."""
import hashlib
import io
import json
import shutil
import threading
from types import SimpleNamespace

import pytest

from learning_imports import HFTransport, LearningImports
from test_learning_imports import SHA, create, make


def resumable(service, transport):
    original = transport.resolve
    def resolve(*args):
        doc = original(*args)
        for row in doc['siblings']:
            row['lfs'] = {'sha256': hashlib.sha256(transport.data[row['rfilename']]).hexdigest()}
        return doc
    transport.resolve = resolve
    offsets = []
    def chunks(kind, repo, revision, filename, token, *, offset=0, total=None):
        offsets.append((filename, offset))
        data = transport.data[filename]
        yield data[offset:offset + 1]
        if transport.fail:
            raise OSError('private provider URL must not leak')
        yield data[offset + 1:]
    transport.chunks = chunks
    return offsets


def test_partial_restart_resumes_pinned_hash_and_records_progress(tmp_path):
    service, transport, _ = make(tmp_path)
    offsets = resumable(service, transport)
    job = create(service)
    transport.fail = True
    service.run(job['id'], 'alice')
    failed = service.get('alice', 'alpha', job['id'])
    assert failed['files'][0]['downloaded_bytes'] == 1
    assert failed['files'][0]['partial_sha256'] == hashlib.sha256(b'v').hexdigest()
    restarted = LearningImports(service.root, service.authorize, service.credential, transport=transport)
    transport.fail = False
    restarted.retry('alice', 'alpha', job['id'])
    restarted.run(job['id'], 'alice')
    done = restarted.get('alice', 'alpha', job['id'])
    assert offsets == [('clip.mp4', 0), ('clip.mp4', 1), ('meta.json', 0)]
    assert done['status'] == 'completed' and done['revision'] == SHA
    assert done['reserved_bytes'] == 0
    assert all(row['downloaded_bytes'] == row['bytes'] for row in done['files'])
    assert 'private provider' not in json.dumps(done)


@pytest.mark.parametrize('damage', ['prefix', 'oversize', 'no_hash'])
def test_untrusted_partial_restarts_without_appending(tmp_path, damage):
    service, transport, _ = make(tmp_path)
    offsets = resumable(service, transport)
    if damage == 'no_hash':
        transport.resolve = type(transport).resolve.__get__(transport)
    job = create(service)
    transport.fail = True
    service.run(job['id'], 'alice')
    part = service.root / '.partial' / job['id'] / 'files/clip.mp4'
    if damage != 'no_hash': part.write_bytes(b'X' if damage == 'prefix' else b'excess bytes')
    transport.fail = False
    service.retry('alice', 'alpha', job['id'])
    service.run(job['id'], 'alice')
    assert offsets[1] == ('clip.mp4', 0)
    assert service.get('alice', 'alpha', job['id'])['status'] == 'completed'


def test_disk_admission_prevents_download_and_retry_recovers(tmp_path, monkeypatch):
    service, transport, _ = make(tmp_path)
    job = create(service)
    actual = shutil.disk_usage
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    service.run(job['id'], 'alice')
    failed = service.get('alice', 'alpha', job['id'])
    assert failed['error'] == 'insufficient_space'
    assert failed['reserved_bytes'] == 0
    assert not transport.downloads
    monkeypatch.setattr(shutil, 'disk_usage', actual)
    service.retry('alice', 'alpha', job['id'])
    service.run(job['id'], 'alice')
    assert service.get('alice', 'alpha', job['id'])['status'] == 'completed'


def test_second_service_does_not_interrupt_active_worker(tmp_path):
    service, transport, _ = make(tmp_path)
    job = create(service)
    entered, release = threading.Event(), threading.Event()
    original = transport.chunks
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        yield from original(*args, **kwargs)
    transport.chunks = paused
    thread = threading.Thread(target=service.run, args=(job['id'], 'alice'))
    thread.start()
    try:
        assert entered.wait(10)
        other = LearningImports(service.root, service.authorize, service.credential, transport=transport)
        assert other.get('alice', 'alpha', job['id'])['status'] == 'running'
        other.run(job['id'], 'alice')
        assert other.get('alice', 'alpha', job['id'])['status'] == 'running'
    finally:
        release.set(); thread.join(10)
    assert not thread.is_alive()
    assert service.get('alice', 'alpha', job['id'])['status'] == 'completed'
    assert len(transport.downloads) == 2


@pytest.mark.parametrize('limits', [{'max_file_bytes': True}, {'reserve_bytes': -1},
                                  {'unexpected': 1}, {'max_total_bytes': 1}])
def test_private_limits_are_validated(tmp_path, limits):
    service, _, _ = make(tmp_path)
    with pytest.raises(ValueError):
        LearningImports(service.root, service.authorize, service.credential, limits=limits)


@pytest.mark.parametrize('status,headers,accepted', [
    (206, {'Content-Range': 'bytes 2-4/5', 'Content-Length': '3'}, True),
    (200, {'Content-Length': '5'}, False),
    (206, {'Content-Range': 'bytes 0-2/5'}, False),
    (206, {'Content-Range': 'bytes 2-4/6'}, False),
    (206, {'Content-Range': 'bytes 2-4/5', 'Content-Encoding': 'gzip'}, False),
])
def test_range_response_requires_exact_offset_total_and_encoding(monkeypatch, status, headers, accepted):
    requests = []
    class Response(io.BytesIO):
        def __init__(self):
            super().__init__(b'deo'); self.status = status; self.headers = headers
    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            return Response()
    monkeypatch.setattr('urllib.request.build_opener', lambda *args: Opener())
    def consume():
        return b''.join(HFTransport().chunks('dataset', 'org/data', SHA, 'clip.mp4',
                                            'secret', offset=2, total=5))
    if accepted:
        assert consume() == b'deo'
    else:
        with pytest.raises(ValueError): consume()
    assert requests[0].get_header('Range') == 'bytes=2-'
