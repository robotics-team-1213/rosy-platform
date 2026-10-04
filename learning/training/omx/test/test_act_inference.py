"""Immutable model/input bytes and truthful ACT chunk provenance, without authority."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/'learning/training/omx'),str(ROOT/'contracts/learning/src'),str(ROOT/'test')]
from act_inference import ACTInference,InferenceObservation
from rosy.contracts.learning import seal
from test_learning_artifact_contracts import policy


def artifact(tmp_path):
    root=tmp_path/'artifact';root.mkdir()
    data={
        'policy/config.json':json.dumps(dict(type='act',n_obs_steps=1,device='cpu',pretrained_backbone_weights=None,
            pretrained_path=None,temporal_ensemble_coeff=None,chunk_size=4,n_action_steps=4,
            input_features={'observation.state':dict(type='STATE',shape=[2]),
                            'observation.images.front':dict(type='VISUAL',shape=[3,8,8])},
            output_features={'action':dict(type='ACTION',shape=[2])})).encode(),
        'policy/model.safetensors':b'weights',
        'normalization.json':json.dumps(dict(state_mean=[0,0],state_std=[1,1],action_mean=[0,0],action_std=[1,1],
            fit_episodes=['train'],image=dict(resize_hw=[8,8],color='rgb',scale=1/255),fixed_source_duration_s=.4)).encode(),
        'offline-report.json':b'{}'}
    for name,payload in data.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
    refs={name:dict(path=name,bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest()) for name,payload in data.items()}
    doc=policy();doc.update(files=[refs['policy/config.json'],refs['policy/model.safetensors']],
        normalization=refs['normalization.json'],evaluations=[refs['offline-report.json']],
        cameras=[dict(name='front',identity='sim-camera',calibration_sha256='a'*64,
                      source_shape=[3,8,8],model_shape=[3,8,8],color='rgb',scale=1/255)])
    doc=seal(doc);(root/'policy-artifact.json').write_text(json.dumps(doc),encoding='utf-8')
    return root,doc,data


def observation(**changes):
    values=dict(episode_id='episode',lease_id='lease',joint_names=('j1','j2'),positions=(.1,.2),
        sequence=10,observed_at_ns=10_000_000_000,camera_identity='sim-camera',
        camera_calibration_sha256='a'*64,camera_shape=(3,8,8),camera_received_at_ns=10_000_000_000,
        rgb=bytes(range(192)))
    values.update(changes)
    return InferenceObservation(**values)


def setup(tmp_path,monkeypatch):
    root,doc,data=artifact(tmp_path);clock=[10.0];seen=[];loaded=[]
    def model(config,weights,stats,metadata):
        loaded.append((config,weights,stats))
        def predict(obs):
            seen.append(obs);clock[0]+=.001
            return [(obs.positions[0]+i/100,obs.positions[1]) for i in range(4)]
        return predict
    monkeypatch.setattr('act_inference._model_from_bytes',model)
    engine=ACTInference(root,doc['revision'],monotonic=lambda:clock[0])
    return engine,root,doc,data,clock,seen,loaded


def test_exact_bytes_and_raw_frame_are_consumed(tmp_path,monkeypatch):
    engine,root,doc,data,clock,seen,loaded=setup(tmp_path,monkeypatch)
    obs=observation();result=engine.infer(obs)
    assert loaded[0][0]==data['policy/config.json'] and loaded[0][1]==data['policy/model.safetensors']
    assert seen==[obs] and result.source==obs and result.policy_revision==doc['revision']
    assert result.source.frame_sha256==hashlib.sha256(obs.rgb).hexdigest()
    assert result.positions==(.1,.2) and result.chunk_index==0 and result.consumed_current
    assert result.candidate_fields()['sequence']==10


def test_queued_actions_keep_original_observation_and_generation_time(tmp_path,monkeypatch):
    engine,_,_,_,clock,seen,_=setup(tmp_path,monkeypatch)
    first=engine.infer(observation());clock[0]=10.1
    queued=engine.infer(observation(sequence=11,observed_at_ns=10_100_000_000,camera_received_at_ns=10_100_000_000,rgb=b'\x00'*192))
    assert len(seen)==1 and queued.source==first.source and queued.produced_at_ns==first.produced_at_ns
    assert not queued.consumed_current and queued.chunk_index==1
    assert queued.candidate_fields()['camera_frames']==(first.source.frame_sha256,)
    assert queued.candidate_fields()['sequence']==10


@pytest.mark.parametrize('change',[dict(episode_id='next'),dict(lease_id='next')])
def test_context_change_drops_old_queue(tmp_path,monkeypatch,change):
    engine,_,_,_,_,seen,_=setup(tmp_path,monkeypatch)
    engine.infer(observation());changed=replace(observation(),**change)
    result=engine.infer(changed)
    assert len(seen)==2 and result.source==changed and result.chunk_index==0


def test_explicit_reset_discards_queue_without_any_owner_call(tmp_path,monkeypatch):
    engine,*rest=setup(tmp_path,monkeypatch)
    engine.infer(observation());engine.reset('hold')
    assert engine.infer(observation()).chunk_index==0
    with pytest.raises(ValueError):engine.reset('automatic_rearm')


def test_mutable_caller_image_is_copied_before_consumption():
    image=bytearray(range(192));obs=observation(rgb=image);image[0]=255
    assert type(obs.rgb) is bytes and obs.rgb[0]==0


@pytest.mark.parametrize('change',[dict(joint_names=('j2','j1')),dict(camera_identity='other'),
    dict(camera_calibration_sha256='b'*64),dict(camera_shape=(3,4,16)),
    dict(camera_received_at_ns=10_000_000_001)])
def test_bad_binding_or_future_camera_never_infers(tmp_path,monkeypatch,change):
    engine,_,_,_,_,seen,_=setup(tmp_path,monkeypatch)
    with pytest.raises(ValueError):engine.infer(observation(**change))
    assert not seen


def test_pin_or_changed_weight_refuses_model_loading(tmp_path,monkeypatch):
    root,doc,_=artifact(tmp_path)
    def forbidden(*_):pytest.fail('unverified bytes reached numerical model')
    monkeypatch.setattr('act_inference._model_from_bytes',forbidden)
    with pytest.raises(ValueError):ACTInference(root,'b'*64)
    (root/'policy/model.safetensors').write_bytes(b'corrupt')
    with pytest.raises(ValueError):ACTInference(root,doc['revision'])


def test_inference_uses_memory_snapshot_after_source_file_change(tmp_path,monkeypatch):
    engine,root,_,_,_,seen,_=setup(tmp_path,monkeypatch)
    (root/'policy/model.safetensors').write_bytes(b'changed')
    assert engine.infer(observation()).positions==(.1,.2) and len(seen)==1


def test_nonfinite_model_output_latches_until_explicit_reset(tmp_path,monkeypatch):
    engine,*_=setup(tmp_path,monkeypatch)
    engine._predict=lambda _:[(float('nan'),0)]*4
    with pytest.raises(ValueError):engine.infer(observation())
    engine._predict=lambda _:[(.1,.2)]*4
    with pytest.raises(ValueError):engine.infer(observation())
    engine.reset('hold')
    assert engine.infer(observation()).positions==(.1,.2)
