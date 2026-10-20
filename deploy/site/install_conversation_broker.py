#!/usr/bin/env python3
"""Install a separately reviewed D-728 snapshot; root only, no inference or GLM calls."""
import argparse
import base64
import hashlib
import io
from email.parser import BytesParser
import zipfile
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import time

REVIEWED = Path('/root/rosy-conversation-reviewed')
VERSIONS = Path('/opt/rosy-deliberation/conversation')
CONFIG = Path('/etc/rosy-deliberation/conversation.json')
LIBEXEC = Path('/usr/local/libexec/rosy-deliberation')
PREVIOUS_INGRESS = LIBEXEC/'model-ingress'
INGRESS = Path('/usr/local/libexec/rosy-model-ingress')
STATUS = LIBEXEC/'status-broker'
BROKER = LIBEXEC/'conversation-broker'
SECURITY_FILES = (Path('/var/lib/rosy-deliberation/glm-coding-plan.json'),
                  Path('/var/lib/rosy-deliberation/smoke/glm-first-review.spent'))
KEYS = Path('/etc/ssh/rosy-status-authorized-keys')
SUDO = Path('/etc/sudoers.d/rosy-status-broker')
SSHD = Path('/etc/ssh/sshd_config.d/65-rosy-status-broker.conf')
OLD_SUDO = b'rosy-model-ingress ALL=(rosy-deliberation) NOPASSWD: /usr/local/libexec/rosy-deliberation/status-broker ""\n'
NEW_SUDO = OLD_SUDO + b'rosy-model-ingress ALL=(rosy-deliberation) NOPASSWD: /usr/local/libexec/rosy-deliberation/conversation-broker ""\n'
OLD_FORCE = 'sudo -n -u rosy-deliberation /usr/local/libexec/rosy-deliberation/status-broker'
NEW_FORCE = str(INGRESS)
PREVIOUS_FORCE = str(PREVIOUS_INGRESS)
SSHD_BASE = ('Match User rosy-model-ingress\n    AuthorizedKeysFile /etc/ssh/rosy-status-authorized-keys\n'
    '    AuthenticationMethods publickey\n    PasswordAuthentication no\n    KbdInteractiveAuthentication no\n'
    '    DisableForwarding yes\n    PermitTTY no\n    ForceCommand {}\nMatch all\n')


def require_admin():
    if os.geteuid() != 0:
        raise ValueError('ADMIN_INSTALL_REQUIRED')


