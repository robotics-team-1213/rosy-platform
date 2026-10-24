"""A completed process or plausible final pose cannot prove contact transport."""
import importlib
from pathlib import Path
import sys

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


def observations():
    mod = implementation()
    rows = []
    for phase, support in [('pinky_initial', 2), ('out_lift', None), ('out_transport', None),
                           ('conveyor_settle', 3), ('back_lift', None), ('back_transport', None),
                           ('pinky_settle', 2)]:
        base = mod.CONVEYOR if phase == 'conveyor_settle' else mod.PINKY
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
    for broken in ('finger', 'support', 'retreat', 'drift', 'nan', 'clock', 'missing', 'tracking'):
        rows = observations()
        for row in rows:
            if broken == 'finger' and row['phase'] == 'back_lift': row['contact_forces'][1] = 0.
            if broken == 'support' and row['phase'] == 'conveyor_settle': row['contact_forces'][3] = 0.
            if broken == 'retreat' and row['phase'] == 'pinky_settle': row['tool_distance'] = 0.
            if broken == 'drift' and row['phase'] == 'pinky_settle': row['position'][0] += .05
            if broken == 'nan': row['position'][0] = float('nan')
            if broken == 'clock': row['tick'] = 0
            if broken == 'tracking': row['tcp_error'] = .05
        if broken == 'missing': rows = rows[:-31]
        assert mod.evaluate(rows)['task_success'] is False, broken
