"""One fixed, offline MuJoCo dataset preset owned by the Learning Center."""
import argparse
from contextlib import suppress
import json
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time

from experiment_io import identifier, read_json, write_json

MODE = 'world_offline_act'
PRESET_ID = 'mujoco-act-cpu'
ACTIVE = ('launching', 'running', 'stopping')
CGROUP_ROOT = Path('/sys/fs/cgroup')
SHA256 = re.compile(r'[0-9a-f]{64}')
INVOCATION_ID = re.compile(r'[0-9a-f]{32}')
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


def check_dataset(preset, source, revision, root):
    if source != 'scripted_teacher' or revision != preset['dataset_revision']:
        raise ValueError('dataset differs from the pinned MuJoCo teacher dataset')
    try:
        receipt = read_json(root / 'conversion-receipt.json', max_bytes=32768)
    except OSError as exc:
        raise ValueError('the MuJoCo teacher dataset requires its conversion receipt') from exc
    if (not isinstance(receipt, dict) or receipt.get('schema') != 'rosy.omx.mujoco-teacher-conversion/1'
            or receipt.get('dataset_origin') != 'mujoco' or receipt.get('dataset_revision') != revision
            or receipt.get('scene_sha256') != preset['scene_sha256']):
        raise ValueError('the MuJoCo teacher dataset receipt differs from the configured scene')


def check_resources(root, jobs_dir):
    from experiment_cuda_train import check_job_locks

    try:
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            raise ValueError('verified Linux worker stop is unavailable')
        if not shutil.which('systemd-run') or _systemctl('show', '--property=Version', '--value').returncode:
            raise ValueError('model host user service manager is unavailable')
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


def _process_identity(pid):
    proc = Path('/proc') / str(pid)
    stamp = (proc / 'stat').read_text().rsplit(') ', 1)[1].split()[19]
    group = next((line[3:] for line in (proc / 'cgroup').read_text().splitlines()
                  if line.startswith('0::')), None)
    if not group:
        raise ValueError('unified Linux cgroup required')
    return dict(pid=pid, pid_start=stamp, uid=proc.stat().st_uid, cgroup=group)


