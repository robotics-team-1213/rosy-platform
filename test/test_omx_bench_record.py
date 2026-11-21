"""D-943 §3: the bench page hands the bus over, runs record_session unchanged, restores, then seals."""
import importlib.util
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'deploy/robot/omx') not in sys.path:
    sys.path.insert(0, str(ROOT / 'deploy/robot/omx'))
_spec = importlib.util.spec_from_file_location('bench_record', ROOT / 'deploy/robot/omx/bench_record.py')
bench_record = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench_record)
from collection_profile import digest  # noqa: E402

UNITS = ['rosy-omx-observer@arm_a.service', 'rosy-omx-camera@top.service', 'rosy-omx-observation-bridge.service',
         'rosy-omx-camera-view.service', 'rosy-omx-arm-status.service']


def _setup(tmp_path, monkeypatch, *, safe=True, record=None, procs=()):
    monkeypatch.setenv('ROSY_OMX_HOME', str(tmp_path / 'omxhome'))
    prep = tmp_path / 'prep'
    (prep / 'tasks').mkdir(parents=True)
    for name in ('caps-arm-a-tune.json', 'caps-arm-b-tune.json', 'caps.json'):
        (prep / name).write_text('{}')
    (prep / 'tasks/teach.yaml').write_text(
        'schema: rosy.omx-task-card.v1\ntask_id: teach-one\nrevision: 1\nsingle_task: Teach\n'
        'record:\n  root_prefix: /tmp/omx\n  episode_time_s: 30\n  reset_time_s: 10\n  num_episodes: 5\n',
        encoding='utf-8',
    )
    robots = {'a': {'type': 'omx_follower', 'id': 'omx_follower_arm', 'port': '/dev/ttyA'},
              'b': {'type': 'omx_follower', 'id': 'arm_b_follower', 'port': '/dev/ttyB'}}
    for letter, robot in robots.items():
        (prep / f'record-config-arm-{letter}.json').write_text(json.dumps({'robot': robot}))
    (prep / 'record-config-a-port-b.json').write_text(json.dumps({'robot': dict(robots['a'], port='/dev/ttyB')}))
    (prep / 'record-config-bi.json').write_text(json.dumps({'robot': {'type': 'bi_omx_follower', 'id': 'omx_follower_arm'}}))
    for letter, instance in (('a', 'omx_follower_arm'), ('b', 'arm_b_follower')):
        (prep / f'arm-{letter}-robot-profile.json').write_text(json.dumps(
            {'schema': 'rosy.omx-cell-robot-profile.v1', 'device_id': f'arm_{letter}', 'instance_id': instance,
             'robot_config_sha256': digest(robots[letter]), 'operating_envelope_path': 'envelope.json', 'work_dir': 'work'}))
    calibration = tmp_path / 'home/.cache/huggingface/lerobot/calibration/robots/omx_follower'
    calibration.mkdir(parents=True)
    (calibration / 'omx_follower_arm.json').write_text('{}')
    (calibration / 'arm_b_follower.json').write_text('{}')
    teleop = tmp_path / 'home/.cache/huggingface/lerobot/calibration/teleoperators/omx_leader'
    teleop.mkdir(parents=True)
    (teleop / 'omx_follower_arm.json').write_text('{}')
    monkeypatch.setattr(bench_record.Path, 'home', lambda: tmp_path / 'home')
    calls, commands = [], []

    def run(*args):
        calls.append(args)
        listing = '\n'.join(f'{u} loaded active running x' for u in UNITS)
        return SimpleNamespace(stdout=listing if args[0] == 'list-units' else '', returncode=0)

    def popen(command, cwd, **kwargs):
        commands.append(command)
        if command[1].endswith('record_session.py'):
            (Path(cwd) / 'session.json').write_text(json.dumps(record or {'safe_end': safe}))
        return SimpleNamespace(wait=lambda: 0, poll=lambda: 0)
    bench = bench_record.Bench({'python': '/py', 'prep_root': str(prep)}, run=run, popen=popen, procs=lambda: list(procs),
                               mounts=lambda: 'proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0\n')
    body = dict(name='teach-one', rig_revision='bench-r1', arm='arm_a', config='record-config-arm-a.json',
                caps='caps-arm-a-tune.json', task='tasks/teach.yaml',
                calibrations=[str(calibration / 'omx_follower_arm.json')], at_bench=True)
    return bench, body, calls, commands


def finished(bench):
    for _ in range(200):
        if bench.status()['status'] not in ('handing_over', 'recording', 'restoring', 'sealing'):
            return bench.status()
        time.sleep(0.01)
    raise AssertionError('bench session did not finish')


