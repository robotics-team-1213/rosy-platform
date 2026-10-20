"""Actual CPU ACT integration on synthetic fixtures; never object-task evidence."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/p) for p in ('learning/training/omx','learning/curation/omx',
    'middleware/devices/omx/adapter','middleware/devices/omx/adapter/test','contracts/foundation')]


def test_actual_act_keeps_all_five_validation_episodes_out_of_training(tmp_path):
    pytest.importorskip('torch')
    pytest.importorskip('lerobot')
    from omx_adapter.demonstration import DemonstrationRecorder
    from test_demonstration import provenance, sample
    from lerobot_export import export_episode
    from act_job import run
    exports,ids,training_actions=[],[],[]
    for index,base in enumerate([-.2,0.,.5,.6,.7,.8,.9]):
        recorder=DemonstrationRecorder(tmp_path/f'raw-{index}',provenance())
        episode=recorder.start('synthetic integration fixture')
        for frame in range(4):
            target={'joint1':base+.001*frame,'gripper_joint_1':-.1}
            sample(recorder,1_000_000_000+frame*100_000_000,target=target)
            if index<2:training_actions.append(list(target.values()))
        recorder.stop('success')
        source=tmp_path/f'raw-{index}'/episode['episode_id']
        export=tmp_path/f'export-{index}'
        assert export_episode(source,export,'rosy-local/omx-sim')['verified_frames']==4
        exports.append(export)
        ids.append(episode['episode_id'])
    out=tmp_path/'study'
    report=run(exports[:2],exports[2:],out,steps=1,n_action_steps=1)
    stats=json.loads((out/'normalization.json').read_text())
    assert stats['fit_episodes']==ids[:2]
    np.testing.assert_allclose(stats['action_mean'],np.mean(training_actions,axis=0),atol=1e-7)
    assert report['train_episodes']==ids[:2] and report['eval_episodes']==ids[2:]
    assert report['eval_frames']==20
    assert set(report['per_episode'])==set(ids[2:])
    assert all(row['eval_frames']==4 for row in report['per_episode'].values())
    assert report['reloaded_prediction_verified'] is True
    assert set(report['task_outcome_judges'].values())=={'operator'}
    assert json.loads((out/'state.json').read_text())['status']=='research_exported'
