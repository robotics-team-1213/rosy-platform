"""Verified passive raw evidence to policy-only LeRobot v3; no native admission."""
import argparse
import importlib.metadata
import json
import math
from pathlib import Path

import passive_recording as recording


def dataset_features(seal):
    profile=seal['config']['profile']
    names=[f"{arm['id']}/{joint}" for arm in profile['arms'] for joint in arm['joint_names']]
    features={key:dict(dtype='float32',shape=(len(names),),names=names[:])
              for key in ('observation.state','action')}
    for camera in profile['cameras']:
        if 'policy' in camera['purposes']:
            channels,height,width=camera['shape']
            features[camera['input_key']]=dict(dtype='image',shape=(height,width,channels),
                names=['height','width','channels'])
    return features


def frame_budget(seal):
    return 2*sum(math.prod(camera['shape']) for camera in seal['config']['profile']['cameras']
                 if 'policy' in camera['purposes'])+64*1024


class StorageBudget:
    def __init__(self,output,policy_keys,frame_bytes):
        self.output=Path(output).resolve()
        self.policy_keys=list(policy_keys)
        self.frame_bytes=frame_bytes
        self.saved_bytes=0
        self.episode_bytes=0

    def before_frame(self):
        recording.require_space(self.output,self.frame_bytes)

    def after_frame(self,child):
        for key in self.policy_keys:
            path=Path(child.episode_buffer[key][-1])
            if (path.is_symlink() or not path.is_file()
                    or not path.resolve().is_relative_to(self.output)):
                raise ValueError('synchronous image writer must produce owned regular PNG files')
            self.episode_bytes+=path.stat().st_size
        if self.saved_bytes+self.episode_bytes>recording.MAX_BYTES:
            raise ValueError('passive export actual PNG/data budget exceeds 2 GiB')

    def before_episode(self):
        recording.require_space(self.output,2*self.episode_bytes)

    def finish_episode(self):
        total=0
        for path in self.output.rglob('*'):
            if path.is_symlink() or not path.resolve().is_relative_to(self.output):
                raise ValueError('export storage must contain owned regular files only')
            if path.is_file():
                total+=path.stat().st_size
                if total>recording.MAX_BYTES:
                    raise ValueError('passive export saved data budget exceeds 2 GiB')
            elif not path.is_dir():
                raise ValueError('regular export files required')
        self.saved_bytes=total
        self.episode_bytes=0


