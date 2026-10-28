"""Pinned ACT computation with immutable input bytes and truthful chunk provenance.

No owner, ROS, registry stage, issuer or actuator authority is imported here.
Queue outputs retain their original observation and generation time; a caller must
let its existing owner reject stale/mismatched candidates, never relabel them.
"""
from collections import deque
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'contracts/learning/src'))
from rosy.contracts.learning import validate_policy
from rosy.contracts.learning.omx import WRIST, camera_role


def _text(value):
    if not isinstance(value,str) or not value or value!=value.strip():raise ValueError('trimmed identity required')


def _ns(value):
    if type(value) is not int or not 0<=value<2**63:raise ValueError('integer owner-monotonic nanoseconds required')


def _vector(values,size=None,positive=False):
    values=tuple(values)
    if (not values or (size is not None and len(values)!=size)
            or any(type(v) not in (float,int) or not math.isfinite(v) or (positive and v<=0) for v in values)):
        raise ValueError('finite numerical vector with declared dimensions required')
    return values


from rosy.contracts.learning.inference import InferenceObservation, InferenceResult


def image_key(doc):
    """Model input key the policy was trained with (D-794 B: never the device's current name)."""
    return 'observation.images.'+doc['cameras'][0]['name']


def _snapshot(root,pin):
    root=Path(root).resolve();manifest=root/'policy-artifact.json';payload=manifest.read_bytes()
    doc=validate_policy(json.loads(payload),root=root)
    if doc['revision']!=pin:raise ValueError('policy revision differs from pinned input')
    if doc['profile']!='omx_joint_target_v1' or doc['environment']!='sim':
        raise ValueError('only the OMX SIM ACT study profile is supported')
    if len(doc['cameras'])!=1 or camera_role(doc['cameras'][0]['name'])!=WRIST:raise ValueError('one explicit wrist RGB camera required')
    buffers={}
    for ref in [*doc['files'],doc['normalization'],*doc['evaluations']]:
        content=(root/ref['path']).read_bytes()
        if len(content)!=ref['bytes'] or hashlib.sha256(content).hexdigest()!=ref['sha256']:
            raise ValueError('artifact file changed while snapshotting')
        buffers[ref['path']]=content
    if manifest.read_bytes()!=payload:raise ValueError('artifact manifest changed while snapshotting')
    return doc,buffers


def action_statistics(stats,size):
    """Decode the representation before model loading; old consumers reject nested statistics."""
    if 'action_transform' not in stats:
        try:
            mean=_vector(stats['action_mean'],size)
            std=_vector(stats['action_std'],size,positive=True)
        except KeyError as error:raise ValueError('missing action statistics') from error
        return 'absolute',mean,std,mean
    transform=stats['action_transform']
    if any(key in stats for key in ('action_mean','action_std')) or type(transform) is not dict:
        raise ValueError('unknown or ambiguous action transform')
    kind=transform.get('type')
    keys={'type','mean','std','absolute_baseline'}
    if kind in ('joint_delta_tanh_from_chunk_source_v1','absolute_tanh_from_chunk_source_v1'):
        keys.add('max_delta_rad')
        bound=transform.get('max_delta_rad')
        if type(bound) not in (int,float) or bound!=.035:
            raise ValueError('exact supported action bound required')
    elif kind!='joint_delta_from_chunk_source_v1':
        raise ValueError('unknown or ambiguous action transform')
    if set(transform)!=keys:raise ValueError('unknown or ambiguous action transform')
    return (transform['type'],_vector(transform['mean'],size),
            _vector(transform['std'],size,positive=True),_vector(transform['absolute_baseline'],size))


