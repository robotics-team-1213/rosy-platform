"""One fixed, offline MuJoCo dataset preset owned by the Learning Center."""
import json
import hashlib
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import threading
import time

from experiment_io import identifier, read_json

MODE = 'world_offline_act'
PRESET_ID = 'mujoco-act-cpu'
ACTIVE = ('launching', 'running', 'stopping')
CGROUP_ROOT = Path('/sys/fs/cgroup')
SHA256 = re.compile(r'[0-9a-f]{64}')
LAUNCH_TIMEOUT = 15
MAX_CHECKPOINT_BYTES = 512 * 1024 * 1024


def parse_preset(value, host_id):
    if value is None:
        return None
    fields = {'dataset_id', 'dataset_revision', 'scene_sha256', 'dataset_origin',
              'steps', 'batch_size', 'seed'}
    if (host_id != 'model' or not isinstance(value, dict)
            or not fields <= set(value) <= fields | {'arm_id'}
            or value['dataset_origin'] != 'mujoco'):
        raise ValueError('trusted model-host MuJoCo dataset binding required')
    identifier(value['dataset_id'])
    for field in ('dataset_revision', 'scene_sha256'):
        if not isinstance(value[field], str) or not SHA256.fullmatch(value[field]):
            raise ValueError('pinned MuJoCo dataset and scene SHA-256 required')
    for field, low, high in (('steps', 1, 100), ('batch_size', 1, 8), ('seed', 0, 2**31-1)):
        if type(value[field]) is not int or not low <= value[field] <= high:
            raise ValueError('bounded offline World experiment required: ' + field)
    if 'arm_id' in value and (not isinstance(value['arm_id'], str) or not value['arm_id']):
        raise ValueError('explicit arm target identity required')
    return dict(value)


def check_dataset(preset, source, revision):
    if source != 'scripted_teacher' or revision != preset['dataset_revision']:
        raise ValueError('dataset differs from the pinned MuJoCo teacher dataset')


def check_resources(root, jobs_dir):
    from experiment_cuda_train import check_job_locks

    try:
        subprocess.run(['/usr/local/bin/rosy-storage', 'check'], check=True,
                       capture_output=True, timeout=10)
        check_job_locks(jobs_dir)
        total, used, free = shutil.disk_usage(root)
        if free < 30 * 1024**3 or 10 * used >= 9 * total:
            raise ValueError('insufficient run storage')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ValueError('World experiment host storage or compute is unavailable') from exc


def _systemctl(*args):
    return subprocess.run(['systemctl', '--user', *args],
                          capture_output=True, text=True, timeout=5)


class Unit:
    def __init__(self, rid):
        identifier(rid)
        self.name = f'rosy-world-act-{rid}.service'
        self.description = f'ROSY World offline ACT {rid}'

    def launch(self, python, root):
        subprocess.run([
            'systemd-run', '--user', '--quiet', f'--unit={self.name}',
            f'--description={self.description}', '--property=Type=exec',
            '--property=RemainAfterExit=yes', '--property=KillMode=control-group',
            '--property=TimeoutStopSec=10', '--property=RuntimeMaxSec=900',
            '--property=MemoryMax=6G', '--property=CPUQuota=300%',
            '--property=TasksMax=128', '--property=UMask=0077',
            f'--property=LimitFSIZE={MAX_CHECKPOINT_BYTES}', '--property=NoNewPrivileges=yes',
            '--property=UnsetEnvironment=ROSY_WORLD_ID ROSY_WORLD_URL ROSY_WORLD_MDNS_HOST '
            'ROSY_WORLD_PORT ROSY_WORLD_SITE_MAP_SHA256 ROSY_WORLD_INGEST_TOKEN',
            '--setenv=HF_HUB_OFFLINE=1', '--setenv=HF_DATASETS_OFFLINE=1',
            '--setenv=OMP_NUM_THREADS=2', '--setenv=MKL_NUM_THREADS=2',
            '--setenv=OPENBLAS_NUM_THREADS=2', '--setenv=TOKENIZERS_PARALLELISM=false',
            python, '-B', str(Path(__file__).with_name('experiment_train.py')),
            '--request', str(root / 'request.json'), '--out', str(root / 'output'),
        ], capture_output=True, text=True, timeout=LAUNCH_TIMEOUT, check=True)

    def observe(self, receipt):
        response = _systemctl('show', '--property=LoadState,Description,ControlGroup,'
                              'InvocationID,ActiveState,SubState,Result', self.name)
        fields = dict(line.split('=', 1) for line in response.stdout.splitlines() if '=' in line)
        cgroup = fields.get('ControlGroup') or receipt.get('cgroup')
        if fields.get('LoadState') == 'not-found':
            return 'gone', _empty_cgroup(cgroup, self.name)
        invocation = fields.get('InvocationID')
        if (response.returncode or fields.get('LoadState') != 'loaded'
                or fields.get('Description') != self.description
                or not re.fullmatch(r'[0-9a-f]{32}', invocation or '')
                or receipt.get('invocation_id', invocation) != invocation
                or receipt.get('cgroup', cgroup) != cgroup):
            raise ValueError('World learner unit ownership is unconfirmed')
        if cgroup:
            empty = _empty_cgroup(cgroup, self.name)
            receipt['cgroup'] = cgroup
        else:
            empty = fields.get('SubState') in ('exited', 'dead', 'failed')
        receipt['invocation_id'] = invocation
        if fields.get('ActiveState') in ('inactive', 'failed'):
            return ('failed' if fields.get('Result') != 'success' else 'gone'), empty
        return fields.get('SubState'), empty

    def stop(self):
        response = _systemctl('stop', '--no-block', self.name)
        if response.returncode:
            raise ValueError('World learner stop was not accepted')


