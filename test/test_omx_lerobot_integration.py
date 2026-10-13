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
import copy, json, sys
from pathlib import Path
import draccus
import numpy as np
root, tmp = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / 'deploy/robot/omx'))
sys.path.insert(0, str(root / 'learning/curation/omx'))
from record_config import validate_config
from native_review import inspect_dataset, split_reviewed, JOINTS
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
for episode in range(2):
    for frame in range(4):
        vector = np.full(6, episode * 20 + frame, dtype=np.float32)
        writer.add_frame({'observation.state':vector, 'action':vector,
                          'observation.images.front':np.full((32,32,3), episode * 100 + frame, dtype=np.uint8),
                          'task':'Pick cube'})
    writer.save_episode()
writer.finalize()
report = inspect_dataset(source, 'local/native-fixture', body_units='normalized_-100_100',
                         rig_revision='synthetic-rig', calibration_revision='synthetic-calibration')
assert report['frame_count'] == 8 and report['reader_verified']
decisions = copy.deepcopy(report['episodes'])
for decision, split in zip(decisions, ('train', 'eval')):
    decision.update(outcome='success', split=split, reviewer='synthetic-test', reason='fixture only')
out = split_reviewed(source, report, decisions, tmp/'splits')
train = LeRobotDataset('local/native-fixture_train', root=out/'train', video_backend='pyav', download_videos=False)
assert train.meta.total_episodes == 1
assert float(train.meta.stats['action']['max'][0]) == 3.0, 'eval data leaked into train stats'
assert (out/'split-receipt.json').is_file()
from lerobot.configs.train import TrainPipelineConfig
from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.policies.act.modeling_act import ACTPolicy
import torch
torch.set_num_threads(2)
training = json.loads((root/'learning/training/omx/native-act.example.json').read_text())
training['dataset'].update(repo_id='local/native-fixture_train', root=str(out/'train'))
training['output_dir'] = str(tmp/'training')
train_config = draccus.decode(TrainPipelineConfig, training)
assert train_config.policy.push_to_hub is False
train_config.policy.input_features = {
    'observation.state': PolicyFeature(type=FeatureType.STATE, shape=(6,)),
    'observation.images.front': PolicyFeature(type=FeatureType.VISUAL, shape=(3,32,32))}
train_config.policy.output_features = {'action': PolicyFeature(type=FeatureType.ACTION, shape=(6,))}
policy = ACTPolicy(train_config.policy)
batch = {'observation.state':torch.zeros(2,6), 'observation.images.front':torch.zeros(2,3,32,32),
         'action':torch.zeros(2,4,6), 'action_is_pad':torch.zeros(2,4,dtype=torch.bool)}
loss, _ = policy.forward(batch)
assert torch.isfinite(loss)
loss.backward()
torch.optim.AdamW(policy.parameters(), lr=1e-4).step()
policy.save_pretrained(tmp/'model')
loaded = ACTPolicy.from_pretrained(tmp/'model')
loaded.eval()
with torch.no_grad():
    action = loaded.select_action({key:value[:1] for key,value in batch.items() if key.startswith('observation.')})
assert action.shape == (1,6) and torch.isfinite(action).all()
print('OFFICIAL_CONFIG_READER_SPLIT_PASS')
'''
    env = {**os.environ, 'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1',
           'HF_HOME': str(tmp_path / 'hf'), 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2'}
    result = subprocess.run([str(PYTHON), '-c', script, str(ROOT), str(tmp_path)],
                            capture_output=True, text=True, env=env, timeout=180)
    assert result.returncode == 0, result.stdout + '\n' + result.stderr
    assert 'OFFICIAL_CONFIG_READER_SPLIT_PASS' in result.stdout