def install_action_head_transform(policy,stats):
    """Reconstruct the byte-bound trained activation without changing weight keys."""
    kind,mean,std,_=action_statistics(stats,len(stats['state_mean']))
    if kind not in ('joint_delta_tanh_from_chunk_source_v1','absolute_tanh_from_chunk_source_v1'):return
    import torch
    head=policy.model.action_head
    if type(head) is not torch.nn.Linear or head.out_features!=len(mean) or head._forward_hooks:
        raise ValueError('one unmodified ACT linear action head required')
    mean=head.weight.new_tensor(mean);std=head.weight.new_tensor(std)
    source=[None]
    if kind=='absolute_tanh_from_chunk_source_v1':
        model=policy.model
        if model._forward_pre_hooks or model._forward_hooks:
            raise ValueError('one unmodified ACT model head source required')
        state_mean=head.weight.new_tensor(_vector(stats['state_mean'],len(mean)))
        state_std=head.weight.new_tensor(_vector(stats['state_std'],len(mean),positive=True))
        def capture_source(_model,inputs):
            if source[0] is not None or len(inputs)!=1 or not isinstance(inputs[0],dict):
                raise ValueError('one model call source required')
            state=inputs[0].get('observation.state')
            if (not isinstance(state,torch.Tensor) or state.ndim!=2 or state.shape[-1]!=len(mean)
                    or not torch.isfinite(state).all()):
                raise ValueError('finite batch source required')
            original=state*state_std+state_mean
            if not torch.isfinite(original).all():raise ValueError('nonfinite source')
            source[0]=original[:,None,:]
        def clear_source(_model,_inputs,_output):
            source[0]=None
        model.register_forward_pre_hook(capture_source)
        model.register_forward_hook(clear_source,always_call=True)
    def bounded_delta(_module,_inputs,output):
        delta=output*std+mean
        if not torch.isfinite(output).all() or not torch.isfinite(delta).all():
            raise ValueError('nonfinite action head')
        if kind=='absolute_tanh_from_chunk_source_v1':
            origin=source[0]
            if origin is None or output.ndim!=3 or output.shape[0]!=origin.shape[0]:
                raise ValueError('same batch model source required for absolute head')
            return (origin+.035*torch.tanh((delta-origin)/.035)-mean)/std
        return (.035*torch.tanh(delta/.035)-mean)/std
    head.register_forward_hook(bounded_delta)


def _configuration(doc,buffers):
    paths={ref['path'] for ref in doc['files']}
    if paths!={'policy/config.json','policy/model.safetensors'}:raise ValueError('exact ACT config and safetensors files required')
    config=json.loads(buffers['policy/config.json']);stats=json.loads(buffers[doc['normalization']['path']])
    camera=doc['cameras'][0];size=len(doc['joint_names'])
    if (config.get('type')!='act' or config.get('device')!='cpu' or config.get('n_obs_steps')!=1
            or config.get('pretrained_backbone_weights') is not None or config.get('pretrained_path') is not None
            or config.get('temporal_ensemble_coeff') is not None):raise ValueError('local CPU ACT with no downloads or ensemble required')
    inputs={'observation.state':dict(type='STATE',shape=[size]),
            image_key(doc):dict(type='VISUAL',shape=camera['model_shape'])}
    outputs={'action':dict(type='ACTION',shape=[size])}
    if config.get('input_features')!=inputs or config.get('output_features')!=outputs:
        raise ValueError('ACT features differ from policy metadata')
    steps=config.get('n_action_steps');chunk=config.get('chunk_size')
    if type(steps) is not int or type(chunk) is not int or not 1<=steps<=chunk<=1024:
        raise ValueError('bounded positive ACT chunk configuration required')
    for name in ('state_mean','state_std'):
        _vector(stats[name],size,positive=name.endswith('_std'))
    action_statistics(stats,size)
    expected=dict(resize_hw=camera['model_shape'][1:],color='rgb',scale=camera['scale'])
    if stats['image']!=expected:raise ValueError('image normalization differs from policy metadata')
    duration=stats['fixed_source_duration_s']
    if type(duration) not in (float,int) or not math.isfinite(duration) or duration<=0:
        raise ValueError('positive original source duration required')
    return steps,stats