def trusted_directory(path):
    for parent in (path, *path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('PROTECTED_DIRECTORY_REQUIRED')


def protected(path):
    trusted_directory(path.parent)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 128*1024*1024:
        raise ValueError('PROTECTED_FILE_REQUIRED')
    return path.read_bytes()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned(path, digest, limit=2_000_000):
    raw = protected(path)
    if len(raw) > limit or not re.fullmatch('[0-9a-f]{64}', digest) or sha(raw) != digest:
        raise ValueError('REVIEWED_INPUT_SHA_MISMATCH')
    return raw


def validate_receipt(receipt, proof, proof_sha):
    if (receipt.get('schema') != 'rosy.conversation-evaluation-receipt/1'
            or receipt.get('verdict') != 'PASS' or receipt.get('evaluation_owner') != 'model_pc'
            or receipt.get('candidate_diagnostics_used') is not False
            or receipt.get('device_commands_performed') is not False
            or receipt.get('protected_admission_performed') is not False
            or receipt.get('proof_sha256') != proof_sha
            or receipt.get('profile_revision') != proof['profile']['revision']
            or any(receipt.get(k) != proof[k] for k in
                   ('source_commit', 'source_manifest_sha256', 'suite_sha256', 'evaluated_at'))):
        raise ValueError('INDEPENDENT_RECEIPT_MISMATCH')


def inputs(bundle, pins):
    if not bundle.is_absolute() or not bundle.is_relative_to(REVIEWED):
        raise ValueError('ROOT_REVIEWED_BUNDLE_REQUIRED')
    trusted_directory(bundle)
    manifest = json.loads(pinned(bundle/'source-manifest.json', pins['manifest']))
    proof_raw = pinned(bundle/'semantic-evaluation-proof.json', pins['proof'])
    proof = json.loads(proof_raw)
    receipt_raw = pinned(bundle/'semantic-evaluation-receipt.json', pins['receipt'])
    receipt = json.loads(receipt_raw)
    key_raw = pinned(bundle/'ingress.pub', pins['public_key'])
    key = key_raw.decode().strip()
    if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]{40,100}={0,2}(?: [A-Za-z0-9_.-]+)?', key):
        raise ValueError('ONE_ED25519_KEY_REQUIRED')
    wire = base64.b64decode(key.split()[1], validate=True)
    if len(wire) != 51 or wire[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
        raise ValueError('INVALID_ED25519_KEY')
    if (set(manifest) != {'source_commit', 'files'}
            or not re.fullmatch('[0-9a-f]{40}', manifest['source_commit'])
            or type(manifest['files']) is not dict or not 1 <= len(manifest['files']) <= 998):
        raise ValueError('SOURCE_MANIFEST_REQUIRED')
    files = manifest['files']
    contents = {}
    for name, digest in files.items():
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or path.as_posix() != name
                or not re.fullmatch('[A-Za-z0-9_./-]+', name)):
            raise ValueError('SOURCE_PATH_REFUSED')
        contents[name] = pinned(bundle/'source'/name, digest)
    required = {'deploy/site/deliberation_install.py', 'deploy/site/requirements-fleet.txt',
        'deploy/ai_pc/conversation_acceptance.py', 'deploy/ai_pc/deliberation_conversation_broker.py',
        'deploy/ai_pc/deliberation_conversation.py', 'operations/decision/src/rosy/decision/conversation/codec.py'}
    if proof['profile']['revision'] == 'd728-semantic-v3-d831':
        required.add('operations/decision/src/rosy/decision/conversation/preprocessing.py')
    if not required <= files.keys() or sum(map(len, contents.values())) > 64*1024*1024:
        raise ValueError('SOURCE_CLOSURE_REQUIRED')
    manifest_sha = sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())
    if (proof['source_commit'] != manifest['source_commit'] or proof['source_manifest_sha256'] != manifest_sha
            or proof['profile']['revision'] not in {'d728-semantic-v2', 'd728-semantic-v3-d831'}):
        raise ValueError('EVALUATED_SOURCE_MISMATCH')
    validate_receipt(receipt, proof, pins['proof'])
    return manifest, proof, contents, proof_raw, receipt_raw, key


def dispatcher():
    return ( '#!/bin/sh\n# ROSY D-728 managed ingress\nset -eu\n[ "$#" = 0 ] || exit 64\n'
        'case "${SSH_ORIGINAL_COMMAND-}" in\n'
        f'  rosy-status-v1) exec /usr/bin/sudo -n -u rosy-deliberation {STATUS} ;;\n'
        f'  rosy-conversation-v1) exec /usr/bin/sudo -n -u rosy-deliberation {BROKER} ;;\n'
        '  *) exit 64 ;;\nesac\n').encode()


def replace_managed(path, data, mode, gid, allowed):
    trusted_directory(path.parent)
    if path.exists() or path.is_symlink():
        old = protected(path)
        if old == data:
            info = path.stat()
            if info.st_mode & 0o777 != mode or info.st_gid != gid:
                raise ValueError('MANAGED_MODE_CONFLICT')
            return
        if old not in allowed:
            raise ValueError('FOREIGN_INSTALL_FILE_REFUSED')
        replace_managed(path.with_name(path.name+'.before-'+sha(old)), old, 0o600, 0, ())
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.rosy-conversation-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.chown(temporary, 0, gid)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    if protected(path) != data:
        raise ValueError('INSTALL_READBACK_FAILED')


