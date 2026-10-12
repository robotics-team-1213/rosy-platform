#!/usr/bin/env python3
"""Root-reviewed D-720 installation; never changes credentials or the spent marker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import time


def run(*args):subprocess.run(args,check=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('public_key',type=Path)
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('root installation required')
    source=args.source.resolve(strict=True)
    if not source.is_relative_to(Path('/home/ai/.rosy/status-incoming')):
        raise SystemExit('fixed staging directory required')
    manifest=json.loads(args.manifest.read_text())
    if set(manifest)!={'source_commit','files'} or not re.fullmatch('[0-9a-f]{40}',manifest['source_commit']):
        raise SystemExit('invalid source manifest')
    commit=manifest['source_commit'];files=manifest['files']
    if type(files) is not dict or not files or len(files)>1000:raise SystemExit('invalid source closure')
    for name,digest in files.items():
        path=source/name
        if not path.resolve().is_relative_to(source) or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise SystemExit('source manifest mismatch')
    key=args.public_key.read_text().strip()
    if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]{40,100}={0,2}(?: [A-Za-z0-9_.-]+)?',key):
        raise SystemExit('one unadorned ed25519 public key required')
    account=pwd.getpwnam('rosy-deliberation')
    marker=Path('/var/lib/rosy-deliberation/smoke/glm-first-review.spent')
    spent=marker.read_bytes() if marker.exists() else None
    target=Path('/opt/rosy-deliberation/status')/commit
    if target.exists():raise SystemExit('version already exists; inspect before reinstall')
    target.mkdir(parents=True,mode=0o755)
    for name in files:
        dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/name,dest);dest.chmod(0o644)
    venv=target/'venv'
    run('/usr/bin/python3','-m','venv',str(venv))
    run(str(venv/'bin/python'),'-m','pip','install','--disable-pip-version-check','-r',
        str(target/'deploy/site/requirements-fleet.txt'))
    # Fixed-code local model readback establishes connection admission, never action calibration.
    env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1',
         'PYTHONPATH':os.pathsep.join((str(target),str(target/'operations/decision/src'),str(target/'contracts/foundation')))}
    probe=('from deploy.ai_pc.deliberation_ollama import loaded,exchange;'
           'loaded(exchange("/api/ps",None,5));print("PINNED_LOCAL_MODEL_OK")')
    subprocess.run(['/usr/sbin/runuser','-u','rosy-deliberation','--',str(venv/'bin/python'),'-c',probe],
                   env=env,check=True)
    cfgdir=Path('/etc/rosy-deliberation');cfgdir.mkdir(mode=0o755,exist_ok=True)
    config=cfgdir/'status.json';backup=cfgdir/('status.before-'+commit+'.json')
    if config.exists():shutil.copyfile(config,backup);backup.chmod(0o600)
    cfg={'source_commit':commit,'profile_revision':'d720-v1','valid_until':time.time()+7*86400,
         'reviewer_admission':None,'billing_policy':None,'files':files}
    config.write_text(json.dumps(cfg,sort_keys=True));config.chmod(0o644)
    wrapper=Path('/usr/local/libexec/rosy-deliberation/status-broker')
    previous=wrapper.with_name('status-broker.before-'+commit)
    if wrapper.exists():shutil.copyfile(wrapper,previous);previous.chmod(0o755)
    wrapper.write_text('#!/bin/sh\nset -eu\n[ "$#" = 0 ] || exit 64\n'
        f'export XDG_RUNTIME_DIR=/run/user/{account.pw_uid}\n'
        f'export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{account.pw_uid}/bus\n'
        'export PYTHONDONTWRITEBYTECODE=1\n'
        f'export PYTHONPATH={env["PYTHONPATH"]}\n'
        f'cd {target}\nexec {venv}/bin/python -m deploy.ai_pc.deliberation_status_broker\n')
    wrapper.chmod(0o755)
    try:pwd.getpwnam('rosy-model-ingress')
    except KeyError:run('/usr/sbin/useradd','--system','--no-create-home','--home-dir','/var/empty',
                        '--shell','/bin/sh','rosy-model-ingress')
    keys=Path('/etc/ssh/rosy-status-authorized-keys')
    keys.write_text('restrict,command="sudo -n -u rosy-deliberation /usr/local/libexec/rosy-deliberation/status-broker" '+key+'\n')
    keys.chmod(0o644)
    sudo=Path('/etc/sudoers.d/rosy-status-broker')
    sudo.write_text('rosy-model-ingress ALL=(rosy-deliberation) NOPASSWD: /usr/local/libexec/rosy-deliberation/status-broker ""\n')
    sudo.chmod(0o440);run('/usr/sbin/visudo','-cf',str(sudo))
    sshd=Path('/etc/ssh/sshd_config.d/65-rosy-status-broker.conf')
    sshd.write_text('Match User rosy-model-ingress\n    AuthorizedKeysFile /etc/ssh/rosy-status-authorized-keys\n'
        '    AuthenticationMethods publickey\n    PasswordAuthentication no\n    KbdInteractiveAuthentication no\n'
        '    DisableForwarding yes\n    PermitTTY no\n'
        '    ForceCommand sudo -n -u rosy-deliberation /usr/local/libexec/rosy-deliberation/status-broker\nMatch all\n')
    sshd.chmod(0o644);run('/usr/sbin/sshd','-t')
    run('/usr/bin/loginctl','enable-linger','rosy-deliberation')
    run('/usr/bin/systemctl','start',f'user@{account.pw_uid}.service')
    run('/usr/bin/systemctl','reload','ssh.service')
    if (marker.read_bytes() if marker.exists() else None)!=spent:
        raise SystemExit('spent marker changed unexpectedly; do not retry a model call')
    print(json.dumps({'source_commit':commit,'primary_admitted':True,'reviewer_admitted':False,
        'valid_until':cfg['valid_until'],'glm_marker_spent':spent is not None,
        'config_backup':str(backup) if backup.exists() else None,'wrapper_backup':str(previous) if previous.exists() else None}))


if __name__=='__main__':main()
