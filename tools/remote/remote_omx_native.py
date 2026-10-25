"""Commit-pinned OMX native SIM deployment over the approved SSH transport (D-786)."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile

HELPER = '/usr/local/sbin/rosy-native-sim-control'
SCHEMA = 'rosy.omx-native-deployment/1'
INSTALLER = 'deploy/hosts/common/install-native-sim-control.py'
HELPER_SOURCE = 'deploy/hosts/common/rosy-native-sim-control'
RUN_ID = re.compile(r'[0-9a-f]{40}-[0-9a-f]{12}')


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


def save(path, value, *, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        pending = path.with_name(path.name+'.pending')
        with pending.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)


def validate_receipt(value):
    if value.get('schema') != SCHEMA or value.get('role') not in ('ai', 'model'):
        raise ValueError('unsupported deployment receipt')
    uid, account = value.get('uid'), value.get('account', '')
    if type(uid) is not int or uid < 1000 or account == 'root' or not re.fullmatch(r'[a-z_][a-z0-9_-]*', account):
        raise ValueError('invalid unprivileged account binding')
    revision, run_id = value.get('revision', ''), value.get('run_id', '')
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or not RUN_ID.fullmatch(run_id) or run_id[:40] != revision:
        raise ValueError('invalid revision/run identity')
    anchor = '/var/lib/rosy-native-sim/'+str(uid)
    expected = {'state_root': anchor, 'release': anchor+'/releases/'+revision,
        'state': anchor+'/state/'+run_id[-12:], 'unit': 'rosy-native-sim-'+run_id}
    if any(value.get(key) != wanted for key, wanted in expected.items()):
        raise ValueError('activation path or service identity is unbound')
    if value.get('deployment_status') != 'READY':
        raise PermissionError('deployment is not READY')


def verify_helper(helper, value):
    expected = {'schema': 'rosy.native-sim-control/1', 'role': value['role'],
        'uid': value['uid'], 'account': value['account'], 'state_root': value['state_root']}
    if any(helper.get(key) != wanted for key, wanted in expected.items()):
        raise PermissionError('root helper identity differs from the deployment binding')


def start_prepared(value, directory, remote, *, approve_sim=False, approve_startup=False,approve_study=False):
    if not (approve_sim and approve_startup):
        raise PermissionError('isolated SIM and startup-home approvals are both required')
    study=value.get('experiment') in {'pick-place-policy','pick-place-policy-calibration','pick-place-policy-contact'}
    if study and approve_study is not True:
        raise PermissionError('explicit isolated policy study approval required')
    validate_receipt(value)
    request = directory/'start-request.json'
    if request.exists():
        raise FileExistsError('start was already requested; use status/fetch to reconcile')
    helper = remote.json(['sudo', '-n', HELPER, 'probe'])
    verify_helper(helper, value)
    # Reserve performs fresh input/capacity checks and its own durable one-shot intent.
    reservation=['/usr/bin/python3',value['release']+'/deploy/robot/omx/native_sim_job.py',
                 'reserve','--state',value['state']]
    if study:reservation.append('--approve-policy-study')
    remote.json(reservation)
    record={'run_id':value['run_id'],'revision':value['revision'],
            'requested_at':datetime.now(timezone.utc).isoformat()}
    if study:record['policy_study_approved']=True
    save(request,record,exclusive=True)
    try:
        response = remote.json(['sudo', '-n', HELPER, 'start', value['run_id']])
        acknowledged = response.get('returncode') == 0 and response.get('unit') == value['unit']
        result = {'service_start': 'ACKNOWLEDGED' if acknowledged else 'UNKNOWN',
                  'task_success': 'UNKNOWN', 'retry': 'RECONCILE_ONLY', 'helper': response}
    except (OSError, TimeoutError, RuntimeError, subprocess.SubprocessError) as error:
        result = {'service_start': 'UNKNOWN', 'task_success': 'UNKNOWN',
                  'retry': 'RECONCILE_ONLY', 'error': str(error)}
    save(directory/'start-result.json', result)
    return result


class SSH:
    def __init__(self, host, runner):
        self.host, self.runner = host, runner

    def script(self, script, *, timeout=60):
        result = self.runner.remote(self.host, script, capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError('SSH operation failed with exit '+str(result.returncode)+': '+
                               result.stderr.decode(errors='replace')[-1500:])
        return result.stdout

    def json(self, args, *, timeout=60):
        raw = self.script(shlex.join(args), timeout=timeout)
        try:
            return json.loads(raw)
        except ValueError as error:
            raise RuntimeError('remote result was not a JSON receipt') from error

    def python(self, program, *, timeout=60):
        return json.loads(self.script("/usr/bin/python3 - <<'NATIVE_DEPLOY'\n"+program+
                                      "\nNATIVE_DEPLOY\n", timeout=timeout))


def identity(remote):
    value = remote.python("from pathlib import Path\nimport json,os,pwd\n"
        "print(json.dumps(dict(uid=os.getuid(),gid=os.getgid(),account=pwd.getpwuid(os.getuid()).pw_name,"
        "home=str(Path.home()),site=(Path.home()/'rosy-jobs/site').exists())))")
    if value['site'] or value['uid'] < 1000 or value['account'] == 'root':
        raise PermissionError('site or privileged SSH account refused')
    return value


def helper_probe(remote):
    present = remote.python("from pathlib import Path\nimport json\np=Path("+repr(HELPER)+")\n"
        "print(json.dumps(dict(installed=p.is_file(),root_owned=p.is_file() and p.stat().st_uid==0)))")
    if not present['installed']:
        return None
    if not present['root_owned']:
        raise PermissionError('installed helper is not root-owned')
    return remote.json(['sudo', '-n', HELPER, 'probe'])


def provisioning_bundle(repo, revision, directory):
    folder = directory/'provisioning'
    folder.mkdir(exist_ok=True)
    hashes = {}
    for name in [INSTALLER, HELPER_SOURCE]:
        raw = subprocess.check_output(['git', '-C', str(repo), 'show', revision+':'+name])
        destination = folder/Path(name).name
        if destination.exists() and destination.read_bytes() != raw:
            raise ValueError('provisioning bundle already differs')
        destination.write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    save(folder/'manifest.json', {'revision': revision, 'sha256': hashes})
    return hashes


def bootstrap_program(payloads, hashes, role, account):
    """Trusted inline root code; never execute mutable staging files as root."""
    if set(payloads) != {Path(INSTALLER).name, Path(HELPER_SOURCE).name} or set(hashes) != set(payloads):
        raise ValueError('unexpected provisioning payload set')
    if role not in ('ai', 'model') or account == 'root' or not re.fullmatch(r'[a-z_][a-z0-9_-]*', account):
        raise ValueError('invalid provisioning role or account')
    encoded = {name: base64.b64encode(raw).decode() for name, raw in payloads.items()}
    return ("import base64,hashlib,os,pathlib,subprocess,tempfile\n"
        "if os.geteuid()!=0: raise PermissionError('root provisioning authority required')\n"
        'encoded='+repr(encoded)+'\nexpected='+repr(hashes)+'\n'
        "payloads={name:base64.b64decode(value,validate=True) for name,value in encoded.items()}\n"
        "for name,raw in payloads.items():\n"
        " if hashlib.sha256(raw).hexdigest()!=expected[name]: raise ValueError('provisioning digest mismatch')\n"
        "with tempfile.TemporaryDirectory(prefix='rosy-native-provision-',dir='/run') as folder:\n"
        " os.chmod(folder,0o700)\n"
        " for name,raw in payloads.items():\n"
        "  path=pathlib.Path(folder)/name\n"
        "  with path.open('xb') as stream:\n"
        "   stream.write(raw);stream.flush();os.fsync(stream.fileno())\n"
        "  path.chmod(0o755)\n"
        " subprocess.run(['/usr/bin/python3','-I',str(pathlib.Path(folder)/'install-native-sim-control.py'),"
        "'--role',"+repr(role)+",'--account',"+repr(account)+",'--approve-native-sim'],check=True)\n")


def provision(value, directory, remote, *, approved=False):
    found = helper_probe(remote)
    if found is not None:
        verify_helper(found, value)
        return found
    if not approved:
        return None
    # General provisioning authority must already exist. Never prompt or capture a password.
    allowed = remote.python("import json,subprocess\np=subprocess.run(['sudo','-n','true'],"
        "capture_output=True,text=True,timeout=10)\nprint(json.dumps({'authorized':p.returncode==0}))")
    if not allowed['authorized']:
        save(directory/'provisioning'/'result.json', {'status': 'NEEDS_PROVISIONING',
            'reason': 'administrator authentication is required', 'attempted_install': False})
        return None
    hashes = json.loads((directory/'provisioning'/'manifest.json').read_text())['sha256']
    repo = Path(__file__).resolve().parents[2]
    payloads = {Path(name).name: subprocess.check_output(
        ['git', '-C', str(repo), 'show', value['revision']+':'+name]) for name in hashes}
    expected = {Path(name).name: digest for name, digest in hashes.items()}
    if any(hashlib.sha256(raw).hexdigest() != expected[name] for name, raw in payloads.items()):
        raise ValueError('provisioning bundle no longer matches the recorded commit')
    program = bootstrap_program(payloads, expected, value['role'], value['account'])
    result = remote.json(['sudo', '-n', '/usr/bin/python3', '-I', '-c', program], timeout=180)
    save(directory/'provisioning'/'result.json', result)
    found = helper_probe(remote)
    if found is None:
        raise RuntimeError('provisioning returned without an installed helper')
    verify_helper(found, value)
    return found


def activate(value, directory, remote):
    helper = helper_probe(remote)
    if helper is None:
        value['deployment_status'] = 'NEEDS_PROVISIONING'
        save(directory/'deployment.json', value)
        return value
    verify_helper(helper, value)
    program = "import json,sys\nfrom pathlib import Path\nsys.path.insert(0,"+repr(
        value['source']+'/deploy/robot/omx')+")\nfrom native_sim_prepare import activate\n"
    program += ('print(json.dumps(activate(Path('+repr(value['staging'])+
                '),Path('+repr(value['state_root'])+'))))')
    result = remote.python(program, timeout=600)
    for key in ['release', 'state', 'run_id', 'revision', 'unit']:
        if result.get(key) != value[key]:
            raise RuntimeError('activation returned an unexpected '+key)
    value.update(deployment_status='READY', activation=result)
    save(directory/'deployment.json', value)
    return value


def deploy(args, repo, runner):
    host = choose_target(runner._LAB, args.host)
    experiment = getattr(args, 'experiment', 'g2')
    if experiment not in ('g2', 'pick-place', 'pick-place-demonstrations', 'pick-place-chunks',
                           'pick-place-chunks-offset', 'pick-place-chunks-yaw-site', 'pick-place-chunks-yaw-box',
                           'pick-place-policy','pick-place-policy-calibration','pick-place-policy-contact'):
        raise ValueError('unknown native simulation experiment')
    episodes = getattr(args, 'episodes', 1)
    if (type(episodes) is not int or not 1 <= episodes <= 3
            or experiment != 'pick-place-demonstrations' and episodes != 1):
        raise ValueError('only demonstrations allow one to three episodes')
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    if config.get('role') != args.host:
        raise ValueError('SDK config role does not match approved target role')
    revision = runner.git(repo, 'rev-parse', args.sha+'^{commit}')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('source must resolve to a full commit ID')
    directory = args.log_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if (directory/'deployment.json').exists():
        raise FileExistsError('deployment receipt exists; use provision/status/fetch for this job')
    remote = SSH(host, runner)
    who = identity(remote)
    nonce = secrets.token_hex(6)
    run_id = revision+'-'+nonce
    stage_name = 'omx-native-'+revision[:10]+'-'+nonce
    home, anchor = who['home'], '/var/lib/rosy-native-sim/'+str(who['uid'])
    value = {'schema': SCHEMA, 'host': host, 'role': args.host, 'revision': revision,
        'run_id': run_id, 'stage_name': stage_name, 'uid': who['uid'], 'account': who['account'],
        'source': home+'/rosy-test/runs/'+stage_name,
        'staging': home+'/rosy-test/native-omx/'+run_id, 'state_root': anchor,
        'release': anchor+'/releases/'+revision, 'state': anchor+'/state/'+nonce,
        'unit': 'rosy-native-sim-'+run_id, 'deployment_status': 'PREPARING',
        'task_execution': 'NOT_RUN', 'real_training_episodes': 0, 'experiment': experiment, 'episodes': episodes}
    save(directory/'deployment.json', value, exclusive=True)
    provisioning_bundle(repo, revision, directory)
    try:
        runner.ship(repo, host, revision, stage_name)
        config_path = home+'/rosy-test/native-omx/'+run_id+'.host.json'
        remote.python('from pathlib import Path\nimport json\np=Path('+repr(config_path)+
            ')\np.parent.mkdir(parents=True,exist_ok=True)\np.write_text('+repr(json.dumps(config))+
            ")\nprint(json.dumps({'config':'STAGED'}))")
        prepared = remote.json(['/usr/bin/python3', value['source']+'/deploy/robot/omx/native_sim_prepare.py',
            '--source', value['source'], '--config', config_path, '--staging', value['staging'],
            '--run-id', run_id, '--experiment', experiment, '--episodes', str(episodes)], timeout=900)
        value['prepared'] = prepared
        value['deployment_status'] = 'STAGED'
        save(directory/'deployment.json', value)
        helper = provision(value, directory, remote, approved=args.approve_host_provisioning)
        if helper is None:
            value['deployment_status'] = 'NEEDS_PROVISIONING'
            save(directory/'deployment.json', value)
            return value
        return activate(value, directory, remote)
    except Exception as error:
        value.update(deployment_status='FAILED_OR_UNKNOWN', error=str(error))
        save(directory/'deployment.json', value)
        raise
    finally:
        # Release only this shipment's reservation; retain the staged source for reconciliation.
        remote.python('from pathlib import Path\nimport json\np=Path('+repr(
            home+'/rosy-jobs/'+stage_name+'.resv')+")\np.unlink(missing_ok=True)\nprint(json.dumps({'reservation':'RELEASED'}))")


def portable_evidence_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {'', '.', '..'} for part in name.split('/')):
        raise ValueError('unsafe evidence archive path')
    parts = []
    reserved = {'con', 'prn', 'aux', 'nul'} | {f'{prefix}{i}' for prefix in ('com', 'lpt') for i in range(1, 10)}
    for part in path.parts:
        encoded = ''.join(chr(byte) if byte in b'abcdefghijklmnopqrstuvwxyz0123456789._-'
                          else f'%{byte:02X}' for byte in part.encode('utf-8'))
        if encoded.split('.')[0] in reserved:
            encoded = f'%{ord(encoded[0]):02X}' + encoded[1:]
        encoded = encoded.rstrip('.') + '%2E' * (len(encoded) - len(encoded.rstrip('.')))
        parts.append(encoded)
    relative = '/'.join(parts)
    # Keep even a long Linux cache/log path inside the Windows path budget.
    return relative if len(relative) <= 100 else '_long/' + hashlib.sha256(name.encode()).hexdigest()


def extract_evidence(raw, destination):
    mapping, targets, total = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        for index, entry in enumerate(archive):
            total += entry.size
            if index >= 10000 or total > 256 * 1024 * 1024 or not entry.isfile():
                raise ValueError('evidence archive must contain bounded regular files only')
            relative = portable_evidence_name(entry.name)
            if relative.casefold() in targets:
                raise ValueError('duplicate portable evidence path')
            targets.add(relative.casefold())
            mapping[entry.name] = relative
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(entry) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
    return mapping


def fetch(value, directory, remote):
    root = value['state'] if value['deployment_status'] == 'READY' else value['staging']
    program = "from pathlib import Path\nimport io,sys,tarfile\nroot=Path("+repr(root)+")\n"
    program += """files=[p for p in root.rglob('*') if p.is_file() and not p.is_symlink() and 'source' not in p.relative_to(root).parts]
