"""Official native ACT reload after fixture Hub transport; no device or real HF access."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from test_hub_export_native import download
from test_hub_sync import FakeHub, module  # noqa: F401

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize('bimanual', [False, True], ids=['single', 'paired'])
def test_native_model_roundtrip_reloads_downloaded_checkpoint(module, tmp_path, monkeypatch, bimanual):
    monkeypatch.setenv('HF_HUB_OFFLINE', '1')
    monkeypatch.setenv('HF_DATASETS_OFFLINE', '1')
    pytest.importorskip('lerobot')
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    for relative in ('learning/curation/omx', 'learning/training/omx'):
        monkeypatch.syspath_prepend(str(ROOT/relative))
    import native_review as native
    import native_segments as segments
    import native_cycle

    names = ([f'{arm}.{joint}' for arm in ('arm_a', 'arm_b') for joint in native.JOINTS]
             if bimanual else list(native.JOINTS))
    size = len(names)
    robot_type = 'bi_omx_follower' if bimanual else 'omx_follower'
    repo_id = 'local/synthetic-native-model-roundtrip'
    features = {key: dict(dtype='float32', shape=(size,), names=names)
                for key in ('action', 'observation.state')}
    features['observation.images.front'] = dict(dtype='video', shape=(32, 32, 3),
                                               names=['height', 'width', 'channels'])
    source = tmp_path/'native'
    writer = LeRobotDataset.create(repo_id=repo_id, root=source, fps=30, robot_type=robot_type,
        features=features, use_videos=True, video_backend='pyav', vcodec='h264', batch_encoding_size=1)
    try:
        for episode in range(2):
            for frame in range(8):
                action = np.arange(size, dtype=np.float32) + episode*20 + frame
                writer.add_frame(dict(action=action, **{'observation.state': action-1,
                    'observation.images.front': np.full((32, 32, 3), episode*80+frame*10, dtype=np.uint8)},
                    task='synthetic model transfer integration; no physical task'))
            writer.save_episode(parallel_encoding=False)
    finally:
        writer.finalize()
    provenance = dict(schema='rosy.omx-native-capture.v1', source_mode='scripted_teacher',
        action_semantics='absolute_joint_position_target_normalized', body_units='normalized_-100_100',
        gripper_units='normalized_0_100', rig_revision='synthetic-fixture-rig',
        calibration_revision='synthetic-fixture-not-physical',
        teacher_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        files=native.dataset_files(source), episodes=[dict(episode_index=i,
            session_id=f'synthetic-session-{i}', cycle_id=f'synthetic-cycle-{i}') for i in range(2)])
    report = native.inspect_dataset(source, repo_id, body_units=provenance['body_units'],
        rig_revision=provenance['rig_revision'], calibration_revision=provenance['calibration_revision'],
        source_mode='scripted_teacher', capture_provenance=provenance)
    rows = [dict(**{key: episode[key] for key in
                    ('episode_index', 'content_sha256', 'frames', 'session_id', 'cycle_id')},
                 start_frame=2, end_frame=5, object='synthetic-fixture', intervention=False,
                 outcome='success', reviewer='synthetic_contract_fixture_not_human',
                 reason='synthetic label for SDK wiring only', split=split)
            for episode, split in zip(report['episodes'], ('train', 'eval'))]
    splits = tmp_path/'segments'
    split_receipt = segments.export_segments(source, report, segments.selection(report, rows), splits)
    assert split_receipt['reader_verified'] and split_receipt['splits'] == {'train': [0], 'eval': [1]}
    split_bytes = (splits/'split-receipt.json').read_bytes()
    cycle = native_cycle.run_cycle(splits, tmp_path/'cycle', steps=2, batch_size=2,
                                   device='cpu', timeout=300)
    assert cycle['offline_only'] and not cycle['device_execution'] and not cycle['promotion']
    model = (tmp_path/'cycle/trainer/checkpoints/last/pretrained_model').resolve()
    original = native_cycle._artifact_files(model)
    assert original == cycle['artifact_files']
    hub = FakeHub()
    bundle = module.prepare_bundle(model, tmp_path/'bundle', 'team/native-act', 'model', sorted(original))
    transport = module.upload_bundle(bundle, api=hub, operation=SimpleNamespace, downloader=download(hub))
    assert transport['bytes_verified'] and transport['reader_verified'] is False
    assert transport['files'] == original and transport['revision'] == 'b'*40
    readback = bundle/'readback'
    assert native_cycle._artifact_files(readback) == original

    def verify(checkpoint, name, timeout):
        output, log = tmp_path/f'{name}.json', tmp_path/f'{name}.log'
        command = [sys.executable, str(ROOT/'learning/training/omx/native_cycle.py'), 'verify',
                   '--model', str(checkpoint), '--splits', str(splits), '--repo-id', repo_id,
                   '--out', str(output)]
        with log.open('x') as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                    env={**os.environ, 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2'},
                                    timeout=timeout)
        return result.returncode, output, log

    code, output, log = verify(readback, 'post-transfer-evaluation', 300)
    assert code == 0, log.read_text()[-4000:]
    evaluation = json.loads(output.read_bytes())
    assert evaluation['model_reloaded_in_new_process'] is True
    assert evaluation['joint_names'] == names and evaluation['samples'] == 3
    assert evaluation['split'] == 'eval' and evaluation['physical_task_success'] is None
    for key in ('mae_per_joint', 'train_mean_baseline_mae_per_joint'):
        assert len(evaluation[key]) == size and all(math.isfinite(value) for value in evaluation[key])
    assert native_cycle.validate_split(splits) == split_receipt
    assert (splits/'split-receipt.json').read_bytes() == split_bytes
    assert native_cycle._artifact_files(model) == original
    assert native_cycle._artifact_files(readback) == original
    assert native.dataset_files(source) == provenance['files']

    broken = tmp_path/'missing-processor'
    shutil.copytree(readback, broken)
    (broken/'policy_preprocessor.json').unlink()
    code, output, log = verify(broken, 'missing-processor-evaluation', 30)
    assert code != 0 and not output.exists()
    assert 'missing model artifact: policy_preprocessor.json' in log.read_text()