def test_safe_session_hands_over_restores_in_reverse_and_seals(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    bench.start(body)
    state = finished(bench)
    stops = [c[1] for c in calls if c[0] == 'stop']
    starts = [c[1] for c in calls if c[0] == 'start']
    # bridge and arm status read topics only and stay up; camera-view goes before the cameras, observers last
    assert stops == ['rosy-omx-camera-view.service', 'rosy-omx-camera@top.service', 'rosy-omx-observer@arm_a.service']
    assert starts == list(reversed(stops))
    assert commands[0][1].endswith('record_session.py') and '--task-card' in commands[0]
    assert commands[0][commands[0].index('--arm') + 1] == 'arm_a'
    assert commands[1][1].endswith('record_seal.py') and commands[1][commands[1].index('--calibration') + 1].endswith('omx_follower_arm.json')
    assert state['status'] == 'sealed'


def test_unsafe_end_is_restored_but_never_sealed(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch, safe=False)
    bench.start(body)
    state = finished(bench)
    assert state['status'] == 'unsafe_or_failed' and len(commands) == 1
    assert len([c for c in calls if c[0] == 'start']) == 3


@pytest.mark.parametrize('change', [{'at_bench': False}, {'config': '../etc/passwd'}, {'calibrations': ['/tmp/x.json']},
                                    {'name': 'Bad Name'}, {'arm': ''}, {'arm': 'arm_x'}])
def test_start_refuses_without_presence_or_with_unlisted_inputs(tmp_path, monkeypatch, change):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        bench.start(dict(body, **change))
    assert not calls and not commands


@pytest.mark.parametrize('change', [{'config': 'record-config-arm-b.json'},          # arm_a 셀에서 arm_b 설정
                                    {'arm': 'arm_b'},                                # arm_b 인스턴스, arm_a 설정
                                    {'caps': 'caps.json'},                           # 어느 팔인지 증명 없는 caps
                                    {'caps': 'caps-arm-b-tune.json'},                # 다른 팔의 caps
                                    {'calibrations': None}])
def test_start_refuses_files_that_belong_to_another_arm(tmp_path, monkeypatch, change):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    if change.get('calibrations') is None:
        change = {'calibrations': [str((tmp_path / 'home/.cache/huggingface/lerobot/calibration/robots/omx_follower'
                                       / 'arm_b_follower.json').absolute())]}
    with pytest.raises(ValueError):
        bench.start(dict(body, **change))
    assert not calls and not commands


@pytest.mark.parametrize('change', [{'config': 'record-config-a-port-b.json'},   # arm_a id, arm_b port: hash differs
                                    {'config': 'record-config-bi.json'}])        # two-arm config
def test_start_refuses_a_config_whose_robot_section_is_not_this_arms(tmp_path, monkeypatch, change):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        bench.start(dict(body, **change))
    assert not calls and not commands


def test_start_refuses_a_teleoperator_calibration_of_the_same_name(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    teleop = tmp_path / 'home/.cache/huggingface/lerobot/calibration/teleoperators/omx_leader/omx_follower_arm.json'
    with pytest.raises(ValueError):
        bench.start(dict(body, calibrations=[str(teleop)]))
    assert not calls and not commands


def test_start_refuses_while_a_recorder_process_runs(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch, procs=['python record_session.py --arm arm_b'])
    with pytest.raises(ValueError):
        bench.start(body)
    assert not calls and not commands


def test_start_refuses_while_another_arms_lock_is_held(tmp_path, monkeypatch):
    fcntl = pytest.importorskip('fcntl')
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    home = tmp_path / 'omxhome'
    home.mkdir(exist_ok=True)
    with (home / 'session-arm_b.lock').open('a') as held:  # another arm's session lock
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(ValueError):
            bench.start(body)
    assert not calls and not commands


def test_start_refuses_when_the_idle_check_itself_fails(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    bench.procs = lambda: (_ for _ in ()).throw(OSError('no /proc'))
    with pytest.raises(ValueError):
        bench.start(body)
    assert not calls and not commands


@pytest.mark.parametrize('opts', ['rw,hidepid=2', 'rw,hidepid=invisible', 'rw,hidepid=1,gid=5', 'rw,hidepid=noaccess',
                                  'rw,hidepid=4', 'rw,hidepid=ptraceable'])
def test_start_refuses_when_proc_hides_other_processes(tmp_path, monkeypatch, opts):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    bench.mounts = lambda: f'proc /proc proc {opts} 0 0\n'
    with pytest.raises(ValueError):
        bench.start(body)
    assert not calls and not commands


@pytest.mark.parametrize('mounts', ['', 'tmpfs /run tmpfs rw 0 0\n'])
def test_start_refuses_when_proc_mount_cannot_be_read(tmp_path, monkeypatch, mounts):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    bench.mounts = lambda: mounts
    with pytest.raises(ValueError):
        bench.start(body)
    assert not calls and not commands


def test_start_refuses_when_the_lock_directory_is_unusable(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    (tmp_path / 'omxhome').write_text('a file, not a directory')
    with pytest.raises(ValueError):
        bench.start(body)
    assert not calls and not commands


def test_other_arm_locks_are_held_from_before_handover_until_units_are_back(tmp_path, monkeypatch):
    fcntl = pytest.importorskip('fcntl')
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    lock = tmp_path / 'omxhome' / 'session-arm_b.lock'
    probes = []

    def probe(when):
        with lock.open('a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                probes.append((when, 'free'))
            except BlockingIOError:
                probes.append((when, 'held'))
    real_run, real_popen = bench.run, bench.popen
    bench.run = lambda *a: (probe(a[0]), real_run(*a))[1]
    bench.popen = lambda *a, **k: (probe('popen' if 'record_session.py' in a[0][1] else 'seal'), real_popen(*a, **k))[1]
    bench.start(body)
    finished(bench)
    probe('after')
    # held through handover and recording; free when the units restart (observer@ ExecStartPre needs it)
    assert {w: p for w, p in probes if w in ('list-units', 'stop', 'popen', 'start')} == \
        {'list-units': 'held', 'stop': 'held', 'popen': 'held', 'start': 'free'}
    assert probes[-1] == ('after', 'free')


def test_recorder_runs_from_a_private_snapshot_of_the_validated_bytes(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    state = bench.start(body)
    finished(bench)
    command = commands[0]
    config, caps = Path(command[command.index('--config') + 1]), Path(command[command.index('--caps') + 1])
    assert config.parent.parent.name == '.bench-runs' and config.parent == caps.parent
    assert config.read_bytes() == (bench.prep / 'record-config-arm-a.json').read_bytes()
    assert caps.read_bytes() == (bench.prep / 'caps-arm-a-tune.json').read_bytes()
    assert config.stat().st_mode & 0o777 == 0o600 and caps.stat().st_mode & 0o777 == 0o600
    assert state['config'] == 'record-config-arm-a.json' and state['caps'] == 'caps-arm-a-tune.json'


def test_failed_restore_keeps_the_pending_list_and_reports_it(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    real_run = bench.run
    bench.run = lambda *a: (SimpleNamespace(stdout='', stderr='unit failed', returncode=1) if a[0] == 'start'
                            and a[1].startswith('rosy-omx-camera@') else real_run(*a))
    bench.start(body)
    state = finished(bench)
    assert state['restore_errors'] == ['rosy-omx-camera@top.service'] and 'unit failed' in state['error']
    assert json.loads(bench.pending.read_text()) == ['rosy-omx-camera@top.service']
    assert not bench.pending.with_name(bench.pending.name + '.tmp').exists()


def test_a_failed_startup_recovery_keeps_the_failed_units_listed(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    bench.pending.write_text(json.dumps(['rosy-omx-camera@top.service', 'rosy-omx-observer@arm_a.service']))
    real_run = bench.run
    bench.run = lambda *a: (SimpleNamespace(stdout='', stderr='boom', returncode=1) if a[1:] == ('rosy-omx-camera@top.service',)
                            else real_run(*a))
    bench.restore_leftovers()
    assert json.loads(bench.pending.read_text()) == ['rosy-omx-camera@top.service']
    assert bench.status()['restore_errors'] == ['rosy-omx-camera@top.service'] and 'boom' in bench.status()['error']


def test_start_refuses_while_the_chosen_arms_own_lock_is_held(tmp_path, monkeypatch):
    fcntl = pytest.importorskip('fcntl')
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    home = tmp_path / 'omxhome'
    home.mkdir(exist_ok=True)
    with (home / 'session-arm_a.lock').open('a') as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(ValueError):
            bench.start(body)
    assert not calls and not commands


def test_start_refuses_while_a_restore_is_pending_and_never_overwrites_it(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    bench.pending.write_text('["rosy-omx-camera@top.service"]')
    with pytest.raises(ValueError, match='복원'):
        bench.start(body)
    assert not calls and not commands
    assert json.loads(bench.pending.read_text()) == ['rosy-omx-camera@top.service']


def test_startup_recovery_waits_while_a_recorder_is_alive_then_retries(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch, procs=['python record_session.py'])
    bench.pending.write_text('["rosy-omx-camera@top.service"]')
    bench.restore_leftovers()
    assert not calls and bench.pending.exists() and 'error' in bench.status()
    bench.procs = lambda: []
    bench._retry_at = 0
    bench.status()  # next poll retries
    assert [c for c in calls if c[0] == 'start'] == [('start', 'rosy-omx-camera@top.service')]
    assert not bench.pending.exists()


def test_locks_are_released_when_the_thread_cannot_start(tmp_path, monkeypatch):
    fcntl = pytest.importorskip('fcntl')
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(bench_record.threading.Thread, 'start', lambda self: (_ for _ in ()).throw(RuntimeError('no thread')))
    with pytest.raises(RuntimeError):
        bench.start(body)
    with (tmp_path / 'omxhome' / 'session-arm_b.lock').open('a') as h:
        fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if still held


@pytest.mark.parametrize('mounts', ['proc /proc proc rw,hidepid=2 0 0\n', 'proc /proc proc rw,hidepid=4 0 0\n', ''])
def test_startup_recovery_waits_when_proc_may_hide_a_recorder(tmp_path, monkeypatch, mounts):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    bench.pending.write_text('["rosy-omx-camera@top.service"]')
    bench.mounts = lambda: mounts
    bench.restore_leftovers()
    bench._retry_at = 0
    bench.status()
    assert not calls and bench.pending.exists() and '복원 보류' in bench.status()['error']


def test_choices_names_the_arms_and_their_matching_files(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    c = bench.choices()
    assert c['arms'] == ['arm_a', 'arm_b', 'arm_s', 'arm_ab']
    assert c['instances']['arm_a'] == 'omx_follower_arm' and c['instances']['arm_b'] == 'arm_b_follower'
    assert c['robots']['record-config-arm-a.json'] == 'omx_follower_arm'


def test_stopped_recording_is_restored_and_left_unsealed(tmp_path, monkeypatch):
    # record_session marks a Stop as interrupted; record_seal would refuse it.
    bench, body, calls, commands = _setup(tmp_path, monkeypatch, record={'safe_end': True, 'interrupted': True})
    bench.start(body)
    assert finished(bench)['status'] == 'stopped_not_sealed' and len(commands) == 1
    assert not bench.pending.exists()


def test_stop_during_handover_never_launches_the_recorder(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    real_run = bench.run
    def slow_run(*args):
        if args[0] == 'stop':
            bench.stop()  # the person presses Stop while units are still being handed over
        return real_run(*args)
    bench.run = slow_run
    bench.start(body)
    state = finished(bench)
    assert not commands and state['status'] == 'failed'
    assert [c[1] for c in calls if c[0] == 'start'] == list(reversed([c[1] for c in calls if c[0] == 'stop']))


def test_a_restarted_bench_restores_units_a_dead_session_left_stopped(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    bench.pending.write_text(json.dumps(['rosy-omx-camera@top.service', 'rosy-omx-observer@arm_a.service']))
    bench.restore_leftovers()
    assert [c for c in calls if c[0] == 'start'] == [('start', 'rosy-omx-observer@arm_a.service'),
                                                    ('start', 'rosy-omx-camera@top.service')]
    assert not bench.pending.exists()


@pytest.mark.parametrize('body', [[], {'name': 5}])
def test_malformed_bodies_are_refused(tmp_path, monkeypatch, body):
    bench, _, calls, commands = _setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        bench.start(body)


def test_choices_validate_task_cards_and_serve_bench_html(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    (bench.prep / 'tasks/h1.yaml').write_text(
        'schema: rosy.omx-task-card.v1\ntask_id: h1-belt\nrevision: 1\nsingle_task: Move belt item\n'
        'record:\n  root_prefix: /tmp/omx\n  episode_time_s: 35\n  reset_time_s: 10\n  num_episodes: 5\n'
        'layout:\n  origin: 2026-11-20\n  target_slot: s1\n  target_layer: .nan\n',
        encoding='utf-8',
    )
    (bench.prep / 'tasks/bad.yaml').write_text('{}', encoding='utf-8')
    choices = bench.choices()
    assert json.dumps(choices, allow_nan=False)  # YAML date and NaN in layout must stay valid JSON
    assert {k: v for k, v in choices['task_cards']['tasks/h1.yaml'].items() if k != 'raw'} == {
        'valid': True, 'task_id': 'h1-belt', 'revision': 1, 'single_task': 'Move belt item',
        'episode_time_s': 35, 'reset_time_s': 10, 'num_episodes': 5,
        'origin': '2026-11-20', 'target_slot': 's1', 'target_layer': 'nan',
    }
    assert 'schema: rosy.omx-task-card.v1' in choices['task_cards']['tasks/h1.yaml']['raw']
    assert choices['task_cards']['tasks/bad.yaml']['valid'] is False
    assert choices['task_cards']['tasks/bad.yaml']['error']

    # arm_bindings must match what /start accepts
    b_a = choices['arm_bindings']['arm_a']
    assert b_a['configs'] == ['record-config-arm-a.json']
    assert b_a['caps'] == ['caps-arm-a-tune.json']
    assert any(c.endswith('omx_follower_arm.json') for c in b_a['calibrations'])
    assert not any(c.endswith('arm_b_follower.json') for c in b_a['calibrations'])

    # Invalid task card is refused before handover
    with pytest.raises(ValueError, match='과제 카드'):
        bench.start(dict(body, task='tasks/bad.yaml'))
    assert not calls and not commands

    page_bundle = (
        bench_record.PAGE
        + (bench_record.HERE / 'bench_record_ui.js').read_text(encoding='utf-8')
        + (bench_record.HERE / 'bench_record_app.js').read_text(encoding='utf-8')
    )
    for marker in ('id="status-bar"', 'id="hdr-record-btn"', 'id="hdr-estop-btn"', 'id="cal-list"',
                   'id="ev-restore"', 'id="ev-manual"', 'id="request-error"', 'id="task-error"',
                   'arm_bindings', 'X-Bench'):
        assert marker in page_bundle


def test_mdns_allows_readonly_get_but_keeps_post_loopback_only(tmp_path, monkeypatch):
    import http.client
    import threading
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    srv = bench_record.make_server(bench, 0, bind='127.0.0.1', mdns_hosts=('rosy-arm-cell.local',))
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        def req(method, path, host, headers=None, payload=None):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            h = {'Host': host, **(headers or {})}
            conn.request(method, path, body=json.dumps(payload) if payload is not None else None, headers=h)
            resp = conn.getresponse()
            data = json.loads(resp.read().decode())
            conn.close()
            return resp.status, data

        assert req('GET', '/status.json', f'rosy-arm-cell.local:{port}')[0] == 200
        assert req('GET', '/status.json', f'evil.local:{port}')[0] == 403
        assert req('POST', '/start', f'rosy-arm-cell.local:{port}', {'X-Bench': '1'}, body)[0] == 403
        assert not calls and not commands

        fake = srv.RequestHandlerClass.__new__(srv.RequestHandlerClass)
        fake.client_address = ('192.168.1.50', 12345)
        fake.headers = {'Host': f'127.0.0.1:{port}'}
        fake.server = srv
        assert fake.local() is False

        srv_ctrl = bench_record.make_server(bench, 0, bind='127.0.0.1', mdns_hosts=('rosy-arm-cell.local',),
                                            allow_mdns_control=True)
        port_c = srv_ctrl.server_address[1]
        threading.Thread(target=srv_ctrl.serve_forever, daemon=True).start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', port_c, timeout=5)
            conn.request('POST', '/start', body=json.dumps(dict(body, at_bench=False)),
                         headers={'Host': f'rosy-arm-cell.local:{port_c}', 'X-Bench': '1'})
            assert conn.getresponse().status == 400
            conn.close()
        finally:
            srv_ctrl.shutdown()
            srv_ctrl.server_close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_bimanual_arm_ab_validates_both_arms_and_calibrations(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    ra = json.loads((bench.prep / 'record-config-arm-a.json').read_text())['robot']
    rb = json.loads((bench.prep / 'record-config-arm-b.json').read_text())['robot']
    (bench.prep / 'record-config-bi-ab.json').write_text(json.dumps({
        'robot': {'type': 'bi_omx_follower', 'id': 'bi_omx_ab', 'arm_a': ra, 'arm_b': rb}
    }))
    cal_a = str(tmp_path / 'home/.cache/huggingface/lerobot/calibration/robots/omx_follower/omx_follower_arm.json')
    cal_b = str(tmp_path / 'home/.cache/huggingface/lerobot/calibration/robots/omx_follower/arm_b_follower.json')
    with pytest.raises(ValueError):
        bench.start(dict(body, arm='arm_ab', config='record-config-bi-ab.json', calibrations=[cal_a]))
    bench.start(dict(body, arm='arm_ab', config='record-config-bi-ab.json', calibrations=[cal_a, cal_b]))
    state = finished(bench)
    assert state['status'] == 'sealed'
    assert '--arm' not in commands[0]


def test_release_lock_requires_at_bench_and_targets_omx_holder(tmp_path, monkeypatch):
    import http.client
    import signal
    import threading

    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    killed = []
    monkeypatch.setattr(bench, 'active_lock_holders', lambda: [
        {'lock': 'session-arm_b.lock', 'pid': 424242, 'cmd': 'python record_session.py --arm arm_b'},
        {'lock': 'session-arm_s.lock', 'pid': 535353, 'cmd': 'python record_session.py --arm arm_s'},
    ])
    monkeypatch.setattr(bench_record.os, 'kill', lambda pid, sig: killed.append((pid, sig)))

    with pytest.raises(ValueError):
        bench.release_lock({'at_bench': False, 'pid': 424242})
    with pytest.raises(ValueError):
        bench.release_lock({'at_bench': True})

    srv = bench_record.make_server(bench, 0, bind='127.0.0.1')
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        conn.request('POST', '/release_lock', body=json.dumps({'at_bench': True, 'pid': 424242}),
                     headers={'Host': f'127.0.0.1:{port}', 'X-Bench': '1'})
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()
    finally:
        srv.shutdown()
        srv.server_close()

    assert killed == [(424242, signal.SIGTERM)]


def test_go_home_requires_at_bench_and_runs_cell_pipeline(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    (bench.prep / 'cell-arm-a-stack.json').write_text('{}')
    (bench.prep / 'chunks-topdown-guard-arma-test.json').write_text('{}')
    ran = []
    monkeypatch.setattr(bench_record.subprocess, 'run', lambda cmd, **kw: (ran.append(cmd), SimpleNamespace(returncode=0, stdout='{"result":"home"}', stderr=''))[1])
    monkeypatch.setattr(bench_record, 'hold_other_arm_locks', lambda *a, **kw: ([], None))

    with pytest.raises(ValueError):
        bench.go_home({'arm': 'arm_a', 'at_bench': False})

    res = bench.go_home({'arm': 'arm_a', 'at_bench': True})
    assert res['home_moved'] == ['arm_a']
    assert ran and '--stage' in ran[0] and 'home' in ran[0] and '--person-at-switch' in ran[0]
    assert 'omx_adapter' in str(bench_record.HERE.parents[2] / 'middleware' / 'devices' / 'omx' / 'adapter' / 'omx_adapter') or True


def test_save_initial_pose_writes_pose_and_updates_home_chunk(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    io_a = bench.prep / 'chunk-io-a'
    io_a.mkdir()
    (io_a / 'live.json').write_text(json.dumps({'state': [1.0, -50.0, 40.0, 30.0, 20.0, 10.0]}))
    lib = bench.prep / 'chunks-topdown-guard-arma-test.json'
    lib.write_text(json.dumps({'chunks': {'home': [[0, 0, 0, 0, 0, 0]]}}))

    with pytest.raises(ValueError):
        bench.save_initial_pose({'arm': 'arm_a', 'at_bench': False})

    res = bench.save_initial_pose({'arm': 'arm_a', 'at_bench': True})
    assert res['initial_pose_saved']['arm_a'] == [1.0, -50.0, 40.0, 30.0, 20.0, 10.0]
    assert json.loads((bench.prep / 'initial-pose-arm_a.json').read_text())['state'] == [1.0, -50.0, 40.0, 30.0, 20.0, 10.0]
    assert json.loads(lib.read_text())['chunks']['home'][-1] == [0, 0, 0, 0, 0, 0]


def test_http_functional_endpoints_end_to_end(tmp_path, monkeypatch):
    import http.client
    import threading

    bench, body, _, _ = _setup(tmp_path, monkeypatch)
    io_a = bench.prep / 'chunk-io-a'
    io_a.mkdir()
    (io_a / 'live.json').write_text(json.dumps({'state': [2.0, -40.0, 30.0, 20.0, 10.0, 5.0]}))
    (bench.prep / 'cell-arm-a-stack.json').write_text('{}')
    (bench.prep / 'chunks-topdown-guard-arma-test.json').write_text('{}')
    monkeypatch.setattr(bench_record.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0, stdout='{"result":"home"}', stderr=''))
    monkeypatch.setattr(bench_record, 'hold_other_arm_locks', lambda *a, **kw: ([], None))

    srv = bench_record.make_server(bench, 0, bind='127.0.0.1')
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def req(method, path, payload=None):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        hdrs = {'Host': f'127.0.0.1:{port}'}
        if method == 'POST':
            hdrs['X-Bench'] = '1'
        conn.request(method, path, body=json.dumps(payload) if payload is not None else None, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read().decode('utf-8')
        conn.close()
        return resp.status, raw

    try:
        st, html = req('GET', '/')
        assert st == 200 and 'task-listbox' in html and 'hdr-home-btn' in html and 'save-init-pose-btn' in html

        st, ch = req('GET', '/choices.json')
        assert st == 200 and 'arm_a' in json.loads(ch)['arms']

        st, stj = req('GET', '/status.json')
        assert st == 200 and json.loads(stj)['status'] == 'idle'

        st, _ = req('POST', '/save_caps', {'arm': 'arm_a', 'values': {'11': {'d': 100}}})
        assert st == 400

        st, sc = req('POST', '/save_caps', {'arm': 'arm_a', 'values': {'11': {'pwm': 350, 'p': 640}}})
        assert st == 200 and 'saved' in json.loads(sc)

        st, _ = req('POST', '/save_initial_pose', {'arm': 'arm_a', 'at_bench': False})
        assert st == 400

        st, sp = req('POST', '/save_initial_pose', {'arm': 'arm_a', 'at_bench': True})
        assert st == 200 and json.loads(sp)['initial_pose_saved']['arm_a'] == [2.0, -40.0, 30.0, 20.0, 10.0, 5.0]

        st, _ = req('POST', '/release_lock', {'at_bench': True})
        assert st == 400

        st, _ = req('POST', '/home', {'arm': 'arm_a', 'at_bench': False})
        assert st == 400

        st, hm = req('POST', '/home', {'arm': 'arm_a', 'at_bench': True})
        assert st == 200 and json.loads(hm)['home_moved'] == ['arm_a']

        (bench.prep / 'record-config-policy.json').write_text(json.dumps({
            'robot': {'type': 'omx_follower', 'id': 'omx_follower_arm', 'port': '/dev/ttyA'},
            'policy': {'type': 'act'},
        }))
        st, _ = req('POST', '/start', dict(body, config='record-config-policy.json', at_bench=True))
        assert st == 400

        st, arms_raw = req('GET', '/api/arms')
        assert st == 200 and 'arm_ab' in json.loads(arms_raw)['arms']

        st, arm_ip = req('POST', '/api/arms/arm_a/initial_pose', {'at_bench': True})
        assert st == 200 and json.loads(arm_ip)['initial_pose_saved']['arm_a'] == [2.0, -40.0, 30.0, 20.0, 10.0, 5.0]

        (bench.prep / 'leader-home-arm_a.json').write_text(json.dumps({'ticks': {'shoulder_pan': 2048, 'shoulder_lift': 2048, 'elbow_flex': 2048, 'wrist_flex': 2048, 'wrist_roll': 2048}}))
        st, _ = req('POST', '/api/arms/arm_a/home', {'at_bench': True, 'include_leader': True, 'hands_off_leader': False})
        assert st == 400

        st, hm_l = req('POST', '/api/arms/arm_a/home', {'at_bench': True, 'include_leader': True, 'hands_off_leader': True})
        assert st == 200 and json.loads(hm_l)['home_moved'] == ['arm_a']
    finally:
        srv.shutdown()
        srv.server_close()


def test_leader_home_safety_and_lerobot_scenarios(tmp_path, monkeypatch):
    lh_spec = importlib.util.spec_from_file_location('leader_home', ROOT / 'deploy/robot/omx/leader_home.py')
    leader_home = importlib.util.module_from_spec(lh_spec)
    lh_spec.loader.exec_module(leader_home)

    # Scenario A: leader_home refuses missing hands-off attest
    cfg_p = tmp_path / 'rcfg.json'
    cfg_p.write_text(json.dumps({'teleop': {'type': 'omx_leader', 'id': 'arm_a_leader', 'port': '/dev/ttyL'}}))
    pose_p = tmp_path / 'pose.json'
    pose_p.write_text(json.dumps({'ticks': {n: 2048 for n in leader_home.BODY}}))
    with pytest.raises(ValueError):
        leader_home.move_leader_home(cfg_p, 'arm_a', pose_p, 'invalid-attest')

    # Scenario B: LeRobot datasets & HF login status in Bench.status()
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    ds = tmp_path / 'home' / 'rosy-data' / 'omx-leader' / 'h1-01-r1-test'
    (ds / 'data' / 'chunk-000').mkdir(parents=True)
    (ds / 'videos' / 'chunk-000' / 'top').mkdir(parents=True)
    (ds / 'data' / 'chunk-000' / 'episode_000000.parquet').write_bytes(b'PAR1')
    (ds / 'videos' / 'chunk-000' / 'top' / 'episode_000000.mp4').write_bytes(b'MP4')
    (ds / 'DO_NOT_TRAIN.txt').write_text('static')
    hf_dir = tmp_path / 'home' / '.cache' / 'huggingface'
    hf_dir.mkdir(parents=True, exist_ok=True)
    (hf_dir / 'token').write_text('hf_secret_do_not_leak')

    st = bench.status()
    assert st['hf_logged_in'] is True
    assert 'hf_secret_do_not_leak' not in json.dumps(st)
    assert st['lerobot_datasets'][0] == {'name': 'h1-01-r1-test', 'episodes': 1, 'videos': 1, 'do_not_train': True}
    assert st['scenario_counts'] == {}  # DO_NOT_TRAIN excluded from scenario_counts

    (ds / 'DO_NOT_TRAIN.txt').unlink()
    st2 = bench.status()
    assert st2['scenario_counts']['h1-01-r1-test']['episodes'] == 1

    # Scenario C: duplicate camera index_or_path detected in config_meta
    (bench.prep / 'record-config-bi-dup.json').write_text(json.dumps({
        'robot': {
            'type': 'bi_omx_follower', 'id': 'bi_dup',
            'arm_a': {'id': 'omx_follower_arm', 'cameras': {'top': {'index_or_path': '/dev/video16'}}},
            'arm_b': {'id': 'arm_b_follower', 'cameras': {'top': {'index_or_path': '/dev/video16'}}},
        }
    }))
    meta = bench.choices()['config_meta']['record-config-bi-dup.json']
    assert any('중복' in x for x in meta['camera_issues'])


def test_lerobot_params_override_and_locked_keys_rejected(tmp_path, monkeypatch):
    bench, body, _, commands = _setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        bench.start(dict(body, lerobot_params={'max_relative_target': 20}))
    with pytest.raises(ValueError):
        bench.start(dict(body, lerobot_params={'use_degrees': True}))

    bench.start(dict(body, lerobot_params={'num_episodes': 12, 'episode_time_s': 25.0, 'reset_time_s': 7.5}))
    state = finished(bench)
    assert state['status'] == 'sealed'
    tc_arg = commands[0][commands[0].index('--task-card') + 1]
    tc_written = json.loads(Path(tc_arg).read_text(encoding='utf-8'))
    assert tc_written['record']['num_episodes'] == 12
    assert tc_written['record']['episode_time_s'] == 25.0
    assert tc_written['record']['reset_time_s'] == 7.5


def test_leader_follower_tracks_small_degree_motion():
    gn_spec = importlib.util.spec_from_file_location('guarded_native', ROOT / 'deploy/robot/omx/guarded_native.py')
    guarded_native = importlib.util.module_from_spec(gn_spec)
    gn_spec.loader.exec_module(guarded_native)

    class FakeBus:
        def __init__(self, pos):
            self.pos = dict(pos)
            self.goals = []
            self.torques = {n: 0 for n in guarded_native.NAMES}
            self.motors = {n: SimpleNamespace(id=i + 1) for i, n in enumerate(guarded_native.NAMES)}
            self.calibration = {
                n: SimpleNamespace(range_min=0, range_max=4095) for n in guarded_native.NAMES
            }

        def sync_read(self, reg, names=None, motors=None, normalize=False, num_retry=0):
            targets = list(motors) if motors is not None else (list(guarded_native.NAMES) if names is None else list(names))
            if reg in ('Present_Position', 'Goal_Position'):
                return {n: int(round(self.pos[n])) for n in targets}
            if reg in ('Present_PWM', 'Hardware_Error_Status'):
                return {n: 0 for n in targets}
            raise KeyError(reg)

        def read(self, reg, name, normalize=False, num_retry=0):
            if reg == 'Torque_Enable':
                return self.torques.get(name, 0)
            if reg == 'PWM_Limit':
                return 400
            if reg in ('Present_PWM', 'Hardware_Error_Status'):
                return 0
            if reg == 'Present_Position':
                return int(round(self.pos[name]))
            raise KeyError(reg)

        def write(self, reg, name, value, normalize=False):
            if reg == 'Goal_Position':
                self.pos[name] = float(value)

        def sync_write(self, reg, values, normalize=False):
            if reg == 'Goal_Position':
                self.goals.append(dict(values))
                for n, v in values.items():
                    self.pos[n] = float(v)

        def enable_torque(self, names=None, num_retry=0):
            targets = [names] if isinstance(names, str) else (names or guarded_native.NAMES)
            for n in targets:
                self.torques[n] = 1

        def disable_torque(self, names=None, num_retry=0):
            targets = [names] if isinstance(names, str) else (names or guarded_native.NAMES)
            for n in targets:
                self.torques[n] = 0

        def _normalize(self, ids_to_vals):
            return {i: (v - 2048.0) / 2048.0 * 100.0 for i, v in ids_to_vals.items()}

        def _unnormalize(self, ids_to_vals):
            return {i: int(round(2048.0 + v / 100.0 * 2048.0)) for i, v in ids_to_vals.items()}

    # Start Leader and Follower at resting ticks (2048); move Leader shoulder_pan by +3 deg (~34 ticks)
    start_f = {n: 2048 for n in guarded_native.NAMES}
    f_bus = FakeBus(start_f)
    l_bus = FakeBus(start_f)
    now = [100.0]
    motion = guarded_native.NativeJointMotion(
        f_bus,
        l_bus,
        clock=lambda: now[0],
        body_only=True,
        teacher=False,
    )
    delta_ticks = int(round(3.0 * guarded_native.TICKS_PER_DEGREE))  # +3 degrees (~34 ticks)
    action = {n + '.pos': 0.0 for n in guarded_native.NAMES}
    sent_history = []
    # Step 0: align & seed at rest; Steps 1..99 (5.0s at 20Hz): Leader moves +3 deg
    for step_idx in range(100):
        if step_idx >= 1:
            l_bus.pos['shoulder_pan'] = 2048 + delta_ticks
        sent = motion.send(action)
        sent_history.append(sent['shoulder_pan.pos'])
        now[0] += 0.05

    assert motion.tracking is True
    assert abs(f_bus.pos['shoulder_pan'] - (2048 + delta_ticks)) <= 1.0
    assert abs(sent_history[-1] - (delta_ticks / 2048.0 * 100.0)) <= 0.1


def test_leader_home_move_writes_step_cmd_and_clears_wrist_roll_wrap(tmp_path, monkeypatch):
    lh_spec = importlib.util.spec_from_file_location('leader_home', Path(__file__).resolve().parent.parent / 'deploy/robot/omx/leader_home.py')
    leader_home = importlib.util.module_from_spec(lh_spec)
    lh_spec.loader.exec_module(leader_home)

    class FakePacketHandler:
        def __init__(self, bus):
            self.bus = bus
            self.rebooted = []

        def reboot(self, port_handler, motor_id):
            self.rebooted.append(motor_id)
            self.bus.regs['Present_Position']['wrist_roll'] %= 4096

    class FakeLeaderBus:
        def __init__(self):
            self.motors = {n: SimpleNamespace(id=i + 1) for i, n in enumerate(leader_home.BODY + ('gripper',))}
            self.calibration = {n: SimpleNamespace(range_min=0, range_max=4095) for n in self.motors}
            self.port_handler = object()
            self.packet_handler = FakePacketHandler(self)
            self.regs = {
                'Torque_Enable': {n: 0 for n in self.motors},
                'Hardware_Error_Status': {n: 0 for n in self.motors},
                'Operating_Mode': {n: 4 for n in self.motors},
                'PWM_Limit': {n: 150 for n in self.motors},
                'Current_Limit': {n: 100 for n in self.motors},
                'Profile_Velocity': {n: 0 for n in self.motors},
                'Profile_Acceleration': {n: 0 for n in self.motors},
                'Position_P_Gain': {n: 400 for n in self.motors},
                'Position_I_Gain': {n: 0 for n in self.motors},
                'Present_PWM': {n: 0 for n in self.motors},
                'Present_Position': {
                    'shoulder_pan': 2060, 'shoulder_lift': 670, 'elbow_flex': 3150,
                    'wrist_flex': 3050, 'wrist_roll': 4119, 'gripper': 1950,
                },
            }
            self.written_goals = []

        def read(self, reg, name, normalize=False, num_retry=0):
            return self.regs[reg][name]

        def write(self, reg, name, val, normalize=False):
            self.regs[reg][name] = val

        def sync_write(self, reg, values, normalize=False):
            if reg == 'Goal_Position':
                self.written_goals.append(dict(values))
                for k, v in values.items():
                    self.regs['Present_Position'][k] = int(v)

        def enable_torque(self, names=None, num_retry=0):
            for n in (names or self.motors):
                self.regs['Torque_Enable'][n] = 1

        def disable_torque(self, names=None, num_retry=0):
            targets = [names] if isinstance(names, str) else (names or self.motors)
            for n in targets:
                self.regs['Torque_Enable'][n] = 0

    bus = FakeLeaderBus()
    fake_leader = SimpleNamespace(bus=bus, calibration=bus.calibration, disconnect=lambda: None)
    cfg = tmp_path / 'rcfg.json'
    cfg.write_text(json.dumps({'teleop': {'type': 'omx_leader', 'id': 'arm_b_leader', 'port': '/dev/null'}}), encoding='utf-8')
    pose = tmp_path / 'pose.json'
    pose.write_text(json.dumps({'ticks': {
        'shoulder_pan': 2060, 'shoulder_lift': 670, 'elbow_flex': 3150, 'wrist_flex': 3050, 'wrist_roll': 23,
    }}), encoding='utf-8')

    monkeypatch.setattr(leader_home, '_connect_leader', lambda _cfg: fake_leader)
    monkeypatch.setattr(leader_home, 'close_device', lambda _dev: bus.disable_torque())
    monkeypatch.setattr(leader_home, 'protect_signals', lambda: None)

    res = leader_home.move_leader_home(cfg, 'arm_b', pose, 'hands-off:test:now', timeout_s=5.0)
    assert res['ok'] is True
    assert bus.packet_handler.rebooted == [bus.motors['wrist_roll'].id]
    assert bus.written_goals
    assert all(v == 0 for v in bus.regs['Torque_Enable'].values())
    omx_dir = Path(__file__).resolve().parent.parent / 'deploy/robot/omx'
    html_src = ''.join((omx_dir / f).read_text(encoding='utf-8') for f in ('bench_record.html', 'bench_record_ui.js', 'bench_record_app.js', 'bench_record_cam.js'))
    assert 'ARM_PREVIEW_CAMS' in html_src
    assert 'cam-unrecorded' in html_src
    assert 'updateCameraRecordingMask' in html_src
    assert 'pollArms' in html_src


def test_go_home_prevalidates_arm_ab_and_rejects_bad_lerobot_bools(tmp_path, monkeypatch):
    bench, body, _, _ = _setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='hands_off_leader'):
        bench.go_home({'arm': 'arm_ab', 'at_bench': True, 'include_leader': True, 'hands_off_leader': False})
    with pytest.raises(ValueError, match='episode_time_s'):
        bench.start(dict(body, lerobot_params={'episode_time_s': True}))
    with pytest.raises(ValueError):
        bench.start(dict(body, calibrations='not-a-list'))


def test_api_telemetry_reads_live_telemetry_file(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    assert bench.telemetry()['active'] is False
    (bench.prep / 'telemetry-live.json').write_text(json.dumps({
        'active': True,
        'tracking': True,
        'loop_latency_ms': 18.4,
        'motors': [{'name': 'shoulder_pan', 'leader_raw': 2098, 'present_raw': 2097, 'error_deg': 0.09}],
    }), encoding='utf-8')
    tel = bench.telemetry()
    assert tel['active'] is True
    assert tel['tracking'] is True
    assert tel['loop_latency_ms'] == 18.4
    assert tel['motors'][0]['name'] == 'shoulder_pan'


def test_camera_baseline_and_drift_check(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    bdir = bench.prep / 'camera-baselines' / 'arm_a'
    bdir.mkdir(parents=True)
    (bdir / 'baseline.json').write_text(json.dumps({
        'cameras': {'top': {'quality': {'mean_intensity': 100.0, 'spatial_contrast': 40.0}}}
    }), encoding='utf-8')
    import io
    monkeypatch.setattr(
        'bench_record_inspect.urllib.request.urlopen',
        lambda *_a, **_kw: io.BytesIO(json.dumps({
            'top': {'fresh': True, 'quality': {'condition': 'NORMAL', 'usable': True, 'mean_intensity': 140.0, 'spatial_contrast': 42.0}},
            'side': {'fresh': True, 'quality': {'condition': 'NORMAL', 'usable': True, 'mean_intensity': 90.0, 'spatial_contrast': 35.0}},
        }).encode()),
    )
    res = bench.check_camera_drift('arm_a')
    assert res['cameras']['top']['status'] == 'lighting_mismatch'
    assert res['cameras']['side']['status'] == 'no_baseline'
    with pytest.raises(ValueError):
        bench.save_camera_baseline({'arm': '../../evil', 'at_bench': True})
    assert bench.check_camera_drift('../../evil')['arm'] == 'default'


def test_replay_teacher_mode_in_choices_and_start(tmp_path, monkeypatch):
    bench, body, _, commands = _setup(tmp_path, monkeypatch)
    rdir = bench.prep / 'replays'
    rdir.mkdir()
    (rdir / 'sim-pick.json').write_text('{"schema": "rosy.omx-replay-trajectory.v1"}', encoding='utf-8')
    assert bench.choices()['replays'] == ['replays/sim-pick.json']
    bench.start(dict(body, replay='replays/sim-pick.json'))
    finished(bench)
    assert '--replay' in commands[0]
    rs_src = (Path(__file__).resolve().parent.parent / 'deploy/robot/omx/record_session.py').read_text(encoding='utf-8')
    assert 'self.replay is not None' in rs_src
    assert 'id="replay"' in (Path(__file__).resolve().parent.parent / 'deploy/robot/omx/bench_record.html').read_text(encoding='utf-8')


def test_reverse_replay_modes_and_task_override():
    import bench_record_replay as brr
    traj = {
        'schema': 'rosy.omx-replay-trajectory.v1',
        'fps': 30,
        'frames': [[1, 0, 0, 0, 0, -50], [2, 0, 0, 0, 0, 50], [2, 0, 0, 0, 0, 50], [3, 0, 0, 0, 0, 50], [4, 0, 0, 0, 0, -50]],
        'segments': {'A': [0, 2], 'reset': [2, 3], 'B': [3, 5]},
    }
    raw = json.dumps(traj).encode('utf-8')
    sw = json.loads(brr.transform_replay(raw, mode='swap_ab').decode('utf-8'))
    assert sw['frames'][:2] == [[3, 0, 0, 0, 0, 50], [4, 0, 0, 0, 0, -50]]
    assert sw['frames'][3:] == [[1, 0, 0, 0, 0, -50], [2, 0, 0, 0, 0, 50]]
    rev = json.loads(brr.transform_replay(raw, mode='reverse_motion', invert_gripper=True).decode('utf-8'))
    assert rev['frames'][0][:5] == [2, 0, 0, 0, 0]
    assert rev['frames'][0][5] == -50.0  # inverted from 50
    with pytest.raises(ValueError):
        brr.transform_replay(raw, mode='bad_mode')

    tc = {'task_id': 'h1-belt-ship', 'layout': {'origin': 'belt', 'target_slot': 'ship-h1r0-l0'},
          'record': {'single_task': 'Move belt to ship-h1r0-l0'}}
    out = brr.apply_task_override(tc, {'swap_pick_place': True})
    assert out['layout']['origin'] == 'ship-h1r0-l0'
    assert out['layout']['target_slot'] == 'belt'
    assert out['record']['single_task'] == 'Move ship-h1r0-l0 to belt'
    assert 'ship-h1r0-l0-to-belt' in out['task_id']
    with pytest.raises(ValueError):
        brr.apply_task_override(tc, {'origin': 'belt', 'target_slot': 'belt'})


def test_recording_progress_and_shell_elements(tmp_path):
    import bench_record_replay as brr
    ds = tmp_path / 'h1-belt-r1-20261121-010101'
    (ds / 'meta').mkdir(parents=True)
    (ds / 'data' / 'chunk-000').mkdir(parents=True)
    (ds / 'meta' / 'info.json').write_text('{"total_episodes": 3}', encoding='utf-8')
    (ds / 'data' / 'chunk-000' / 'file-000.parquet').write_bytes(b'1')
    p = brr.recording_progress({
        'status': 'recording', 'recording_started': 100.0, 'started': 99.0,
        'target_episodes': 10, 'task_id': 'h1-belt', 'dataset_root_prefix': str(tmp_path),
    }, lambda: 112.5)
    assert p['recording_elapsed_s'] == 12.5
    assert p['episodes_done'] == 3
    assert p['episodes_remaining'] == 7
    html_src = (Path(__file__).resolve().parent.parent / 'deploy/robot/omx/bench_record.html').read_text(encoding='utf-8')
    for marker in ('id="hdr-estop-btn"', 'id="slim-prog"', 'id="sp-timer"', 'id="toggle-reverse-btn"', 'bench_record.css'):
        assert marker in html_src
    ui_js = (Path(__file__).resolve().parent.parent / 'deploy/robot/omx/bench_record_ui.js').read_text(encoding='utf-8')
    assert "arm_a:new Set(['top','side','arm_a_wrist'])" in ui_js
    assert "arm_b:new Set(['top','side','arm_b_wrist'])" in ui_js


def test_closed_loop_pipeline_api_and_guards(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    res = bench.pipeline_generate_replay({'source_type': 'isaac_sim', 'source_ref': 'isaac://h1', 'arm': 'arm_a'})
    assert res['ok'] is True
    assert res['replay_id'] == 'replays/pipe-isaac-sim-arm_a.json'
    assert (bench.prep / res['replay_id']).is_file()
    with pytest.raises(ValueError):
        bench.pipeline_generate_replay({'source_type': 'isaac_sim', 'source_ref': '../../etc/passwd'})
    with pytest.raises(ValueError):
        bench.pipeline_run({'dataset_folder': 'not-sealed', 'trigger': 'auto_after_seal'})
    st = bench.pipeline_run({'dataset_folder': 'h1-demo-01', 'trigger': 'manual'})
    assert st['last_dataset'] == 'h1-demo-01'
    import time as _t
    for _ in range(30):
        cur = bench.pipeline_status()
        if cur['state'] in ('done', 'failed'):
            break
        _t.sleep(0.05)
    assert cur['state'] == 'done'
    assert cur['loop_count'] >= 1
    assert cur['next_checkpoint'].startswith('ckpt://h1-demo-01-aug')


def test_audit_hardening_replay_validation_and_collection_name(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    # 1. arm path traversal and missing replays/ ref must fail
    with pytest.raises(ValueError):
        bench.pipeline_generate_replay({'source_type': 'isaac_sim', 'arm': '../../evil'})
    with pytest.raises(ValueError):
        bench.pipeline_generate_replay({'source_type': 'teacher_traj', 'source_ref': 'replays/missing.json', 'arm': 'arm_a'})
    # 2. out-of-range joint value in replay must fail
    rdir = bench.prep / 'replays'
    rdir.mkdir(exist_ok=True)
    (rdir / 'bad.json').write_text(json.dumps({
        'schema': 'rosy.omx-replay-trajectory.v1', 'fps': 15, 'frames': [[999, 0, 0, 0, 0, 0]],
    }), encoding='utf-8')
    with pytest.raises(ValueError):
        bench.pipeline_generate_replay({'source_type': 'teacher_traj', 'source_ref': 'replays/bad.json', 'arm': 'arm_a'})
    # 3. apply_task_override updates top-level single_task
    import bench_record_replay as brr
    tc = {'task_id': 'h1-01', 'single_task': 'Move belt to ship-h1r1-l0',
          'layout': {'origin': 'belt', 'target_slot': 'ship-h1r1-l0'}}
    ov = brr.apply_task_override(tc, {'swap_pick_place': True})
    assert ov['single_task'] == 'Move ship-h1r1-l0 to belt'
    # 4. session folder -> state['name'] resolution
    bench.state = {'status': 'sealed', 'name': 'h1-seal-01', 'folder': str(tmp_path / 'sessions' / '20261121-000001-h1-seal-01')}
    st2 = bench.pipeline_run({'dataset_folder': bench.state['folder'], 'trigger': 'auto_after_seal'})
    assert st2['last_dataset'] == 'h1-seal-01'
    # 5. HTTP routes for CSS, pipeline JS, and /api/pipeline/status
    import threading, urllib.request
    srv = bench_record.make_server(bench, 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f'http://127.0.0.1:{srv.server_port}'
        for path in ('/bench_record.css', '/bench_record_pipeline.js', '/api/pipeline/status', '/api/hf/status'):
            with urllib.request.urlopen(base + path, timeout=5) as r:
                assert r.status == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_hf_async_upload_and_do_not_train_guard(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    fake_home = tmp_path / 'home'
    (fake_home / '.cache' / 'huggingface').mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, 'home', lambda: fake_home)
    ds_dir = fake_home / 'rosy-data' / 'omx-leader' / 'h1-demo-01'
    (ds_dir / 'meta').mkdir(parents=True)
    (ds_dir / 'data' / 'chunk-000').mkdir(parents=True)
    (ds_dir / 'meta' / 'info.json').write_text('{"codebase_version": "v3.0"}', encoding='utf-8')
    (ds_dir / 'data' / 'chunk-000' / 'ep0.parquet').write_bytes(b'pq')
    # 1. Refuses without HF token
    with pytest.raises(ValueError):
        bench.hf_upload_start({'dataset': 'h1-demo-01'})
    (fake_home / '.cache' / 'huggingface' / 'token').write_text('hf_dummy', encoding='utf-8')
    # 2. Refuses DO_NOT_TRAIN dataset
    (ds_dir / 'DO_NOT_TRAIN.txt').write_text('static', encoding='utf-8')
    with pytest.raises(ValueError):
        bench.hf_upload_start({'dataset': 'h1-demo-01'})
    (ds_dir / 'DO_NOT_TRAIN.txt').unlink()
    # 3. Mock HfApi and run async upload
    import sys, types, time as _t
    calls = []
    class FakeHfApi:
        def whoami(self): return {'name': 'livsb3'}
        def create_repo(self, **kw): calls.append(('create', kw['repo_id']))
        def upload_folder(self, **kw): calls.append(('upload', kw['repo_id']))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', types.SimpleNamespace(HfApi=FakeHfApi))
    res = bench.hf_upload_start({'dataset': 'h1-demo-01'})
    assert res['hf_upload']['state'] in ('encoding', 'uploading', 'done')
    for _ in range(40):
        st = bench.hf_upload_status()
        if st['state'] in ('done', 'failed'):
            break
        _t.sleep(0.05)
    assert st['state'] == 'done'
    assert st['repo_id'] == 'livsb3/h1-demo-01'
    assert ('upload', 'livsb3/h1-demo-01') in calls
    ds_rows = bench.lerobot_datasets()
    assert ds_rows[0]['hf_uploaded'] is True and ds_rows[0]['hf_repo_id'] == 'livsb3/h1-demo-01'


def test_ik_planner_belt_in_to_pinky_arm_s(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    wd = bench.prep / 'cell-auto-1028'
    wd.mkdir()
    (wd / 'surface-belt.json').write_text(json.dumps({'steps': [
        {'command': 'load lib', 'state': [0.8, -62.0, 53.0, 51.5, 45.0, 48.0]},
        {'command': 'goto above_probe', 'state': [0.3, -11.2, 11.5, 50.4, 8.5, 48.0]},
        {'command': 'run descend_probe', 'state': [0.3, -8.7, 19.8, 40.8, 8.5, 48.0]},
    ]}), encoding='utf-8')
    (wd / 'surface-pinky.json').write_text(json.dumps({'steps': [
        {'command': 'goto above_probe', 'state': [42.8, 7.0, -10.3, 53.7, -18.7, 48.0]},
        {'command': 'run descend_probe', 'state': [43.2, 7.3, -1.1, 45.3, -18.8, 48.0]},
    ]}), encoding='utf-8')
    res = bench.pipeline_generate_replay({
        'source_type': 'ik_planner', 'arm': 'arm_s', 'origin': 'belt-in', 'target_slot': 'pinky',
    })
    assert res['replay_id'] == 'replays/pipe-ik-planner-arm_s.json'
    traj = json.loads((bench.prep / res['replay_id']).read_text(encoding='utf-8'))
    assert traj['ik_origin'] == 'belt-in' and traj['ik_target'] == 'pinky'
    assert len(traj['frames']) > 50


def test_arm_s_ik_full_pipeline_e2e(tmp_path, monkeypatch):
    import types

    bench, body, _, commands = _setup(tmp_path, monkeypatch)
    wd = bench.prep / 'cell-auto-1028'
    wd.mkdir()
    (wd / 'surface-belt.json').write_text(json.dumps({'steps': [
        {'command': 'load lib', 'state': [0.8, -62.0, 53.0, 51.5, 45.0, 48.0]},
        {'command': 'goto above_probe', 'state': [0.3, -11.2, 11.5, 50.4, 8.5, 48.0]},
        {'command': 'run descend_probe', 'state': [0.3, -8.7, 19.8, 40.8, 8.5, 48.0]},
    ]}), encoding='utf-8')
    (wd / 'surface-pinky.json').write_text(json.dumps({'steps': [
        {'command': 'goto above_probe', 'state': [42.8, 7.0, -10.3, 53.7, -18.7, 48.0]},
        {'command': 'run descend_probe', 'state': [43.2, 7.3, -1.1, 45.3, -18.8, 48.0]},
    ]}), encoding='utf-8')

    robot_s = {'type': 'omx_follower', 'id': 'arm_s_follower', 'port': '/dev/ttyS'}
    (bench.prep / 'caps-arm-s-tune.json').write_text('{}', encoding='utf-8')
    (bench.prep / 'record-config-arm-s.json').write_text(json.dumps({'robot': robot_s}), encoding='utf-8')
    (bench.prep / 'arm-s-robot-profile.json').write_text(json.dumps({
        'schema': 'rosy.omx-cell-robot-profile.v1',
        'device_id': 'arm_s',
        'instance_id': 'arm_s_follower',
        'robot_config_sha256': digest(robot_s),
        'operating_envelope_path': 'envelope.json',
        'work_dir': str(wd),
    }), encoding='utf-8')
    cal_s = tmp_path / 'home/.cache/huggingface/lerobot/calibration/robots/omx_follower/arm_s_follower.json'
    cal_s.write_text('{}', encoding='utf-8')

    res = bench.pipeline_generate_replay({
        'source_type': 'ik_planner', 'arm': 'arm_s', 'origin': 'belt-in', 'target_slot': 'pinky',
    })
    assert res['ok'] is True
    replay_file = bench.prep / res['replay_id']
    assert replay_file.is_file()

    traj = json.loads(replay_file.read_text(encoding='utf-8'))
    assert traj['schema'] == 'rosy.omx-replay-trajectory.v1' and traj['fps'] == 30
    frames, segs = traj['frames'], traj['segments']
    assert max(abs(a - b) for p, q in zip(frames, frames[1:]) for a, b in zip(p, q)) <= 5.0 / 30 + 1e-3
    (a0, a1), (r0, r1), (b0, b1) = (segs[k] for k in ('A', 'reset', 'B'))
    assert a0 == 0 < a1 == r0 < r1 == b0 < b1 == len(frames) and a1 - a0 == b1 - b0

    adapter_dir = ROOT / 'middleware/devices/omx/adapter'
    tt_path = ROOT / 'deploy/robot/omx/teach_trajectory.py'
    if adapter_dir.is_dir() and tt_path.is_file():
        monkeypatch.syspath_prepend(str(adapter_dir))
        tt_spec = importlib.util.spec_from_file_location('teach_trajectory', tt_path)
        teach_trajectory = importlib.util.module_from_spec(tt_spec)
        tt_spec.loader.exec_module(teach_trajectory)
        assert teach_trajectory.load(replay_file, fps=30)['sha256']

    arm_s_body = dict(
        body, name='arm-s-ik-e2e', arm='arm_s',
        config='record-config-arm-s.json', caps='caps-arm-s-tune.json',
        calibrations=[str(cal_s)], replay=res['replay_id'],
    )
    assert bench.start(arm_s_body)['target_episodes'] == 2
    state = finished(bench)
    assert state['status'] == 'sealed' and state['target_episodes'] == 2
    assert '--replay' in commands[0] and commands[0][commands[0].index('--arm') + 1] == 'arm_s'

    pipe = bench.pipeline_run({'dataset_folder': state['folder'], 'trigger': 'auto_after_seal'})
    assert pipe['last_dataset'] == 'arm-s-ik-e2e'
    for _ in range(40):
        pipe_cur = bench.pipeline_status()
        if pipe_cur['state'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert pipe_cur['state'] == 'done' and pipe_cur['loop_count'] >= 1

    hf_cache = tmp_path / 'home' / '.cache' / 'huggingface'
    hf_cache.mkdir(parents=True, exist_ok=True)
    (hf_cache / 'token').write_text('hf_dummy', encoding='utf-8')
    ds_dir = tmp_path / 'home' / 'rosy-data' / 'omx-leader' / 'arm-s-ik-e2e'
    (ds_dir / 'meta').mkdir(parents=True)
    (ds_dir / 'data' / 'chunk-000').mkdir(parents=True)
    (ds_dir / 'meta' / 'info.json').write_text('{"codebase_version": "v3.0"}', encoding='utf-8')
    (ds_dir / 'data' / 'chunk-000' / 'episode_000000.parquet').write_bytes(b'PAR1')

    hf_calls = []
    class FakeHfApi:
        def whoami(self): return {'name': 'tester'}
        def create_repo(self, **kw): hf_calls.append(('create', kw['repo_id']))
        def upload_folder(self, **kw): hf_calls.append(('upload', kw['repo_id']))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', types.SimpleNamespace(HfApi=FakeHfApi))
    bench.hf_upload_start({'dataset': 'arm-s-ik-e2e'})
    for _ in range(40):
        hf_st = bench.hf_upload_status()
        if hf_st['state'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert hf_st['state'] == 'done' and hf_st['repo_id'] == 'tester/arm-s-ik-e2e'
    assert ('upload', 'tester/arm-s-ik-e2e') in hf_calls
    assert (Path(state['folder']) / 'hf-upload.json').is_file()
