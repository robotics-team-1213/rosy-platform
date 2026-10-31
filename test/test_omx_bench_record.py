"""D-943 §3: the bench page hands the bus over, runs record_session unchanged, restores, then seals."""
import importlib.util
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('bench_record', ROOT / 'deploy/robot/omx/bench_record.py')
bench_record = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench_record)
UNITS = ['rosy-omx-observer@arm_a.service', 'rosy-omx-camera@top.service', 'rosy-omx-observation-bridge.service',
         'rosy-omx-camera-view.service', 'rosy-omx-arm-status.service']


def setup(tmp_path, monkeypatch, *, safe=True, record=None):
    prep = tmp_path / 'prep'
    (prep / 'tasks').mkdir(parents=True)
    for name in ('record-config.json', 'caps.json', 'tasks/teach.yaml'):
        (prep / name).write_text('{}')
    calibration = tmp_path / 'home/.cache/huggingface/lerobot/calibration/robots/omx_follower'
    calibration.mkdir(parents=True)
    (calibration / 'arm_a_follower.json').write_text('{}')
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
    bench = bench_record.Bench({'python': '/py', 'prep_root': str(prep)}, run=run, popen=popen)
    body = dict(name='teach-one', rig_revision='bench-r1', config='record-config.json', caps='caps.json',
                task='tasks/teach.yaml', calibrations=[str(calibration / 'arm_a_follower.json')], at_bench=True)
    return bench, body, calls, commands


def finished(bench):
    for _ in range(200):
        if bench.status()['status'] not in ('handing_over', 'recording', 'restoring', 'sealing'):
            return bench.status()
        time.sleep(0.01)
    raise AssertionError('bench session did not finish')


def test_safe_session_hands_over_restores_in_reverse_and_seals(tmp_path, monkeypatch):
    bench, body, calls, commands = setup(tmp_path, monkeypatch)
    bench.start(body)
    state = finished(bench)
    stops = [c[1] for c in calls if c[0] == 'stop']
    starts = [c[1] for c in calls if c[0] == 'start']
    # bridge and arm status read topics only and stay up; camera-view goes before the cameras, observers last
    assert stops == ['rosy-omx-camera-view.service', 'rosy-omx-camera@top.service', 'rosy-omx-observer@arm_a.service']
    assert starts == list(reversed(stops))
    assert commands[0][1].endswith('record_session.py') and '--task-card' in commands[0]
    assert commands[1][1].endswith('record_seal.py') and commands[1][commands[1].index('--calibration') + 1].endswith('arm_a_follower.json')
    assert state['status'] == 'sealed'


def test_unsafe_end_is_restored_but_never_sealed(tmp_path, monkeypatch):
    bench, body, calls, commands = setup(tmp_path, monkeypatch, safe=False)
    bench.start(body)
    state = finished(bench)
    assert state['status'] == 'unsafe_or_failed' and len(commands) == 1
    assert len([c for c in calls if c[0] == 'start']) == 3


@pytest.mark.parametrize('change', [{'at_bench': False}, {'config': '../etc/passwd'}, {'calibrations': ['/tmp/x.json']},
                                    {'name': 'Bad Name'}])
def test_start_refuses_without_presence_or_with_unlisted_inputs(tmp_path, monkeypatch, change):
    bench, body, calls, commands = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        bench.start(dict(body, **change))
    assert not calls and not commands


def test_stopped_recording_is_restored_and_left_unsealed(tmp_path, monkeypatch):
    # record_session marks a Stop as interrupted; record_seal would refuse it.
    bench, body, calls, commands = setup(tmp_path, monkeypatch, record={'safe_end': True, 'interrupted': True})
    bench.start(body)
    assert finished(bench)['status'] == 'stopped_not_sealed' and len(commands) == 1
    assert not bench.pending.exists()


def test_stop_during_handover_never_launches_the_recorder(tmp_path, monkeypatch):
    bench, body, calls, commands = setup(tmp_path, monkeypatch)
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
    bench, body, calls, commands = setup(tmp_path, monkeypatch)
    bench.pending.write_text(json.dumps(['rosy-omx-camera@top.service', 'rosy-omx-observer@arm_a.service']))
    bench.restore_leftovers()
    assert [c for c in calls if c[0] == 'start'] == [('start', 'rosy-omx-observer@arm_a.service'),
                                                    ('start', 'rosy-omx-camera@top.service')]
    assert not bench.pending.exists()


@pytest.mark.parametrize('body', [[], {'name': 5}])
def test_malformed_bodies_are_refused(tmp_path, monkeypatch, body):
    bench, _, calls, commands = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        bench.start(body)
