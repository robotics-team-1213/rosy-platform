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


def test_range_ignored_restarts_and_hash_mismatch_never_publishes(tmp_path):
    from learning_imports import RangeRestart
    service, transport, _ = make(tmp_path)
    offsets = resumable(service, transport)
    job = create(service)
    transport.fail = True
    service.run(job['id'], 'alice')
    transport.fail = False
    original = transport.chunks
    rejected = []
    def ignores(*args, **kwargs):
        if kwargs.get('offset'):
            rejected.append(kwargs['offset'])
            raise RangeRestart('full response')
        yield from original(*args, **kwargs)
    transport.chunks = ignores
    service.retry('alice', 'alpha', job['id'])
    service.run(job['id'], 'alice')
    assert rejected == [1] and offsets[1] == ('clip.mp4', 0)
    assert service.get('alice', 'alpha', job['id'])['status'] == 'completed'
    bad = create(service, files=['clip.mp4'], rights={'internal_use': True, 'evidence': 'second review'})
    transport.data['clip.mp4'] = b'WRONG'
    service.run(bad['id'], 'alice')
    assert service.get('alice', 'alpha', bad['id'])['error'] == 'verification_failed'
    assert not (service.root / 'artifacts' / bad['id']).exists()
    transport.data['clip.mp4'] = b'video'
    service.retry('alice', 'alpha', bad['id']); service.run(bad['id'], 'alice')
    assert service.get('alice', 'alpha', bad['id'])['status'] == 'completed'


def test_cancel_then_retry_cannot_be_overwritten_by_old_worker(tmp_path):
    service, transport, _ = make(tmp_path)
    job = create(service)
    other = LearningImports(service.root, service.authorize, service.credential, transport=transport)
    original = transport.chunks
    def cancelled(*args):
        yield b'v'
        other.cancel('alice', 'alpha', job['id'])
        other.retry('alice', 'alpha', job['id'])
        yield b'ideo'
    transport.chunks = cancelled
    service.run(job['id'], 'alice')
    assert service.get('alice', 'alpha', job['id'])['status'] == 'queued'
    transport.chunks = original
    other.run(job['id'], 'alice')
    assert other.get('alice', 'alpha', job['id'])['status'] == 'completed'


def test_cross_service_create_is_idempotent(tmp_path):
    service, transport, _ = make(tmp_path)
    other = LearningImports(service.root, service.authorize, service.credential, transport=transport)
    barrier = threading.Barrier(2)
    original = transport.resolve
    def together(*args):
        doc = original(*args); barrier.wait(10); return doc
    transport.resolve = together
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as pool:
        first, second = [future.result() for future in [pool.submit(create, service), pool.submit(create, other)]]
    assert first['id'] == second['id']
    assert len(service.list('alice', 'alpha')) == 1


def test_resume_capacity_uses_remaining_bytes_across_all_files(tmp_path, monkeypatch):
    service, transport, _ = make(tmp_path)
    resumable(service, transport)
    job = create(service)
    original = transport.chunks
    def fails_second(*args, **kwargs):
        transport.fail = args[3] == 'meta.json'
        yield from original(*args, **kwargs)
    transport.chunks = fails_second
    service.run(job['id'], 'alice')
    # clip is complete, metadata has one byte; only one data byte remains.
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=1024 ** 3 + 1024 ** 2 + 1))
    transport.fail = False; transport.chunks = original
    service.retry('alice', 'alpha', job['id']); service.run(job['id'], 'alice')
    assert service.get('alice', 'alpha', job['id'])['status'] == 'completed'