def dependencies(bundle, digest, direct):
    manifest = json.loads(pinned(bundle/'dependencies.json', digest))
    if set(manifest) != {'wheels'} or type(manifest['wheels']) is not dict or not 1 <= len(manifest['wheels']) <= 100:
        raise ValueError('DEPENDENCY_MANIFEST_REQUIRED')
    resolved = {}
    lines = []
    for name, expected in manifest['wheels'].items():
        if not re.fullmatch('[A-Za-z0-9_.+-]+[.]whl', name):
            raise ValueError('DEPENDENCY_WHEEL_NAME_REFUSED')
        raw = pinned(bundle/'wheels'/name, expected, limit=128*1024*1024)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            metadata = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
            if len(metadata) != 1 or archive.getinfo(metadata[0]).file_size > 1_000_000:
                raise ValueError('DEPENDENCY_METADATA_REQUIRED')
            fields = BytesParser().parsebytes(archive.read(metadata[0]))
        package, version = fields['Name'], fields['Version']
        if (not package or not re.fullmatch('[A-Za-z0-9_.-]+', package)
                or not version or not re.fullmatch('[A-Za-z0-9_.+!-]+', version)):
            raise ValueError('DEPENDENCY_METADATA_REFUSED')
        package = re.sub('[-_.]+', '-', package).lower()
        if package in resolved:
            raise ValueError('DEPENDENCY_DUPLICATE_REFUSED')
        resolved[package] = version
        lines.append(f'{package}=={version} --hash=sha256:{expected}\n')
    for line in direct.decode().splitlines():
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch('([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)', line)
        if not match or resolved.get(re.sub('[-_.]+', '-', match[1]).lower()) != match[2]:
            raise ValueError('DEPENDENCY_DIRECT_PIN_MISMATCH')
    return ''.join(sorted(lines)).encode()


def activate(plans, verify, reload):
    originals = {}
    for path, data, mode, gid, allowed in plans:
        trusted_directory(path.parent)
        if path.exists() or path.is_symlink():
            raw = protected(path)
            if raw not in (data, *allowed):
                raise ValueError('FOREIGN_INSTALL_FILE_REFUSED')
            info = path.stat()
            if info.st_mode & 0o777 != mode or info.st_gid != gid:
                raise ValueError('MANAGED_MODE_CONFLICT')
            originals[path] = raw
        else:
            originals[path] = None
    changed = []
    try:
        for path, data, mode, gid, allowed in plans:
            if originals[path] != data:
                # Include the target before atomic replace: readback can fail after replacement.
                changed.append((path, data, mode, gid))
            replace_managed(path, data, mode, gid, allowed)
        verify()
        reload()
    except BaseException:
        for path, data, mode, gid in reversed(changed):
            old = originals[path]
            if not path.exists() and not path.is_symlink():
                if old is not None:
                    raise ValueError('ROLLBACK_TARGET_DISAPPEARED')
                continue
            current = protected(path)
            if current == old:
                continue
            if current != data:
                raise ValueError('ROLLBACK_FOREIGN_CHANGE_REFUSED')
            if old is None:
                path.unlink()
            else:
                replace_managed(path, old, mode, gid, (data,))
        reload()
        raise


def run(*args, **kwargs):
    return subprocess.run(args, check=kwargs.pop('check', True), timeout=120, **kwargs)


def previous_transport(key):
    if not PREVIOUS_INGRESS.exists() and not PREVIOUS_INGRESS.is_symlink():
        return (), ()
    info = PREVIOUS_INGRESS.stat()
    if (protected(PREVIOUS_INGRESS) != dispatcher()
            or info.st_mode & 0o777 != 0o755 or info.st_gid != 0):
        raise ValueError('PREVIOUS_MANAGED_INGRESS_REQUIRED')
    return ((f'restrict,command="{PREVIOUS_FORCE}" '+key+'\n').encode(),), (SSHD_BASE.format(PREVIOUS_FORCE).encode(),)


def optional_status(gid):
    config = CONFIG.parent/'status.json'
    if not STATUS.exists() and not STATUS.is_symlink():
        if config.exists() or config.is_symlink():
            raise ValueError('PARTIAL_STATUS_INSTALLATION_REQUIRES_REVIEW')
        return False
    for path, mode in ((STATUS, 0o750), (config, 0o640)):
        if path == config and not path.exists() and not path.is_symlink():
            continue
        protected(path)
        info = path.stat()
        if info.st_mode & 0o777 != mode or info.st_gid != gid:
            raise ValueError('PROTECTED_STATUS_INSTALLATION_REQUIRED')
    return True


