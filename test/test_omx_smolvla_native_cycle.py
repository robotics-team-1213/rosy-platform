"""Opt-in ACT/SmolVLA training and saved train statistics; never a physical task score."""
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
policy_type = sys.argv[6]
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
            vector = np.arange(size, dtype=np.float32)/10 + episode*20+frame
            writer.add_frame({'observation.state':vector, 'action':vector+.25,
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
options = dict(base_model=base, vlm_assets=vlm) if policy_type == 'smolvla' else {}
receipt = run_cycle(splits, run, policy_type=policy_type, **options,
                    steps=1, batch_size=1, device='cpu', timeout=450)
assert (splits/'split-receipt.json').read_bytes() == before
assert receipt['policy_type'] == policy_type and receipt['policy_revision'].startswith(policy_type+'-')
assert receipt['offline_only'] and not receipt['promotion'] and not receipt['device_execution']
assert set(receipt['code_files']) == {'native_cycle.py', 'smolvla_training.py', 'policy_assets.py'}
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
probe = r"""
import json, math, sys
from pathlib import Path
import numpy as np
root, model, size = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
splits, policy_type = Path(sys.argv[4]), sys.argv[5]
sys.path[:0] = [str(root/'integrations/robots/omx/src'), str(root/'contracts/learning/src'), str(root/'test')]
from omx_policy_statistics import assert_train_statistics
from rosy.integrations.robots.omx.policy_runner import LeRobotAdapter, BENCH_POLICY_TYPES, ALLOWED_POLICY_TYPES
assert 'smolvla' not in ALLOWED_POLICY_TYPES
adapter = LeRobotAdapter(str(model), 'cpu', joint_names=[str(i) for i in range(size)],
    cameras=['front'], unit='lerobot_norm_v1',
    allowed_types=BENCH_POLICY_TYPES if policy_type == 'smolvla' else ALLOWED_POLICY_TYPES)
normalizer = next(step for step in adapter.pre.steps if type(step).__name__ == 'NormalizerProcessorStep')
unnormalizer = next(step for step in adapter.post.steps if type(step).__name__ == 'UnnormalizerProcessorStep')
stats = {split:json.loads((splits/split/'meta/stats.json').read_text()) for split in ('train','eval','test')}
assert_train_statistics(normalizer.stats, unnormalizer.stats, stats['train'], [stats['eval'], stats['test']])
assert len(stats['train']['action']['mean']) == size
assert len(set(stats['train']['action']['mean'])) == size
frame = dict(positions=[20.]*size, images={'front':np.full((32,32,3), 60, dtype=np.uint8)})
action = adapter.postprocess(adapter.infer(adapter.preprocess(frame, 'synthetic wiring verification only')))
assert len(action) == size and all(math.isfinite(value) for value in action)
"""
subprocess.run([sys.executable, '-I', '-B', '-c', probe, str(root), str(moved), str(size), str(splits), policy_type],
               env=env, check=True, timeout=180)
print(json.dumps(dict(policy_type=policy_type, joints=size, optimizer_steps=1,
    relocated_offline_reload=True, runner_reloaded=True, normalization_train_only=True, physical_task_success=None,
    policy_revision=receipt['policy_revision'])))
'''


@pytest.mark.parametrize('joints', [6, 12], ids=['single', 'paired'])
def test_actual_smolvla_trains_and_reloads_after_relocation(tmp_path, joints):
    _run_actual_cycle(tmp_path, joints, 'smolvla')


@pytest.mark.parametrize('joints', [6, 12], ids=['single', 'paired'])
def test_actual_act_saved_statistics_are_train_only(tmp_path, joints):
    _run_actual_cycle(tmp_path, joints, 'act')


def _run_actual_cycle(tmp_path, joints, policy_type):
    keys = ('ROSY_OMX_LEROBOT_PYTHON',)
    if policy_type == 'smolvla':
        keys += ('ROSY_SMOLVLA_BASE', 'ROSY_SMOLVLA_VLM_ASSETS')
    if not all(os.environ.get(key) for key in keys):
        pytest.skip('explicit installed learner, SmolVLA base and local VLM metadata are required')
    python = os.environ[keys[0]]
    base = os.environ['ROSY_SMOLVLA_BASE'] if policy_type == 'smolvla' else str(tmp_path)
    vlm = os.environ['ROSY_SMOLVLA_VLM_ASSETS'] if policy_type == 'smolvla' else str(tmp_path)
    assert Path(python).is_file() and Path(base).is_dir() and Path(vlm).is_dir()
    env = dict(os.environ, HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', CUDA_VISIBLE_DEVICES='',
               OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')
    result = subprocess.run([python, '-I', '-B', '-c', DRIVER, str(Path(__file__).resolve().parents[1]),
                             str(tmp_path), base, vlm, str(joints), policy_type],
                            capture_output=True, text=True, env=env, timeout=720)
    assert result.returncode == 0, (result.stdout+'\n'+result.stderr)[-7000:]
    assert '"relocated_offline_reload": true' in result.stdout
    assert '"normalization_train_only": true' in result.stdout
    print(result.stdout.splitlines()[-1])
