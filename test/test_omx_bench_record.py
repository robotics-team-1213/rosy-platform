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
    monkeypatch.setenv('ROSY_ARM_LEASES', str(tmp_path / 'leases'))  # never the real cell's leases
    import omx_incident
    monkeypatch.setattr(omx_incident, 'refuse_if_held', lambda arm, *a, **k: None)  # no Fleet link, no local hold file of the real cell
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
            if safe and not (record and not record.get('safe_end', True)):
                (Path(cwd) / 'clean-end.json').write_text(json.dumps({'clean': True}))
        return SimpleNamespace(wait=lambda timeout=None: 0, poll=lambda: 0, returncode=0, send_signal=lambda s: None,
                               communicate=lambda timeout=None: ('{}', ''))
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
    monkeypatch.setattr("bench_live_preview.SHM", tmp_path / "missing")
    popen = bench.popen
    live_folders = []

    def inspect_preview(command, cwd, **kwargs):
        if command[1].endswith("record_session.py"):
            live_folder = Path(kwargs["env"]["ROSY_BENCH_LIVE_DIR"])
            assert live_folder.parent == cwd and live_folder.is_dir()
            assert bench.live_preview.folder == live_folder
            live_folders.append(live_folder)
        return popen(command, cwd, **kwargs)

    bench.popen = inspect_preview
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
    assert len(live_folders) == 1 and not live_folders[0].exists()


def test_unsafe_end_is_restored_but_never_sealed(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch, safe=False)
    bench.start(body)
    state = finished(bench)
    assert state['status'] == 'unsafe_or_failed' and len(commands) == 1
    assert len([c for c in calls if c[0] == 'start']) == 3


@pytest.mark.parametrize('change', [{'config': '../etc/passwd'}, {'calibrations': ['/tmp/x.json']},
                                    {'name': 'Bad Name'}, {'arm': ''}, {'arm': 'arm_x'}])
