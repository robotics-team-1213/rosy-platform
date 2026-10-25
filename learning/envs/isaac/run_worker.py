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
                    contact_task = row['input']['scenario_id'] == 'pinky-conveyor-roundtrip'
                    arm_task = row['input']['scenario_id'].startswith('arm-s-cell-')
                    report_path = directory / ('contact-report.json' if contact_task else
                                               'arm-s-cell-report.json' if arm_task else 'import-report.json')
                    if arm_task:  # the real cell's chunk frames for this scenario (system python: the planner)
                        frames = directory / 'frames.json'
                        repo = Path(__file__).resolve().parents[3]
                        subprocess.run(['/usr/bin/python3', str(repo / 'deploy/robot/omx/isaac_cell_frames.py'),
                                        '--scenario', row['input']['config']['scenario'], '--out', str(frames)],
                                       cwd=directory, env=env, check=True, timeout=120, capture_output=True)
                        argv = [binding['sdk_python'], str(Path(__file__).with_name('arm_s_cell_task.py')),
                                '--urdf', str(urdf), '--frames', str(frames), '--output-dir', str(directory/'usd'),
                                '--report', str(report_path), '--steps-per-frame', '1']  # ~3,800 steps: 4x real speed
                                # inside the run's 165 s supervision, like the contact task's 4,800
                    if contact_task:
                        argv = [binding['sdk_python'], str(Path(__file__).with_name('conveyor_task.py')),
                                '--urdf', str(urdf), '--output-dir', str(directory/'usd'),
                                '--report', str(report_path)]
                    outcome = supervise(argv, cwd=directory, env=env, descriptors=descriptors,
                                        output=directory, stop_requested=stopped)
                    if outcome['exit_code'] == 0 and outcome['reason'] == 'process_exited':
                        if contact_task:
                            from conveyor_report import verify_report as verify_contact_report
                            report = verify_contact_report(report_path, sdk_version=binding['sdk_version'])
                        elif arm_task:
                            from arm_s_cell_report import verify_report as verify_arm_report
                            report = verify_arm_report(report_path, scenario=row['input']['config']['scenario'],
                                frames_sha256=hashlib.sha256(frames.read_bytes()).hexdigest(),
                                sdk_version=binding['sdk_version'])
                        else:
                            report = verify_report(report_path, model='omx_f', frames=120,
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
                raw = report_path.read_bytes()
                artifacts = [{'id': report_path.stem, 'name': report_path.name, 'bytes': len(raw),
                              'sha256': hashlib.sha256(raw).hexdigest(), 'media_type': 'application/json'}]
                for name in report.get('images', []):
                    fd = os.open(directory/name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(fd, 'rb') as stream:
                        info = os.fstat(stream.fileno())
                        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024*1024:
                            raise ValueError('Unsafe task image')
                        data = stream.read(1024*1024+1)
                    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                        raise ValueError('Invalid task image')
                    artifacts.append(dict(id=Path(name).stem, name=name, bytes=len(data),
                                          sha256=hashlib.sha256(data).hexdigest(), media_type='image/png'))
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
    contact_task = current['input']['scenario_id'] == 'pinky-conveyor-roundtrip'
    arm_task = current['input']['scenario_id'].startswith('arm-s-cell-')
    passed = report is not None and (not (contact_task or arm_task) or report['task_success'] is True)
    status = 'STOPPED' if stopped else ('SUCCEEDED' if passed else 'FAILED')
    result = dict(outcome, status=status, stage='model_import', task_success=None,
                  import_verified=report is not None, completed_frames=report['completed_frames'] if report else None,
                  cleanup=cleanup, gpu=gpu, video_unavailable_reason='model_import_does_not_record_video')
    if contact_task:
        result.update(stage='contact_roundtrip', task_success=bool(report and report['task_success']),
            evidence_class=report['judgement']['evidence_class'] if report else 'INCOMPLETE_CONTACT_TASK',
            failures=report['judgement']['failures'] if report else [outcome['reason']],
            coordinate_scope='SYNTHETIC_NOT_CAMERA_REGISTERED', controller='DETERMINISTIC_CAD_IK_NOT_LEARNED_POLICY',
            video_unavailable_reason='phase_pngs_only_no_video')
    if arm_task:
        judgement = report['judgement'] if report else {'result': outcome['reason']}
        result.update(stage='arm_s_cell', task_success=bool(report and report['task_success']),
            evidence_class='ARM_S_CELL_' + str(judgement.get('result')).upper(), judgement=judgement,
            coordinate_scope='ARM_FK_FROM_REAL_GRASPS_NOT_CAMERA_REGISTERED',
            controller='ARM_S_CHUNK_FRAMES_NOT_LEARNED_POLICY', video_unavailable_reason='phase_pngs_only_no_video')
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
