"""World run tests do not require a real systemd user manager or trainer."""
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import experiment_world as world


def test_preset_pins_reviewed_sim_identity_and_limits():
    preset = dict(dataset_id=str(uuid.uuid4()), dataset_revision='a' * 64,
                  scene_sha256='b' * 64, dataset_origin='mujoco',
                  steps=4, batch_size=2, seed=0)
    assert world.parse_preset(preset, 'model') == preset
    with pytest.raises(ValueError):
        world.parse_preset(preset, 'ai')
    with pytest.raises(ValueError):
        world.parse_preset(dict(preset, dataset_origin='isaac'), 'model')
    with pytest.raises(ValueError):
        world.parse_preset(dict(preset, steps=1001), 'model')
    with pytest.raises(ValueError):
        world.check_dataset(preset, 'reviewed_demonstration', 'a' * 64)
    with pytest.raises(ValueError):
        world.check_dataset(preset, 'scripted_teacher', 'c' * 64)


def test_stop_has_persistent_intent_and_waits_for_children(tmp_path, monkeypatch):
    rid = str(uuid.uuid4())
    unit = world.Unit(rid)
    runtime = tmp_path / 'runtime'
    cgroup = runtime / 'app.slice' / unit.name
    cgroup.mkdir(parents=True)
    events = cgroup / 'cgroup.events'
    events.write_text('populated 1\nfrozen 0\n')
    monkeypatch.setattr(world, 'CGROUP_ROOT', runtime)
    requests = []

    def systemctl(*args):
        requests.append(args)
        return subprocess.CompletedProcess(args, 0, '\n'.join((
            'LoadState=loaded', f'Description={unit.description}',
            f'ControlGroup=/app.slice/{unit.name}', 'InvocationID=' + 'a' * 32,
            'ActiveState=active', 'SubState=running', 'Result=success')))

    monkeypatch.setattr(world, '_systemctl', systemctl)
    row = dict(id=rid, status='stopping', created_at=0, steps=4)
    receipt = dict(invocation_id='a' * 32, cgroup=f'/app.slice/{unit.name}')
    output = tmp_path / 'output'
    output.mkdir()
    world.refresh(row, receipt, output)
    assert row['status'] == 'stopping'
    assert any(command[0] == 'stop' for command in requests)
    events.write_text('populated 0\nfrozen 0\n')
    world.refresh(row, receipt, output)
    assert row['status'] == 'stopping'  # empty group with active unit is still stopping
    monkeypatch.setattr(world, '_systemctl', lambda *args: subprocess.CompletedProcess(
        args, 1, 'LoadState=not-found\nActiveState=inactive\n'))
    world.refresh(row, receipt, output)
    assert row['status'] == 'cancelled'


def test_replaced_unit_is_not_stopped(tmp_path, monkeypatch):
    rid = str(uuid.uuid4())
    unit = world.Unit(rid)
    requests = []

    def systemctl(*args):
        requests.append(args)
        return subprocess.CompletedProcess(args, 0, '\n'.join((
            'LoadState=loaded', f'Description={unit.description}',
            f'ControlGroup=/app.slice/{unit.name}', 'InvocationID=' + 'f' * 32,
            'ActiveState=active', 'SubState=running', 'Result=success')))

    monkeypatch.setattr(world, '_systemctl', systemctl)
    row = dict(id=rid, status='stopping', created_at=0, steps=4)
    receipt = dict(invocation_id='a' * 32, cgroup=f'/app.slice/{unit.name}')
    world.refresh(row, receipt, tmp_path)
    assert row['status'] == 'stopping'
    assert row['status_uncertain'] is True
    assert requests[0][0] == 'show' and len(requests) == 1