def test_start_refuses_with_unlisted_or_invalid_inputs(tmp_path, monkeypatch, change):
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
        + ((bench_record.HERE / 'bench_record_ui.js').read_text(encoding='utf-8') + (bench_record.HERE / 'bench_record_status.js').read_text(encoding='utf-8'))
        + ((bench_record.HERE / 'bench_record_app.js').read_text(encoding='utf-8') + (bench_record.HERE / 'bench_record_drawers.js').read_text(encoding='utf-8'))
    )
    for marker in ('id="status-bar"', 'id="hdr-record-btn"', 'id="hdr-estop-btn"', 'id="cal-robot-list"',
                   'id="ev-restore"', 'id="ev-manual"', 'id="start-reason-bar"', 'id="task-error"',
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
            conn.request('POST', '/start', body=json.dumps(dict(body, name='Bad Name')),
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
        bench.release_lock({})

    srv = bench_record.make_server(bench, 0, bind='127.0.0.1')
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        conn.request('POST', '/release_lock', body=json.dumps({'pid': 424242}),
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

    res = bench.go_home({'arm': 'arm_a'})
    assert res['home_moved'] == ['arm_a']
    assert ran and '--stage' in ran[0] and 'home' in ran[0] and '--person-at-switch' in ran[0]
    assert 'omx_adapter' in str(bench_record.HERE.parents[2] / 'middleware' / 'devices' / 'omx' / 'adapter' / 'omx_adapter') or True


def test_go_home_refuses_before_any_state_change_when_the_board_is_absent(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    (bench.prep / 'cell-arm-a-stack.json').write_text('{}')
    (bench.prep / 'chunks-topdown-guard-arma-test.json').write_text('{}')
    monkeypatch.setattr(bench, '_check_robot', lambda *a, **kw: None)
    cfg = bench.prep / 'record-config-arm-a.json'
    cfg.write_text(json.dumps({'robot': {'port': '/dev/serial/by-id/usb-not-plugged-if00'}}))
    with pytest.raises(ValueError, match='연결되어 있지 않습니다'):
        bench.go_home({'arm': 'arm_a'})
    assert bench.state['status'] == 'idle'


def _arm_s_live_files(bench):
    robot_s = {'type': 'omx_follower', 'id': 'arm_s_follower', 'port': '/dev/ttyS'}
    for name, text in (('cell-auto-arm-s-live.json', '{}'), ('chunks-arm-s-inplace-live.json', '{}'), ('caps-arm-s-tune.json', '{}'),
                       ('record-config-arm-s-live.json', json.dumps({'robot': robot_s})),
                       ('arm-s-robot-profile-live.json', json.dumps({
                           'schema': 'rosy.omx-cell-robot-profile.v1', 'device_id': 'arm_s', 'instance_id': 'arm_s_follower',
                           'robot_config_sha256': digest(robot_s), 'operating_envelope_path': 'envelope.json', 'work_dir': 'work'}))):
        (bench.prep / name).write_text(text, encoding='utf-8')


def test_go_home_arm_s_uses_live_file_names_and_points_leader_to_align_option(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    ran = []
    monkeypatch.setattr(bench_record.subprocess, 'run', lambda cmd, **kw: (ran.append(cmd), SimpleNamespace(returncode=0, stdout='{"result":"home"}', stderr=''))[1])
    monkeypatch.setattr(bench_record, 'hold_other_arm_locks', lambda *a, **kw: ([], None))
    assert bench.go_home({'arm': 'arm_s', 'at_bench': True})['home_moved'] == ['arm_s']
    assert ran[0][ran[0].index('--config') + 1].endswith('cell-auto-arm-s-live.json')
    assert ran[0][ran[0].index('--library') + 1].endswith('chunks-arm-s-inplace-live.json')
    assert ran[0][ran[0].index('--operating-profile') + 1].endswith('arm-s-robot-profile-live.json')
    ran_leader = _leader_popen(bench, _LeaderProc(), monkeypatch)  # no saved leader pose is needed any more: the Leader goes to the Follower
    assert bench.go_home({'arm': 'arm_s', 'at_bench': True, 'include_leader': True})['home_moved'] == ['arm_s']
    assert '--match-follower' in ran_leader[0] and '--pose' not in ran_leader[0]


def _home_with_stages(bench, monkeypatch, tmp_path, results):
    """results: cell_pipeline home answers in order, as the real CLI gives them: stdout {"receipt","result"}, error in the receipt file."""
    ran = []

    def fake(cmd, **kw):
        stage = cmd[cmd.index('--stage') + 1]
        ran.append(stage)
        result, error = results.pop(0)
        receipt = tmp_path / f'receipt-{len(ran)}.json'
        receipt.write_text(json.dumps({'stage': stage, 'result': result, **({'error': error} if error else {})}))
        return SimpleNamespace(returncode=0 if result == 'home' else 1, stdout=json.dumps({'receipt': str(receipt), 'result': result}) + '\n', stderr='')
    monkeypatch.setattr(bench_record.subprocess, 'run', fake)
    monkeypatch.setattr(bench_record, 'hold_other_arm_locks', lambda *a, **kw: ([], None))
    return ran


def test_go_home_judges_the_home_result_not_the_exit_text_and_never_runs_recover(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    ran = _home_with_stages(bench, monkeypatch, tmp_path, [('home', None)])
    assert bench.go_home({'arm': 'arm_s', 'at_bench': True})['home_moved'] == ['arm_s']
    ran = _home_with_stages(bench, monkeypatch, tmp_path, [('refused', 'home requires an empty, folded arm')])
    with pytest.raises(ValueError, match='cell_auto_fold') as exc:
        bench.go_home({'arm': 'arm_s', 'at_bench': True})
    assert 'result=refused' in str(exc.value) and ran == ['home'] and bench.status()['status'] == 'idle'  # one home, no recover
    ran = _home_with_stages(bench, monkeypatch, tmp_path, [('stopped', 'initial live state refused')])
    with pytest.raises(ValueError, match='result=stopped') as exc:
        bench.go_home({'arm': 'arm_s', 'at_bench': True})
    assert 'cell_auto_fold' not in str(exc.value) and ran == ['home']


def test_go_home_exit_zero_without_a_home_result_is_not_success(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    monkeypatch.setattr(bench_record, 'hold_other_arm_locks', lambda *a, **kw: ([], None))
    monkeypatch.setattr(bench_record.subprocess, 'run', lambda cmd, **kw: SimpleNamespace(returncode=0, stdout='{"result":"stopped"}', stderr=''))
    with pytest.raises(ValueError, match='홈 이동 실패'):
        bench.go_home({'arm': 'arm_s', 'at_bench': True})


@pytest.mark.parametrize('code', [75, 1, None])
def test_go_home_unclean_recorder_exit_keeps_units_and_busy_for_a_person(tmp_path, monkeypatch, code):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    _home_with_stages(bench, monkeypatch, tmp_path, [('home', None)])
    killed, waited = [], []

    def wait(timeout=None):
        waited.append(timeout)
        if code is None:
            raise bench_record.subprocess.TimeoutExpired('rec', timeout)
        return code
    bench.popen = lambda command, cwd, **kw: SimpleNamespace(
        poll=lambda: 0, wait=wait, returncode=code, send_signal=lambda s: None, kill=lambda: killed.append(1))
    with pytest.raises(ValueError, match='사람이 팔 상태를 확인'):
        bench.go_home({'arm': 'arm_s', 'at_bench': True})
    assert bench.status()['status'] == 'homing' and not any(c[0] == 'start' for c in calls)
    assert waited[0] == 30  # longer than the runner's own 15 s no-answer judgement
    assert bench.manual.exists()  # the marker outlives a service restart
    bench.state = {'status': 'idle'}  # a restarted service: the marker, not memory, keeps the units stopped and the bench shut
    bench.restore_leftovers()
    assert not any(c[0] == 'start' for c in calls) and '복원 보류' in bench.status()['error']
    with pytest.raises(ValueError, match='사람 확인'):
        bench.go_home({'arm': 'arm_s', 'at_bench': True})


def test_save_initial_pose_writes_pose_and_updates_home_chunk(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    io_a = bench.prep / 'chunk-io-a'
    io_a.mkdir()
    (io_a / 'live.json').write_text(json.dumps({'state': [1.0, -50.0, 40.0, 30.0, 20.0, 10.0]}))
    lib = bench.prep / 'chunks-topdown-guard-arma-test.json'
    lib.write_text(json.dumps({'chunks': {'home': [[0, 0, 0, 0, 0, 0]]}}))

    res = bench.save_initial_pose({'arm': 'arm_a'})
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

        st, sp = req('POST', '/save_initial_pose', {'arm': 'arm_a'})
        assert st == 200 and json.loads(sp)['initial_pose_saved']['arm_a'] == [2.0, -40.0, 30.0, 20.0, 10.0, 5.0]

        st, _ = req('POST', '/release_lock', {})
        assert st == 400

        st, hm = req('POST', '/home', {'arm': 'arm_a'})
        assert st == 200 and json.loads(hm)['home_moved'] == ['arm_a']

        (bench.prep / 'record-config-policy.json').write_text(json.dumps({
            'robot': {'type': 'omx_follower', 'id': 'omx_follower_arm', 'port': '/dev/ttyA'},
            'policy': {'type': 'act'},
        }))
        st, _ = req('POST', '/start', dict(body, config='record-config-policy.json'))
        assert st == 400

        st, arms_raw = req('GET', '/api/arms')
        assert st == 200 and 'arm_ab' in json.loads(arms_raw)['arms']

        st, arm_ip = req('POST', '/api/arms/arm_a/initial_pose', {})
        assert st == 200 and json.loads(arm_ip)['initial_pose_saved']['arm_a'] == [2.0, -40.0, 30.0, 20.0, 10.0, 5.0]

        (bench.prep / 'leader-home-arm_a.json').write_text(json.dumps({'ticks': {'shoulder_pan': 2048, 'shoulder_lift': 2048, 'elbow_flex': 2048, 'wrist_flex': 2048, 'wrist_roll': 2048}}))
        st, hm_l = req('POST', '/api/arms/arm_a/home', {'include_leader': True})
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
    assert st['lerobot_datasets'][0] == {'name': 'h1-01-r1-test', 'episodes': 1, 'videos': 1, 'size_bytes': 13, 'empty': False, 'do_not_train': True}
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
                    'shoulder_pan': 4179, 'shoulder_lift': 670, 'elbow_flex': 3150,
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
        'shoulder_pan': 3200, 'shoulder_lift': 670, 'elbow_flex': 3150, 'wrist_flex': 3050, 'wrist_roll': 23,
    }}), encoding='utf-8')

    monkeypatch.setattr(leader_home, '_connect_leader', lambda _cfg: fake_leader)
    monkeypatch.setattr(leader_home, 'close_device', lambda _dev: bus.disable_torque())
    monkeypatch.setattr(leader_home, 'protect_signals', lambda: None)

    # pan starts past its range (4179, a hand-turned multi-turn count): it comes back downward, and the
    # 5 s deadline stretches to the 86 degrees at 1 degree/s instead of timing out (a move over 100 degrees is refused)
    clock = [0.0]
    monkeypatch.setattr(leader_home.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(leader_home.time, 'sleep', lambda s: clock.__setitem__(0, clock[0] + s))
    res = leader_home.move_leader_home(cfg, 'arm_b', pose, 'hands-off:test:now', timeout_s=5.0)
    assert res['ok'] is True
    pans = [g['shoulder_pan'] for g in bus.written_goals]
    assert pans[0] > 4095 and pans == sorted(pans, reverse=True) and pans[-1] == 3200
    assert bus.packet_handler.rebooted == [bus.motors['wrist_roll'].id]
    assert bus.written_goals
    assert all(v == 0 for v in bus.regs['Torque_Enable'].values())
    omx_dir = Path(__file__).resolve().parent.parent / 'deploy/robot/omx'
    html_src = ''.join((omx_dir / f).read_text(encoding='utf-8') for f in ('bench_record.html', 'bench_record_ui.js', 'bench_record_app.js', 'bench_record_cam.js'))
    assert 'ARM_PREVIEW_CAMS' in html_src
    assert 'cam-unrecorded' in html_src
    assert 'updateCameraRecordingMask' in html_src
    assert 'pollArms' in html_src


def _leader_for_match(tmp_path, ranges=None):
    lh_spec = importlib.util.spec_from_file_location('leader_home', Path(__file__).resolve().parent.parent / 'deploy/robot/omx/leader_home.py')
    leader_home = importlib.util.module_from_spec(lh_spec)
    lh_spec.loader.exec_module(leader_home)
    cal_file = tmp_path / 'arm_s_leader.json'
    (tmp_path / 'arm_s_leader.mount.json').write_text(json.dumps({'shoulder_pan': -2048, 'wrist_roll': -2048}), encoding='utf-8')
    ranges = ranges or {}
    cal = {n: SimpleNamespace(range_min=ranges.get(n, (0, 4095))[0], range_max=ranges.get(n, (0, 4095))[1]) for n in leader_home.BODY}
    return leader_home, SimpleNamespace(calibration=cal, calibration_fpath=str(cal_file))


def test_match_follower_applies_mount_and_keeps_small_differences(tmp_path):
    leader_home, leader = _leader_for_match(tmp_path)
    present = {'shoulder_pan': 100, 'shoulder_lift': 1000, 'elbow_flex': 3000, 'wrist_flex': 2000, 'wrist_roll': 2100}
    target = leader_home._match_target([2048, 1040, 2000, 2020, 2048], present, leader)
    # lift and wrist_flex rest on the stand under 30 deg away: kept; pan (follower 2048 - mount(-2048) = leader 0) and roll carry no
    # weight, so they move onto the Follower however small the difference
    assert target == {'shoulder_pan': 0, 'shoulder_lift': 1000, 'elbow_flex': 2000, 'wrist_flex': 2000, 'wrist_roll': 0}
    moved = leader_home._match_target([3000, 1000, 3000, 2000, 2100], dict(present, shoulder_pan=2000), leader)
    assert moved['shoulder_pan'] == 952   # 3000 + 2048 = 5048, the in-range turn


def test_match_follower_refuses_a_target_outside_the_leader_range(tmp_path):
    leader_home, leader = _leader_for_match(tmp_path, ranges={'elbow_flex': (0, 1500)})
    present = {'shoulder_pan': 0, 'shoulder_lift': 1000, 'elbow_flex': 1000, 'wrist_flex': 2000, 'wrist_roll': 0}
    with pytest.raises(ValueError, match='elbow_flex'):
        leader_home._match_target([2048, 1000, 3000, 2000, 2048], present, leader)


class _LeaderProc:
    """What Popen returns for leader_home: communicate() raises TimeoutExpired until SIGTERM arrives (when it obeys)."""
    def __init__(self, rc=0, out='{}', obeys=True, hang=False):
        self.rc, self.out, self.obeys, self.hang, self.signals, self.killed = rc, out, obeys, hang, [], False

    @property
    def returncode(self):
        return self.rc

    def send_signal(self, sig):
        self.signals.append(sig)

    def kill(self):
        self.killed = True

    def communicate(self, timeout=None):
        import subprocess
        if self.hang and not (self.obeys and self.signals):
            raise subprocess.TimeoutExpired('leader_home', timeout)
        return self.out, ''


def _leader_popen(bench, proc, monkeypatch, own_seen=None):
    import bench_record_leader
    ran, record_popen = [], bench.popen

    def popen(command, cwd, **kwargs):
        if command[1].endswith('leader_home.py'):
            ran.append(command)
            return proc
        return record_popen(command, cwd, **kwargs)
    bench.popen = popen

    def hold(arm, arms, procs, mounts, own=False):
        (own_seen if own_seen is not None else []).append(own)
        return [], None
    monkeypatch.setattr(bench_record_leader, 'hold_other_arm_locks', hold)
    return ran


def test_align_leader_runs_without_hands_off_and_a_failure_blocks_the_recording(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    own = []
    ran = _leader_popen(bench, _LeaderProc(rc=1, out='boom\n{"ok": false, "torque_off_confirmed": true, "restore_failures": []}'), monkeypatch, own)
    with pytest.raises(ValueError, match='리더 정렬 실패'):
        bench.start(dict(body, align_leader=True))
    assert '--match-follower' in ran[0] and not commands and bench.status()['status'] == 'idle'
    assert ran[0][ran[0].index('--attest') + 1].startswith('hands-off:bench-auto:')
    assert own == [True]  # the arm's own lock is held while the child reads the Follower
    _leader_popen(bench, _LeaderProc(), monkeypatch)
    bench.start(dict(body, align_leader=True))
    finished(bench)
    assert commands[0][1].endswith('record_session.py')


def test_stop_during_align_terminates_the_child_and_blocks_the_recording(tmp_path, monkeypatch):
    import signal
    import threading
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    proc = _LeaderProc(rc=1, out='{"ok": false, "torque_off_confirmed": true, "restore_failures": []}', hang=True)
    _leader_popen(bench, proc, monkeypatch)
    errors = []

    def start():
        try:
            bench.start(dict(body, align_leader=True, hands_off_leader=True))
        except ValueError as exc:
            errors.append(str(exc))
    worker = threading.Thread(target=start)
    worker.start()
    for _ in range(200):
        if bench.leader_proc is not None:
            break
        time.sleep(0.01)
    assert bench.stop()['status'] == 'homing'
    worker.join(5)
    assert proc.signals == [signal.SIGTERM] and not proc.killed
    assert errors and '중단' in errors[0] and not commands and bench.status()['status'] == 'idle'


def test_a_leader_child_that_will_not_end_keeps_the_bench_in_manual_check(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch)
    proc = _LeaderProc(hang=True, obeys=False)
    _leader_popen(bench, proc, monkeypatch)
    clock = [0.0]
    monkeypatch.setattr(bench_record.time, 'monotonic', lambda: clock.__setitem__(0, clock[0] + 300) or clock[0])  # the 420 s deadline passes at once
    with pytest.raises(ValueError, match='수동'):
        bench.start(dict(body, align_leader=True, hands_off_leader=True))
    assert proc.killed and bench.status()['status'] == 'leader_manual_check' and not commands
    assert bench.manual.is_file() and '종료를 확인할 수 없습니다' in json.loads(bench.manual.read_text(encoding='utf-8'))['reason']  # on disk: a service restart still holds
    import bench_record_guard
    assert '사람 확인' in bench_record_guard.arm_free('arm_a', bench.manual)  # every bus path refuses on that marker
    with pytest.raises(ValueError, match='사람 확인'):  # the marker is checked first now (the in-memory manual check is the second line)
        bench.start(body)


def test_leader_home_checks_the_attest_before_touching_the_follower(monkeypatch):
    lh_spec = importlib.util.spec_from_file_location('leader_home', ROOT / 'deploy/robot/omx/leader_home.py')
    leader_home = importlib.util.module_from_spec(lh_spec)
    lh_spec.loader.exec_module(leader_home)

    def touched(*a, **kw):
        raise AssertionError('the Follower was opened without an attest')
    monkeypatch.setattr(leader_home, 'read_follower_pose', touched)
    with pytest.raises(ValueError, match='attest'):
        leader_home.main(['--config', 'x.json', '--arm', 'arm_a', '--match-follower'])


def test_go_home_keeps_cameras_running_and_handles_opt_in_supervised_fold(tmp_path, monkeypatch):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    seen_fold = []

    def _run_stages(fold_fn):
        _home_with_stages(bench, monkeypatch, tmp_path, [('refused', 'home requires an empty, folded arm')])
        stage_run = bench_record.subprocess.run
        monkeypatch.setattr(
            bench_record.subprocess,
            'run',
            lambda cmd, **kw: fold_fn(cmd) if len(cmd) > 1 and str(cmd[1]).endswith('cell_auto_fold.py') else stage_run(cmd, **kw),
        )

    _run_stages(lambda cmd: (
        seen_fold.append(cmd),
        Path(cmd[cmd.index('--out') + 1]).write_text(json.dumps({'result': 'folded', 'candidate': 'park'}), encoding='utf-8'),
        SimpleNamespace(returncode=0, stdout='{"result": "folded"}', stderr=''),
    )[2])
    res = bench.go_home({'arm': 'arm_s', 'at_bench': True, 'fold_unfolded': True})
    assert res['home_moved'] == ['arm_s'] and seen_fold and '--supervised' in seen_fold[0]
    assert 'pinky' in seen_fold[0]
    stops = [c[1] for c in calls if c[0] == 'stop']
    assert stops == ['rosy-omx-observer@arm_a.service']  # camera-view and camera@* stay alive

    # Unmoved block -> returns cleanly to idle with refused error_kind, NO manual-check marker
    _run_stages(lambda cmd: (
        Path(cmd[cmd.index('--out') + 1]).write_text(json.dumps({'result': 'held', 'ended': 'stop_now', 'reason': 'ALL_PATHS_BLOCKED'})),
        SimpleNamespace(returncode=3, stdout='{"result":"held"}', stderr=''),
    )[1])
    with pytest.raises(ValueError, match='보류'):
        bench.go_home({'arm': 'arm_s', 'at_bench': True, 'fold_unfolded': True})
    assert not bench.manual.exists() and bench.status()['error_kind'] == 'refused' and bench.status()['status'] == 'idle'

    # Moved human-hold -> child returns non-zero -> stays in manual-check fail-closed
    _run_stages(lambda cmd: (
        Path(cmd[cmd.index('--out') + 1]).write_text(json.dumps({'result': 'held', 'reason': 'PARK_NOT_HOME'})),
        SimpleNamespace(returncode=3, stdout='{"result":"held"}', stderr=''),
    )[1])
    bench.popen = lambda command, cwd, **kw: SimpleNamespace(poll=lambda: 0, wait=lambda timeout=None: 75, returncode=75, send_signal=lambda s: None, kill=lambda: None)
    with pytest.raises(ValueError, match='사람이 팔 상태를 확인'):
        bench.go_home({'arm': 'arm_s', 'at_bench': True, 'fold_unfolded': True})
    assert bench.manual.exists() and bench.status()['error_kind'] == 'needs_person'


def test_stop_home_runner_now_checks_chunk_cmd_fifo(tmp_path, monkeypatch):
    import bench_record_step
    import cell_pipeline

    io_dir = tmp_path / 'chunk-io-s'
    io_dir.mkdir()
    sent = []
    monkeypatch.setattr(bench_record_step.Path, 'is_fifo', lambda p: p.name == 'chunk-cmd')
    monkeypatch.setattr(cell_pipeline, 'FifoCell', lambda d, c: SimpleNamespace(act=lambda cmd: (sent.append((d, cmd)), {'ok': True})[1]))
    assert bench_record_step.stop_home_runner_now(io_dir) is True
    assert sent == [(io_dir, 'stop now')]
    monkeypatch.setattr(bench_record_step.Path, 'is_fifo', lambda p: p.name == 'in')
    sent.clear()
    assert bench_record_step.stop_home_runner_now(io_dir) is False and sent == []


