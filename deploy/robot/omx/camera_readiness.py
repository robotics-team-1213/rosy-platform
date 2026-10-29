"""Automatic bounded low-light tuning of existing camera producers, without capture or arm I/O.

The viewer supplies quality measured before JPEG encoding. A receipt is a short-lived
photometric assessment, never authorization to move or evidence of task success.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time
import urllib.parse
import urllib.request

CONTROLS = {'auto_exposure', 'exposure_time_absolute', 'gain', 'gamma', 'brightness'}


@contextmanager
def control_locks(cameras):
    """Serialize tuners across state directories and persistent aliases, without opening a stream."""
    import fcntl
    root = Path.home()/'.local/state/rosy/camera-control-locks'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    streams = []
    try:
        for rdev in sorted({identity(spec['device'])['rdev'] for spec in cameras.values()}):
            fd = os.open(root/str(rdev), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            stream = os.fdopen(fd, 'r+')
            streams.append(stream)
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        for stream in reversed(streams):
            stream.close()


def validate_profile(profile):
    url = urllib.parse.urlsplit(profile['viewer_url'])
    if (url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port
            or url.path or url.query or url.fragment or url.username or url.password):
        raise ValueError('viewer must be an explicit localhost HTTP origin')
    cameras = profile['cameras']
    if set(cameras) != {'top', 'front'}:
        raise ValueError('both camera roles required')
    devices, units = [], []
    for role, spec in cameras.items():
        units.append(unit(role, spec))
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', units[-1]):
            raise ValueError('camera preview unit must be a plain instance name')
        device = Path(spec['device'])
        if device.parent != Path('/dev/v4l/by-id'):
            raise ValueError('persistent camera identity required')
        devices.append(str(device))
        candidates = spec['candidates']
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
            raise ValueError('one to three bounded candidates required')
        bright = spec.get('bright_candidates', [])
        if not isinstance(bright, list) or len(bright) > 3:
            raise ValueError('up to three bounded bright candidates required')
        for candidate in candidates+bright:
            if (not isinstance(candidate, dict) or not set(candidate) <= CONTROLS
                    or candidate.get('auto_exposure') != 1
                    or not all(type(value) is int for value in candidate.values())
                    or not 1 <= candidate.get('exposure_time_absolute', 0) <= 800):
                raise ValueError('manual exposure up to 80 ms and supported controls required')
    if len(set(devices)) != 2 or len(set(units)) != 2:
        raise ValueError('camera roles must have different devices and preview units')
    return profile


def unit(role, spec):
    # 2026-10-28: the front role's camera is arm S's gripper camera, opened by rosy-omx-camera@arm_a_wrist
    return spec.get('unit', role)


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=3).stdout


def get_controls(device, names):
    raw = command(['v4l2-ctl', '--device='+device, '--get-ctrl='+','.join(sorted(names))])
    values = dict((key, int(value)) for key, value in re.findall(r'^(\w+):\s*(-?\d+)', raw, re.M))
    if set(values) != set(names):
        raise RuntimeError('incomplete camera control readback')
    return values


def write_control(device, name, value):
    command(['v4l2-ctl', '--device='+device, '--set-ctrl='+name+'='+str(value)])


def validate_controls(metadata, snapshots):
    controls, current = {}, None
    for line in metadata.splitlines():
        header = re.match(r'^\s*(\w+)\s+0x\w+\s+\(([^)]+)\)\s*:\s*(.*)', line)
        if header:
            name, kind, attributes = header.groups()
            current = dict(kind=kind, attributes=attributes, menu=set(),
                           bounds=dict((k, int(v)) for k, v in re.findall(r'\b(min|max|step)=(-?\d+)', attributes)))
            controls[name] = current
        elif current is not None and (item := re.match(r'^\s*(-?\d+):', line)):
            current['menu'].add(int(item[1]))
    for snapshot in snapshots:
        for name, value in snapshot.items():
            control = controls.get(name)
            if (control is None or type(value) is not int
                    or any(flag in control['attributes'] for flag in ('read-only', 'disabled'))):
                raise ValueError('unavailable camera control: '+name)
            if control['kind'] == 'menu':
                valid = value in control['menu']
            else:
                bounds = control['bounds']
                step = bounds.get('step', 0)
                valid = (control['kind'] == 'int' and step > 0 and 'min' in bounds and 'max' in bounds
                         and bounds['min'] <= value <= bounds['max'] and (value-bounds['min']) % step == 0)
            if not valid:
                raise ValueError('value outside actual device controls: '+name)


def intent_binding(role, spec, digest):
    return dict(role=role, profile_sha256=digest, identity=spec['identity'],
                unit=unit(role, spec), original=spec['original'])


def control_intent(root, role, spec, digest, run_id, previous, requested, *, phase='applying'):
    record = dict(binding=intent_binding(role, spec, digest), producer=spec['producer'], run_id=run_id,
                  previous=dict(previous), requested=dict(requested), phase=phase)
    save(root/f'control-intent-{role}.json', record)
    return record


def owned_controls(actual, original, record):
    previous, requested = record['previous'], record['requested']
    if set(actual) != set(original) or set(previous) != set(original) or set(requested) != set(original):
        return False
    if 'actual' in record:
        return record['actual'] == requested == actual
    return all(type(value) is int and (value in (previous[name], requested[name])
               or (name == 'auto_exposure' and record['phase'] == 'restoring' and value == 1))
               for name, value in actual.items())


def restore_controls(original, write):
    errors = []
    order = [('auto_exposure', 1)] + [(k, v) for k, v in original.items() if k != 'auto_exposure']
    order.append(('auto_exposure', original['auto_exposure']))
    for name, value in order:
        try:
            write(name, value)
        except Exception as exc:
            errors.append(dict(control=name, error=repr(exc)))
    return errors


def save(path, value, *, exclusive=False):
    raw = json.dumps(value, indent=2, allow_nan=False)+'\n'
    temporary = path if exclusive else path.with_suffix('.tmp')
    with temporary.open('x' if exclusive else 'w') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if not exclusive:
        temporary.replace(path)
    sync_directory(path.parent)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def ensure_directory(path):
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for current in reversed(missing):
        current.mkdir(mode=0o700)
        sync_directory(current.parent)


class BudgetExhausted(RuntimeError):
    """Recovery waits for its rolling window; final baseline restoration is exempt."""


def reserve_budget(root, *, now_ns=None):
    now_ns = time.time_ns() if now_ns is None else now_ns
    path = root/'recovery-budget.json'
    entries = json.loads(path.read_text()) if path.exists() else []
    if (not isinstance(entries, list) or any(type(t) is not int or t <= 0 for t in entries)
            or entries != sorted(entries) or any(t > now_ns for t in entries)):
        raise RuntimeError('invalid budget or wall clock rollback; recovery is not admitted')
    entries = [t for t in entries if t > now_ns-60_000_000_000]
    if len(entries) >= 6:
        raise BudgetExhausted('six setting batches per minute exhausted')
    save(path, entries+[now_ns])  # reserve before attempted or partial control writes


def append_event(path, value):
    with path.open('a+b') as stream:
        if stream.tell():
            stream.seek(-1, os.SEEK_END)
            if stream.read(1) != b'\n':
                raise RuntimeError('preserve interrupted environment ledger; do not append')
        stream.write((json.dumps(value, allow_nan=False)+'\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def apply_candidate(candidate, write):
    write('auto_exposure', 1)
    for name, value in candidate.items():
        if name != 'auto_exposure':
            write(name, value)


def identity(device):
    path = Path(device)
    info = path.stat()
    if not path.is_symlink() or not stat.S_ISCHR(info.st_mode):
        raise RuntimeError('configured camera must resolve to a character device')
    return dict(realpath=str(path.resolve()), rdev=info.st_rdev)


def producer(role, device, wait_s=15.0):
    # The preview unit is Type=simple: at boot it is active before it opens the camera.
    deadline = time.monotonic()+wait_s
    while True:
        raw = command(['systemctl', '--user', 'show', 'rosy-omx-camera@'+role+'.service',
                       '-p', 'ActiveState', '-p', 'MainPID', '-p', 'InvocationID'])
        props = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        try:
            owners = command(['fuser', device]).split()
        except subprocess.CalledProcessError:
            owners = []  # fuser exits 1 while no process holds the device
        if props['ActiveState'] == 'active' and props['MainPID'] != '0' and owners == [props['MainPID']]:
            return props
        if time.monotonic() >= deadline:
            raise RuntimeError('existing producer must be the sole camera owner')
        time.sleep(0.5)


def prepare(profile, root, digest):
    target = root/'baseline.json'
    if target.exists():
        baseline = json.loads(target.read_text())
        if baseline['profile_sha256'] != digest:
            raise RuntimeError('profile changed; use a new state directory')
        for role, spec in baseline['cameras'].items():
            if identity(spec['device']) != spec['identity']:
                raise RuntimeError('camera identity changed')
            metadata = command(['v4l2-ctl', '--device='+spec['device'], '--list-ctrls-menus'])
            profile_spec = profile['cameras'][role]
            validate_controls(metadata, profile_spec['candidates']+profile_spec.get('bright_candidates', [])+[spec['original']])
            # The baseline keeps the original settings; the owner to guard is this run's preview, not the first one.
            spec['producer'] = producer(unit(role, spec), spec['device'])
            if get_controls(spec['device'], spec['original']) != spec['original']:
                raise RuntimeError('camera settings changed since baseline; refusing overwrite')
        return baseline
    cameras = {}
    for role, spec in profile['cameras'].items():
        device = spec['device']
        candidates = spec['candidates']+spec.get('bright_candidates', [])
        names = {'auto_exposure'} | set().union(*(set(c) for c in candidates))
        metadata = command(['v4l2-ctl', '--device='+device, '--list-ctrls-menus'])
        original = get_controls(device, names)
        validate_controls(metadata, candidates+[original])
        cameras[role] = dict(device=device, identity=identity(device), unit=unit(role, spec),
                             producer=producer(unit(role, spec), device),
                             original=original, control_metadata=metadata)
    if len({s['identity']['rdev'] for s in cameras.values()}) != 2:
        raise RuntimeError('camera aliases select the same device')
    baseline = dict(profile_sha256=digest, cameras=cameras, recorded_ns=time.time_ns())
    save(target, baseline, exclusive=True)  # durable before any setting write
    return baseline


def restore(root):
    path = root/'baseline.json'
    if not path.exists():
        return
    baseline = json.loads(path.read_text())
    results = {}
    for role, spec in baseline['cameras'].items():
        try:
            if identity(spec['device']) != spec['identity']:
                raise RuntimeError('camera identity changed; refusing wrong device')
            owner = producer(unit(role, spec), spec['device'], wait_s=5.0)
            before = get_controls(spec['device'], spec['original'])
            if before == spec['original']:
                results[role] = dict(errors=[], actual=before, restored=True)
                continue
            record = json.loads((root/f'control-intent-{role}.json').read_text())
            run = json.loads((root/'control-run.json').read_text())
            if (record['binding'] != intent_binding(role, spec, baseline['profile_sha256'])
                    or record['producer'] != owner or record['run_id'] != run['run_id']
                    or not owned_controls(before, spec['original'], record)):
                raise RuntimeError('unowned camera controls; refusing restore overwrite')
            metadata = command(['v4l2-ctl', '--device='+spec['device'], '--list-ctrls-menus'])
            validate_controls(metadata, [spec['original']])
            live = {**spec, 'producer': owner}
            record = control_intent(root, role, live, baseline['profile_sha256'], run['run_id'],
                                    before, spec['original'], phase='restoring')
            errors = restore_controls(spec['original'], lambda n, v: write_control(spec['device'], n, v))
            actual = get_controls(spec['device'], spec['original'])
            if not errors and actual == spec['original']:
                record['actual'] = actual
                save(root/f'control-intent-{role}.json', record)
            results[role] = dict(errors=errors, actual=actual, restored=actual == spec['original'] and not errors)
        except Exception as exc:
            results[role] = dict(restored=False, error=repr(exc))
    save(root/'restoration.json', results)
    if not all(value['restored'] for value in results.values()):
        raise RuntimeError('camera restore incomplete; inspect restoration.json')


def run(profile, root, digest, duration):
    from camera_environment import monitor
    from types import SimpleNamespace
    names = ('prepare', 'identity', 'producer', 'get_controls', 'write_control', 'apply_candidate',
             'restore_controls', 'save', 'restore', 'reserve_budget', 'BudgetExhausted', 'append_event', 'control_intent')
    return monitor(profile, root, digest, duration, SimpleNamespace(**{name: globals()[name] for name in names}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['run', 'restore'])
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--duration', type=float, default=0)
    args = parser.parse_args()
    if args.duration < 0 or not args.duration < float('inf'):
        parser.error('duration must be finite and nonnegative')
    if args.operation == 'restore':
        path = args.state_dir/'baseline.json'
        if path.exists():
            with control_locks(json.loads(path.read_text())['cameras']):
                restore(args.state_dir)
        return
    if args.profile is None:
        parser.error('--profile required for run')
    raw = args.profile.read_bytes()
    profile = validate_profile(json.loads(raw))
    ensure_directory(args.state_dir)
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    with control_locks(profile['cameras']):
        run(profile, args.state_dir, hashlib.sha256(raw).hexdigest(), args.duration)


if __name__ == '__main__':
    main()
