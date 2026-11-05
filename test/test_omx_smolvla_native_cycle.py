"""Opt-in actual SmolVLA training on synthetic data; never a physical task score."""
import os
from pathlib import Path
import subprocess

import pytest


DRIVER = r'''
import hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np
root, tmp, base, vlm = map(Path, sys.argv[1:5])
size = int(sys.argv[5])
sys.path[:0] = [str(root/'learning/curation/omx'), str(root/'learning/training/omx')]
import native_review as native
from native_cycle import run_cycle, _artifact_files
from lerobot.datasets.lerobot_dataset import LeRobotDataset
names = (list(native.JOINTS) if size == 6 else
         [f'{arm}.{joint}' for arm in ('arm_a', 'arm_b') for joint in native.JOINTS])
features = {key: dict(dtype='float32', shape=(size,), names=names)
            for key in ('action', 'observation.state')}
features['observation.images.front'] = dict(dtype='video', shape=(32,32,3), names=['height','width','channels'])
source = tmp/'source'
repo_id = 'local/synthetic-smolvla-cycle'
writer = LeRobotDataset.create(repo_id=repo_id, root=source, fps=10,
    robot_type='omx_follower' if size == 6 else 'bi_omx_follower', features=features,
    use_videos=True, video_backend='pyav', vcodec='h264', batch_encoding_size=1)
try:
    for episode in range(3):
        for frame in range(4):
            vector = np.full(size, episode*20+frame, dtype=np.float32)
            writer.add_frame({'observation.state':vector, 'action':vector,
                'observation.images.front':np.full((32,32,3), episode*60+frame, dtype=np.uint8),
                'task':'synthetic wiring verification only'})
        writer.save_episode(parallel_encoding=False)
finally:
    writer.finalize()
provenance = dict(schema='rosy.omx-native-capture.v1', source_mode='scripted_teacher',
    teacher_sha256=hashlib.sha256(b'synthetic smolvla fixture').hexdigest(),
    action_semantics='absolute_joint_position_target_normalized', body_units='normalized_-100_100',
    gripper_units='normalized_0_100', rig_revision='synthetic-rig', calibration_revision='synthetic-not-physical',
    files=native.dataset_files(source), episodes=[dict(episode_index=i, session_id=f'session-{i}',
        cycle_id=f'cycle-{i}') for i in range(3)])
report = native.inspect_dataset(source, repo_id, body_units=provenance['body_units'],
    rig_revision=provenance['rig_revision'], calibration_revision=provenance['calibration_revision'],
    source_mode='scripted_teacher', capture_provenance=provenance)
decisions = [dict(row, outcome='success', split=split, reviewer='synthetic-fixture-not-human',
    reason='SDK wiring only') for row, split in zip(report['episodes'], ('train','eval','test'))]
splits = native.split_reviewed(source, report, decisions, tmp/'splits')
before = (splits/'split-receipt.json').read_bytes()
run = tmp/'run'
receipt = run_cycle(splits, run, policy_type='smolvla', base_model=base, vlm_assets=vlm,
                    steps=1, batch_size=1, device='cpu', timeout=450)
assert (splits/'split-receipt.json').read_bytes() == before
assert receipt['policy_type'] == 'smolvla' and receipt['policy_revision'].startswith('smolvla-')
assert receipt['offline_only'] and not receipt['promotion'] and not receipt['device_execution']
assert receipt['evaluation']['joint_names'] == names
assert receipt['evaluation']['samples'] == 4 and receipt['evaluation']['physical_task_success'] is None
model = (run/'trainer/checkpoints/last/pretrained_model').resolve()
moved = tmp/'moved-policy'
shutil.move(str(model), moved)
shutil.move(str(run/'inputs'), tmp/'hidden-original-inputs')
assert _artifact_files(moved) == receipt['artifact_files']
env = dict(os.environ, HF_HOME=str(tmp/'empty-cache'), HF_HUB_CACHE=str(tmp/'empty-cache/hub'),
           HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1')
subprocess.run([sys.executable, str(root/'learning/training/omx/native_cycle.py'), 'verify',
    '--model', str(moved), '--splits', str(splits), '--repo-id', repo_id,
    '--out', str(tmp/'moved-evaluation.json')], env=env, check=True, timeout=180)
assert json.loads((tmp/'moved-evaluation.json').read_text())['samples'] == 4
print(json.dumps(dict(policy_type='smolvla', joints=size, optimizer_steps=1,
    relocated_offline_reload=True, physical_task_success=None, policy_revision=receipt['policy_revision'])))
'''


@pytest.mark.parametrize('joints', [6, 12], ids=['single', 'paired'])
def test_actual_smolvla_trains_and_reloads_after_relocation(tmp_path, joints):
    keys = ('ROSY_OMX_LEROBOT_PYTHON', 'ROSY_SMOLVLA_BASE', 'ROSY_SMOLVLA_VLM_ASSETS')
    if not all(os.environ.get(key) for key in keys):
        pytest.skip('explicit installed learner, SmolVLA base and local VLM metadata are required')
    python, base, vlm = (os.environ[key] for key in keys)
    assert Path(python).is_file() and Path(base).is_dir() and Path(vlm).is_dir()
    env = dict(os.environ, HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', CUDA_VISIBLE_DEVICES='',
               OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')
    result = subprocess.run([python, '-I', '-B', '-c', DRIVER, str(Path(__file__).resolve().parents[1]),
                             str(tmp_path), base, vlm, str(joints)],
                            capture_output=True, text=True, env=env, timeout=720)
    assert result.returncode == 0, (result.stdout+'\n'+result.stderr)[-7000:]
    assert '"relocated_offline_reload": true' in result.stdout
    print(result.stdout.splitlines()[-1])
