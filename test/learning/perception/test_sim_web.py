"""SIM requests retain the existing review app's project/CSRF boundaries."""
import inspect
import json
import threading
from contextlib import contextmanager
from pathlib import Path
import urllib.error
import urllib.request

import pytest

from review_app import make_server
from test_review_app import open_store
from test_learning_collaboration import Accounts, request


class Runs:
    source_sha = 'a' * 40
    def __init__(self):
        self.calls = []
        self.row = {'run_id': 'b' * 32, 'revision': 1, 'status': 'RUNNING',
                    'input_sha256': 'c' * 64, 'runtime': {'private_path': '/private/operator'},
                    'input': {'source_sha': self.source_sha, 'scenario_id': 'omx-f-import',
                              'config': {'seed': 0, 'frames': 120}}, 'snapshot': 'OBSERVATION_NOT_ATOMIC'}
    def call(self, payload):
        self.calls.append(payload)
        if payload['action'] == 'catalog':
            return [{'id': 'omx-f-import', 'implemented': True},
                    {'id': 'port-mixed-stacking', 'implemented': False, 'reason': 'E0 필요'}]
        if payload['action'] == 'list':
            return [self.row]
        if payload['action'] == 'check':
            return {'ready': True, 'input_sha256': 'c' * 64, 'input': self.row['input']}
        return self.row


@contextmanager
def running(tmp_path, *, authenticated=True):
    assert 'sim_runs' in inspect.signature(make_server).parameters, 'SIM injection is missing'
    runs = Runs()
    server = make_server(open_store(tmp_path), 0, accounts=Accounts() if authenticated else None, sim_runs=runs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', runs
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_sim_reads_hide_runtime_paths_and_keep_disabled_reasons(tmp_path):
    with running(tmp_path) as (base, runs):
        assert request(base, '/api/learning/sim/runs')[0] == 401
        code, data = request(base, '/api/learning/sim/catalog', 'reader')
        assert code == 200 and data['scenarios'][1]['reason'] == 'E0 필요'
        code, data = request(base, '/api/learning/sim/runs', 'reader')
        assert code == 200
        assert 'runtime' not in data['runs'][0]
        assert '/private/operator' not in json.dumps(data)


def test_sim_control_needs_manage_token_and_current_source(tmp_path):
    with running(tmp_path) as (base, runs):
        body = {'scenario_id': 'omx-f-import', 'config': {'seed': 0}}
        for session, expected in [('reader', 403), ('editor', 403), ('reviewer', 200)]:
            _, state = request(base, '/api/accounts/session', session)
            code, data = request(base, '/api/learning/sim/check', session, body, state['token'])
            assert code == expected
        assert runs.calls[-1]['source_sha'] == runs.source_sha
        before = len(runs.calls)
        for change in [{'cmd': 'anything'}, {'source_sha': 'd' * 40}, {'host': 'other'}]:
            assert request(base, '/api/learning/sim/check', 'reviewer', dict(body, **change), state['token'])[0] == 400
        assert len(runs.calls) == before
        assert request(base, '/api/learning/sim/check', 'reviewer', body, 'bad-token')[0] == 403


def test_unidentified_local_mode_cannot_start_or_stop(tmp_path):
    with running(tmp_path, authenticated=False) as (base, runs):
        _, workspace = request(base, '/api/learning')
        sim = next(row for row in workspace['domains'] if row['id'] == 'sim')
        assert sim['stages'][0]['state'] == 'active' and '최근 RUNNING' in sim['stages'][0]['evidence']
        code, _ = request(base, '/api/learning/sim/start', body={'request_id': 'b' * 32}, token=workspace['token'])
        assert code == 403 and runs.calls == [{'action': 'list'}]  # the home row reads; nothing starts
        request(base, '/api/learning')
        assert runs.calls == [{'action': 'list'}], 'the home row reads the SIM list at most once a minute'


def test_start_retry_and_stop_use_shared_run_and_revision(tmp_path):
    with running(tmp_path) as (base, runs):
        _, state = request(base, '/api/accounts/session', 'reviewer')
        body = {'request_id': 'd' * 32, 'scenario_id': 'omx-f-import', 'config': {'seed': 0},
                'expected_input_sha256': 'c' * 64}
        for _ in range(2):
            code, row = request(base, '/api/learning/sim/start', 'reviewer', body, state['token'])
            assert code == 200 and row['run_id'] == 'b' * 32
        starts = [p for p in runs.calls if p['action'] == 'start']
        assert starts[0] == starts[1]
        code, _ = request(base, '/api/learning/sim/stop', 'reviewer',
                          {'run_id': 'b' * 32, 'expected_revision': 1}, state['token'])
        assert code == 200 and runs.calls[-1]['expected_revision'] == 1


def test_sim_page_and_existing_learning_link(tmp_path):
    with running(tmp_path) as (base, runs):
        for path in ['/learning/sim', '/sim.js', '/learning']:
            req = urllib.request.Request(base + path, headers={'Cookie': 'rosy_learning_session=reader'})
            with urllib.request.urlopen(req) as response:
                text = response.read().decode()
                assert ('/learning/sim' in text if path == '/learning' else 'sim' in text.lower())


def test_local_adapter_pins_source_and_workspace_without_importing_sdk(tmp_path, monkeypatch):
    import hashlib
    import sim_web
    from types import SimpleNamespace
    source = tmp_path / 'source'
    entry = source / 'learning/envs/isaac/run_control.py'
    entry.parent.mkdir(parents=True)
    entry.write_text('pinned helper')
    binding = tmp_path / 'binding.json'
    binding.write_text(json.dumps({'source_root': str(source), 'source_sha': 'a' * 40}))
    config = tmp_path / 'web.json'
    config.write_text(json.dumps({'workspace_id': 'workspace', 'source_root': str(source),
        'source_sha': 'a' * 40, 'binding_file': str(binding),
        'binding_sha256': hashlib.sha256(binding.read_bytes()).hexdigest(),
        'entry_sha256': hashlib.sha256(entry.read_bytes()).hexdigest()}))
    config.chmod(0o600)
    calls = []
    monkeypatch.setenv('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/test/bus')
    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] != 'git':
            assert kwargs['env']['DBUS_SESSION_BUS_ADDRESS'] == 'unix:path=/run/user/test/bus'
        return SimpleNamespace(stdout=('a' * 40 if 'rev-parse' in argv else '') if argv[0] == 'git' else b'{"ready":true}')
    monkeypatch.setattr(sim_web.subprocess, 'run', run)
    with pytest.raises(ValueError):
        sim_web.LocalRuns(config, 'other-workspace')
    adapter = sim_web.LocalRuns(config, 'workspace')
    assert adapter.call({'action': 'check'})['ready'] is True
    assert calls[-1][0:2] == ['/usr/bin/python3', str(entry)]
    assert '--expected-binding-sha256' in calls[-1]
    before = len(calls)
    binding.write_text(json.dumps({'source_root': str(source), 'source_sha': 'a' * 40,
                                  'data_root': str(tmp_path / 'another-store')}))
    with pytest.raises(ValueError, match='SIM'):
        adapter.call({'action': 'list'})
    assert len(calls) == before
    binding.write_text(json.dumps({'source_root': str(source), 'source_sha': 'a' * 40}))
    before = len(calls)
    entry.write_text('changed helper')
    with pytest.raises(ValueError, match='SIM'):
        adapter.call({'action': 'start'})
    assert len(calls) == before