def test_center_run_retry_shared_slot_and_stop_restart(tmp_path, monkeypatch):
    from experiment_io import read_json
    from experiment_dataset import load_dataset
    from test_experiment_center import center
    from test_experiment_dataset import dataset, save

    owner = center(tmp_path, monkeypatch)
    did = str(uuid.uuid4())
    dataset_root = owner.root / 'datasets' / did
    dataset_root.mkdir()
    document = dataset(dataset_root)
    save(dataset_root, dict(document, source='scripted_teacher'))
    revision = load_dataset(dataset_root).revision
    preset = dict(dataset_id=did, dataset_revision=revision, scene_sha256='c' * 64,
                  dataset_origin='mujoco', steps=4, batch_size=2, seed=0)
    owner.world_preset = world.parse_preset(preset, 'model')
    owner.methods['act']['available'] = True
    with owner.connect() as db:
        db.execute('INSERT INTO datasets VALUES (?,?)', (did, json.dumps({'revision': revision})))
    launched, stopped = [], []

    def launch(unit, python, root):
        request = read_json(root / 'request.json')
        assert request['expected_dataset_revision'] == revision
        assert request['method'] == 'act' and request['device'] == 'cpu'
        launched.append(unit.name)

    def observe(unit, receipt):
        receipt['invocation_id'] = 'a' * 32
        return ('gone', True) if unit.name in stopped else ('running', False)

    monkeypatch.setattr(world, 'check_resources', lambda *args: None)
    monkeypatch.setattr(world.Unit, 'launch', launch)
    monkeypatch.setattr(world.Unit, 'observe', observe)
    monkeypatch.setattr(world.Unit, 'stop', lambda unit: stopped.append(unit.name))
    body = dict(preset_id=world.PRESET_ID, request_id=str(uuid.uuid4()))
    monkeypatch.setattr(owner.canonical, 'has_active_runs', lambda: True)
    with pytest.raises(ValueError, match='Canonical'):
        owner.start_world_experiment(body)
    monkeypatch.setattr(owner.canonical, 'has_active_runs', lambda: False)
    first = owner.start_world_experiment(body)
    assert first['status'] == 'running'
    assert first['dataset_revision'] == revision and first['scene_sha256'] == 'c' * 64
    assert owner.start_world_experiment(body)['id'] == first['id']
    assert len(launched) == 1
    assert owner.snapshot()['runs'] == []
    with pytest.raises(ValueError, match='stay in the experiment'):
        owner.artifact(first['id'])
    with pytest.raises(ValueError, match='one owned'):
        owner.start_world_experiment(dict(body, request_id=str(uuid.uuid4())))
    with pytest.raises(PermissionError):
        owner.stop({'id': first['id']})
    with owner._canonical_admission() as busy:
        assert busy is True
    assert owner.stop_world_experiment({'id': first['id']})['status'] == 'stopping'
    monkeypatch.setattr(world, 'start_supervisor', lambda *args: None)
    reopened = center(tmp_path, monkeypatch)
    assert reopened.world_experiment()['runs'][0]['status'] == 'cancelled'
    assert reopened.start_world_experiment(body)['id'] == first['id']
    assert stopped == launched


def test_result_checkpoint_hash_must_match_actual_weights(tmp_path):
    (tmp_path / 'policy').mkdir()
    (tmp_path / 'policy/model.safetensors').write_bytes(b'learned weights')
    result = dict(method='act', execution_mode='offline_replay', source='scripted_teacher',
                  physical_learning_verified=False, policy_activation=False,
                  dataset_revision='a' * 64, optimizer_steps=4, policy_sha256='c' * 64)
    path = tmp_path / 'result.json'
    path.write_text(json.dumps(result))
    row = {'dataset_revision': 'a' * 64, 'steps': 4}
    world._finish(row, tmp_path)
    assert row['status'] == 'failed'
    result['policy_sha256'] = hashlib.sha256(b'learned weights').hexdigest()
    path.write_text(json.dumps(result))
    world._finish(row, tmp_path)
    assert row['status'] == 'succeeded'
    assert row['result'] == result
