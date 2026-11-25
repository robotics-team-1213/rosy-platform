import importlib.util
import json
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'sim'))
import world_s3_pickup_train as pickup


def test_conditions_guard_and_bounded_correction():
    training = [pickup.make_condition(i, 'train') for i in range(3)]
    evaluation = [pickup.make_condition(i, 'evaluation') for i in range(6)]
    assert set(x.seed for x in training).isdisjoint(x.seed for x in evaluation)
    assert {x.stratum for x in evaluation} == {'nominal', 'overhang', 'wrong-yaw'}
    assert all(pickup.allowed(x) == (x.stratum == 'nominal') for x in evaluation)
    assert pickup.bounded((9, -9, 1)) == (0.012, -0.012, 0.15)
    with pytest.raises(ValueError):
        pickup.bounded((0, 0, float('nan')))


@pytest.mark.skipif(importlib.util.find_spec('mujoco') is None, reason='MuJoCo SDK unavailable')
def test_replay_uses_run_scene_and_paired_physics(tmp_path):
    out = tmp_path / 'run'
    report = pickup.run(out, trials=1)
    assert report['registration'] == 'unregistered-arm-local-proxy'
    assert report['scene_sha256'] == json.loads((out / 'checkpoint.json').read_text())['scene_sha256']
    assert report['policies']['ik']['episodes'] == report['policies']['learned']['episodes'] == 6
    assert report['policies']['ik']['safe_refusals'] == report['policies']['learned']['safe_refusals'] == 4
    for pair in report['pairs']:
        base, learned = pair['ik'], pair['learned']
        assert base['condition'] == learned['condition']
        for result in (base, learned):
            replay = json.loads((out / result['replay']).read_text())
            assert replay['run_id'] == report['run_id']
            assert replay['scene_sha256'] == report['scene_sha256']
            assert replay['condition'] == result['condition']
            assert replay['frames'][0]['sim_time_s'] == 0
            assert len(replay['frames'][0]['tcp_m']) == 3
            if result['condition']['stratum'] == 'nominal':
                assert replay['frames'][-1]['sim_time_s'] > 0
                assert len(replay['frames'][-1]['box_pose_m_wxyz']) == 7
            else:
                assert not result['attempted'] and result['placement_error_m'] is None
                assert len(replay['frames']) == 1