if len(files)>10000 or sum(p.stat().st_size for p in files)>256*1024*1024:
 raise RuntimeError('evidence exceeds bounded collection size')
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:
 for path in files: archive.add(path,arcname=str(path.relative_to(root)),recursive=False)
"""
    raw = remote.script("/usr/bin/python3 - <<'NATIVE_FETCH'\n"+program+"\nNATIVE_FETCH\n", timeout=180)
    snapshot = directory/'fetches'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+secrets.token_hex(6))
    snapshot.mkdir(parents=True)
    archive_path = snapshot/'archive.tar.gz'
    with archive_path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    archive_hash = hashlib.sha256(raw).hexdigest()
    save(snapshot/'archive-receipt.json', {'archive_sha256': archive_hash, 'bytes': len(raw)}, exclusive=True)
    destination = snapshot/'files'
    destination.mkdir()
    mapping_path = snapshot/'extraction-map.json'
    save(mapping_path, extract_evidence(raw, destination), exclusive=True)
    result = {'evidence': str(destination), 'archive': str(archive_path),
              'archive_sha256': archive_hash, 'extraction_map': str(mapping_path),
              'extraction_map_sha256': hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
              'snapshot': 'OBSERVATION_NOT_ATOMIC',
              'task_success': 'INSPECT_CANONICAL_RESULT', 'deployment_status': value['deployment_status']}
    save(snapshot/'receipt.json', result, exclusive=True)
    save(directory/'latest-fetch.json', {'receipt': str(snapshot/'receipt.json')})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    shipping = commands.add_parser('deploy')
    shipping.add_argument('--host', choices=['ai', 'model'], required=True)
    shipping.add_argument('--config', type=Path, required=True)
    shipping.add_argument('--log-dir', type=Path, required=True)
    shipping.add_argument('--sha', default='HEAD')
    shipping.add_argument('--experiment', choices=['g2', 'pick-place', 'pick-place-demonstrations', 'pick-place-chunks',
        'pick-place-chunks-offset', 'pick-place-chunks-yaw-site', 'pick-place-chunks-yaw-box',
        'pick-place-policy','pick-place-policy-calibration','pick-place-policy-contact'], default='g2')
    shipping.add_argument('--episodes', type=int, choices=(1, 2, 3), default=1)
    shipping.add_argument('--approve-host-provisioning', action='store_true')
    for action in ['provision', 'start', 'status', 'fetch']:
        command = commands.add_parser(action)
        command.add_argument('--receipt', type=Path, required=True)
        if action == 'provision':
            command.add_argument('--approve-host-provisioning', action='store_true', required=True)
        if action == 'start':
            command.add_argument('--approve-isolated-simulation', action='store_true')
            command.add_argument('--approve-startup-home', action='store_true')
            command.add_argument('--approve-policy-study',action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import remote_pytest as runner
    repo = Path(__file__).resolve().parents[2]
    if args.action == 'deploy':
        value = deploy(args, repo, runner)
    else:
        directory = args.receipt.resolve().parent
        value = json.loads(args.receipt.read_text())
        host = choose_target(runner._LAB, value['role'])
        if host != value['host']:
            raise PermissionError('receipt does not belong to the approved host')
        remote = SSH(host, runner)
        if args.action == 'provision':
            provision(value, directory, remote, approved=args.approve_host_provisioning)
            value = activate(value, directory, remote)
        elif args.action == 'start':
            value = start_prepared(value, directory, remote,
                approve_sim=args.approve_isolated_simulation, approve_startup=args.approve_startup_home,
                approve_study=args.approve_policy_study)
        elif args.action == 'status':
            helper = helper_probe(remote)
            if helper is None:
                value = {'deployment_status': value['deployment_status'], 'helper': 'NEEDS_PROVISIONING',
                         'task_execution': 'NOT_RUN'}
            else:
                verify_helper(helper, value)
                value = {'helper': remote.json(['sudo', '-n', HELPER, 'status', value['run_id']]),
                    'runtime': remote.json(['/usr/bin/python3', value['release']+
                        '/deploy/robot/omx/native_sim_job.py', 'status', '--state', value['state']])}
            save(directory/'latest-status.json', value)
        else:
            value = fetch(value, directory, remote)
    # Keep large/private file inventories in the receipt, never terminal output.
    brief = {key: value[key] for key in ['deployment_status', 'run_id', 'service_start',
        'task_success', 'task_execution', 'retry', 'evidence', 'helper'] if key in value and key != 'helper'}
    print(json.dumps(brief or {'result': 'RECORDED'}, ensure_ascii=False))
    blocked = value.get('deployment_status') in ('NEEDS_PROVISIONING', 'FAILED_OR_UNKNOWN')
    return 3 if args.action in ('deploy', 'provision') and blocked else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, PermissionError, subprocess.SubprocessError) as error:
        print('NOT COMPLETED: '+str(error), file=sys.stderr)
        raise SystemExit(1)
