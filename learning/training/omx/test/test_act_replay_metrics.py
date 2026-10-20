"""Control-flow regression with stub readers; no model or SIM execution evidence."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'learning/training/omx'),str(ROOT/'learning/curation/omx')]
import act_inference_replay as replay_module


@pytest.mark.parametrize('multi',[False,True])
def test_reader_file_map_cannot_replace_selected_episode_metrics(tmp_path,monkeypatch,multi):
    root = tmp_path/'artifact'
    export = root/'reader-inputs/eval-a'
    source = export/'rosy_provenance/eval-a'
    source.mkdir(parents=True)
    (source/'manifest.json').write_text('{}')
    payload = (source/'manifest.json').read_bytes()
    dataset = dict(revision='d'*64,files=[dict(path='reader-inputs/eval-a/rosy_provenance/eval-a/manifest.json',
        bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())])
    metrics = dict(eval_frames=2,mae_rad=0.,constant_baseline_mae_rad=0.,verdict='reject')
    report = dict(metrics,train_episodes=['train-a','train-b'],eval_episode='eval-a')
    if multi:
        report.update(eval_episodes=['eval-a','eval-b'],per_episode={'eval-a':metrics},
                      verdict='offline_only',mae_rad=.123,eval_frames=4)
    policy = dict(revision='a'*64,dataset_revisions=[dataset['revision']],
        evaluations=[dict(path='offline-report.json')],normalization=dict(path='normalization.json'),
        cameras=[dict(name='front',identity='camera',calibration_sha256='c'*64,source_shape=[3,2,2])],
        joint_names=['j1','j2'],action=dict(limits=[[-1,1],[-1,1]]),
        timing=dict(period_ns=100_000_000,max_observation_age_ns=50_000_000,max_action_age_ns=50_000_000))
    for name, document in [('policy-artifact.json',policy),('dataset-manifest.json',dataset),
                           ('offline-report.json',report),('normalization.json',dict(
                               fit_episodes=report['train_episodes'],action_mean=[0.,0.]))]:
        (root/name).write_text(json.dumps(document))
    rows = [dict(action=[0.,0.],capture_time_ns=1_000_000_000+i*100_000_000,
                 state_time_ns=1_000_000_000+i*100_000_000,state_sequence=i+1,
                 received_at_ns=2_000_000_000+i*100_000_000,**{'observation.state':[0.,0.]}) for i in range(2)]
    monkeypatch.setattr(replay_module,'validate_policy',lambda doc,**_:doc)
    monkeypatch.setattr(replay_module,'validate_dataset',lambda doc,**_:doc)
    monkeypatch.setattr('common_episode.validate_omx',lambda _:dict(samples=rows))
    class Tensor:
        def __init__(self,value): self.value=np.asarray(value)
        @property
        def shape(self): return self.value.shape
        def numpy(self): return self.value
        def item(self): return self.value.item()
        def tolist(self): return self.value.tolist()
        def permute(self,*axes): return Tensor(self.value.transpose(axes))
    class Reader:
        num_episodes, num_frames = 1,2
        def __getitem__(self,index):
            row=rows[index]
            result={key:Tensor(row[key]) for key in ('action','observation.state')}
            result.update({'source.'+key:Tensor(row[key]) for key in ('capture_time_ns','state_time_ns','state_sequence')})
            result['source.received_wall_time_ns']=Tensor(row['received_at_ns'])
            result['observation.images.front']=Tensor(np.zeros((3,2,2)))
            return result
    monkeypatch.setitem(sys.modules,'torch',NS(set_num_threads=lambda _:None))
    monkeypatch.setitem(sys.modules,'lerobot.datasets.lerobot_dataset',NS(LeRobotDataset=lambda *_,**__:Reader()))
    def infer(observation):
        return NS(source=observation,positions=(0.,0.),returned_at_ns=observation.observed_at_ns,
                  produced_at_ns=observation.observed_at_ns,consumed_current=True,chunk_index=0)
    monkeypatch.setattr(replay_module,'ACTInference',lambda *_:NS(infer=infer))
    result=replay_module.replay(root,export,tmp_path/'replay',policy['revision'],paced=False)
    assert result['original_metrics_reproduced'] is True
    assert result['original_verdict'] == 'reject'
    assert result['aggregate_original_verdict'] == report['verdict']
    assert json.loads((tmp_path/'replay/state.json').read_text())['status'] == 'research_replayed'
