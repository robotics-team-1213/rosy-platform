"""Run fixed Isaac scenarios on the explicitly declared model PC."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))

LIMIT = 1024 * 1024
CONTAINER_ARTIFACTS = {
    'mapped-stack-report': ('mapped-stack-report.json', 16 * LIMIT),
    'mapped-video': ('mapped-video.mp4', 64 * LIMIT),
    'mapped-video-frames': ('mapped-video.frames.jsonl', 16 * LIMIT),
    'mapped-video-encoder': ('mapped-video.encoder.log', LIMIT),
}
# Base64 expansion plus a bounded allowance for the artifact metadata.
ARTIFACT_RPC_LIMITS = {key: (size + 2) // 3 * 4 + LIMIT
                       for key, (_, size) in CONTAINER_ARTIFACTS.items()}
TERMINAL = {'SUCCEEDED', 'FAILED', 'STOPPED'}  # learning/envs/isaac/run_store.py


def choose_target(lab, role):
    if role not in ('ai', 'model'):
        raise ValueError('simulation role must be ai or model')
    found = []
    for entry in lab.get('sim_hosts', []):
        host, _, declared = entry.partition('=')
        if declared == role and host != lab.get('site_host'):
            if not re.fullmatch(r'[a-z_][a-z0-9_-]*@[a-zA-Z0-9.-]+', host):
                raise ValueError('invalid approved SSH target')
            found.append(host)
    if len(found) != 1:
        raise ValueError('exactly one explicitly declared simulation host is required for '+role)
    return found[0]


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('A full lower-case commit SHA is required')
    return value


def _json(path):
    if path.is_symlink() or path.stat().st_size > LIMIT:
        raise ValueError('Unsafe or oversized JSON input')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('JSON input must be an object')
    return value


def _save(path, value):
    temporary = path.with_name('.pending-' + uuid.uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    _sync_directory(path.parent)


def _sync_directory(path):
    if hasattr(os, 'O_DIRECTORY'):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _receipt(request):
    required = {'request_id', 'scenario_id', 'config', 'source_sha', 'expected_input_sha256'}
    if (not isinstance(request, dict) or not required <= request.keys()
            or request.keys() - required - {'parent_run_id'}
            or not isinstance(request['request_id'], str)
            or not re.fullmatch('[0-9a-f]{32}', request['request_id'])
            or not isinstance(request['expected_input_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', request['expected_input_sha256'])):
        raise ValueError('Invalid Isaac start request')
    _sha(request['source_sha'])
    return {'schema': 'rosy.remote-isaac-receipt/1', 'role': 'model',
            'source_sha': request['source_sha'], 'request_id': request['request_id'],
            'run_id': uuid.uuid5(uuid.NAMESPACE_URL, 'rosy.isaac-run:' + request['request_id']).hex,
            'input_sha256': request['expected_input_sha256'],
            'request_sha256': hashlib.sha256(json.dumps(request, sort_keys=True,
                separators=(',', ':'), allow_nan=False).encode()).hexdigest()}


def read_receipt(path):
    value = _json(path)
    if (value.get('schema') != 'rosy.remote-isaac-receipt/1' or value.get('role') != 'model'
            or not re.fullmatch('[0-9a-f]{32}', str(value.get('run_id', '')))
            or not re.fullmatch('[0-9a-f]{64}', str(value.get('input_sha256', '')))):
        raise ValueError('Invalid model-PC receipt')
    _sha(value.get('source_sha'))
    return value


def start(request, receipt_file, remote):
    value = _receipt(request)
    if getattr(remote, 'target_id', None):
        value['target_id'] = remote.target_id
    try:
        _save(receipt_file, value)
    except FileExistsError:
        if read_receipt(receipt_file) != value:
            raise ValueError('Receipt already belongs to a different request') from None
    row = remote.call(value['source_sha'], {'action': 'start', 'request': request})
    if row['run_id'] != value['run_id'] or row['input_sha256'] != value['input_sha256']:
        raise ValueError('Remote run differs from the persisted receipt')
    remote.hold(value['run_id'], row['status'] not in TERMINAL)
    return row


def observe(receipt_file, remote, *, stop=False):
    value = read_receipt(receipt_file)
    if value.get('target_id') != getattr(remote, 'target_id', None):
        raise ValueError('Receipt model-PC identity changed')
    row = remote.call(value['source_sha'], {'action': 'status', 'run_id': value['run_id']})
    if row['run_id'] != value['run_id'] or row['input_sha256'] != value['input_sha256']:
        raise ValueError('Remote observation differs from receipt')
    if stop:
        row = remote.call(value['source_sha'], {'action': 'stop', 'run_id': value['run_id'],
                                               'expected_revision': row['revision']})
    remote.hold(value['run_id'], not stop and row['status'] not in TERMINAL)
    return row


def run_experiment(scenario, config, sha, directory, remote, *, parent=None, sleep=None, fetch=None,
                   attempts=20, interval=30, max_polls=240, max_errors=10):
    """check until ready -> start once -> wait (riding out lost replies) -> fetch a terminal run.

    Hand-rolled loops started a run while the model PC was busy and stopped waiting on one lost reply.
    """
    import time
    sleep = sleep or time.sleep
    fetch = fetch or fetch_snapshot
    remote.prepare(_sha(sha))
    for attempt in range(attempts):
        checked = remote.call(sha, {'action': 'check', 'scenario_id': scenario, 'config': config, 'source_sha': sha})
        if checked.get('ready') is True:
            break
        if attempt + 1 < attempts:
            sleep(interval)
    else:
        raise ValueError(f"Model PC not ready after {attempts} checks: {checked.get('reason')}")
    request = {'request_id': uuid.uuid4().hex, 'scenario_id': scenario, 'config': config, 'source_sha': sha,
               'expected_input_sha256': checked['input_sha256'], **({'parent_run_id': parent} if parent else {})}
    directory.mkdir(parents=True, exist_ok=True)
    _save(directory / 'request.json', request)
    receipt = directory / 'receipt.json'
    row, errors = start(request, receipt, remote), 0
    for _ in range(max_polls):
        if row['status'] in TERMINAL or row['status'] == 'UNKNOWN':
            break
        sleep(interval)
        try:
            row, errors = observe(receipt, remote), 0
        except (ConnectionError, OSError):
            errors += 1
            if errors > max_errors:
                raise
    else:
        raise ValueError('Run still active; continue with status --receipt')
    snapshot = fetch(read_receipt(receipt), remote, directory / 'snapshots') if row['status'] in TERMINAL else None
    return {'run_id': row['run_id'], 'status': row['status'], 'result': row.get('result'),
            'snapshot_directory': str(snapshot) if snapshot else None}


def _name(value):
    if (not isinstance(value, str) or len(value) > 180 or not re.fullmatch('[A-Za-z0-9_.-]+', value)
            or value in {'.', '..'} or value.endswith('.')
            or value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                *('COM' + str(i) for i in range(1, 10)), *('LPT' + str(i) for i in range(1, 10))}):
        raise ValueError('Unsafe portable snapshot filename')
    return value


def fetch_snapshot(receipt, remote, destination):
    if receipt.get('target_id') != getattr(remote, 'target_id', None):
        raise ValueError('Receipt model-PC identity changed')
    row = remote.call(receipt['source_sha'], {'action': 'status', 'run_id': receipt['run_id']})
    if row['run_id'] != receipt['run_id'] or row.get('input_sha256') != receipt['input_sha256']:
        raise ValueError('Snapshot belongs to a different run')
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError('Linked snapshot root')
    snapshot = destination / (receipt['run_id'] + '-' + uuid.uuid4().hex)
    snapshot.mkdir(mode=0o700)
    _save(snapshot / 'observation.json', row)
    names, total = {'observation.json', 'snapshot.json'}, 0
    items = row.get('artifacts', {}).get('files', []) if row.get('snapshot') == 'FINAL' else []
    if len(items) > 256:
        raise ValueError('Too many snapshot artifacts')
    for item in items:
        name = _name(item['name'])
        total += item['bytes']
        scenario = row.get('input', {}).get('scenario_id')
        registered_name, registered_limit = CONTAINER_ARTIFACTS.get(item['id'], (None, LIMIT))
        limit = LIMIT
        if scenario == 'omx-map-container-stack' and name == registered_name:
            limit = registered_limit
        elif scenario == 'omx-map-cube-stack' and name == registered_name == 'mapped-stack-report.json':
            limit = 2 * LIMIT
        if name.casefold() in names or not 0 <= item['bytes'] <= limit or total > 256 * LIMIT:
            raise ValueError('Snapshot artifact size/name conflict')
        names.add(name.casefold())
        blob = remote.call(receipt['source_sha'], {'action': 'artifact', 'run_id': receipt['run_id'],
                                                  'artifact_id': item['id']})
        if {k: blob[k] for k in item} != item:
            raise ValueError('Artifact metadata changed')
        raw = base64.b64decode(blob['data_base64'], validate=True)
        if len(raw) != item['bytes'] or hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('Snapshot artifact digest differs')
        with (snapshot / name).open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    _sync_directory(snapshot)
    _save(snapshot / 'snapshot.json', {'snapshot': row['snapshot'], 'run_id': receipt['run_id'],
                                      'files': items})
    return snapshot


BOOTSTRAP = 'ARTIFACT_RPC_LIMITS = ' + repr(ARTIFACT_RPC_LIMITS) + '\n' + r'''
import json,subprocess,sys
from pathlib import Path
value=json.loads(sys.stdin.buffer.read(1048577)); sha=value['sha']
if len(sha)!=40 or any(c not in '0123456789abcdef' for c in sha): raise ValueError('SHA')
config=Path.home()/'.config/rosy/isaac-runs'/('source-'+sha+'.json')
binding=json.loads(config.read_text())
source=Path(binding['source_root'])/'learning/envs/isaac/run_control.py'
result=subprocess.run(['/usr/bin/python3',str(source),'--binding',str(config)],
 input=json.dumps(value['payload']).encode(),capture_output=True,timeout=35)
payload=value['payload']
limit=ARTIFACT_RPC_LIMITS.get(payload.get('artifact_id'),2097152) if payload.get('action')=='artifact' else 2097152
if result.returncode or len(result.stdout)>limit:
 print(json.dumps({'error':'model-PC operation refused or unavailable'}));sys.exit(2)
json.loads(result.stdout)
sys.stdout.buffer.write(result.stdout)
'''

PREPARE = r'''
import hashlib,json,os,sys
from pathlib import Path
value=json.loads(sys.stdin.buffer.read(65537)); sha=value['sha']; name=value.get('name')
if len(sha)!=40 or any(c not in '0123456789abcdef' for c in sha): raise ValueError('SHA')
root=Path.home()/'.config/rosy/isaac-runs';root.mkdir(mode=0o700,parents=True,exist_ok=True)
target=root/('source-'+sha+'.json')
if target.exists(): print('{"ready":true}');sys.exit(0)
if not name: print('{"ready":false}');sys.exit(0)
if not name.startswith('sim-isaac-') or not all(c.isalnum() or c=='-' for c in name): raise ValueError('source')
sdk=json.loads((Path.home()/'.config/rosy/isaac-sdk.json').read_text())
owner=json.loads((Path.home()/'.config/rosy/model-code.json').read_text())
data=Path.home()/'.cache/rosy-isaac/runs';data.mkdir(mode=0o700,parents=True,exist_ok=True)
binding={'uid':os.getuid(),'source_root':str(Path.home()/'rosy-test/runs'/name),'source_sha':sha,
 'sdk_python':sdk['python'],'sdk_python_sha256':sdk['python_sha256'],'sdk_version':sdk['version'],
 'model_code_root':owner['root'],'data_root':str(data)}
temporary=root/('.pending-'+name)
try:
 with temporary.open('x') as f:
  os.fchmod(f.fileno(),0o600);json.dump(binding,f);f.flush();os.fsync(f.fileno())
 try: os.link(temporary,target)
 except FileExistsError: pass
finally: temporary.unlink(missing_ok=True)
fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
try: os.fsync(fd)
finally: os.close(fd)
(Path.home()/'rosy-jobs'/(name+'.resv')).unlink(missing_ok=True)
print('{"ready":true}')
'''

# The supervisor run holds no ~/rosy-jobs lock, so host_probe would call the model PC idle: hold a
# gpu reservation (Gazebo sim budget, 6 cores 8 GB) renewed per poll. The probe deletes it 2 h after a lost client.
HOLD = r'''
import json,os,sys,time
from pathlib import Path
value=json.loads(sys.stdin.buffer.read(4097)); run=value['run_id']
if len(run)!=32 or any(c not in '0123456789abcdef' for c in run): raise ValueError('run')
path=Path.home()/'rosy-jobs'/('isaac-'+run+'.resv')
if value['active'] is True:
 path.parent.mkdir(parents=True,exist_ok=True); temporary=path.with_name('.pending-isaac-'+run)
 temporary.write_text('%d gpu 6 8\n'%(time.time()+7200)); os.replace(temporary,path)
else: path.unlink(missing_ok=True)
print(json.dumps({'held':path.exists()}))
'''


class SSH:
    def __init__(self, repo):
        import remote_pytest
        import lab_hosts
        self.runner, self.repo = remote_pytest, repo
        self.host = choose_target(lab_hosts.load(), 'model')
        self.target_id = hashlib.sha256(self.host.encode()).hexdigest()

    def _invoke(self, script, value):
        payload = value.get('payload', {})
        timeout = (180 if payload.get('action') == 'artifact' and payload.get('artifact_id') in
                   {'mapped-video', 'mapped-video-frames', 'mapped-stack-report'} else 50)
        result = self.runner.remote(self.host, 'exec /usr/bin/python3 -c ' + shlex.quote(script),
            input=json.dumps(value).encode(), capture_output=True, timeout=timeout)
        limit = (ARTIFACT_RPC_LIMITS.get(payload.get('artifact_id'), 2 * LIMIT)
                 if payload.get('action') == 'artifact' else 2 * LIMIT)
        if result.returncode or len(result.stdout) > limit:
            raise ConnectionError('Model-PC operation refused or disconnected; retain the receipt')
        value = json.loads(result.stdout)
        if isinstance(value, dict) and set(value) == {'error'}:
            raise ValueError('Model-PC operation refused')
        return value

    def prepare(self, sha):
        if not self._invoke(PREPARE, {'sha': _sha(sha)})['ready']:
            name = 'sim-isaac-' + uuid.uuid4().hex
            self.runner.ship(self.repo, self.host, sha, name)
            self._invoke(PREPARE, {'sha': sha, 'name': name})

    def hold(self, run_id, active):
        self._invoke(HOLD, {'run_id': run_id, 'active': active})

    def call(self, sha, payload):
        return self._invoke(BOOTSTRAP, {'sha': _sha(sha), 'payload': payload})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    check = commands.add_parser('check')
    check.add_argument('--scenario', required=True, choices=['omx-f-import', 'omx-stacking-rl', 'omx-map-long-stack', 'omx-map-stacking-rl', 'omx-map-cube-stack', 'omx-map-container-stack', 'pinky-conveyor-roundtrip',
                       'arm-s-cell-nominal', 'arm-s-cell-overhang', 'arm-s-cell-wrong-yaw', 'arm-s-cell-case'])
    check.add_argument('--config', required=True, type=Path)
    check.add_argument('--sha', required=True)
    run_command = commands.add_parser('run', help='check until ready, start, wait, fetch')
    run_command.add_argument('--scenario', required=True, choices=check._actions[1].choices)
    run_command.add_argument('--config', required=True, type=Path)
    run_command.add_argument('--sha', required=True)
    run_command.add_argument('--out', required=True, type=Path, help='new directory for request, receipt and snapshots')
    run_command.add_argument('--parent-run-id')
    start_command = commands.add_parser('start')
    start_command.add_argument('--request', required=True, type=Path)
    start_command.add_argument('--receipt', required=True, type=Path)
    for name in ('status', 'stop', 'fetch'):
        commands.add_parser(name).add_argument('--receipt', required=True, type=Path)
    args = parser.parse_args()
    remote = SSH(Path(__file__).resolve().parents[2])
    if args.action == 'check':
        remote.prepare(_sha(args.sha))
        result = remote.call(args.sha, {'action': 'check', 'scenario_id': args.scenario,
                                       'config': _json(args.config), 'source_sha': args.sha})
    elif args.action == 'run':
        result = run_experiment(args.scenario, _json(args.config), args.sha, args.out, remote,
                                parent=args.parent_run_id)
        report = Path(result['snapshot_directory'] or '.') / 'mapped-stack-report.json'
        if result['snapshot_directory'] and report.is_file():
            import subprocess
            summary = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] /
                                      'learning/envs/isaac/mapped_stack_report.py'), 'summary', str(report)],
                                     capture_output=True, text=True, encoding='utf-8', timeout=120)
            result['summary'] = json.loads(summary.stdout) if summary.returncode == 0 else {'error': summary.stderr[-500:]}
    elif args.action == 'start':
        result = start(_json(args.request), args.receipt, remote)
    elif args.action == 'fetch':
        snapshot = fetch_snapshot(read_receipt(args.receipt), remote, args.receipt.parent / 'snapshots')
        result = {'snapshot_directory': str(snapshot)}
    else:
        result = observe(args.receipt, remote, stop=args.action == 'stop')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, ConnectionError):
        print(json.dumps({'error': 'Isaac operation failed; retain the request and receipt for status/retry'}))
        raise SystemExit(2)