class Unit:
    def __init__(self, rid):
        identifier(rid)
        self.name = f'rosy-world-act-{rid}.service'
        self.description = f'ROSY World offline ACT {rid}'

    def launch(self, python, root):
        subprocess.run([
            'systemd-run', '--user', '--quiet', '--collect', f'--unit={self.name}',
            f'--description={self.description}', '--property=Type=exec',
            '--property=KillMode=control-group', '--property=PrivateTmp=yes',
            '--property=TimeoutStopSec=10', '--property=RuntimeMaxSec=900',
            '--property=MemoryMax=6G', '--property=CPUQuota=300%',
            '--property=TasksMax=128', '--property=UMask=0077',
            f'--property=LimitFSIZE={MAX_CHECKPOINT_BYTES}', '--property=NoNewPrivileges=yes',
            '--property=UnsetEnvironment=ROSY_WORLD_ID ROSY_WORLD_URL ROSY_WORLD_MDNS_HOST '
            'ROSY_WORLD_PORT ROSY_WORLD_SITE_MAP_SHA256 ROSY_WORLD_INGEST_TOKEN',
            '--setenv=HF_HUB_OFFLINE=1', '--setenv=HF_DATASETS_OFFLINE=1',
            '--setenv=OMP_NUM_THREADS=2', '--setenv=MKL_NUM_THREADS=2',
            '--setenv=OPENBLAS_NUM_THREADS=2', '--setenv=TOKENIZERS_PARALLELISM=false',
            python, '-B', str(Path(__file__)), '--worker', str(root),
        ], capture_output=True, text=True, timeout=LAUNCH_TIMEOUT, check=True)

    def observe(self, receipt):
        response = _systemctl('show', '--property=LoadState,Description,ControlGroup,'
                              'InvocationID,ActiveState,SubState,Result,MainPID', self.name)
        fields = dict(line.split('=', 1) for line in response.stdout.splitlines() if '=' in line)
        cgroup = fields.get('ControlGroup') or receipt.get('cgroup')
        if fields.get('LoadState') == 'not-found':
            return 'gone', _empty_cgroup(cgroup, self.name)
        invocation = fields.get('InvocationID')
        if (response.returncode or fields.get('LoadState') != 'loaded'
                or fields.get('Description') != self.description
                or not INVOCATION_ID.fullmatch(invocation or '')
                or receipt.get('invocation_id', invocation) != invocation
                or receipt.get('cgroup', cgroup) != cgroup):
            raise ValueError('World learner unit ownership is unconfirmed')
        if cgroup:
            empty = _empty_cgroup(cgroup, self.name)
            receipt['cgroup'] = cgroup
        else:
            empty = fields.get('SubState') in ('exited', 'dead', 'failed')
        receipt['invocation_id'] = invocation
        pid = int(fields.get('MainPID', '0'))
        if pid:
            owner = _process_identity(pid)
            if owner['cgroup'] != cgroup or owner['uid'] != os.getuid():
                raise ValueError('World learner process identity is unconfirmed')
            receipt.update(owner)
        if fields.get('ActiveState') in ('inactive', 'failed'):
            return ('failed' if fields.get('Result') != 'success' else 'gone'), empty
        return fields.get('SubState'), empty

    def stop(self, receipt):
        pid = receipt.get('pid')
        if type(pid) is not int or pid <= 0 or not receipt.get('pid_start'):
            raise ValueError('World learner process identity is unconfirmed')
        fd = os.pidfd_open(pid)
        try:
            current = dict(receipt)
            state, _ = self.observe(current)
            owner = _process_identity(pid)
            if (state in ('gone', 'failed', 'exited')
                    or any(current.get(key) != receipt.get(key) for key in ('invocation_id', *owner))
                    or any(receipt.get(key) != value for key, value in owner.items())):
                raise ValueError('World learner process identity changed')
            signal.pidfd_send_signal(fd, signal.SIGUSR1)
        finally:
            os.close(fd)


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


