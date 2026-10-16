"""Real LeRobot export environment smoke; synthetic records never assert field acceptance."""
import os
from pathlib import Path
import subprocess

import pytest


def test_collection_intake_real_native_split_roundtrip(tmp_path):
    python = os.environ.get('ROSY_OMX_LEROBOT_PYTHON')
    if not python:
        pytest.skip('set ROSY_OMX_LEROBOT_PYTHON to the pinned LeRobot 0.4.4 export environment')
    assert Path(python).is_file(), 'configured LeRobot interpreter is missing'
    root = Path(__file__).resolve().parents[1]
    script = r'''
import importlib.metadata
import json
from pathlib import Path
import sys
assert importlib.metadata.version('lerobot') == '0.4.4'
repo, work = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repo/'learning/curation/omx'))
sys.path.insert(0, str(repo/'learning/training/omx'))
sys.path.insert(0, str(repo/'deploy/robot/omx'))
from collection_store import RawCollection, append
from collection_intake import prepare
from native_review import load_dataset, split_reviewed
from native_cycle import run_cycle, validate_split
sessions = []
for i in range(3):
    source = work/f'raw-{i}'
    start = 100+i*100
    profile = dict(rig_revision='synthetic-rig', calibration_revision='synthetic-cal', fps=10,
                   task='synthetic pipeline fixture', camera_shapes={r:[32,32,3] for r in ('top','front')})
    # The journal is exercised directly; this fixture never invokes a motion backend.
    store = RawCollection(source, profile, 'b'*64, 'hardware')
    event = dict(policy='omx-photometric-v3', run_id=f'synthetic-run-{i}', profile_sha256='a'*64,
                 recorded_ns=start, motion_admitted=False, physical_acceptance=False,
                 photometric_ready=False, observations={}, environment={r:dict(state='OBSERVING',
                     condition=None, environment_epoch=0, control_generation=0) for r in ('top','front')})
    append(source/'environment.jsonl', event)
    episode = store.begin(start, event)
    observation = dict(time_ns=start+1, observation_state=[0.]*6, action=[float(i+1)]*6,
                       joint_source_stamp=1.+i, reference_source_stamp=1.+i,
                       images={r:dict(data=bytes([100,110,120])*1024, width=32, height=32,
                                      source_stamp=1.+i) for r in ('top','front')})
    store.sample(episode, observation, [0.]*6)
    episode.update(complete=True, reason='', end_ns=start+10)
    store.close(dict(hold_requested=True, physical_stop_verified=False))
    sessions.append(source)
dataset = work/'dataset'
receipt = prepare(sessions, dataset, 'rosy-fixture/collection')
report = json.loads((dataset/'inspection.json').read_text())
decisions = json.loads((dataset/'decisions.json').read_text())
assert report['reader_verified'] and report['frame_count'] == 3
reader = load_dataset(dataset, 'rosy-fixture/collection')
for i in range(3):
    assert reader[i]['action'].tolist() == [float(i+1)]*6
    assert reader[i]['observation.state'].tolist() == [0.]*6
assert all(e['outcome'] == 'unknown' and e['split'] == 'exclude' for e in decisions)
for decision, split in zip(decisions, ('train','eval','test')):
    decision.update(outcome='success', split=split, reviewer='synthetic test fixture',
                    reason='synthetic labels for byte and pipeline compatibility only')
splits = work/'splits'
split_reviewed(dataset, report, decisions, splits)
bound = validate_split(splits)
assert bound['splits'] == dict(train=[0], eval=[1], test=[2])
assert all(bound['environment_coverage'][name]['episodes'] == 1 for name in ('train','eval','test'))
assert bound['source']['environment_summary']['physical_acceptance'] is False
assert receipt['sessions'][0]['manifest_sha256']
assert not receipt['uploaded']
cycle = run_cycle(splits, work/'act-cycle', steps=2, batch_size=1, device='cpu', timeout=240)
assert (work/'act-cycle').is_dir()
print('verified synthetic closed-record intake -> LeRobot reader -> independent reviewed splits -> trainer input')
'''
    result = subprocess.run([python, '-c', script, str(root), str(tmp_path)],
                            env={**os.environ, 'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1'},
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout+'\n'+result.stderr
    assert 'verified synthetic closed-record intake' in result.stdout
