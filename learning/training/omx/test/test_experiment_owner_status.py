"""The Learning observer can read one configured Fleet owner and cannot send commands."""
import json
from pathlib import Path
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def fleet(monkeypatch):
    state = dict(calls=[], code=200, body={'version': 1, 'status': 200,
        'workcell_id': 'cell', 'instance_id': 'arm',
        'owner': {'state': 'hold', 'reason': 'operator_pause', 'observed_sequence': 12}})
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state['calls'].append((self.command, self.path, self.headers.get('Authorization')))
            self.send_response(state['code'])
            if state['code'] == 302:
                self.send_header('Location', '/must-not-follow')
            self.end_headers()
            raw = json.dumps(state['body']).encode()
            try:
                if state.get('trickle'):
                    for byte in raw:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(.03)
                else:
                    self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('ROSY_TEST_FLEET_VIEWER', 'fixture-secret')
    state['config'] = dict(origin=f'http://127.0.0.1:{server.server_port}',
        token_env='ROSY_TEST_FLEET_VIEWER', targets={'cell': 'arm'}, timeout_s=1.)
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_fixed_get_binding_and_receipt_never_imply_physical_readiness(fleet, monkeypatch):
    from experiment_owner_status import OwnerStatus
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:1')
    reader = OwnerStatus(fleet['config'])
    assert reader.describe()['targets'] == [{'workcell_id': 'cell', 'instance_id': 'arm'}]
    value = reader.read('cell')
    assert value['status'] == 'observed' and value['owner'] == fleet['body']['owner']
    assert value['physical_control_available'] is False and value['feedback_freshness_verified'] is False
    assert value['source'] == 'fleet_owner_state' and len(value['response_sha256']) == 64
    assert value['received_at'] and value['query_id'] and value['elapsed_ms'] >= 0
    assert fleet['calls'] == [('GET', '/api/fleet/workcells/cell/owner', 'Bearer fixture-secret')]
    assert 'fixture-secret' not in json.dumps(value) and '127.0.0.1' not in json.dumps(reader.describe())
    value['owner']['state'] = 'ready'
    assert reader.read('cell')['owner']['state'] == 'hold'
    with pytest.raises(ValueError): reader.read('../arbitrary')
    assert len(fleet['calls']) == 2


@pytest.mark.parametrize('fault', ['identity', 'boolean_sequence', 'invalid_state', 'missing_reason',
                                  'oversize', 'redirect', 'auth', 'token', 'json_number'])
def test_bad_or_unavailable_source_has_no_retained_owner_state(fleet, monkeypatch, fault):
    from experiment_owner_status import OwnerStatus
    reader = OwnerStatus(fleet['config'])
    assert reader.read('cell')['status'] == 'observed'
    if fault == 'identity': fleet['body']['instance_id'] = 'other'
    elif fault == 'boolean_sequence': fleet['body']['owner']['observed_sequence'] = True
    elif fault == 'invalid_state': fleet['body']['owner']['state'] = 'running'
    elif fault == 'missing_reason': del fleet['body']['owner']['reason']
    elif fault == 'oversize': fleet['body']['padding'] = 'x'*65537
    elif fault == 'redirect': fleet['code'] = 302
    elif fault == 'auth': fleet['code'] = 403
    elif fault == 'token': monkeypatch.delenv('ROSY_TEST_FLEET_VIEWER')
    elif fault == 'json_number': fleet['body'] = 1
    value = reader.read('cell')
    assert value['status'] == 'unavailable' and value['physical_control_available'] is False
    assert 'owner' not in value and 'response_sha256' not in value
    assert 'fixture-secret' not in json.dumps(value)
    if fault == 'redirect': assert len(fleet['calls']) == 2


@pytest.mark.parametrize('patch', [{'origin': 'http://example.com:80'},
    {'origin': None}, {'origin': []},
    {'origin': 'http://user:pass@127.0.0.1:80'}, {'origin': 'http://127.0.0.1:80/path'},
    {'targets': {'../escape': 'arm'}}, {'targets': {'cell': ''}}, {'timeout_s': True},
    {'timeout_s': 0}, {'timeout_s': 30}, {'token_env': 'invalid\r\n'}])
def test_configuration_is_server_owned_and_bounded(fleet, patch):
    from experiment_owner_status import OwnerStatus
    with pytest.raises(ValueError): OwnerStatus({**fleet['config'], **patch})


def test_unconfigured_reader_and_center_are_compatible(tmp_path, monkeypatch):
    from experiment_owner_status import OwnerStatus
    from test_experiment_center import center
    reader = OwnerStatus(None)
    assert reader.describe() == {'configured': False, 'targets': [], 'physical_control_available': False}
    c = center(tmp_path, monkeypatch)
    assert c.snapshot()['owner_status'] == reader.describe()
    with pytest.raises(ValueError): c.read_owner_status('cell')


def test_trickling_reply_cannot_retain_request_thread_beyond_total_deadline(fleet):
    from experiment_owner_status import OwnerStatus
    reader = OwnerStatus({**fleet['config'], 'timeout_s': .15})
    fleet['trickle'] = True
    started = time.monotonic()
    value = reader.read('cell')
    assert time.monotonic()-started < .8
    assert value['status'] == 'unavailable' and 'owner' not in value
