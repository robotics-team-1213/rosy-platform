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
    photos = Path('/nonexistent/cell-photos')
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


@pytest.mark.parametrize('artifact_id,media_type,raw', [
    ('import-report', 'application/json', b'{"import_verified":true}'),
    ('contact-report', 'application/json', b'{"task_success":true}'),
    *[(name, 'image/png', b'\x89PNG\r\n\x1a\n') for name in (
        'pinky_initial', 'out_lift', 'conveyor_settle', 'back_lift', 'pinky_settle')],
    ('mapped-stack-report', 'application/json', b'{"task_success":false}'),
    ('mapped-video', 'video/mp4', b'\x00\x00\x00\x18ftypmp42'),
    *[(name, 'image/png', b'\x89PNG\r\n\x1a\n') for name in (
        'mapped-overview', 'mapped-initial', 'mapped-layer-9', 'mapped-trial-1', 'mapped-leveling-12')],
])
def test_contact_evidence_is_readable_through_learning_routes(tmp_path, artifact_id, media_type, raw):
    import base64
    import hashlib
    with running(tmp_path) as (base, runs):
        original = runs.call
        def call(payload):
            if payload['action'] == 'artifact':
                assert payload == {'action': 'artifact', 'run_id': 'b' * 32, 'artifact_id': artifact_id}
                return {'media_type': media_type, 'bytes': len(raw),
                        'sha256': hashlib.sha256(raw).hexdigest(), 'data_base64': base64.b64encode(raw).decode()}
            return original(payload)
        runs.call = call
        url = base + '/api/learning/sim/runs/' + 'b' * 32 + '/artifacts/' + artifact_id
        req = urllib.request.Request(url, headers={'Cookie': 'rosy_learning_session=reader'})
        with urllib.request.urlopen(req) as response:
            assert response.headers.get_content_type() == media_type
            assert response.read() == raw


@pytest.mark.parametrize('corruption', ['hash', 'type', 'size'])
def test_contact_evidence_rejects_changed_or_mistyped_bytes(tmp_path, corruption):
    import base64
    import hashlib
    with running(tmp_path) as (base, runs):
        raw = b'\x89PNG\r\n\x1a\n'
        blob = {'media_type': 'image/png', 'bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(), 'data_base64': base64.b64encode(raw).decode()}
        blob.update({'hash': {'sha256': '0' * 64}, 'type': {'media_type': 'text/html'},
                     'size': {'bytes': 1048577}}[corruption])
        runs.call = lambda payload: blob
        url = base + '/api/learning/sim/runs/' + 'b' * 32 + '/artifacts/pinky_initial'
        req = urllib.request.Request(url, headers={'Cookie': 'rosy_learning_session=reader'})
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req)
        assert caught.value.code == 400


def blob(raw, media_type, size=None):
    import base64
    import hashlib
    return {'media_type': media_type, 'bytes': len(raw) if size is None else size,
            'sha256': hashlib.sha256(raw).hexdigest(), 'data_base64': base64.b64encode(raw).decode()}


def test_video_and_report_bounds_follow_the_container_run_limits(tmp_path):
    with running(tmp_path) as (base, runs):
        def get(artifact_id):
            req = urllib.request.Request(base + '/api/learning/sim/runs/' + 'b' * 32 + '/artifacts/' + artifact_id,
                                         headers={'Cookie': 'rosy_learning_session=reader'})
            try:
                with urllib.request.urlopen(req) as response:
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code
        runs.call = lambda payload: blob(b'video', 'video/mp4', 64 * 1024 * 1024 + 1)
        assert get('mapped-video') == 400
        runs.call = lambda payload: blob(b'\x89PNG', 'image/png', 1048577)
        assert get('mapped-layer-1') == 400
        # Frame logs and encoder logs are run evidence, not something the page shows.
        assert get('mapped-video-frames') == 404 and get('mapped-layer-123') == 404


