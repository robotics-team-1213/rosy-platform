"""Actual CPU ACT integration on synthetic fixtures; never object-task evidence."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/p) for p in ('learning/training/omx','learning/curation/omx',
    'middleware/devices/omx/adapter','middleware/devices/omx/adapter/test','contracts/foundation')]


@pytest.mark.parametrize('representation,queue_steps', [('absolute',1),('joint_delta_from_chunk_source_v1',2)])
def test_actual_act_keeps_all_five_validation_episodes_out_of_training(tmp_path,monkeypatch,representation,queue_steps):
    torch=pytest.importorskip('torch')
    pytest.importorskip('lerobot')
    from omx_adapter.demonstration import DemonstrationRecorder
    from test_demonstration import provenance, sample
    from lerobot_export import export_episode
    from act_job import run
    exports,ids,training_actions,training_states=[],[],[],[]
    for index,base in enumerate([-.2,0.,.5,.6,.7,.8,.9]):
        recorder=DemonstrationRecorder(tmp_path/f'raw-{index}',provenance())
        episode=recorder.start('synthetic integration fixture')
        for frame in range(4):
            target={'joint1':base+.001*frame,'gripper_joint_1':-.1}
            state={'joint1':.01+.02*frame,'gripper_joint_1':-.1}
            sample(recorder,1_000_000_000+frame*100_000_000,target=target,positions=state)
            if index<2:
                training_actions.append(list(target.values()));training_states.append(list(state.values()))
        recorder.stop('success')
        source=tmp_path/f'raw-{index}'/episode['episode_id']
        export=tmp_path/f'export-{index}'
        assert export_episode(source,export,'rosy-local/omx-sim')['verified_frames']==4
        exports.append(export)
        ids.append(episode['episode_id'])
    out=tmp_path/'study'
    from lerobot.policies.act.modeling_act import ACTPolicy
    original=ACTPolicy.forward
    checked=[]
    def check_chunk_origin(model,batch,*args,**kwargs):
        if representation!='absolute':
            stats=json.loads((out/'normalization.json').read_text());t=stats['action_transform']
            origin=batch['observation.state']*torch.tensor(stats['state_std'])+torch.tensor(stats['state_mean'])
            restored=batch['action']*torch.tensor(t['std'])+torch.tensor(t['mean'])+origin[:,None,:]
            gaps=restored[:,1:,0]-restored[:,:-1,0]
            assert torch.all(torch.isclose(gaps,torch.zeros_like(gaps),atol=1e-6)|
                             torch.isclose(gaps,torch.full_like(gaps,.001),atol=1e-6))
            checked.append(True)
        return original(model,batch,*args,**kwargs)
    monkeypatch.setattr(ACTPolicy,'forward',check_chunk_origin)
    report=run(exports[:2],exports[2:],out,steps=1,n_action_steps=queue_steps,action_representation=representation)
    stats=json.loads((out/'normalization.json').read_text())
    assert stats['fit_episodes']==ids[:2]
    if representation=='absolute':
        np.testing.assert_allclose(stats['action_mean'],np.mean(training_actions,axis=0),atol=1e-7)
    else:
        assert checked and 'action_mean' not in stats and 'action_std' not in stats
        np.testing.assert_allclose(stats['action_transform']['mean'],
            np.mean(np.asarray(training_actions)-np.asarray(training_states),axis=0),atol=1e-7)
        np.testing.assert_allclose(stats['action_transform']['absolute_baseline'],np.mean(training_actions,axis=0),atol=1e-7)
    assert report['train_episodes']==ids[:2] and report['eval_episodes']==ids[2:]
    assert report['eval_frames']==20
    assert set(report['per_episode'])==set(ids[2:])
    assert all(row['eval_frames']==4 for row in report['per_episode'].values())
    assert report['reloaded_prediction_verified'] is True
    # Keep the measured backbone rate when constructing the real optimizer.
    optimizer = report['optimizer']
    assert [group['lr'] for group in optimizer['parameter_groups']] == [1e-4, 1e-5]
    config = json.loads((out/'policy/config.json').read_text())
    assert config['optimizer_lr'] == 1e-4
    assert config['optimizer_lr_backbone'] == 1e-5
    assert set(report['task_outcome_judges'].values())=={'operator'}
    assert json.loads((out/'state.json').read_text())['status']=='research_exported'
    from act_inference_replay import replay
    policy=json.loads((out/'policy-artifact.json').read_text())
    replayed=replay(out,out/'reader-inputs'/ids[2],tmp_path/'replay',policy['revision'],paced=False)
    assert replayed['original_metrics_reproduced'] is True
    assert replayed['queued_candidates']==(0 if queue_steps==1 else 2)
