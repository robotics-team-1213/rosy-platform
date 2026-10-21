"""Reserve a fixed host worker before spawning its independently owned process group."""
import json
import os
from pathlib import Path
import subprocess
import time

from experiment_io import identifier


def check_request(body, methods):
    required = {'dataset_id', 'method', 'steps', 'batch_size', 'device', 'seed', 'request_id'}
    if not required <= body.keys() or set(body) - required - {'profile_id', 'arm_id'}:
        raise ValueError('learning request fields differ from schema')
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
