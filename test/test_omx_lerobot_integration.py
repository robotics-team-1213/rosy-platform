"""Optional real LeRobot 0.4.4 checks in a separate remote CPU environment."""
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(os.environ.get('ROSY_OMX_LEROBOT_PYTHON',
                            str(Path.home() / 'rosy-test/venvs/omx-lerobot-0.4.4/bin/python')))


@pytest.mark.skipif(not PYTHON.is_file(), reason='isolated LeRobot 0.4.4 CPU environment not configured')
def test_official_config_reader_and_split_roundtrip(tmp_path):
    script = r'''
import copy, hashlib, json, subprocess, sys
from pathlib import Path
import draccus
import numpy as np
root, tmp = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / 'deploy/robot/omx'))
sys.path.insert(0, str(root / 'learning/curation/omx'))
from record_config import validate_config
from native_review import inspect_dataset, split_reviewed, dataset_files, JOINTS
from lerobot.scripts.lerobot_record import RecordConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset
config = json.loads((root / 'deploy/robot/omx/lerobot-record.example.json').read_text())
config['robot'].update(id='fixture-follower', port='/dev/serial/by-id/fixture-follower', max_relative_target=1.0)
config['teleop'].update(id='fixture-leader', port='/dev/serial/by-id/fixture-leader')
config['robot']['cameras']['front']['index_or_path'] = '/dev/v4l/by-id/fixture-camera'
config['dataset'].update(repo_id='local/native-fixture', root=str(tmp / 'not-recorded'), single_task='Pick cube')
validate_config(config)
parsed = draccus.decode(RecordConfig, config)
assert parsed.robot.use_degrees is False
assert parsed.dataset.push_to_hub is False and parsed.dataset.private is True
features = {key: {'dtype':'float32','shape':(6,), 'names':JOINTS}
            for key in ('action', 'observation.state')}
features['observation.images.front'] = {'dtype':'video', 'shape':(32,32,3), 'names':['height','width','channels']}
source = tmp / 'source'
writer = LeRobotDataset.create(repo_id='local/native-fixture', root=source, fps=10,
                               robot_type='omx_follower', features=features, use_videos=True,
                               video_backend='pyav', vcodec='h264')
for episode in range(3):
    for frame in range(4):
        vector = np.full(6, episode * 20 + frame, dtype=np.float32)
        writer.add_frame({'observation.state':vector, 'action':vector,
                          'observation.images.front':np.full((32,32,3), episode * 100 + frame, dtype=np.uint8),
                          'task':'Pick cube'})
    writer.save_episode()
writer.finalize()
provenance = dict(schema='rosy.omx-native-capture.v1', source_mode='scripted_teacher',
                  teacher_sha256=hashlib.sha256(b'synthetic teacher fixture only').hexdigest(),
                  action_semantics='absolute_joint_position_target_normalized',
                  body_units='normalized_-100_100', gripper_units='normalized_0_100',
                  rig_revision='synthetic-rig', calibration_revision='synthetic-calibration',
                  files=dataset_files(source),
                  episodes=[dict(episode_index=i, session_id=f'fixture-session-{i}',
                                 cycle_id=f'fixture-cycle-{i}') for i in range(3)])
events, windows = [], []
for i, condition in enumerate(('UNDEREXPOSED', 'OVEREXPOSED', 'MIXED_LIGHTING')):
    stamp = (i+1)*10**9
    events.append(dict(policy='omx-photometric-v3', run_id=f'synthetic-run-{i}',
                       profile_sha256='d'*64, recorded_ns=stamp, expires_ns=stamp+750_000_000,
                       motion_admitted=False, physical_acceptance=False, photometric_ready=False,
                       environment={r: dict(condition=condition, state='OBSERVING',
                                            environment_epoch=1, control_generation=0) for r in ('top', 'front')},
                       observations={r: dict(fresh=True, source_stamp=i+1., sequence=1,
                           receipt_age_s=0., source_age_s=0., quality=dict(policy='omx-photometric-v3',
                           condition=condition, usable=False, mean_intensity=100., spatial_contrast=20.,
                           p5=20., p95=180., dark_fraction=.1, clipped_fraction=.01)) for r in ('top', 'front')}))
    windows.append(dict(episode_index=i, start_ns=stamp, end_ns=stamp+500_000_000,
                        run_id=f'synthetic-run-{i}', profile_sha256='d'*64))
log, window_file = tmp/'synthetic-environment.jsonl', tmp/'synthetic-windows.json'
log.write_text(''.join(json.dumps(e)+'\n' for e in events))
window_file.write_text(json.dumps(windows))
sealed = tmp/'sealed'
subprocess.run([sys.executable, str(root/'learning/curation/omx/native_review.py'), 'seal-environment',
                str(source), '--log', str(log), '--windows', str(window_file),
                '--rig-revision', 'synthetic-rig', '--calibration-revision', 'synthetic-calibration',
                '--out', str(sealed)], check=True)
environment = json.loads((sealed/'environment.json').read_text())
assert environment['log_sha256'] == hashlib.sha256(log.read_bytes()).hexdigest()
report = inspect_dataset(source, 'local/native-fixture', body_units='normalized_-100_100',
                         rig_revision='synthetic-rig', calibration_revision='synthetic-calibration',
                         source_mode='scripted_teacher', capture_provenance=provenance,
                         environment_evidence=environment)
assert report['frame_count'] == 12 and report['reader_verified']
assert report['source_mode'] == 'scripted_teacher'
decisions = copy.deepcopy(report['episodes'])
for decision, split in zip(decisions, ('train', 'eval', 'test')):
    decision.update(outcome='success', split=split, reviewer='synthetic-test', reason='fixture only')
out = split_reviewed(source, report, decisions, tmp/'splits')
train = LeRobotDataset('local/native-fixture_train', root=out/'train', video_backend='pyav', download_videos=False)
assert train.meta.total_episodes == 1
assert float(train.meta.stats['action']['max'][0]) == 3.0, 'eval data leaked into train stats'
assert (out/'split-receipt.json').is_file()
receipt = json.loads((out/'split-receipt.json').read_text())
assert receipt['source']['capture_provenance'] == provenance
assert receipt['source']['environment_evidence'] == environment
assert receipt['environment_coverage']['eval']['roles']['front'] == {'OVEREXPOSED': 1}
assert receipt['splits'] == dict(train=[0], eval=[1], test=[2])
assert receipt['outputs'] == {name:dataset_files(out/name) for name in ('train','eval','test')}
assert LeRobotDataset('local/native-fixture_test', root=out/'test',
                     video_backend='pyav', download_videos=False).meta.total_episodes == 1
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_pre_post_processors
import torch
torch.set_num_threads(2)
sys.path.insert(0, str(root/'learning/training/omx'))
from native_cycle import run_cycle
cycle = run_cycle(out, tmp/'training', steps=2, batch_size=2, device='cpu', timeout=120)
assert cycle['offline_only'] and cycle['source_mode'] == 'scripted_teacher'
assert cycle['evaluation']['samples'] == 4
assert len(cycle['evaluation']['mae_per_joint']) == 6
assert cycle['evaluation']['physical_task_success'] is None
assert cycle['split_files'] == receipt['outputs']
assert cycle['environment_coverage'] == receipt['environment_coverage']
assert cycle['evaluation']['environment_coverage'] == receipt['environment_coverage']
assert cycle['environment_summary']['photometric_continuity_verified'] is False
model = tmp/'training/trainer/checkpoints/last/pretrained_model'
assert (model/'policy_preprocessor.json').is_file()
assert (model/'policy_postprocessor.json').is_file()
loaded = ACTPolicy.from_pretrained(model)
pre, post = make_pre_post_processors(loaded.config, pretrained_path=str(model))
batch = next(iter(torch.utils.data.DataLoader(train, batch_size=1)))
loaded.eval()
with torch.no_grad():
    action = post(loaded.select_action(pre(batch)))
assert action.shape == (1,6) and torch.isfinite(action).all()
print('OFFICIAL_CONFIG_READER_SPLIT_PASS')
'''
    env = {**os.environ, 'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1',
           'HF_HOME': str(tmp_path / 'hf'), 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2'}
    result = subprocess.run([str(PYTHON), '-c', script, str(ROOT), str(tmp_path)],
                            capture_output=True, text=True, env=env, timeout=180)
    assert result.returncode == 0, result.stdout + '\n' + result.stderr
    assert 'OFFICIAL_CONFIG_READER_SPLIT_PASS' in result.stdout
