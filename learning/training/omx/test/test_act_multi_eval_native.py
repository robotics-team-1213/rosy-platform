"""Actual CPU ACT integration on synthetic fixtures; never object-task evidence."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/p) for p in ('learning/training/omx','learning/curation/omx',
    'middleware/devices/omx/adapter','middleware/devices/omx/adapter/test','contracts/foundation')]


@pytest.mark.parametrize('representation,queue_steps,noise', [('absolute',1,0.),
    ('joint_delta_from_chunk_source_v1',2,0.),('joint_delta_from_chunk_source_v1',1,.02),
    ('joint_delta_tanh_from_chunk_source_v1',1,.02),('joint_delta_tanh_from_chunk_source_v1',1,0.),
    ('absolute_tanh_from_chunk_source_v1',1,0.)])
def test_actual_act_keeps_all_five_validation_episodes_out_of_training(tmp_path,monkeypatch,representation,queue_steps,noise):
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
    initial=None
    if representation=='absolute_tanh_from_chunk_source_v1':
        initial=tmp_path/'parent'
        run(exports[:2],exports[2:],initial,steps=1,n_action_steps=queue_steps)
    from lerobot.policies.act.modeling_act import ACTPolicy
    original=ACTPolicy.forward
    checked=[]
    def check_chunk_origin(model,batch,*args,**kwargs):
        if representation!='absolute':
            stats=json.loads((out/'normalization.json').read_text());t=stats['action_transform']
            origin=batch['observation.state']*torch.tensor(stats['state_std'])+torch.tensor(stats['state_mean'])
            restored=batch['action']*torch.tensor(t['std'])+torch.tensor(t['mean'])
            if representation.startswith('joint_delta_'):restored=restored+origin[:,None,:]
            gaps=restored[:,1:,0]-restored[:,:-1,0]
            assert torch.all(torch.isclose(gaps,torch.zeros_like(gaps),atol=1e-6)|
                             torch.isclose(gaps,torch.full_like(gaps,.001),atol=1e-6))
            distances=(restored.reshape(-1,1,2)-torch.tensor(training_actions)).abs().amax(dim=-1)
            assert torch.all(distances.amin(dim=-1)<1e-6)
            torch.testing.assert_close(restored[:,:,1],torch.full_like(restored[:,:,1],-.1))
            if noise:
                assert torch.all(torch.abs(origin[:,1]+.1)>1e-6)
            checked.append(True)
        return original(model,batch,*args,**kwargs)
    monkeypatch.setattr(ACTPolicy,'forward',check_chunk_origin)
    original_predict=ACTPolicy.predict_action_chunk
    evaluated=[]
    def clean_validation(model,batch,*args,**kwargs):
        stats=json.loads((out/'normalization.json').read_text())
        origin=batch['observation.state']*torch.tensor(stats['state_std'])+torch.tensor(stats['state_mean'])
        torch.testing.assert_close(origin[:,1],torch.full_like(origin[:,1],-.1))
        assert all(any(abs(value-item)<1e-6 for item in [.01,.03,.05,.07]) for value in origin[:,0].tolist())
        evaluated.append(True)
        return original_predict(model,batch,*args,**kwargs)
    monkeypatch.setattr(ACTPolicy,'predict_action_chunk',clean_validation)
    kwargs=dict(state_noise_std_rad=noise) if noise else {}
    if initial is not None:kwargs['initial_policy']=initial
    report=run(exports[:2],exports[2:],out,steps=1,n_action_steps=queue_steps,
               action_representation=representation,**kwargs)
    stats=json.loads((out/'normalization.json').read_text())
    if representation in ('joint_delta_tanh_from_chunk_source_v1','absolute_tanh_from_chunk_source_v1'):
        assert stats['action_transform']['max_delta_rad']==.035
    assert stats['fit_episodes']==ids[:2]
    np.testing.assert_allclose(stats['state_mean'],np.mean(training_states,axis=0),atol=1e-7)
    assert evaluated
    if noise:
        augmentation=stats['training_augmentation']
        assert augmentation==dict(type='gaussian_state_noise_v1',std_rad=noise,seed=42751,
            joint_names=['joint1','gripper_joint_1'],train_only=True,source_kind='synthetic_training_inputs')
        assert report['training_augmentation']==augmentation
        dataset=json.loads((out/'dataset-manifest.json').read_text())
        import hashlib
        assert dataset['transformation']['config_sha256']==hashlib.sha256(json.dumps(stats,sort_keys=True).encode()).hexdigest()
    else:
        assert 'training_augmentation' not in stats and 'training_augmentation' not in report
    if representation=='absolute':
        np.testing.assert_allclose(stats['action_mean'],np.mean(training_actions,axis=0),atol=1e-7)
    elif representation.startswith('joint_delta_'):
        assert checked and 'action_mean' not in stats and 'action_std' not in stats
        np.testing.assert_allclose(stats['action_transform']['mean'],
            np.mean(np.asarray(training_actions)-np.asarray(training_states),axis=0),atol=1e-7)
        np.testing.assert_allclose(stats['action_transform']['absolute_baseline'],np.mean(training_actions,axis=0),atol=1e-7)
    else:
        assert checked and 'action_mean' not in stats and 'action_std' not in stats
        np.testing.assert_allclose(stats['action_transform']['mean'],np.mean(training_actions,axis=0),atol=1e-7)
        parent=json.loads((initial/'policy-artifact.json').read_text())
        initialization=report['training_initialization']
        assert initialization==stats['training_initialization']
        assert initialization['policy_revision']==parent['revision']
        assert initialization['parent_training_steps']==1 and initialization['optimizer_state']=='fresh_AdamW'
        assert initialization['weights_sha256']==next(v['sha256'] for v in parent['files'] if v['path'].endswith('.safetensors'))
        import copy
        from act_job import initialize_absolute_parent
        camera=parent['cameras'][0]
        source=dict(joint_names=parent['joint_names'],position_limits_rad=dict(zip(parent['joint_names'],parent['action']['limits'])),
            camera=dict(name=camera['name'],identity=camera['identity'],camera_info_sha256=camera['calibration_sha256'],
                height=camera['source_shape'][1],width=camera['source_shape'][2]))
        model=ACTPolicy.from_pretrained(initial/'policy',local_files_only=True)
        def never_load(*args,**kwargs):pytest.fail('incompatible parent weights were loaded')
        monkeypatch.setattr(model,'load_state_dict',never_load)
        for key in ('state_mean','action_transform'):
            bad=copy.deepcopy(stats)
            if key=='state_mean':bad[key][0]+=.001
            else:bad[key]['std'][0]*=1.001
            with pytest.raises(ValueError,match='must match'):
                initialize_absolute_parent(model,bad,source,initial)
        bad_source=copy.deepcopy(source);bad_source['camera']['camera_info_sha256']='0'*64
        with pytest.raises(ValueError,match='must match'):
            initialize_absolute_parent(model,stats,bad_source,initial)
        model.config.n_action_steps=4
        with pytest.raises(ValueError,match='must match'):
            initialize_absolute_parent(model,stats,source,initial)
        model.config.n_action_steps=queue_steps
        weights=initial/'policy/model.safetensors';raw=weights.read_bytes()
        try:
            weights.write_bytes(b'changed parent')
            with pytest.raises(ValueError,match='changed'):
                initialize_absolute_parent(model,stats,source,initial)
        finally:weights.write_bytes(raw)
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
