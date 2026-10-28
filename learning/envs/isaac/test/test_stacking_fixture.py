"""Mixed 30 mm cargo must fit the bin, and a pushed or held box is not stacked."""
import importlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fixture():
    assert importlib.util.find_spec('stacking_fixture'), 'two-arm stacking fixture is missing'
    return importlib.import_module('stacking_fixture')


def test_mixed_plan_tiles_the_27_cells_without_overlap():
    mod = fixture()
    occupied = set()
    plan = mod.stack_plan()
    assert {p['cells'] for p in plan} == {1, 2, 3}
    for item in plan:
        x, y, z = item['cell']
        cells = {(x + dx, y, z) for dx in range(item['cells'])}
        assert not occupied & cells
        assert all(0 <= v < 3 for c in cells for v in c)
        occupied |= cells
    assert len(occupied) == 27
    assert len(plan) == 15


def test_gripped_pushed_tilted_and_unsettled_boxes_do_not_count():
    mod = fixture()
    item = mod.stack_plan()[0]
    target = mod.target(item)
    sample = dict(position=target, orientation=[1., 0., 0., 0.], speed=0.,
                  finger_force=0., support_force=.1, lifted=True)
    assert mod.placed(item, **sample)
    for override in [dict(lifted=False), dict(finger_force=.1), dict(support_force=0.),
                     dict(speed=.1), dict(orientation=[.7071, .7071, 0., 0.]),
                     dict(position=[target[0]+.004, *target[1:]])]:
        assert not mod.placed(item, **dict(sample, **override))


def test_stacking_training_is_bounded_and_not_a_physics_success_claim():
    import run_catalog
    config = run_catalog.normalize('omx-stacking-rl', {'seed': 42})
    assert config['iterations'] == 32
    assert config['seed'] == 42
    assert config['num_envs'] == 1
    with pytest.raises(ValueError):
        run_catalog.normalize('omx-stacking-rl', {'seed': 42, 'iterations': 100000})
    import run_worker
    finished = []
    class Store:
        def get(self, run_id):
            return {'input': {'scenario_id': 'omx-stacking-rl'}, 'revision': 2, 'status': 'RUNNING'}
        def finish(self, run_id, revision, result, artifacts):
            finished.append(result)
    report = dict(training_verified=True, task_success=False, updates=32,
                  transitions=1024, evaluation_successes=0, evaluation_episodes=1)
    run_worker._finish(Store(), 'r', {'exit_code': 0, 'reason': 'process_exited'}, report, [], False)
    assert finished[0]['status'] == 'SUCCEEDED'
    assert finished[0]['training_verified'] is True
    assert finished[0]['task_success'] is False
    assert finished[0]['stage'] == 'stacking_rl'


def test_real_store_requires_training_artifacts_but_accepts_zero_task_successes(tmp_path):
    import hashlib
    import uuid
    from run_store import RunStore
    store = RunStore(tmp_path/'runs')
    row = store.create(uuid.uuid4().hex, 'omx-stacking-rl', {'seed': 42}, 'a'*40)
    row = store.update(row['run_id'], row['revision'], {'status': 'RUNNING'})
    result = dict(status='SUCCEEDED', stage='stacking_rl', training_verified=True, task_success=False,
                  updates=32, transitions=1024, evaluation_successes=0, evaluation_episodes=1,
                  cleanup='OWNED_PROCESSES_EXITED_GPU_RELEASED', coordinate_scope='SYNTHETIC_NOT_CAMERA_REGISTERED')
    with pytest.raises(ValueError, match='verified stacking'):
        store.finish(row['run_id'], row['revision'], result, [])
    artifacts = []
    for name in ('stacking-report.json', 'stacking-policy.pt', 'stacking-initial.png', 'stacking-evaluation.png'):
        raw = b'evidence'
        (tmp_path/'runs/runs'/row['run_id']/name).write_bytes(raw)
        artifacts.append(dict(id=Path(name).stem, name=name, bytes=len(raw),
                              sha256=hashlib.sha256(raw).hexdigest(), media_type='application/octet-stream'))
    done = store.finish(row['run_id'], row['revision'], result, artifacts)
    assert done['status'] == 'SUCCEEDED'
    assert done['result']['task_success'] is False


def test_long_cargo_rotated_outside_the_envelope_is_rejected():
    import math
    mod = fixture()
    item = mod.stack_plan()[0]
    angle = math.radians(2)
    assert not mod.placed(item, position=mod.target(item), orientation=[math.cos(angle/2), 0., 0., math.sin(angle/2)],
                          speed=0., finger_force=0., support_force=.1, lifted=True)


def test_training_report_checks_transport_and_checkpoint_without_loading_weights(tmp_path):
    import hashlib
    import json
    from stacking_fixture import FIXTURE
    from stacking_report import verify_report
    weights = b'opaque checkpoint: the verifier must never execute it'
    (tmp_path/'stacking-policy.pt').write_bytes(weights)
    joints = ['joint'+str(i) for i in range(1, 6)]+['gripper_joint_1', 'gripper_joint_2']
    report = dict(schema='rosy.omx-stacking-rl/1', fixture=FIXTURE, sdk_version='6.2.0.0', seed=42,
        updates=32, transitions=1024, parameter_delta=.1, training_verified=True, task_success=False,
        evaluation_seed=10042, evaluation_episodes=1, evaluation_successes=0, evaluation_steps=600,
        articulations=['/World/A', '/World/B'], joints=[joints, joints], attachment_aid=False,
        belt_displacement_m=[0., .018, 0.], checkpoint=dict(name='stacking-policy.pt', bytes=len(weights),
            sha256=hashlib.sha256(weights).hexdigest()), images=['stacking-initial.png', 'stacking-evaluation.png'])
    path = tmp_path/'report.json'
    path.write_text(json.dumps(report))
    assert verify_report(path, sdk_version='6.2.0.0', seed=42)['task_success'] is False
    for override in [dict(belt_displacement_m=[0., 0., 0.]), dict(parameter_delta=0.),
                     dict(task_success=True), dict(evaluation_seed=42)]:
        path.write_text(json.dumps(dict(report, **override)))
        with pytest.raises(ValueError):
            verify_report(path, sdk_version='6.2.0.0', seed=42)
    path.write_text(json.dumps(report))
    (tmp_path/'stacking-policy.pt').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='fingerprint'):
        verify_report(path, sdk_version='6.2.0.0', seed=42)


def test_joint_commands_accelerate_within_sim_profile_and_stop_at_position_limit():
    mod = fixture()
    limits = dict(position=[-.1, 1.1], velocity=.5, acceleration=.5)
    position, velocity = mod.advance_joint(0., 0., 100., limits, 1/30)
    assert velocity == pytest.approx(.5/30)
    assert position == pytest.approx(.5/900)
    for _ in range(300):
        previous_velocity = velocity
        position, velocity = mod.advance_joint(position, velocity, 100., limits, 1/30)
        assert -.1 <= position <= 1.1 and abs(velocity) <= .5
        assert abs(velocity-previous_velocity) <= .5/30+1e-12
    assert position == pytest.approx(1.1) and abs(velocity) < 1e-9
