"""One SDK process tree in its own transient unit, with bounded evidence."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time

from import_report import verify_report
from prepare_omx_urdf import prepare
from run_admission import acquire, gpu_state
from run_binding import load_binding, sdk_check
from run_store import RunConflict, TERMINAL, input_snapshot
from run_system import System


def _budget(directory):
    count, size = 0, 0
    for base, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            path = Path(base) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                return 'unsafe_output'
            if stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    return 'unsafe_output'
                count += 1
                size += info.st_size
                if info.st_size > 128 * 1024 * 1024:
                    return 'output_limit'
    return 'output_limit' if count > 256 or size > 256 * 1024 * 1024 else None


def _reap(child):
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=2)
    # A grandchild may still be in the owned group after its parent exited.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def supervise(argv, *, cwd, env, descriptors, output, stop_requested, timeout=165,
              log_limit=16 * 1024 * 1024):
    deadline, written, reason = time.monotonic() + timeout, 0, None
    child = subprocess.Popen(argv, cwd=cwd, env=env, pass_fds=tuple(descriptors),
                             start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        with selectors.DefaultSelector() as selector, (output / 'sdk.log').open('xb') as log:
            os.set_blocking(child.stdout.fileno(), False)
            selector.register(child.stdout, selectors.EVENT_READ)
            while True:
                if stop_requested():
                    reason = 'stop_requested'
                elif time.monotonic() >= deadline:
                    reason = 'runtime_limit'
                else:
                    reason = _budget(output)
                if reason:
                    break
                if selector.select(0.05):
                    chunk = os.read(child.stdout.fileno(), 65536)
                    if chunk:
                        keep = min(len(chunk), max(0, log_limit - written))
                        log.write(chunk[:keep])
                        written += keep
                        if keep < len(chunk):
                            reason = 'output_limit'
                            break
                    elif child.poll() is not None:
                        break
                elif child.poll() is not None:
                    break
            log.flush()
            os.fsync(log.fileno())
    finally:
        _reap(child)
        child.stdout.close()
    return {'exit_code': child.returncode, 'reason': reason or _budget(output) or 'process_exited'}


def _cleanup(owner):
    """Use pidfds inside our verified cgroup; never signal an external GPU PID."""
    group = Path('/sys/fs/cgroup') / owner['cgroup'].lstrip('/')
    own_group = Path('/proc/self/cgroup').read_text().strip()
    if own_group != '0::' + owner['cgroup'] or owner.get('main_pid') != os.getpid():
        return False
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid_text in (group / 'cgroup.procs').read_text().split():
            pid = int(pid_text)
            if pid == os.getpid():
                continue
            try:
                fd = os.pidfd_open(pid)
                try:
                    if Path('/proc', pid_text, 'cgroup').read_text().strip() == own_group:
                        signal.pidfd_send_signal(fd, sig)
                finally:
                    os.close(fd)
            except ProcessLookupError:
                pass
        until = time.monotonic() + 1
        while time.monotonic() < until:
            if set((group / 'cgroup.procs').read_text().split()) <= {str(os.getpid())}:
                return True
            time.sleep(0.05)
    return False


def execute(store, binding_file, run_id, *, expected_binding_sha256=None):
    options = {'expected_digest': expected_binding_sha256} if expected_binding_sha256 else {}
    binding = load_binding(binding_file, **options)
    row = store.get(run_id)
    if row['status'] in TERMINAL:
        return 0
    expected = input_snapshot(row['input']['scenario_id'],
                              {'seed': row['input']['config']['seed']}, binding['source_sha'])
    if expected['input_sha256'] != row['input_sha256']:
        raise ValueError('Worker source and immutable input differ')
    owner = System().observe('rosy-isaac-' + run_id + '.service')
    if (owner['invocation_id'] != os.environ.get('INVOCATION_ID')
            or owner['main_pid'] != os.getpid() or not owner['cgroup']):
        raise ValueError('Worker lacks its own confirmed unit')
    stop = [False]
    signal.signal(signal.SIGTERM, lambda signum, frame: stop.__setitem__(0, True))
    signal.signal(signal.SIGUSR1, lambda signum, frame: stop.__setitem__(0, True))
    directory = store.root / 'runs' / run_id
    artifacts, report, outcome = [], None, {'exit_code': None, 'reason': 'admission_refused'}

    def stopped():
        return stop[0] or store.get(run_id)['status'] == 'STOP_REQUESTED'

    leased = False
    try:
        # Check the installed SDK without loading SimulationApp before leasing it.
        admitted_gpu = sdk_check(binding)
        with acquire(binding) as descriptors:
            leased = True
            try:
                binding = load_binding(binding_file, row['input']['source_sha'], **options)
                row = store.get(run_id)
                if stopped():
                    outcome['reason'] = 'stop_requested'
                else:
                    row = store.update(run_id, row['revision'],
                        {'status': 'RUNNING', 'phase': 'SDK_IMPORT', 'runtime': dict(owner, gpu=admitted_gpu)})
                    urdf = prepare('omx_f', directory / 'prepared.urdf')
                    env = {key: os.environ[key] for key in ('HOME', 'USER', 'LOGNAME', 'XDG_RUNTIME_DIR')
                           if key in os.environ}
                    env.update(PATH='/usr/local/bin:/usr/bin:/bin', LANG='C.UTF-8',
                               ROS_DOMAIN_ID='99', ROS_LOCALHOST_ONLY='1',
                               ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST', ROS_STATIC_PEERS='',
                               PYTHONUNBUFFERED='1', ACCEPT_EULA='Y')
                    argv = [binding['sdk_python'], str(Path(__file__).with_name('import_omx.py')),
                            '--model', 'omx_f', '--urdf', str(urdf), '--output-dir', str(directory / 'usd'),
                            '--headless', '--frames', '120', '--report', str(directory / 'import-report.json')]
                    outcome = supervise(argv, cwd=directory, env=env, descriptors=descriptors,
                                        output=directory, stop_requested=stopped)
                    if outcome['exit_code'] == 0 and outcome['reason'] == 'process_exited':
                        report = verify_report(directory / 'import-report.json', model='omx_f', frames=120,
                                               sdk_version=binding['sdk_version'])
            except (OSError, ValueError, subprocess.SubprocessError):
                outcome['reason'] = 'sdk_or_report_verification_failed'
                report = None
            try:
                clean = _cleanup(owner)
            except OSError:
                clean = False
            until = time.monotonic() + 3
            observed_gpu = gpu_state()
            while clean and not observed_gpu['ready'] and time.monotonic() < until:
                time.sleep(0.2)
                observed_gpu = gpu_state()
            if not clean or not observed_gpu['ready']:
                current = store.get(run_id)
                store.update(run_id, current['revision'], {'status': 'UNKNOWN',
                             'cleanup': 'UNCONFIRMED', 'error': 'owned cleanup or GPU release unconfirmed'})
                return 2
            if report is not None:
                raw = (directory / 'import-report.json').read_bytes()
                artifacts = [{'id': 'import-report', 'name': 'import-report.json', 'bytes': len(raw),
                              'sha256': hashlib.sha256(raw).hexdigest(), 'media_type': 'application/json'}]
            return _finish(store, run_id, outcome, report, artifacts, stopped(), gpu=admitted_gpu)
    except (OSError, ValueError, subprocess.SubprocessError):
        if leased:
            raise
        # No SDK launch occurs outside the lease; admission failures have no child to clean up.
        outcome['reason'] = 'admission_refused'
        return _finish(store, run_id, outcome, None, [], stopped(), cleanup='SDK_NOT_STARTED')


def _finish(store, run_id, outcome, report, artifacts, stopped, *, gpu=None,
            cleanup='OWNED_PROCESSES_EXITED_GPU_RELEASED'):
    current = store.get(run_id)
    status = 'STOPPED' if stopped else ('SUCCEEDED' if report else 'FAILED')
    result = dict(outcome, status=status, stage='model_import', task_success=None,
                  import_verified=report is not None, completed_frames=report['completed_frames'] if report else None,
                  cleanup=cleanup, gpu=gpu, video_unavailable_reason='model_import_does_not_record_video')
    try:
        store.finish(run_id, current['revision'], result, artifacts)
    except RunConflict:
        current = store.get(run_id)
        if current['status'] == 'STOP_REQUESTED':
            result['status'] = 'STOPPED'
            store.finish(run_id, current['revision'], result, artifacts)
        else:
            raise
    return 0 if status in {'SUCCEEDED', 'STOPPED'} else 1