def _claim_launch(root, decision):
    """The worker's entry and revocation compete for one durable decision."""
    import fcntl

    path = root / 'launch-decision.json'
    fd = os.open(root / 'launch.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if path.exists():
            return read_json(path, max_bytes=4096)
        write_json(path, decision)
        return decision
    finally:
        os.close(fd)


def run_worker(root):
    """Retain the host-wide World lease until the owned trainer has stopped."""
    import fcntl

    unit = Unit(root.name)
    owner = _process_identity(os.getpid())
    invocation = os.environ['INVOCATION_ID']
    if not INVOCATION_ID.fullmatch(invocation) or PurePosixPath(owner['cgroup']).name != unit.name:
        raise ValueError('World learner must run in its owned service')
    lease = Path.home() / '.cache' / 'rosy-learning' / 'world-act.lock'
    lease.parent.mkdir(parents=True, exist_ok=True)
    if lease.parent.is_symlink():
        raise ValueError('World learner lease directory must be owned locally')
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGUSR1, request_stop)
    identity = dict(invocation_id=invocation, cgroup=owner['cgroup'])
    if _claim_launch(root, identity) != identity:
        return 1
    exit_code, reason = 1, 'launch_error'
    fd = os.open(lease, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            reason = 'host_busy'
        else:
            if stopping:
                reason = 'stopped'
            else:
                child = subprocess.Popen([
                    sys.executable, '-B', str(Path(__file__).with_name('experiment_train.py')),
                    '--request', str(root / 'request.json'), '--out', str(root / 'output'),
                ], pass_fds=(fd,), start_new_session=True, stdin=subprocess.DEVNULL)
                while child.poll() is None and not stopping:
                    time.sleep(0.25)
                if child.poll() is None:
                    with suppress(ProcessLookupError):
                        os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        with suppress(ProcessLookupError):
                            os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                exit_code = child.returncode
                reason = 'stopped' if stopping else 'finished'
    finally:
        try:
            write_json(root / 'worker-exit.json', dict(invocation_id=invocation,
                cgroup=owner['cgroup'], code=exit_code, reason=reason))
        finally:
            os.close(fd)
    return int(exit_code != 0)


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


def _exit_marker(output, receipt, unit):
    path = output.parent / 'worker-exit.json'
    if not path.exists():
        return None
    marker = read_json(path, max_bytes=4096)
    if (not isinstance(marker, dict) or set(marker) != {'invocation_id', 'cgroup', 'code', 'reason'}
            or not isinstance(marker['invocation_id'], str) or not INVOCATION_ID.fullmatch(marker['invocation_id'])
            or not isinstance(marker['cgroup'], str) or PurePosixPath(marker['cgroup']).name != unit.name
            or type(marker['code']) is not int
            or marker['reason'] not in ('launch_error', 'host_busy', 'stopped', 'finished')
            or any(receipt.get(key, marker[key]) != marker[key] for key in ('invocation_id', 'cgroup'))):
        raise ValueError('invalid World worker exit proof')
    receipt.update({key: marker[key] for key in ('invocation_id', 'cgroup')})
    return marker


def refresh(row, receipt, output):
    unit = Unit(row['id'])
    row.pop('status_uncertain', None)
    marker = None
    try:
        marker = _exit_marker(output, receipt, unit)
    except (OSError, ValueError):
        pass  # invalid completion evidence cannot prevent a verified stop
    try:
        state, empty = unit.observe(receipt)
    except (OSError, ValueError, subprocess.SubprocessError):
        row['status_uncertain'] = True
        return
    if state == 'gone' and empty and not receipt.get('invocation_id'):
        if time.time() > row['created_at'] + 2 * LAUNCH_TIMEOUT:
            try:
                decision = _claim_launch(output.parent, {'revoked': True})
                if decision == {'revoked': True}:
                    if row['status'] == 'stopping':
                        row['status'] = 'cancelled'
                    else:
                        row.update(status='failed', error='학습 실행을 시작하지 못했습니다.')
                    return
                if (set(decision) == {'invocation_id', 'cgroup'}
                        and INVOCATION_ID.fullmatch(decision['invocation_id'])
                        and PurePosixPath(decision['cgroup']).name == unit.name):
                    receipt.update(decision)
            except (OSError, TypeError, ValueError):
                pass
        row['status_uncertain'] = True
        return
    try:
        _progress(row, output)
    except (OSError, ValueError, AttributeError, OverflowError):
        pass  # a bad sample must not prevent a stop
    if row['status'] == 'stopping':
        if state in ('gone', 'failed') and empty:
            if receipt.get('invocation_id'):
                row['status'] = 'cancelled'
            else:
                row['status_uncertain'] = True
        elif state not in ('gone', 'failed', 'stop-sigterm', 'stop-sigkill'):
            try:
                unit.stop(receipt)
            except (OSError, ValueError, subprocess.SubprocessError):
                row['status_uncertain'] = True
        return
    if state not in ('gone', 'failed', 'exited'):
        row['status'] = 'running'
        return
    if not empty or not receipt.get('invocation_id'):
        # A missing unit after an ambiguous RPC is not proof it never started.
        row['status_uncertain'] = True
        return
    if marker and marker['reason'] == 'host_busy':
        row.update(status='failed', error='모델 호스트에서 다른 World 학습이 실행 중입니다.')
    elif not marker or marker['reason'] != 'finished' or marker['code'] != 0 or state == 'failed':
        row.update(status='failed', error='학습 프로세스가 오류로 종료되었습니다.')
    else:
        try:
            _finish(row, output)
        except (OSError, ValueError, AttributeError):
            row.update(status='failed', error='학습 결과를 읽을 수 없습니다.')


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


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--worker', type=Path, required=True)
    raise SystemExit(run_worker(cli.parse_args().worker))