def verify_ingress(status_installed=False):
    # Malformed requests reach both brokers but cannot reach inference/provider dispatch.
    cases = [('rosy-conversation-v1', (), 'CONVERSATION'),
        ('unknown', (), None), ('rosy-conversation-v1 extra', (), None),
        ('rosy-status-v1', ('unexpected',), None), ('rosy-conversation-v1', ('unexpected',), None)]
    if status_installed:
        cases.insert(0, ('rosy-status-v1', (), 'STATUS'))
    for command, extra, expected in cases:
        result = run('/usr/sbin/runuser', '-u', 'rosy-model-ingress', '--', str(INGRESS), *extra,
                     check=False, capture_output=True, input=b'{}\n', cwd='/',
                     env={'PATH':'/usr/bin:/bin', 'SSH_ORIGINAL_COMMAND':command})
        if expected is None:
            valid = result.returncode == 64 and not result.stdout and not result.stderr
        else:
            try:
                valid = (result.returncode == 1 and not result.stderr and json.loads(result.stdout) == {
                    'state':'HOLD', 'reason':expected+'_BROKER_NOT_ADMITTED_OR_RESULT_UNKNOWN'})
            except (ValueError, UnicodeDecodeError):
                valid = False
        if not valid:
            raise ValueError('INGRESS_EXECUTION_READBACK_FAILED '+json.dumps({
                'command':command, 'extra_arguments':bool(extra), 'returncode':result.returncode,
                'stdout':result.stdout[:512].decode('utf-8', errors='replace'),
                'stderr':result.stderr[:512].decode('utf-8', errors='replace')}, sort_keys=True))


def account_registration(helper, cfgdir):
    import grp
    import pwd
    import spwd
    registration = cfgdir/'ingress.json'
    try:
        ingress = pwd.getpwnam('rosy-model-ingress')
    except KeyError:
        if registration.exists() or registration.is_symlink():
            raise ValueError('ORPHAN_INGRESS_REGISTRATION')
        run('/usr/sbin/useradd', '--system', '--user-group', '--no-create-home',
            '--home-dir', '/var/empty', '--shell', '/bin/sh', 'rosy-model-ingress')
        ingress = pwd.getpwnam('rosy-model-ingress')
        helper.install_file(registration, json.dumps({'uid':ingress.pw_uid, 'gid':ingress.pw_gid}).encode(), 0o600)
    group = grp.getgrgid(ingress.pw_gid)
    if (json.loads(protected(registration)) != {'uid':ingress.pw_uid, 'gid':ingress.pw_gid}
            or registration.stat().st_mode & 0o777 != 0o600
            or not 0 < ingress.pw_uid < 1000 or ingress.pw_dir != '/var/empty' or ingress.pw_shell != '/bin/sh'
            or group.gr_name != ingress.pw_name or group.gr_mem
            or any(p.pw_gid == ingress.pw_gid and p.pw_name != ingress.pw_name for p in pwd.getpwall())
            or set(os.getgrouplist(ingress.pw_name, ingress.pw_gid)) != {ingress.pw_gid}
            or not spwd.getspnam(ingress.pw_name).sp_pwdp.startswith(('!', '*'))):
        raise ValueError('DEDICATED_INGRESS_ACCOUNT_REQUIRED')


def python_code(target, code):
    roots = [str(target), str(target/'operations/decision/src'), str(target/'contracts/foundation')]
    return 'import sys;sys.path[:0]='+repr(roots)+';'+code


def broker_wrapper(target):
    venv = target/'venv'
    return ('#!/bin/sh\n# ROSY D-728 managed conversation\nset -eu\n[ "$#" = 0 ] || exit 64\n'
        f'cd {target}\nexec {venv}/bin/python -I -B -c '+
        "'"+python_code(target, 'from deploy.ai_pc.deliberation_conversation_broker import main;sys.exit(main())')
        .replace("'", "'\"'\"'")+"'\n").encode()


def previous_admission(config_pin, broker_pin, config, wrapper, gid):
    pins = (config_pin, broker_pin)
    reviewed = any(pin is not None for pin in pins)
    if reviewed and any(type(pin) is not str or not re.fullmatch('[0-9a-f]{64}', pin) for pin in pins):
        raise ValueError('PAIRED_PREVIOUS_SHA256_REQUIRED')
    current = []
    for path, wanted, mode, pin in ((CONFIG, config, 0o640, config_pin), (BROKER, wrapper, 0o750, broker_pin)):
        if not path.exists() and not path.is_symlink():
            if reviewed:raise ValueError('REVIEWED_PREVIOUS_FILE_MISSING')
            current.append(None)
            continue
        raw = protected(path)
        info = path.stat()
        if info.st_mode & 0o777 != mode or info.st_gid != gid:
            raise ValueError('MANAGED_MODE_CONFLICT')
        if (reviewed and sha(raw) != pin) or (not reviewed and raw != wanted):
            raise ValueError('REVIEWED_PREVIOUS_SHA256_REQUIRED')
        current.append(raw)
    if reviewed:
        previous = json.loads(current[0])
        commit = previous.get('source_commit')
        if (type(commit) is not str or not re.fullmatch('[0-9a-f]{40}', commit)
                or current[1] != broker_wrapper(VERSIONS/commit)):
            raise ValueError('PREVIOUS_MANAGED_VERSION_REQUIRED')
        return tuple((raw,) for raw in current)
    return (), ()


