"""Opt-in CPU task-to-artifact verification in an existing isolated learner environment."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


DRIVER = r'''
import hashlib, io, json, pathlib, sys, time, uuid, zipfile
source, root, python, host = map(str, sys.argv[1:])
source, root = pathlib.Path(source), pathlib.Path(root)
sys.path[:0] = [str(source/'learning/training/omx'), str(source/'learning/curation/perception')]
from experiment_center import Center
from experiment_smoke import generate
from learning_tasks import Tasks
center = Center(dict(schema='rosy.omx.center-config/1', root=str(root/'center'),
    python=dict(act=python, hilserl=python), host_id=host))
center.bind_workspace('synthetic-learning-verification')
center.tasks = Tasks(root/'review.sqlite', 'synthetic-learning-verification')
uid = lambda: str(uuid.uuid4())
actor = dict(user_id='synthetic-test-operator')
did = uid()
generate(center.root/'uploads'/did, arms=2, cameras=3)
data = center.publish(dict(upload_id=did, name='Synthetic verification only'))
profile = json.loads((center.root/'datasets'/did/'dataset.json').read_text())['profile']
saved = center.profiles.save(dict(profile=profile, request_id=uid()))
participants = []
for index, arm in enumerate(profile['arms']):
    robot = center.tasks.robot(dict(request_id=uid(), name='Synthetic arm '+str(index),
        kind='omx', model_revision='synthetic-only', device_id='synthetic-device-'+str(index)), actor)
    participants.append(dict(robot_id=robot['id'], component_id=arm['id'], role='arm-'+str(index)))
task = center.tasks.task(dict(request_id=uid(), name='Synthetic cooperative verification',
    objective='Verify model plumbing', success='Model reloads', failure='Worker fails',
    reset='Create new synthetic fixture', mode='cooperative', adapter='omx',
    participants=participants, profile_id=saved['id']), actor, saved)
proof = []
try:
    for method in ('act', 'hilserl'):
        assert center.methods[method]['available'], 'pinned learner unavailable: '+method
        row = center.start(dict(dataset_id=did, task_id=task['id'], compute_host=host,
            method=method, steps=2, batch_size=2, device='cpu', seed=7, request_id=uid()))
        deadline = time.monotonic()+180
        while time.monotonic() < deadline:
            row = next(item for item in center.snapshot()['runs'] if item['id']==row['id'])
            if row['status'] not in ('launching', 'running', 'stopping'): break
            time.sleep(.2)
        assert row['status']=='succeeded', (method, row['status'], row.get('error'))
        assert row['result']['physical_learning_verified'] is False
        with zipfile.ZipFile(io.BytesIO(center.artifact(row['id']))) as archive:
            evaluation = archive.read('evaluation.json')
            receipt = json.loads(archive.read('learning-task.json'))
            assert receipt['task_id']==task['id'] and receipt['compute_host']==host
            assert receipt['evaluation_sha256']==hashlib.sha256(evaluation).hexdigest()
            assert len(receipt['robots'])==2
            assert json.loads(evaluation)['frames']>0
            assert archive.read('policy/model.safetensors')
        proof.append(dict(method=method, status=row['status'], steps=row['result']['steps']))
finally:
    for run in center.snapshot()['runs']:
        if run['status'] in ('running','launching','stopping'):
            center.stop(dict(id=run['id']))
print(json.dumps(dict(host=host, methods=proof, physical_learning_verified=False)))
'''


def test_pinned_task_models_train_reload_and_download(tmp_path):
    if os.environ.get('ROSY_RUN_PINNED_LEARNING') != '1':
        pytest.skip('explicit existing isolated learner environment required')
    python = Path.home()/'.local/share/rosy-learning-center/venv-cpu/bin/python'
    assert python.is_file(), 'existing pinned learner Python is unavailable'
    host = os.environ.get('ROSY_LEARNING_TEST_HOST_ID')
    assert host in ('model', 'ai')
    source = Path(__file__).resolve().parents[4]
    env = {key: os.environ[key] for key in ('HOME', 'PATH', 'USER', 'LOGNAME') if key in os.environ}
    env.update(HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', CUDA_VISIBLE_DEVICES='',
               OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')
    with (tmp_path/'learner.log').open('wb') as log:
        result = subprocess.run([str(python), '-I', '-B', '-c', DRIVER, str(source),
            str(tmp_path), str(python), host], stdout=log, stderr=subprocess.STDOUT,
            env=env, timeout=450, check=False)
    assert result.returncode == 0, (tmp_path/'learner.log').read_text(errors='replace')[-4000:]
    proof = json.loads((tmp_path/'learner.log').read_text().splitlines()[-1])
    assert [row['method'] for row in proof['methods']] == ['act', 'hilserl']
    assert proof['physical_learning_verified'] is False