def export(episode_roots,output,*,repo_id='rosy-passive/local-recording'):
    roots=[Path(path) for path in episode_roots]
    if not 2<=len(roots)<=1000 or len({root.resolve() for root in roots})!=len(roots):
        raise ValueError('at least two distinct kept passive episodes required')
    seals=[recording.verify(root) for root in roots]
    first=seals[0]
    config=first['config']
    frozen=lambda value:{key:content for key,content in value.items() if key not in ('preflight_at','revision')}
    if any(frozen(seal['config'])!=frozen(config) for seal in seals):
        raise ValueError('passive export requires the same frozen profile/producer/timing session')
    if sum(seal['frames'] for seal in seals)>200000:
        raise ValueError('passive export exceeds 200000-frame capability')
    output=Path(output)
    if (not output.is_absolute() or output.exists() or output.is_symlink()
            or any(output.resolve().is_relative_to(root.resolve()) for root in roots)):
        raise ValueError('new absolute export outside raw recordings required')
    from omx_output_paths import in_source_checkout
    if in_source_checkout(output):
        raise ValueError('passive datasets belong outside source checkout')
    recording.require_space(output,frame_budget(first))
    if importlib.metadata.version('lerobot')!='0.4.4':
        raise ValueError('passive export requires pinned lerobot==0.4.4')
    import numpy as np
    from PIL import Image
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    features=dataset_features(first)
    policy=[c for c in config['profile']['cameras'] if 'policy' in c['purposes']]
    budget=StorageBudget(output,[c['input_key'] for c in policy],frame_budget(first))
    child=LeRobotDataset.create(repo_id,fps=config['timing']['fps'],features=features,
        root=output,robot_type='passive_observer',use_videos=False,image_writer_threads=0)
    try:
        for root,seal in zip(roots,seals):
            for row in recording.frames(root,seal):
                budget.before_frame()
                values={'observation.state':np.asarray(row['state'],dtype=np.float32),
                        'action':np.asarray(row['action'],dtype=np.float32),'task':config['profile']['task']}
                for camera in policy:
                    with Image.open(root/row['cameras'][camera['id']]['path']) as image:
                        values[camera['input_key']]=np.asarray(image,dtype=np.uint8).copy()
                child.add_frame(values)
                budget.after_frame(child)
            budget.before_episode()
            child.save_episode()
            budget.finish_episode()
    finally:
        child.finalize()
    reader=LeRobotDataset(repo_id,root=output,download_videos=False,video_backend='pyav')
    if len(reader)!=sum(seal['frames'] for seal in seals) or reader.num_episodes!=len(seals):
        raise ValueError('official passive export reader count differs')
    if set(reader.meta.info['features'])-{'timestamp','frame_index','episode_index','index','task_index'}!=set(features):
        raise ValueError('non-policy views or unexpected features entered training data')
    count=0
    for episode,(root,seal) in enumerate(zip(roots,seals)):
        for frame,row in enumerate(recording.frames(root,seal)):
            actual=reader[count]
            if (int(actual['episode_index'].item())!=episode or int(actual['frame_index'].item())!=frame
                    or abs(float(actual['timestamp'].item())-frame/config['timing']['fps'])>1e-6):
                raise ValueError('LeRobot timestamp/order differs from validated recording grid')
            for key,value in [('observation.state',row['state']),('action',row['action'])]:
                np.testing.assert_array_equal(actual[key].numpy().reshape(features[key]['shape']),
                    np.asarray(value,dtype=np.float32))
            for camera in policy:
                with Image.open(root/row['cameras'][camera['id']]['path']) as image:
                    expected=np.asarray(image,dtype=np.float32).transpose(2,0,1)/255
                np.testing.assert_array_equal(actual[camera['input_key']].numpy(),expected)
            count+=1
        if recording.verify(root)!=seal:
            raise ValueError('passive source changed during export/readback')
    provenance=dict(schema='rosy.passive-export-provenance/1',source_mode='passive_owner_observation',
        content_integrity_only=True,profile_revision=config['profile_revision'],
        timing=config['timing'],clock_domain_semantics='host receipt, not exposure synchronization',
        vector_encoding='float32; original values retained in sealed raw evidence',
        arms=[dict(id=a['id'],joint_names=a['joint_names'],units=a['units']) for a in config['profile']['arms']],
        policy_cameras=[dict(input_key=c['input_key'],shape=c['shape'],source_identity_sha256=recording.digest(c['source_identity'])) for c in policy],
        episodes=[dict(index=i,frames=s['frames'],seal_revision=s['revision'],task_outcome=s['task_outcome'],
            raw_hashes=s['files'],review_only_sources=[recording.digest(c['source_identity'])
                for c in recording.retained(config['profile']) if 'policy' not in c['purposes']]) for i,s in enumerate(seals)],
        physical_learning_verified=False,native_safe_end=False)
    recording.write_json(output/'source-provenance.json',provenance)
    budget.finish_episode()
    receipt=dict(schema='rosy.passive-export-result/1',frames=count,episodes=len(seals),
        profile_revision=config['profile_revision'],policy_camera_keys=[c['input_key'] for c in policy],
        files=recording.hashes(output),reader_verified=True,physical_learning_verified=False)
    recording.write_json(output.with_name(output.name+'.receipt.json'),receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--episode',type=Path,action='append',required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--repo-id',default='rosy-passive/local-recording')
    args=parser.parse_args()
    try:
        print(json.dumps(export(args.episode,args.out,repo_id=args.repo_id)),flush=True)
    except Exception as exc:
        recording.write_json(args.out.with_name(args.out.name+'.error.json'),
            dict(error='Passive export failed: '+type(exc).__name__,status='failed'))
        raise


if __name__=='__main__':
    main()
