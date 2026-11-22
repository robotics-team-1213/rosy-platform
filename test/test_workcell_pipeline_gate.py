"""Workcell pipeline gate unit checks with a fake opener — no network, no real fleet."""
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import ssl

import pytest

_FILE = Path(__file__).resolve().parents[1] / 'tools/remote/workcell_pipeline_gate.py'
_SPEC = spec_from_file_location('workcell_pipeline_gate', _FILE)
gate = module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)

CELL = 'https://cell.example'
NO_SLEEP = lambda _seconds: None  # noqa: E731


class FakeResponse:
    def __init__(self, status, body=b'', headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class FakeOpener:
    """Records every request (method, url, data) and answers from handler(method, url, data)."""

    def __init__(self, handler):
        self.handler, self.requests = handler, []

    def open(self, request, timeout=None):
        method, url = request.get_method(), request.full_url
        self.requests.append((method, url, request.data))
        response = self.handler(method, url, request.data)
        assert response is not None, f'unexpected {method} {url}'
        return response


def arm(sid, *, fresh=True, epoch='0' * 32, sequence=1, captured_at=1000.0, age=0.5, positions=None):
    return {'source_id': sid, 'epoch': epoch, 'sequence': sequence, 'captured_at': captured_at,
            'fresh': fresh, 'source_age_s': age if fresh else None, 'positions': positions,
            'motor_health': {'session_id': 'live-session'}}


def gate_handler(base, arms_for_round, cameras=(), leases=None, tasks=None):
    """A fleet: advancing observation rounds, a lease per camera, frames and R cell tasks."""
    leases = leases or {}
    rounds = {'n': 0}

    def handler(method, url, data=None):
        path = url[len(base):]
        if (method, path) == ('GET', gate.OBSERVATIONS_PATH):
            rounds['n'] += 1
            body = {'workcells': [{'arms': arms_for_round(rounds['n']),
                                   'cameras': [{'source_id': s} for s in cameras]}]}
            return FakeResponse(200, json.dumps(body).encode())
        if (method, path) == ('POST', gate.LEASE_PATH):
            source = json.loads(data)['source_id']
            issued = leases.get(source, {'lease': 'tok',
                                         'frame_path': f'/api/vision/sources/{source}/frame'})
            return FakeResponse(200, json.dumps(issued).encode())
        if method == 'GET' and path.startswith('/api/vision/sources/'):
            return FakeResponse(200, b'x' * 2000, {'X-Frame-Age-Ms': '120', 'X-Frame-State': 'ok'})
        if (method, path) == ('GET', gate.CELL_TASKS_PATH):
            body = tasks if tasks is not None else {'tasks': [], 'arm_live_states': {}}
            return FakeResponse(200, json.dumps(body).encode())
        return None

    return handler


def client(name, handler, base=CELL):
    fleet = gate.FleetClient(name, base, None, 5, None)
    fleet._opener = FakeOpener(handler)
    return fleet


def one(rows, check):
    return next(row for row in rows if row['check'] == check)


def test_fake_marker_fails():
    fake = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
    handler = gate_handler(CELL, lambda _round: [arm('arm_s', epoch=fake)])
    rows = gate.run({'cell': client('cell', handler)}, sleep=NO_SLEEP)
    assert one(rows, 'cell.arm_s.not_fake')['result'] == 'FAIL'
    assert gate.verdict(rows)[0] == 'FAIL'
    session = [arm('arm_s', epoch='1' * 32)]
    session[0]['motor_health']['session_id'] = 'e957f879-5ec9-48c1-ad98-d642fa8a5a7e'
    rows = gate.run({'cell': client('cell', gate_handler(CELL, lambda _r: session))}, sleep=NO_SLEEP)
    assert one(rows, 'cell.arm_s.not_fake')['result'] == 'FAIL'


def test_fresh_stall_fails():
    # both rounds identical: fresh=true but nothing advances
    handler = gate_handler(CELL, lambda _round: [arm('arm_s', sequence=7, captured_at=1000.0, age=0.4)])
    rows = gate.run({'cell': client('cell', handler)}, sleep=NO_SLEEP)
    assert one(rows, 'cell.arm_s.fresh_and_advancing')['result'] == 'FAIL'
    # advancing but the source age is out of the 0..2 s window
    stalled = gate_handler(CELL, lambda _round: [arm('arm_s', age=9.0)])
    rows = gate.run({'cell': client('cell', stalled)}, sleep=NO_SLEEP)
    assert one(rows, 'cell.arm_s.fresh_and_advancing')['result'] == 'FAIL'


def test_honest_unknown_passes_with_missing_line():
    handler = gate_handler(CELL, lambda _round: [arm('arm_s', fresh=False)])
    rows = gate.run({'cell': client('cell', handler)}, sleep=NO_SLEEP)
    assert one(rows, 'cell.arm_s.honest_unknown')['result'] == 'PASS'
    assert one(rows, 'cell.arm_s.live')['result'] == 'MISSING'
    assert gate.verdict(rows)[0] == 'PASS' and gate.verdict(rows)[2] == 0
    # a not-fresh arm that still carries positions is not honest
    liar = gate_handler(CELL, lambda _r: [arm('arm_s', fresh=False, positions={'j1': 1.0})])
    rows = gate.run({'cell': client('cell', liar)}, sleep=NO_SLEEP)
    assert one(rows, 'cell.arm_s.honest_unknown')['result'] == 'FAIL'


def test_mirror_delay_fails():
    cell = gate_handler(CELL, lambda _round: [arm('arm_s', captured_at=1000.0)])
    lagging = gate_handler(CELL, lambda r: [arm('arm_s', captured_at=995.0, sequence=r)])
    rows = gate.run({'cell': client('cell', cell), 'R': client('R', lagging)}, sleep=NO_SLEEP)
    row = one(rows, 'mirror.arm_s')
    assert row['result'] == 'FAIL' and row['lag_s'] == 5.0
    gone = gate_handler(CELL, lambda _r: [arm('arm_s', fresh=False)])
    rows = gate.run({'cell': client('cell', cell), 'R': client('R', gone)}, sleep=NO_SLEEP)
    assert one(rows, 'mirror.arm_s')['result'] == 'FAIL'
    ahead = gate_handler(CELL, lambda _r: [arm('arm_s', captured_at=1002.0)])
    rows = gate.run({'cell': client('cell', cell), 'R': client('R', ahead)}, sleep=NO_SLEEP)
    assert one(rows, 'mirror.arm_s')['result'] == 'PASS'


def test_camera_frame_path_origin_forgery_rejected():
    leases = {'ceiling-1': {'lease': 'tok', 'frame_path': 'https://evil.example/frame'}}
    handler = gate_handler(CELL, lambda _r: [arm('arm_s')], cameras=['ceiling-1'], leases=leases)
    fleet = client('cell', handler)
    rows = gate.run({'cell': fleet}, sleep=NO_SLEEP)
    row = one(rows, 'cell.camera.ceiling-1')
    assert row['result'] == 'FAIL' and row['stage'] == 'frame_path'
    assert not any('evil.example' in url for _method, url, _data in fleet._opener.requests)


def test_no_write_requests_and_json_document(tmp_path):
    arms = lambda round_: [arm('arm_s', age=0.0, sequence=round_, captured_at=1000.0 + round_ * 0.5)]  # noqa: E731  an age of exactly 0 s is fresh
    tasks = {'tasks': [{'task_id': 't1', 'status': 'RUNNING'}],
             'arm_live_states': {'arm_s': {'source': 'boot_default'}}}
    handler = gate_handler(CELL, arms, cameras=['ceiling-1'], tasks=tasks)
    targets = {'cell': client('cell', handler), 'R': client('R', handler)}
    rows = gate.run(targets, sleep=NO_SLEEP)
    for method, url, _data in targets['cell']._opener.requests:
        assert method in ('GET', 'POST')
        assert 'claim' not in url and 'complete' not in url and 'cancel' not in url
        if method == 'POST':
            assert url.endswith('/api/fleet/vision/lease')
    assert one(rows, 'cell.arm_s.fresh_and_advancing')['result'] == 'PASS'
    assert one(rows, 'R.arm_live.arm_s')['result'] == 'MISSING'
    assert one(rows, 'R.cell_tasks_api')['result'] == 'PASS'
    assert gate.verdict(rows)[0] == 'PASS'
    doc = gate.document(rows, targets, '2026-11-20T00:00:00+00:00')
    assert doc['schema'] == 'rosy.workcell-pipeline-gate.v1' and doc['verdict'] == 'PASS'
    assert doc['targets'] == {'cell': CELL, 'R': CELL} and len(doc['checks']) == len(rows)


def test_tls_verification_cannot_be_skipped(monkeypatch):
    seen = {}

    def fake_context(*, cafile):
        seen['cafile'] = cafile
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return context

    monkeypatch.setattr(gate.ssl, 'create_default_context', fake_context)
    context = gate.tls_context('anchor.pem')
    assert seen['cafile'] == 'anchor.pem'
    assert context.verify_mode == ssl.CERT_REQUIRED and not context.check_hostname
    for empty in ('', None):
        with pytest.raises(gate.GateError):
            gate.tls_context(empty)


def test_missing_ca_file_or_insecure_is_a_usage_error(tmp_path, capsys):
    cookie = tmp_path / 'cookie.txt'
    cookie.write_text('session=abc\n', encoding='utf-8')
    for argv in (['--cell-url', CELL, '--cookie-file', str(cookie)],
                 ['--cell-url', CELL, '--cookie-file', str(cookie), '--insecure'],
                 ['--cell-url', CELL, '--cookie-file', str(cookie), '--ca-file']):
        with pytest.raises(SystemExit) as stop:
            gate.main(argv)
        assert stop.value.code == 2
    assert capsys.readouterr().out == ''


def test_main_exit_code_and_json_out(tmp_path, capsys, monkeypatch):
    cookie = tmp_path / 'cookie.txt'
    cookie.write_text('session=abc\n', encoding='utf-8')
    fake = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
    handler = gate_handler(CELL, lambda _r: [arm('arm_s', epoch=fake)], tasks={
        'tasks': [], 'arm_live_states': {'arm_s': {'source': 'boot_default'}}})

    def factory(name, url):
        return client(name, handler, url)

    anchors = []

    def fake_context(*, cafile):
        anchors.append(str(cafile))
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    monkeypatch.setattr(gate.ssl, 'create_default_context', fake_context)
    ca = tmp_path / 'ca.pem'
    ca.write_text('-----BEGIN CERTIFICATE-----\n', encoding='utf-8')
    out = tmp_path / 'gate.json'
    code = gate.main(['--cell-url', CELL, '--r-url', CELL, '--cookie-file', str(cookie),
                      '--ca-file', str(ca), '--json-out', str(out)], client_factory=factory)
    assert anchors == [str(ca)]
    assert code == 1
    doc = json.loads(out.read_text(encoding='utf-8'))
    assert doc['schema'] == 'rosy.workcell-pipeline-gate.v1' and doc['verdict'] == 'FAIL'
    assert doc['targets'] == {'cell': CELL, 'R': CELL}
    lines = capsys.readouterr().out.strip().splitlines()
    assert json.loads(lines[-1])['verdict'] == 'FAIL'
    assert all(json.loads(line).get('result') in ('PASS', 'FAIL', 'MISSING', None) for line in lines)