def _empty_cgroup(value, name):
    if not value:
        return True  # unit is gone and no process group was observed
    path = PurePosixPath(value)
    if not path.is_absolute() or path.name != name or '..' in path.parts:
        raise ValueError('unexpected World learner cgroup')
    group = CGROUP_ROOT.joinpath(*path.parts[1:])
    try:
        states = (group / 'cgroup.events').read_text(encoding='ascii').splitlines()
    except FileNotFoundError:
        return not group.exists()
    if 'populated 0' in states:
        return True
    if 'populated 1' in states:
        return False
    raise ValueError('World learner cgroup process state is unconfirmed')


def _progress(row, output):
    path = output / 'progress.json'
    if not path.exists():
        return
    data = read_json(path, max_bytes=4096)
    step, loss = data.get('step'), data.get('loss')
    prior = row.get('progress', {}).get('step', 0)
    if (type(step) is int and prior <= step <= row['steps']
            and type(loss) in (int, float) and math.isfinite(loss)):
        row['progress'] = dict(step=step, steps=row['steps'], loss=loss)


def _finish(row, output):
    result_path = output / 'result.json'
    if not result_path.is_file():
        row.update(status='failed', error='학습이 결과를 남기지 않고 종료되었습니다.')
        return
    result = read_json(result_path)
    digest = result.get('policy_sha256')
    checkpoint = output / 'policy/model.safetensors'
    if (result.get('method') != 'act' or result.get('source') != 'scripted_teacher'
            or result.get('execution_mode') != 'offline_replay'
            or result.get('physical_learning_verified') is not False
            or result.get('policy_activation') is not False
            or result.get('dataset_revision') != row['dataset_revision']
            or result.get('optimizer_steps') != row['steps']
            or not isinstance(digest, str) or not SHA256.fullmatch(digest)
            or checkpoint.parent.is_symlink() or checkpoint.is_symlink() or not checkpoint.is_file()
            or not 0 < checkpoint.stat().st_size <= MAX_CHECKPOINT_BYTES):
        row.update(status='failed', error='학습 결과의 실행 근거를 확인할 수 없습니다.')
        return
    with checkpoint.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
            row.update(status='failed', error='체크포인트의 해시가 학습 결과와 일치하지 않습니다.')
            return
    row.update(status='succeeded', result=result)


def refresh(row, receipt, output):
    unit = Unit(row['id'])
    row.pop('status_uncertain', None)
    try:
        state, empty = unit.observe(receipt)
    except (OSError, ValueError, subprocess.SubprocessError):
        row['status_uncertain'] = True
        return
    try:
        _progress(row, output)
    except (OSError, ValueError, AttributeError, OverflowError):
        pass  # a bad sample must not prevent a stop
    if row['status'] == 'stopping':
        if state in ('gone', 'failed') and empty:
            if receipt.get('invocation_id') or time.time() > row['created_at']+2*LAUNCH_TIMEOUT:
                row['status'] = 'cancelled'
        elif state not in ('gone', 'failed', 'stop-sigterm', 'stop-sigkill'):
            try:
                unit.stop()
            except (OSError, ValueError, subprocess.SubprocessError):
                row['status_uncertain'] = True
        return
    if state not in ('gone', 'failed', 'exited'):
        row['status'] = 'running'
        return
    if not empty or (state == 'gone' and not receipt.get('invocation_id')
                     and time.time() <= row['created_at']+2*LAUNCH_TIMEOUT):
        row['status_uncertain'] = True
        return
    if state == 'failed':
        row.update(status='failed', error='학습 프로세스가 오류로 종료되었습니다.')
    else:
        try:
            _finish(row, output)
        except (OSError, ValueError, AttributeError):
            row.update(status='failed', error='학습 결과를 읽을 수 없습니다.')
    if state == 'exited':
        try:
            unit.stop()  # clean up the retained successful transient unit
        except (OSError, ValueError, subprocess.SubprocessError):
            row['status_uncertain'] = True


def launch(center, db, request_id, request, row):
    root = center.root / 'runs' / row['id']
    db.execute('INSERT INTO runs VALUES (?,?,?,?,?)',
               (row['id'], request_id, json.dumps(row), request, '{}'))
    db.commit()  # never launch before the admission and idempotency key are durable
    uncertain = False
    try:
        Unit(row['id']).launch(center.python['act'], root)
    except (OSError, subprocess.SubprocessError):
        # Cancellation or a timeout can race a successful systemd submission.
        # Reconcile by run unit instead of resubmitting or releasing the slot.
        uncertain = True
    db.execute('BEGIN IMMEDIATE')
    document, process = db.execute('SELECT document,process FROM runs WHERE id=?', (row['id'],)).fetchone()
    row, receipt = json.loads(document), json.loads(process)
    if row['status'] in ACTIVE:
        if uncertain:
            row['status_uncertain'] = True
        center._refresh_world_experiment(db, row, receipt)
    return row


def public(row):
    fields = ('id', 'status', 'created_at', 'dataset_revision', 'scene_sha256',
              'steps', 'progress', 'status_uncertain', 'error')
    value = {key: row[key] for key in fields if key in row}
    if 'result' in row:
        value['result'] = {key: row['result'][key] for key in ('policy_sha256', 'optimizer_steps')}
    return value


def start_supervisor(center):
    def supervise():
        while True:
            try:
                with center.lock, center.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    center.refresh_world_experiments(db)
            except (OSError, ValueError, sqlite3.Error):
                pass
            time.sleep(2)

    threading.Thread(target=supervise, name='world-training-supervisor', daemon=True).start()
