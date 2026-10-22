"""Reserve a fixed host worker before spawning its independently owned process group."""
import json
import os
from pathlib import Path
import subprocess
import time
import re

from experiment_io import identifier


def check_request(body, methods):
    required = {'dataset_id', 'method', 'steps', 'batch_size', 'device', 'seed', 'request_id'}
    if not isinstance(body, dict) or not required <= body.keys() or set(body) - required - {'profile_id', 'arm_id', 'task_id', 'compute_host'}:
        raise ValueError('learning request fields differ from schema')
    if ('task_id' in body) != ('compute_host' in body):
        raise ValueError('task and compute host are required together')
    if 'task_id' in body:
        identifier(body['task_id'])
        if body['compute_host'] not in ('model', 'ai'):
            raise ValueError('model or ai compute host required')
    identifier(body['dataset_id'])
    identifier(body['request_id'])
    if 'arm_id' in body and (not isinstance(body['arm_id'], str) or not body['arm_id']):
        raise ValueError('explicit arm target identity required')
    if body['device'] != 'cpu':
        raise ValueError('CPU only until shared GPU admission is connected')
    if body['method'] not in methods:
        raise ValueError('unknown learning method')
    for key, lower, upper in [('steps', 1, 100000), ('batch_size', 1, 64), ('seed', 0, 2147483647)]:
        if type(body[key]) is not int or not lower <= body[key] <= upper:
            raise ValueError('learning integer outside allowed range: ' + key)


def check_learning_task(binding, dataset=None, scope=None):
    """Validate the fixed worker snapshot without importing the review database."""
    required = {'task_id', 'task_revision', 'project_id', 'dataset_id', 'dataset_revision',
                'profile_id', 'profile_revision', 'task_participants', 'compute_host',
                'component_ids', 'participants', 'robots'}
    if (not isinstance(binding, dict) or not required <= set(binding)
            or set(binding) - required - {'attachment_kind', 'source_receipts'}):
        raise ValueError('fixed learning task lineage required')
    if len(json.dumps(binding, allow_nan=False).encode('utf-8')) > 65536:
        raise ValueError('bounded learning task lineage required')
    for key in ('task_id', 'dataset_id', 'profile_id'):
        identifier(binding[key])
    for key in ('task_revision', 'dataset_revision', 'profile_revision'):
        if not isinstance(binding[key], str) or not re.fullmatch('[0-9a-f]{64}', binding[key]):
            raise ValueError('task lineage SHA256 revision required')
    def text(value):
        if not isinstance(value, str) or not 1 <= len(value) <= 256 or any(ord(c) < 32 for c in value):
            raise ValueError('bounded task lineage identity required')
    text(binding['project_id'])
    if binding['compute_host'] not in ('model', 'ai'):
        raise ValueError('trusted task compute host required')
    for key in ('task_participants', 'participants'):
        if not isinstance(binding[key], list) or not 1 <= len(binding[key]) <= 32:
            raise ValueError('bounded task participants required')
        for entry in binding[key]:
            if not isinstance(entry, dict) or set(entry) != {'robot_id', 'component_id', 'role'}:
                raise ValueError('fixed task participant required')
            identifier(entry['robot_id'])
            text(entry['component_id'])
            text(entry['role'])
    components = binding['component_ids']
    all_components = [p['component_id'] for p in binding['task_participants']]
    if (not isinstance(components, list) or not components or len(set(all_components)) != len(all_components)
            or components != [p['component_id'] for p in binding['participants']]
            or binding['participants'] != [p for p in binding['task_participants'] if p['component_id'] in components]):
        raise ValueError('task selected component group differs')
    robots = binding['robots']
    if not isinstance(robots, list) or not 1 <= len(robots) <= 32:
        raise ValueError('bounded task robot references required')
    for robot in robots:
        if not isinstance(robot, dict) or set(robot) != {'id', 'kind', 'model_revision', 'device_id', 'revision'}:
            raise ValueError('fixed task robot reference required')
        identifier(robot['id'])
        for key in ('kind', 'model_revision', 'device_id'):
            text(robot[key])
        if not isinstance(robot['revision'], str) or not re.fullmatch('[0-9a-f]{64}', robot['revision']):
            raise ValueError('task robot SHA256 revision required')
    if [r['id'] for r in robots] != list(dict.fromkeys(p['robot_id'] for p in binding['task_participants'])):
        raise ValueError('task robot references differ from participants')
    if 'attachment_kind' in binding and binding['attachment_kind'] != 'historical_dataset_attachment':
        raise ValueError('explicit historical task attachment required')
    receipts = binding.get('source_receipts', [])
    if not isinstance(receipts, list) or len(receipts) > 2:
        raise ValueError('bounded source receipt references required')
    for receipt in receipts:
        if (not isinstance(receipt, dict) or set(receipt) != {'name', 'sha256'}
                or receipt['name'] not in ('native-split-receipt.json', 'conversion-receipt.json')
                or not isinstance(receipt['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', receipt['sha256'])):
            raise ValueError('fixed source receipt hash required')
    if dataset is not None:
        from experiment_profile import profile_revision
        if binding['dataset_revision'] != dataset.revision or binding['profile_revision'] != profile_revision(dataset.profile):
            raise ValueError('learning task source dataset/profile revision differs')
    if scope is not None and (components != scope['arm_ids'] or binding['profile_revision'] != scope['source_profile_revision']):
        raise ValueError('learning task training scope differs')
    return binding


def launch(center, db, request_id, request, row, stamp):
    rid = row['id']
    root = center.root / 'runs' / rid
    db.execute('INSERT INTO runs VALUES (?,?,?,?,?)',
               (rid, request_id, json.dumps(row), request,
                json.dumps({'launcher': stamp(os.getpid())})))
    db.commit()
    env = dict(os.environ, OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
               HF_HUB_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
    child = None
    try:
        with (root / 'worker.log').open('wb') as log:
            worker = {'online_experience': 'experiment_online.py',
                      'native_export': 'experiment_export.py'}.get(row['execution_mode'], 'experiment_train.py')
            child = subprocess.Popen([center.python[row['method']], str(Path(__file__).with_name(worker)),
                '--request', str(root / 'request.json'), '--out', str(root / 'output')],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        receipt, deadline = None, time.monotonic() + 2
        while child.poll() is None:
            receipt = stamp(child.pid, root / 'request.json')
            if receipt or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        if not receipt:
            raise ValueError('learner process identity could not be established')
        row['status'] = 'running'
        db.execute('UPDATE runs SET document=?,process=? WHERE id=?',
                   (json.dumps(row), json.dumps(receipt), rid))
        db.commit()
        center.children[rid] = child
    except Exception:
        if child and child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        row.update(status='failed', error='Worker launch failed')
        db.execute('UPDATE runs SET document=? WHERE id=?', (json.dumps(row), rid))
        db.commit()
        raise
    return row