def test_container_summary_comes_from_the_registered_report(tmp_path):
    import sys
    import sim_web
    sys.path.append(str(sim_web.ISAAC))
    from mapped_stack_fixture import container_fixture
    report = {'fixture': container_fixture(layers=3, case='nominal'), 'trials': [{'layers': []}], 'task_success': False}
    with running(tmp_path) as (base, runs):
        asked = []
        def call(payload):
            asked.append(payload)
            return blob(json.dumps(report).encode(), 'application/json')
        runs.call = call
        code, data = request(base, '/api/learning/sim/runs/' + 'b' * 32 + '/summary', 'reader')
        assert code == 200 and data['placed'] == 0 and data['planned'] == 9 and data['unstable'] == []
        assert asked == [{'action': 'artifact', 'run_id': 'b' * 32, 'artifact_id': 'mapped-stack-report'}]
        runs.call = lambda payload: blob(b'{"trials":[]}', 'application/json')
        code, data = request(base, '/api/learning/sim/runs/' + 'b' * 32 + '/summary', 'reader')
        assert code == 502 and data['error'] == '적층 보고서 형식을 확인하세요.'


def test_cell_inventory_is_complete_and_its_photos_stay_outside_the_repository(tmp_path):
    import re
    import sim_web
    with running(tmp_path) as (base, runs):
        code, data = request(base, '/api/learning/sim/inventory', 'reader')
        assert code == 200 and data['schema'] == 'rosy.cell-model-inventory/1'
        ids = {model['id'] for model in data['models']}
        assert {'gripper', 'ship_plate', 'workbench', 'belt', 'container', 'arm_base'} <= ids
        assert sum(model['id'].startswith('camera_') for model in data['models']) == 4
        for model in data['models']:
            assert model['sim'] in {'reflected', 'stand_in', 'none'} and model['name']
            assert model['cad']['sha256'] is None or re.fullmatch('[0-9a-f]{64}', model['cad']['sha256'])
        for photo in data['photos']:
            assert re.fullmatch('[a-z0-9_]{1,32}', photo['id']) and re.fullmatch(r'[a-z0-9_-]+\.(jpg|png)', photo['file'])
            assert photo['sim_view'] is None or any(re.fullmatch(p, photo['sim_view']) for p in sim_web.ARTIFACT_TYPES)
        assert all(task['status'] in {'open', 'done'} and task['task'] and task['why'] for task in data['person_tasks'])
        assert not list(sim_web.INVENTORY.parent.glob('cell-photos'))

        runs.photos = tmp_path / 'cell-photos'
        assert request(base, '/api/learning/sim/photos/ceiling', 'reader')[0] == 404
        runs.photos.mkdir()
        (runs.photos / 'ceiling.jpg').write_bytes(b'\xff\xd8\xff')
        req = urllib.request.Request(base + '/api/learning/sim/photos/ceiling', headers={'Cookie': 'rosy_learning_session=reader'})
        with urllib.request.urlopen(req) as response:
            assert response.headers.get_content_type() == 'image/jpeg' and response.read() == b'\xff\xd8\xff'
        assert request(base, '/api/learning/sim/photos/unknown', 'reader')[0] == 404


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
        assert sim['next']['href'] == '/learning/sim?run=' + 'b' * 32
        assert '/private/operator' not in json.dumps(workspace)  # the home row reads public() rows only
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


def test_a_malformed_sim_row_does_not_break_the_home_page(tmp_path):
    with running(tmp_path, authenticated=False) as (base, runs):
        runs.row = dict(runs.row, result=None)  # public() raises TypeError on this row
        code, workspace = request(base, '/api/learning')
        sim = next(row for row in workspace['domains'] if row['id'] == 'sim')
        assert code == 200 and sim['blocked'] == 'SIM 실행 연결을 확인하세요.'


def test_a_malformed_sim_row_is_skipped_in_the_list_and_502_on_its_own(tmp_path):
    with running(tmp_path) as (base, runs):
        good = runs.row
        runs.call = lambda payload: [good, dict(good, result=None)] if payload['action'] == 'list' else dict(good, result=None)
        code, data = request(base, '/api/learning/sim/runs', 'reader')
        assert code == 200 and data['skipped'] == 1 and [row['run_id'] for row in data['runs']] == [good['run_id']]
        code, data = request(base, '/api/learning/sim/runs/' + 'b' * 32, 'reader')
        assert code == 502 and data['error'].startswith('SIM 실행 기록 형식을 확인하세요.')
