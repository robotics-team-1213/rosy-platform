"""Replay actual ACT evaluation reader with checked model bytes and queue provenance.

No ROS/owner/authority/registry promotion. Output is a new research artifact on X.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'contracts/learning/src'),str(ROOT/'learning/curation/omx')]
from act_inference import ACTInference,InferenceObservation
from rosy.contracts.learning import validate_dataset,validate_policy


def _write(path,data):
    path.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def replay(policy_root,eval_export,out,policy_revision,*,dataset_root=None,paced=True):
    out=Path(out).resolve();policy_root=Path(policy_root).resolve();eval_export=Path(eval_export).resolve()
    dataset_root=Path(dataset_root or policy_root).resolve()
    if out.exists() or out.drive.upper()=='F:':raise ValueError('new artifact directory outside F: required')
    if type(paced) is not bool:raise ValueError('explicit replay cadence flag required')
    if any(out.is_relative_to(p) or p.is_relative_to(out) for p in (policy_root,eval_export,dataset_root)):
        raise ValueError('output must be separate from policy and source inputs')
    policy=validate_policy(json.loads((policy_root/'policy-artifact.json').read_bytes()),root=policy_root)
    if policy['revision']!=policy_revision:raise ValueError('pinned policy revision mismatch')
    dataset=validate_dataset(json.loads((dataset_root/'dataset-manifest.json').read_bytes()),root=dataset_root)
    if policy['dataset_revisions']!=[dataset['revision']]:raise ValueError('exact bound dataset required')
    paths=sorted((eval_export/'rosy_provenance').glob('*/manifest.json'))
    if len(paths)!=1:raise ValueError('one exact evaluation Episode export required')
    from common_episode import validate_omx
    source=validate_omx(paths[0].parent)
    if len(policy['evaluations'])!=1:raise ValueError('one bound original offline report required')
    original=json.loads((policy_root/policy['evaluations'][0]['path']).read_bytes())
    if (original['eval_episode']!=paths[0].parent.name or original['eval_episode'] in original['train_episodes']
            or len(source['samples'])!=original['eval_frames']):raise ValueError('source differs from held-out evaluation')
    stats=json.loads((policy_root/policy['normalization']['path']).read_bytes())
    if stats['fit_episodes']!=original['train_episodes']:raise ValueError('normalization fit sources differ')
    # The actual evaluation reader must be byte-for-byte covered by the bound Dataset.
    expected={ref['path']:ref for ref in dataset['files']}
    input_refs=[]
    for file in sorted(eval_export.rglob('*')):
        if not file.is_file():continue
        try:key=file.relative_to(dataset_root).as_posix()
        except ValueError:raise ValueError('reader must be within bound dataset root') from None
        ref=expected.get(key)
        if ref is None or file.stat().st_size!=ref['bytes'] or hashlib.sha256(file.read_bytes()).hexdigest()!=ref['sha256']:
            raise ValueError('reader file not covered by bound dataset bytes')
        input_refs.append(ref)
    out.mkdir(parents=True)
    source_bytes={name:(Path(__file__).parent/name).read_bytes() for name in ('act_inference.py','act_inference_replay.py')}
    (out/'source').mkdir()
    for name,content in source_bytes.items():(out/'source'/name).write_bytes(content)
    _write(out/'state.json',dict(status='running',policy_revision=policy_revision,authority='none'))
    try:
        import numpy as np
        import torch
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
        torch.set_num_threads(4)
        engine=ACTInference(policy_root,policy_revision)
        reader=LeRobotDataset('rosy-local/omx-sim',root=eval_export,video_backend='pyav',download_videos=False)
        if reader.num_episodes!=1 or reader.num_frames!=len(source['samples']):raise ValueError('reader frame count differs')
        camera=policy['cameras'][0];period=policy['timing']['period_ns']/1e9
        predictions=[];frames=[];next_at=time.monotonic()
        for index,row in enumerate(source['samples']):
            if paced:
                delay=next_at-time.monotonic()
                if delay>0:time.sleep(delay)
            actual=reader[index]
            for key in ('observation.state','action'):
                np.testing.assert_allclose(actual[key].numpy(),row[key],atol=1e-7,rtol=1e-6)
            for field in ('capture_time_ns','state_time_ns','state_sequence'):
                if int(actual['source.'+field].item())!=row[field]:raise ValueError('reader source clock/sequence differs')
            if int(actual['source.received_wall_time_ns'].item())!=row['received_at_ns']:
                raise ValueError('reader original wall receipt differs')
            image=actual['observation.images.front']
            if list(image.shape)!=camera['source_shape']:raise ValueError('reader source image dimensions differ')
            rgb=(image.permute(1,2,0).numpy()*255).round().astype(np.uint8).tobytes()
            received=time.monotonic_ns()
            obs=InferenceObservation(original['eval_episode'],'offline-replay:'+policy_revision,
                tuple(policy['joint_names']),tuple(actual['observation.state'].tolist()),row['state_sequence'],received,
                camera['identity'],camera['calibration_sha256'],tuple(camera['source_shape']),received,rgb)
            result=engine.infer(obs);predictions.append(result.positions)
            if paced:next_at=result.returned_at_ns/1e9+period
            matched=(result.source.sequence,result.source.observed_at_ns,result.source.frame_sha256)==(
                     obs.sequence,obs.observed_at_ns,obs.frame_sha256)
            age=result.returned_at_ns-result.source.observed_at_ns
            action_age=result.returned_at_ns-result.produced_at_ns
            frames.append(dict(index=index,source_capture_time_ns=row['capture_time_ns'],source_state_time_ns=row['state_time_ns'],
                source_received_wall_time_ns=row['received_at_ns'],input_sequence=obs.sequence,
                input_received_at_owner_monotonic_ns=received,input_rgb_sha256=obs.frame_sha256,
                consumed_current=result.consumed_current,chunk_index=result.chunk_index,
                consumed_sequence=result.source.sequence,consumed_rgb_sha256=result.source.frame_sha256,
                consumed_received_at_owner_monotonic_ns=result.source.observed_at_ns,
                produced_at_owner_monotonic_ns=result.produced_at_ns,returned_at_owner_monotonic_ns=result.returned_at_ns,
                inference_latency_ns=result.produced_at_ns-result.source.observed_at_ns,
                candidate_matches_current_observation=matched,observation_age_ns=age,action_age_ns=action_age,
                observation_age_within_budget=age<=policy['timing']['max_observation_age_ns'],
                action_age_within_budget=action_age<=policy['timing']['max_action_age_ns'],positions=list(result.positions)))
        truth=np.asarray([row['action'] for row in source['samples']]);prediction=np.asarray(predictions)
        mae=float(np.abs(truth-prediction).mean())
        baseline=float(np.abs(truth-np.asarray(stats['action_mean'])).mean())
        if abs(mae-original['mae_rad'])>1e-6 or abs(baseline-original['constant_baseline_mae_rad'])>1e-9:
            raise ValueError('actual queued prediction metrics differ from bound offline evaluation')
        # Revalidate all referenced source bytes after video decoding/inference.
        validate_policy(json.loads((policy_root/'policy-artifact.json').read_bytes()),root=policy_root)
        if json.loads((policy_root/'policy-artifact.json').read_bytes())['revision']!=policy_revision:
            raise ValueError('policy changed during replay')
        validate_dataset(dataset,root=dataset_root);validate_omx(paths[0].parent)
        limits=np.asarray(policy['action']['limits'])
        gaps=[frames[i]['input_received_at_owner_monotonic_ns']-frames[i-1]['returned_at_owner_monotonic_ns'] for i in range(1,len(frames))]
        report=dict(schema='rosy.act-inference-replay/1',policy_revision=policy_revision,dataset_revision=dataset['revision'],
            evaluation_episode=original['eval_episode'],frames=len(frames),actual_model_computations=sum(f['consumed_current'] for f in frames),
            queued_candidates=sum(not f['consumed_current'] for f in frames),
            observation_mismatch_count=sum(not f['candidate_matches_current_observation'] for f in frames),
            observation_age_violation_count=sum(not f['observation_age_within_budget'] for f in frames),
            action_age_violation_count=sum(not f['action_age_within_budget'] for f in frames),
            mae_rad=mae,constant_baseline_mae_rad=baseline,
            joint_limit_violation_count=int(((prediction<limits[:,0])|(prediction>limits[:,1])).sum()),
            original_metrics_reproduced=True,original_verdict=original['verdict'],cadence='minimum-period-after-return' if paced else 'unpaced',
            requested_period_ns=policy['timing']['period_ns'],minimum_input_after_previous_return_gap_ns=min(gaps) if gaps else None,
            timestamp_basis='replay-input-receipt owner monotonic; original source clocks preserved separately',
            owner_dispatch='not_attempted',operating_authority='none',independent_sim_task='not_executed',
            promotion='not_eligible',evaluation_input_files=input_refs,
            tool_sha256=hashlib.sha256(source_bytes['act_inference_replay.py']).hexdigest(),
            inference_source_sha256=hashlib.sha256(source_bytes['act_inference.py']).hexdigest())
        _write(out/'frames.json',frames);_write(out/'report.json',report)
        _write(out/'state.json',dict(status='research_replayed',policy_revision=policy_revision,promotion='not_eligible'))
        return report
    except BaseException as exc:
        _write(out/'state.json',dict(status='failed',error=f'{type(exc).__name__}: {exc}',policy_revision=policy_revision))
        raise


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--policy-root',type=Path,required=True);ap.add_argument('--dataset-root',type=Path,required=True)
    ap.add_argument('--eval-export',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--policy-revision',required=True)
    args=ap.parse_args()
    print(json.dumps(replay(args.policy_root,args.eval_export,args.out,args.policy_revision,dataset_root=args.dataset_root)))


if __name__=='__main__':main()
