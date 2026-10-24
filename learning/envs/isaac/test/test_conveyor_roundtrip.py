"""A completed process or plausible final pose cannot prove contact transport."""
import importlib
import hashlib
import json
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))


def implementation():
    assert (Path(__file__).parents[1] / 'conveyor_fixture.py').is_file(), 'Stationary roundtrip fixture is missing'
    return importlib.import_module('conveyor_fixture')


def test_only_fixed_stationary_fixture_is_accepted():
    import run_catalog
    config = run_catalog.normalize('pinky-conveyor-roundtrip', {'seed': 0})
    assert config['fixture'] == 'stationary-proxy-v1'
    assert config['frames'] == 4800
    for extra in ({'belt_speed': 1}, {'path': '/tmp/task'}, {'frames': 0}):
        with pytest.raises(ValueError):
            run_catalog.normalize('pinky-conveyor-roundtrip', dict(seed=0, **extra))


def test_reachable_targets_have_small_fk_error_and_unreachable_fails():
    mod = implementation()
    for pose in (mod.PINKY, mod.CONVEYOR):
        for dz in (0., .08):
            target = [pose[0], pose[1], pose[2] + mod.CARGO_SIZE / 2 + dz]
            q = mod.solve(target)
            assert max(abs(a-b) for a, b in zip(mod.forward(q), target)) < 1e-8
            assert all(abs(v) <= 6.283185307179586 for v in q)
    with pytest.raises(ValueError):
        mod.solve([2., 0., 0.])


def test_measured_roll_is_included_in_fk_even_when_commanded_roll_is_zero():
    import math
    assert implementation().forward([0., 0., 0., math.pi/2, math.pi/2]) == pytest.approx([.19065, 0., .09002])


def observations():
    mod = implementation()
    rows = []
    for phase, support in [('pinky_initial', 2), ('out_raise', None), ('out_lift', None), ('out_move', None), ('out_transport', None),
                           ('out_lower', None), ('conveyor_settle', 3), ('back_raise', None), ('back_lift', None), ('back_move', None), ('back_transport', None),
                           ('back_lower', None),
                           ('pinky_settle', 2)]:
        base = mod.CONVEYOR if phase in ('conveyor_settle', 'out_move', 'out_transport', 'out_lower', 'back_raise', 'back_lift') else mod.PINKY
        for step in range(0, 124, 4):
            forces = [0., 0., 0., 0.]
            if support is None:
                forces[:2] = [.3, .3]
            else:
                forces[support] = .49
            rows.append(dict(tick=len(rows)*4, phase=phase,
                position=[base[0], base[1], base[2]+mod.CARGO_SIZE/2+(.08 if support is None else 0)],
                orientation=[1., 0., 0., 0.], linear_velocity=[0., 0., 0.], angular_velocity=[0., 0., 0.],
                contact_forces=forces, tool_distance=.08 if support is not None else 0.,
                joint_error=0., tcp_error=0.))
    return rows


def test_two_contact_lifts_and_unassisted_settles_are_required():
    mod = implementation()
    assert mod.evaluate(observations())['task_success'] is True
    for broken in ('finger', 'support', 'retreat', 'drift', 'nan', 'clock', 'missing', 'tracking', 'dropped', 'no_transport'):
        rows = observations()
        for row in rows:
            if broken == 'finger' and row['phase'] == 'back_lift': row['contact_forces'][1] = 0.
            if broken == 'support' and row['phase'] == 'conveyor_settle': row['contact_forces'][3] = 0.
            if broken == 'retreat' and row['phase'] == 'pinky_settle': row['tool_distance'] = 0.
            if broken == 'drift' and row['phase'] == 'pinky_settle': row['position'][0] += .05
            if broken == 'nan': row['position'][0] = float('nan')
            if broken == 'clock': row['tick'] = 0
            if broken == 'tracking': row['tcp_error'] = .05
            if broken == 'dropped' and row['phase'] == 'out_move': row['contact_forces'][1] = 0.
            if broken == 'no_transport' and row['phase'] == 'out_transport': row['position'][:2] = list(implementation().PINKY[:2])
        if broken == 'missing': rows = rows[:-31]
        assert mod.evaluate(rows)['task_success'] is False, broken


def test_contact_worker_finalizes_its_scenario_and_keeps_failed_evidence(tmp_path):
    import run_store
    import run_worker
    for passed in (True, False):
        store = run_store.RunStore(tmp_path/str(passed))
        row = store.create(uuid.uuid4().hex, 'pinky-conveyor-roundtrip', {'seed': 0}, 'a'*40)
        row = store.update(row['run_id'], 0, {'status': 'RUNNING'})
        report = dict(completed_frames=4000, task_success=passed,
                      judgement=dict(evidence_class='PHYSICS_GRASP' if passed else 'INCOMPLETE_CONTACT_TASK', failures=[] if passed else ['slip']))
        artifacts = []
        for name in ['contact-report.json', 'pinky_initial.png', 'out_lift.png', 'conveyor_settle.png', 'back_lift.png', 'pinky_settle.png']:
            raw = json.dumps(report).encode() if name.endswith('.json') else b'\x89PNG\r\n\x1a\nfixture'
            (store.root/'runs'/row['run_id']/name).write_bytes(raw)
            artifacts.append(dict(id=Path(name).stem, name=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                                  media_type='application/json' if name.endswith('.json') else 'image/png'))
        run_worker._finish(store, row['run_id'], dict(exit_code=0, reason='process_exited'), report, artifacts, False)
        final = store.get(row['run_id'])
        assert final['status'] == ('SUCCEEDED' if passed else 'FAILED')
        assert final['result']['task_success'] is passed
        assert store.artifact(row['run_id'], 'contact-report')['bytes'] > 0


def test_rendering_never_advances_the_control_step():
    from conveyor_task import physics_step
    class World:
        physics = 0
        renders = 0
        def step(self, *, render, update_fabric):
            assert render is False and update_fabric is True
            self.physics += 1
        def render(self):
            self.renders += 1
    world = World()
    for tick in range(24):
        physics_step(world, tick)
    assert world.physics == 24 and world.renders == 2