def snapshot(target, contents, helper):
    trusted_directory(target.parent.parent)
    target.parent.mkdir(mode=0o755, exist_ok=True)
    trusted_directory(target.parent)
    target.mkdir(mode=0o755, exist_ok=True)
    trusted_directory(target)
    for name, data in contents.items():
        path = target/name
        parent = target
        for part in Path(name).parts[:-1]:
            parent = parent/part
            parent.mkdir(mode=0o755, exist_ok=True)
            trusted_directory(parent)
        helper.install_file(path, data, 0o644)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    for name in ('manifest', 'proof', 'receipt', 'public-key', 'dependencies'):
        parser.add_argument('--'+name+'-sha256', required=True)
    parser.add_argument('--previous-config-sha256')
    parser.add_argument('--previous-broker-sha256')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    require_admin()
    os.umask(0o022)
    pins = {name:getattr(args, name+'_sha256') for name in ('manifest','proof','receipt','public_key')}
    manifest, proof, contents, proof_raw, receipt_raw, key = inputs(args.bundle, pins)
    # The helper is executed only after the independent source inventory has been pinned.
    spec = importlib.util.spec_from_file_location('reviewed_install', args.bundle/'source/deploy/site/deliberation_install.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    account = helper.validated_account()
    for path in (CONFIG.parent, LIBEXEC, INGRESS.parent, KEYS.parent, SUDO.parent, SSHD.parent, VERSIONS.parent):
        trusted_directory(path)
    target = VERSIONS/manifest['source_commit']
    cfg = {'source_commit':manifest['source_commit'], 'profile':proof['profile'], 'policy':proof['policy'],
           'valid_until':proof['evaluated_at']+7*86400, 'semantic_evidence_sha256':pins['proof'],
           'files':{**manifest['files'], 'semantic-evaluation-proof.json':pins['proof']}}
    if not time.time() < cfg['valid_until']:
        raise ValueError('EVALUATION_EXPIRED')
    config = json.dumps(cfg, sort_keys=True).encode()
    wrapper = broker_wrapper(target)
    previous_config, previous_broker = previous_admission(
        args.previous_config_sha256, args.previous_broker_sha256, config, wrapper, account.pw_gid)
    previous_keys, previous_sshd = previous_transport(key)
    status_installed = optional_status(account.pw_gid)
    lock = dependencies(args.bundle, args.dependencies_sha256, contents['deploy/site/requirements-fleet.txt'])
    if args.check:
        print(json.dumps({'state':'INPUT_HASHES_CHECKED_ONLY', 'source_commit':manifest['source_commit']}))
        return 0
    # Retain exact evidence and credentials; nothing in this installer invokes the paid provider.
    preserved = [CONFIG.parent/'status.json', CONFIG.parent/'status-reviewer-admission.json', STATUS,
                 PREVIOUS_INGRESS, *SECURITY_FILES]
    before = {p:p.read_bytes() if p.exists() else None for p in preserved}
    snapshot(target, {**contents, 'semantic-evaluation-proof.json':proof_raw,
                     'semantic-evaluation-receipt.json':receipt_raw, 'requirements.lock':lock}, helper)
    venv = target/'venv'
    marker = target/'dependencies-ready.json'
    if not marker.exists():
        if venv.exists():
            raise ValueError('INCOMPLETE_VENV_REQUIRES_ADMIN_INSPECTION')
        run('/usr/bin/python3', '-I', '-m', 'venv', str(venv))
        run(str(venv/'bin/python'), '-I', '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check',
            '--no-index', '--only-binary=:all:', '--require-hashes', '--find-links', str(args.bundle/'wheels'),
            '-r', str(target/'requirements.lock'))
        helper.install_file(marker, json.dumps({'requirements_sha256':sha(lock), 'dependencies_sha256':args.dependencies_sha256}).encode(), 0o644)
    else:
        if json.loads(protected(marker)) != {'requirements_sha256':sha(lock), 'dependencies_sha256':args.dependencies_sha256}:
            raise ValueError('DEPENDENCY_RECEIPT_CHANGED')
    trusted_directory(venv)
    for path in venv.rglob('*'):
        if path.is_symlink():
            if not path.resolve().is_relative_to(venv) and path.resolve() != Path('/usr/bin/python3').resolve():
                raise ValueError('VENV_LINK_REFUSED')
        elif path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
            raise ValueError('VENV_PROTECTION_REQUIRED')
    env = {'PATH':'/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE':'1',
           'XDG_RUNTIME_DIR':f'/run/user/{account.pw_uid}',
           'DBUS_SESSION_BUS_ADDRESS':f'unix:path=/run/user/{account.pw_uid}/bus'}
    validate = ('import json;from pathlib import Path;from rosy.decision.conversation.codec import Profile,source_policy;'
        'from deploy.ai_pc.conversation_acceptance import source_files,validate;'
        'cfg=json.loads(sys.argv[1]);p=Profile.model_validate(cfg["profile"]);'
        'assert cfg["policy"]==source_policy(cfg["source_commit"],p);'
        'assert set(source_files(Path.cwd()))<=set(cfg["files"]);'
        'validate(json.load(open("semantic-evaluation-proof.json")),cfg,p);'
        'from deploy.ai_pc.deliberation_ollama import loaded,exchange;loaded(exchange("/api/ps",None,5));'
        'print("SNAPSHOT_EVALUATION_AND_LOADED_MODEL_VALID")')
    run('/usr/sbin/runuser', '-u', account.pw_name, '--', str(venv/'bin/python'), '-I', '-B', '-c',
        python_code(target, validate), json.dumps(cfg), cwd=target, env=env)
    account_registration(helper, CONFIG.parent)
    old_key = (f'restrict,command="{OLD_FORCE}" '+key+'\n').encode()
    new_key = (f'restrict,command="{NEW_FORCE}" '+key+'\n').encode()
    plans = [(CONFIG,config,0o640,account.pw_gid,previous_config),
             (BROKER,wrapper,0o750,account.pw_gid,previous_broker), (INGRESS,dispatcher(),0o755,0,()),
             (KEYS,new_key,0o644,0,(old_key,*previous_keys)), (SUDO,NEW_SUDO,0o440,0,(OLD_SUDO,)),
             (SSHD,SSHD_BASE.format(NEW_FORCE).encode(),0o644,0,(SSHD_BASE.format(OLD_FORCE).encode(),*previous_sshd))]
    def verify():
        run('/usr/sbin/visudo', '-cf', str(SUDO))
        run('/usr/sbin/sshd', '-t')
        effective = run('/usr/sbin/sshd', '-T', '-C',
                        'user=rosy-model-ingress,host=localhost,addr=127.0.0.1',
                        capture_output=True, text=True).stdout.splitlines()
        expected = {'forcecommand '+str(INGRESS), 'authorizedkeysfile '+str(KEYS),
                    'authenticationmethods publickey', 'pubkeyauthentication yes', 'passwordauthentication no',
                    'kbdinteractiveauthentication no', 'disableforwarding yes', 'permittty no'}
        if not expected <= set(effective):
            raise ValueError('EFFECTIVE_SSH_ADMISSION_CONFLICT')
        run('/usr/sbin/runuser', '-u', account.pw_name, '--', str(venv/'bin/python'), '-I', '-B', '-c',
            python_code(target, 'from deploy.ai_pc.deliberation_conversation_broker import configuration;configuration();'
                        'print("PROTECTED_CONVERSATION_CONFIGURATION_VALID")'), cwd=target, env=env)
        verify_ingress(status_installed)
        if any((p.read_bytes() if p.exists() else None) != data for p,data in before.items()):
            raise ValueError('PRESERVED_SECURITY_STATE_CHANGED')
    for script in (wrapper, dispatcher()):
        run('/bin/sh', '-n', input=script)
    activate(plans, verify, lambda:run('/usr/bin/systemctl', 'reload', 'ssh.service'))
    print(json.dumps({'state':'INSTALLED_TRANSPORT_ONLY', 'source_commit':manifest['source_commit'],
                      'valid_until':cfg['valid_until'], 'inference_performed':False,
                      'optional_status_transport_checked':status_installed}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