def test_process_crash_keeps_verified_checkpoint_and_existing_server_recovers(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    service, transport, _ = make(tmp_path)
    transport.data = {'weights.bin': b'x' * (10 * 1024 ** 2)}
    offsets = resumable(service, transport)
    job = create(service, repo_type='model', files=['weights.bin'])
    script = '''
import os, sys
from pathlib import Path
from test_learning_imports import make
import learning_imports
service, transport, _ = make(Path(sys.argv[1]))
learning_imports.time.monotonic = lambda: 0
def killed(*args, **kwargs):
    yield b'x' * (8 * 1024 ** 2)
    yield b'x' * (1024 ** 2)
    os._exit(23)
transport.chunks = killed
service.run(sys.argv[2], 'alice')
'''
    # Exercise accumulated full-suite import roots without collecting every module.
    module_dir = os.path.dirname(os.path.abspath(__file__))
    monkeypatch.setattr(sys, 'path', sys.path + [module_dir] * (2 * 1024 ** 2 // len(module_dir) + 1))
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), job['id']],
        env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)}, timeout=30)
    assert result.returncode == 23
    part = service.root / '.partial' / job['id'] / 'files/weights.bin'
    assert part.stat().st_size == 9 * 1024 ** 2
    interrupted = service.list('alice', 'alpha')[0]
    assert interrupted['status'] == 'interrupted'
    assert interrupted['files'][0]['downloaded_bytes'] == 8 * 1024 ** 2
    service.retry('alice', 'alpha', job['id']); service.run(job['id'], 'alice')
    assert offsets == [('weights.bin', 8 * 1024 ** 2)]
    assert service.get('alice', 'alpha', job['id'])['status'] == 'completed'


def test_large_import_over_8gib_has_bounded_memory_and_resumes(tmp_path, request):
    import os
    import time
    if os.environ.get('ROSY_RUN_LARGE_IMPORT_TESTS') != '1':
        pytest.skip('opt-in remote large import experiment')
    import resource
    if shutil.disk_usage(tmp_path).free < 12 * 1024 ** 3:
        pytest.skip('large import requires 12 GiB free on test host')
    service, transport, _ = make(tmp_path)
    total, block = 9 * 1024 ** 3, b'x' * 1024 ** 2
    digest = hashlib.sha256()
    for _ in range(total // len(block)): digest.update(block)
    expected, offsets = digest.hexdigest(), []
    def resolve(*args):
        return dict(sha=SHA, siblings=[dict(rfilename='weights.bin', size=total, lfs={'sha256': expected})])
    def chunks(*args, offset=0, total=None):
        offsets.append(offset)
        for position in range(offset, 9 * 1024 ** 3, len(block)):
            yield block
            if len(offsets) == 1 and position >= 3 * len(block): raise OSError('interrupted')
    transport.resolve, transport.chunks = resolve, chunks
    limits = dict(max_file_bytes=total, max_total_bytes=total)
    service = LearningImports(service.root, service.authorize, service.credential, transport=transport, limits=limits)
    before, started = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, time.monotonic()
    job = create(service, repo_type='model', files=['weights.bin'])
    def remove_test_payload():
        for location in ('.partial', 'artifacts'):
            (service.root / location / job['id'] / 'files/weights.bin').unlink(missing_ok=True)
    request.addfinalizer(remove_test_payload)
    service.run(job['id'], 'alice')
    restarted = LearningImports(service.root, service.authorize, service.credential, transport=transport, limits=limits)
    restarted.retry('alice', 'alpha', job['id']); restarted.run(job['id'], 'alice')
    done = restarted.get('alice', 'alpha', job['id'])
    assert done['status'] == 'completed' and offsets == [0, 4 * len(block)]
    assert done['files'][0]['sha256'] == expected
    path = service.root / 'artifacts' / job['id'] / 'files/weights.bin'
    with path.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == expected
    peak_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
    assert peak_kib < 128 * 1024
    allocated = sum(p.stat().st_blocks * 512 for p in service.root.rglob('*') if p.is_file())
    assert allocated < total + 16 * 1024 ** 2
    print(json.dumps(dict(bytes=total, resume_offset=offsets[1], extra_peak_kib=peak_kib,
                         allocated_bytes=allocated, elapsed_s=round(time.monotonic() - started, 2))))
