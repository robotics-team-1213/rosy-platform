"""A field publisher reuses one sealed source and identities across lost acknowledgements."""
import json
import sys
import uuid
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_experiment_center import center
from test_experiment_dataset import dataset
from experiment_transfer import transfer, Http


@pytest.mark.parametrize('lost', ['upload', 'publish', 'experience'])
def test_retry_after_ack_loss_preserves_one_dataset_and_experience(tmp_path, monkeypatch, lost):
    c = center(tmp_path, monkeypatch)
    root = tmp_path/'sealed'
    root.mkdir()
    dataset(root)
    originals = {p.name: p.read_bytes() for p in root.iterdir()}
    checkpoint = tmp_path/'transfer.json'
    run_id = str(uuid.uuid4())
    inputs, receipts, dropped = {}, [], False
    def post(path, body):
        nonlocal dropped
        operation = path.rsplit('/', 1)[1]
        if operation == 'experience':
            inputs.setdefault(body['request_id'], dict(id=body['request_id'],
                dataset_id=body['dataset_id'], sequence=1, status='queued'))
            reply = inputs[body['request_id']]
        else:
            reply = getattr(c, operation)(body)
        receipts.append((operation, body.copy()))
        if operation == lost and not dropped:
            dropped = True
            raise TimeoutError('acknowledgement lost')
        return reply
    options = dict(origin='http://127.0.0.1:8769', name='Sealed field batch', run_id=run_id, post=post)
    with pytest.raises(TimeoutError):
        transfer(root, checkpoint, **options)
    saved = checkpoint.read_bytes()
    result = transfer(root, checkpoint, **options)
    assert checkpoint.read_bytes() == saved
    assert len(c.snapshot()['datasets']) == 1 and len(inputs) == 1
    assert result['dataset']['id'] == result['experience']['dataset_id']
    assert {p.name: p.read_bytes() for p in root.iterdir()} == originals
    assert not list((c.root/'uploads').iterdir())
    for change in ({'origin': 'http://127.0.0.1:8770'}, {'run_id': str(uuid.uuid4())}, {'name': 'Other'}):
        count = len(receipts)
        with pytest.raises(ValueError, match='checkpoint'):
            transfer(root, checkpoint, **dict(options, **change))
        assert len(receipts) == count
    (root/'train.npz').write_bytes(b'changed')
    with pytest.raises(ValueError, match='checkpoint'):
        transfer(root, checkpoint, **options)


@pytest.mark.parametrize('url', ['http://example.com:8769', 'https://127.0.0.1:8769',
    'http://user:secret@127.0.0.1:8769', 'http://127.0.0.1:8769/path',
    'http://127.0.0.1:8769?key=secret'])
def test_transport_requires_an_explicit_loopback_tunnel_without_url_credentials(url):
    with pytest.raises(ValueError, match='loopback'):
        Http(url)


def test_real_http_transport_binds_cookie_origin_csrf_and_refuses_redirect(tmp_path, monkeypatch):
    from urllib.error import HTTPError
    c = center(tmp_path, monkeypatch)
    root = tmp_path/'source'
    root.mkdir()
    dataset(root)
    seen, redirect = [], False
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, value, status=200):
            raw = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if redirect:
                self.send_response(302)
                self.send_header('Location', '/unexpected-redirect')
                self.end_headers()
                return
            assert self.path == '/api/learning'
            assert self.headers['Cookie'] == 'session=private-test'
            self.reply({'token': 'csrf-test'})

        def do_POST(self):
            assert self.headers['Cookie'] == 'session=private-test'
            assert self.headers['X-Pinky-Token'] == 'csrf-test'
            assert self.headers['Origin'] == origin
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            operation = self.path.rsplit('/', 1)[1]
            seen.append(operation)
            self.reply(getattr(c, operation)(body))
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    origin = f'http://127.0.0.1:{server.server_port}'
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('ROSY_LEARNING_SESSION_COOKIE', 'session=private-test')
    try:
        result = transfer(root, tmp_path/'http-checkpoint.json', origin=origin, name='HTTP fixture')
        assert result['dataset']['id'] == c.snapshot()['datasets'][0]['id']
        assert seen.count('publish') == 1 and seen.count('upload') >= 4
        assert 'private-test' not in (tmp_path/'http-checkpoint.json').read_text()
        redirect = True
        with pytest.raises(HTTPError) as error:
            Http(origin).post('/api/learning/omx/center/publish', {})
        assert error.value.code == 302
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_bad_upload_ack_never_publishes_or_queues_experience(tmp_path):
    root = tmp_path/'source'
    root.mkdir()
    dataset(root)
    calls = []
    def post(path, body):
        calls.append(path)
        return dict(upload_id=body['upload_id'], name=body['name'], offset=-1)
    with pytest.raises(ValueError, match='acknowledgement'):
        transfer(root, tmp_path/'checkpoint.json', origin='http://127.0.0.1:8769',
                 name='Invalid ACK', run_id=str(uuid.uuid4()), post=post)
    assert calls == ['/api/learning/omx/center/upload']


def test_checkpoint_directory_is_synced_before_network_side_effects(tmp_path, monkeypatch):
    import experiment_transfer as module
    import os
    import stat
    root = tmp_path/'source'
    root.mkdir()
    dataset(root)
    synced = []
    fsync = os.fsync
    def record(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            synced.append(True)
        fsync(fd)
    monkeypatch.setattr(module.os, 'fsync', record)
    def post(path, body):
        assert synced, 'checkpoint directory was not synced before transmission'
        raise TimeoutError('stop after durability assertion')
    with pytest.raises(TimeoutError):
        transfer(root, tmp_path/'checkpoint.json', origin='http://127.0.0.1:8769',
                 name='Durable checkpoint', post=post)