def _model_from_bytes(config_bytes,weight_bytes,stats,metadata):
    """No mutable file reread or pretrained download; models consume checked bytes."""
    if importlib.metadata.version('lerobot')!='0.4.4':raise ValueError('lerobot==0.4.4 required')
    import draccus
    import numpy as np
    import torch
    from safetensors.torch import load
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.act.configuration_act import ACTConfig
    config=draccus.decode(PreTrainedConfig,json.loads(config_bytes))
    if not isinstance(config,ACTConfig):raise ValueError('ACT config required')
    policy=ACTPolicy(config)
    policy.load_state_dict(load(weight_bytes),strict=True)
    install_action_head_transform(policy,stats)
    policy.eval()
    representation,action_mean,action_std,_=action_statistics(stats,len(metadata['joint_names']))
    means=dict(state_mean=torch.tensor(stats['state_mean'],dtype=torch.float32),
               action_mean=torch.tensor(action_mean,dtype=torch.float32))
    stds=dict(state_std=torch.tensor(stats['state_std'],dtype=torch.float32),
              action_std=torch.tensor(action_std,dtype=torch.float32))
    camera=metadata['cameras'][0];key=image_key(metadata)

    def predict(obs):
        _,height,width=obs.camera_shape
        rgb=np.frombuffer(obs.rgb,dtype=np.uint8).reshape(height,width,3).copy()
        image=torch.from_numpy(rgb).permute(2,0,1).float().unsqueeze(0)*camera['scale']
        image=torch.nn.functional.interpolate(image,size=tuple(camera['model_shape'][1:]),mode='bilinear',align_corners=False)
        state=(torch.tensor(obs.positions,dtype=torch.float32)-means['state_mean'])/stds['state_std']
        with torch.inference_mode():
            chunk=policy.predict_action_chunk({'observation.state':state.unsqueeze(0),key:image})
            actions=chunk[0,:config.n_action_steps]*stds['action_std']+means['action_mean']
            if representation in ('joint_delta_from_chunk_source_v1','joint_delta_tanh_from_chunk_source_v1'):
                actions=actions+torch.tensor(obs.positions,dtype=torch.float32)
        return actions.tolist()
    return predict


class ACTInference:
    """Numerical computation only; artifact pin is integrity, not operating trust."""
    def __init__(self,root,policy_revision,*,monotonic=time.monotonic):
        self._doc,buffers=_snapshot(root,policy_revision)
        self._steps,stats=_configuration(self._doc,buffers)
        self._predict=_model_from_bytes(buffers['policy/config.json'],buffers['policy/model.safetensors'],stats,self._doc)
        self._clock=monotonic;self._last_now=None;self._context=None;self._queue=deque()
        self._lock=threading.RLock();self._fault=''

    @property
    def metadata(self):return json.loads(json.dumps(self._doc))

    def _now(self):
        value=self._clock()
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise ValueError('invalid owner clock')
        now=int(value*1_000_000_000);_ns(now)
        if self._last_now is not None and now<self._last_now:raise ValueError('owner clock rollback')
        self._last_now=now
        return now

    def reset(self,reason):
        if reason not in self._doc['reset_events']:raise ValueError('declared inference reset event required')
        with self._lock:self._queue.clear();self._context=None;self._fault=''

    def infer(self,observation):
        with self._lock:
            if self._fault:raise ValueError(self._fault)
            try:
                if not isinstance(observation,InferenceObservation):raise ValueError('immutable inference observation required')
                camera=self._doc['cameras'][0]
                if (observation.joint_names!=tuple(self._doc['joint_names'])
                        or (observation.camera_identity,observation.camera_calibration_sha256,observation.camera_shape)!=
                           (camera['identity'],camera['calibration_sha256'],tuple(camera['source_shape']))):
                    raise ValueError('observation differs from model binding')
                now=self._now()
                if max(observation.observed_at_ns,observation.camera_received_at_ns)>now:
                    raise ValueError('future observation cannot produce action')
                context=(observation.lease_id,observation.episode_id)
                if context!=self._context:self._queue.clear();self._context=context
                consumed=not self._queue
                if consumed:
                    actions=tuple(_vector(action,len(self._doc['joint_names'])) for action in self._predict(observation))
                    if len(actions)!=self._steps:raise ValueError('predicted chunk size differs from config')
                    produced=self._now()
                    self._queue.extend((observation,action,produced,index) for index,action in enumerate(actions))
                source,action,produced,index=self._queue.popleft()
                return InferenceResult(self._doc['revision'],source,action,produced,self._now(),index,consumed)
            except Exception as exc:
                self._queue.clear();self._fault='inference_fault:'+type(exc).__name__
                raise ValueError(self._fault) from exc
