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
import tempfile
import time

from deploy.site.deliberation_install import trusted_directory,validated_account,install_file


def replace_owned(path,data,mode,gid,commit,*,validate):
    trusted_directory(path.parent)
    if path.exists() or path.is_symlink():
        info=path.lstat()
        if path.is_symlink() or info.st_uid!=0 or info.st_mode&0o022 or not validate(path.read_bytes()):
            raise ValueError('FOREIGN_INSTALL_FILE_REFUSED')
        install_file(path.with_name(path.name+'.before-'+commit),path.read_bytes(),0o600)
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.rosy-status-',delete=False) as stream:
        temporary=Path(stream.name)
        try:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.chmod(temporary,mode);os.chown(temporary,0,gid)
            os.replace(temporary,path)
        finally:
            if temporary.exists():temporary.unlink()


def run(*args):subprocess.run(args,check=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('public_key',type=Path)
    parser.add_argument('--manifest-sha256',required=True)
    parser.add_argument('--check',action='store_true',help='validate staged inputs without installing')
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('root installation required')
    source=args.source.resolve(strict=True)
    if not source.is_relative_to(Path('/root/rosy-status-reviewed')):
        raise SystemExit('root-owned reviewed snapshot required')
    trusted_directory(source)
    manifest_bytes=args.manifest.read_bytes()
    if (not re.fullmatch('[0-9a-f]{64}',args.manifest_sha256)
            or hashlib.sha256(manifest_bytes).hexdigest()!=args.manifest_sha256):
        raise SystemExit('approved manifest digest required')
    manifest=json.loads(manifest_bytes)
    if set(manifest)!={'source_commit','files'} or not re.fullmatch('[0-9a-f]{40}',manifest['source_commit']):
        raise SystemExit('invalid source manifest')
    commit=manifest['source_commit'];files=manifest['files']
    if type(files) is not dict or not files or len(files)>1000:raise SystemExit('invalid source closure')
    contents={}
    for name,digest in files.items():
        if Path(name).is_absolute() or '..' in Path(name).parts:raise SystemExit('invalid source path')
        path=source/name
        data=path.read_bytes()
        if (not path.resolve().is_relative_to(source) or path.is_symlink() or len(data)>2_000_000
                or hashlib.sha256(data).hexdigest()!=digest):
            raise SystemExit('source manifest mismatch')
        contents[name]=data
    if sum(map(len,contents.values()))>64*1024*1024:raise SystemExit('source closure limit')
    key=args.public_key.read_text().strip()
    if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]{40,100}={0,2}(?: [A-Za-z0-9_.-]+)?',key):
        raise SystemExit('one unadorned ed25519 public key required')
    account=validated_account()
    for parent in ('/opt','/opt/rosy-deliberation','/etc','/etc/ssh','/etc/ssh/sshd_config.d',
                   '/etc/sudoers.d','/usr/local/libexec/rosy-deliberation'):
        trusted_directory(Path(parent))
    marker=Path('/var/lib/rosy-deliberation/smoke/glm-first-review.spent')
    spent=marker.read_bytes() if marker.exists() else None
    if args.check:
        print(json.dumps({'source_commit':commit,'files':len(files),'glm_marker_spent':spent is not None}))
        return
    target=Path('/opt/rosy-deliberation/status')/commit
    target.parent.mkdir(mode=0o755,exist_ok=True);trusted_directory(target.parent)
    if target.exists():raise SystemExit('version already exists; inspect before reinstall')
    target.mkdir(parents=True,mode=0o755)
    for name in files:
        dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(contents[name]);dest.chmod(0o644)
    venv=target/'venv'
    run('/usr/bin/python3','-m','venv',str(venv))
    run(str(venv/'bin/python'),'-m','pip','install','--disable-pip-version-check','-r',
        str(target/'deploy/site/requirements-fleet.txt'))
    # Fixed-code local model readback establishes connection admission, never action calibration.
    env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1',
         'XDG_RUNTIME_DIR':f'/run/user/{account.pw_uid}',
         'DBUS_SESSION_BUS_ADDRESS':f'unix:path=/run/user/{account.pw_uid}/bus',
         'PYTHONPATH':os.pathsep.join((str(target),str(target/'operations/decision/src'),str(target/'contracts/foundation')))}
    probe=('from deploy.ai_pc.deliberation_ollama import loaded,exchange;'
           'loaded(exchange("/api/ps",None,5));print("PINNED_LOCAL_MODEL_OK")')
    subprocess.run(['/usr/sbin/runuser','-u','rosy-deliberation','--',str(venv/'bin/python'),'-c',probe],
                   env=env,check=True)
    cfgdir=Path('/etc/rosy-deliberation');cfgdir.mkdir(mode=0o755,exist_ok=True)
    trusted_directory(cfgdir)
    config=cfgdir/'status.json';backup=cfgdir/('status.json.before-'+commit)
    cfg={'source_commit':commit,'profile_revision':'d720-v1','valid_until':time.time()+7*86400,
         'reviewer_admission':None,'billing_policy':None,'files':files}
    # This explicit root-approved policy exempts only factual status display from action calibration.
    probe=('import json,time;from rosy.decision.deliberation import Problem;'
        'from rosy.decision.deliberation.status_profiles import profiles,status_query_policy;'
        'from rosy.decision.deliberation.profiles import BoundProfile;'
        'from rosy.decision.deliberation.versioned_request import prepare_request;'
        'from deploy.ai_pc.deliberation_ollama import execute;'
        'p=Problem("fleet","status-conformance","smoke","fleet_status",time.time(),'
        '("smoke:local-model",),("human","reobserve"),"READ_ONLY_QUERY");'
        'b=BoundProfile(profiles("d720-v1")[0],p.digest);'
        '_,raw=prepare_request(p,b,(),30,budget_usd=0,missing_allowlist=("core_state","network","camera","map"));'
        'r=execute(raw,30);assert r["cost_usd"]==0;'
        f'print(json.dumps(status_query_policy("{commit}","d720-v1")))')
    checked=subprocess.run(['/usr/sbin/runuser','-u','rosy-deliberation','--',str(venv/'bin/python'),'-c',probe],
        env=env,check=True,capture_output=True,text=True,timeout=35)
    cfg['status_query_policy']=json.loads(checked.stdout)
    proof=cfgdir/'status-reviewer-admission.json'
    if proof.exists():
        info=proof.lstat()
        if proof.is_symlink() or info.st_uid!=0 or info.st_mode&0o027:raise SystemExit('protected reviewer evidence required')
        evidence=json.loads(proof.read_text())
        if set(evidence)!={'reviewer_admission','billing_policy'}:raise SystemExit('invalid reviewer evidence')
        cfg.update(evidence)
        run('/usr/bin/loginctl','enable-linger','rosy-deliberation')
        run('/usr/bin/systemctl','start',f'user@{account.pw_uid}.service')
        checked=subprocess.run(['/usr/sbin/runuser','-u','rosy-deliberation','--',str(venv/'bin/python'),
            '-m','deploy.site.deliberation_preflight'],env=env,check=True,capture_output=True,text=True,timeout=30)
        if json.loads(checked.stdout)['state']!='PASS_HOST_OFFLINE_ONLY':raise SystemExit('sandbox not admitted')
        # Verify the actual protected key fingerprint without printing or copying the credential.
        probe=('import json;from dataclasses import asdict;'
            'from deploy.ai_pc import deliberation_glm_receipt as b;'
            'from deploy.ai_pc.deliberation_glm_gateway import read_secret;'
            'from rosy.decision.deliberation.status_profiles import profiles;'
            'd=json.load(open("/etc/rosy-deliberation/status-reviewer-admission.json"));'
            'c=b.admission(b.AdapterCapabilities(**d["reviewer_admission"]));'
            'assert c==b.replace(b.status_capabilities(),ready=True,isolated=True,cost_verified=True);'
            'p=b.TrustedIncludedPlanPolicy(**d["billing_policy"]);'
            'p.validate(b.digest(asdict(profiles("d720-v1")[1])));'
            'b.credential(read_secret(),p.credential_sha256);print("STATUS_REVIEW_POLICY_BOUND")')
        subprocess.run(['/usr/sbin/runuser','-u','rosy-deliberation','--',str(venv/'bin/python'),'-c',probe],env=env,check=True)
    replace_owned(config,json.dumps(cfg,sort_keys=True).encode(),0o640,account.pw_gid,commit,
        validate=lambda raw:json.loads(raw).get('profile_revision')=='d720-v1')
    wrapper=Path('/usr/local/libexec/rosy-deliberation/status-broker')
    previous=wrapper.with_name('status-broker.before-'+commit)
    content=('#!/bin/sh\n# ROSY D-720 managed\nset -eu\n[ "$#" = 0 ] || exit 64\n'
        f'export XDG_RUNTIME_DIR=/run/user/{account.pw_uid}\n'
        f'export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{account.pw_uid}/bus\n'
        'export PYTHONDONTWRITEBYTECODE=1\n'
        f'export PYTHONPATH={env["PYTHONPATH"]}\n'
        f'cd {target}\nexec {venv}/bin/python -m deploy.ai_pc.deliberation_status_broker\n')
    replace_owned(wrapper,content.encode(),0o750,account.pw_gid,commit,
                  validate=lambda raw:raw.startswith(b'#!/bin/sh\n# ROSY D-720 managed\n'))
    registration=cfgdir/'ingress.json'
    try:ingress=pwd.getpwnam('rosy-model-ingress')
    except KeyError:
        run('/usr/sbin/useradd','--system','--user-group','--no-create-home','--home-dir','/var/empty',
            '--shell','/bin/sh','rosy-model-ingress')
        ingress=pwd.getpwnam('rosy-model-ingress')
        install_file(registration,json.dumps({'uid':ingress.pw_uid,'gid':ingress.pw_gid}).encode(),0o600)
    import spwd
    if (not registration.exists() or registration.is_symlink() or registration.stat().st_uid!=0
            or json.loads(registration.read_text())!={'uid':ingress.pw_uid,'gid':ingress.pw_gid}
            or not 0<ingress.pw_uid<1000 or ingress.pw_dir!='/var/empty' or ingress.pw_shell!='/bin/sh'
            or set(os.getgrouplist(ingress.pw_name,ingress.pw_gid))!={ingress.pw_gid}
            or not spwd.getspnam(ingress.pw_name).sp_pwdp.startswith(('!','*'))):
        raise SystemExit('dedicated registered ingress account required')
    keys=Path('/etc/ssh/rosy-status-authorized-keys')
    install_file(keys,('restrict,command="sudo -n -u rosy-deliberation /usr/local/libexec/rosy-deliberation/status-broker" '+key+'\n').encode(),0o644)
    sudo=Path('/etc/sudoers.d/rosy-status-broker')
    install_file(sudo,b'rosy-model-ingress ALL=(rosy-deliberation) NOPASSWD: /usr/local/libexec/rosy-deliberation/status-broker ""\n',0o440)
    run('/usr/sbin/visudo','-cf',str(sudo))
    sshd=Path('/etc/ssh/sshd_config.d/65-rosy-status-broker.conf')
    install_file(sshd,('Match User rosy-model-ingress\n    AuthorizedKeysFile /etc/ssh/rosy-status-authorized-keys\n'
        '    AuthenticationMethods publickey\n    PasswordAuthentication no\n    KbdInteractiveAuthentication no\n'
        '    DisableForwarding yes\n    PermitTTY no\n'
        '    ForceCommand sudo -n -u rosy-deliberation /usr/local/libexec/rosy-deliberation/status-broker\nMatch all\n').encode(),0o644)
    run('/usr/sbin/sshd','-t')
    run('/usr/bin/loginctl','enable-linger','rosy-deliberation')
    run('/usr/bin/systemctl','start',f'user@{account.pw_uid}.service')
    run('/usr/bin/systemctl','reload','ssh.service')
    if (marker.read_bytes() if marker.exists() else None)!=spent:
        raise SystemExit('spent marker changed unexpectedly; do not retry a model call')
    print(json.dumps({'source_commit':commit,'primary_admitted':True,'reviewer_admitted':proof.exists() and spent is None,
        'valid_until':cfg['valid_until'],'glm_marker_spent':spent is not None,
        'config_backup':str(backup) if backup.exists() else None,'wrapper_backup':str(previous) if previous.exists() else None}))


if __name__=='__main__':main()
