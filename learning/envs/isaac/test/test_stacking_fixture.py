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
