#!/usr/bin/env python3
"""Install the private D-720 client after reviewing the protected host receipt."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import re
import subprocess
import tempfile
import time

from deploy.site.deliberation_install import install_file,trusted_directory


def main():
    p=argparse.ArgumentParser()
    p.add_argument('config',type=Path);p.add_argument('known_hosts',type=Path);p.add_argument('public_key',type=Path)
    p.add_argument('--config-sha256',required=True);p.add_argument('--known-hosts-sha256',required=True)
    args=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('root installation required')
    for path,expected in ((args.config,args.config_sha256),(args.known_hosts,args.known_hosts_sha256)):
        if (not path.resolve().is_relative_to('/root/rosy-status-reviewed') or path.is_symlink()
                or path.stat().st_uid!=0 or hashlib.sha256(path.read_bytes()).hexdigest()!=expected):
            raise SystemExit('reviewed client input required')
    cfg=json.loads(args.config.read_bytes())
    expected_fields={'host','key_file','known_hosts_file','profile_revision','source_commit','valid_until',
                     'primary_admitted','reviewer_admitted'}
    if (set(cfg)!=expected_fields or cfg['key_file']!='/run/rosy-deliberation/broker.key'
            or cfg['known_hosts_file']!='/run/rosy-deliberation/known_hosts'
            or cfg['profile_revision']!='d720-v1' or cfg['primary_admitted'] is not True
            or type(cfg['reviewer_admitted']) is not bool or not re.fullmatch('[0-9a-f]{40}',cfg['source_commit'])
            or type(cfg['valid_until']) not in (int,float) or not time.time()<cfg['valid_until']):
        raise SystemExit('verified host admission receipt required')
    raw=args.known_hosts.read_text().strip().split()
    if len(raw)!=3 or raw[:2]!=[cfg['host'],'ssh-ed25519']:raise SystemExit('one fixed host pin required')
    original=Path('/home/robttt/.rosy/status-incoming/broker.key')
    fd=os.open(original,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=pwd.getpwnam('robttt').pw_uid
                or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>4096):raise SystemExit('private key boundary failed')
        key=os.read(fd,4097)
    finally:os.close(fd)
    with tempfile.TemporaryDirectory(prefix='rosy-status-client-') as temp:
        snapshot=Path(temp)/'key';snapshot.write_bytes(key);snapshot.chmod(0o600)
        public=subprocess.check_output(['ssh-keygen','-y','-f',str(snapshot)],text=True).strip().split()
    if (not args.public_key.resolve().is_relative_to('/root/rosy-status-reviewed')
            or args.public_key.is_symlink() or args.public_key.stat().st_uid!=0
            or public[:2]!=args.public_key.read_text().split()[:2]):raise SystemExit('approved broker key changed')
    parent=Path('/etc/rosy');trusted_directory(parent)
    destination=parent/'fleet-deliberation'
    destination.mkdir(mode=0o750,exist_ok=True);trusted_directory(destination)
    if any(destination.iterdir()) and (destination.stat().st_gid!=10001 or stat.S_IMODE(destination.stat().st_mode)!=0o750):
        raise SystemExit('foreign client directory refused')
    os.chown(destination,0,10001);destination.chmod(0o750)
    install_file(destination/'broker.key',key,0o640,10001)
    install_file(destination/'known_hosts',args.known_hosts.read_bytes(),0o644)
    install_file(destination/'status.json',args.config.read_bytes(),0o640,10001)
    print('PRIVATE_STATUS_CLIENT_INSTALLED; signed Fleet deployment and fresh Discord readback remain required')


if __name__=='__main__':main()
