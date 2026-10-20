#!/usr/bin/env python3
"""Install a reviewed private client; conversation admission is separate from D-720."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import stat
import re
import subprocess
import tempfile
import time

from deploy.site.deliberation_install import install_file,trusted_directory


def reviewed_bytes(path, expected, root):
    if not path.is_relative_to(root) or path.is_symlink():
        raise ValueError('reviewed client input required')
    trusted_directory(path.parent)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_size>1048576:
            raise ValueError('reviewed client input required')
        raw=os.read(fd,1048577)
    finally:os.close(fd)
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('reviewed client hash changed')
    return raw


def validate_conversation(cfg, raw):
    # Standard library only: root must not import a user-owned Fleet venv.
    proof=json.loads(raw)
    if type(cfg) is not dict or type(proof) is not dict or type(cfg.get('profile')) is not dict:
        raise ValueError('verified conversation admission proof required')
    fields={'host','ssh_port','key_file','known_hosts_file','profile','source_commit','valid_until',
            'primary_admitted','semantic_evidence_sha256','policy'}
    finite=lambda n:type(n) in (int,float) and math.isfinite(n)
    canonical=lambda v:json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    profile=cfg.get('profile',{})
    expected={'profile_id':'qwen-conversation-primary','revision':profile.get('revision'),
        'model_id':'qwen3-vl:8b-instruct',
        'model_digest':'0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319',
        'protocol':'rosy-conversation-v1','context_length':8192,'timeout_s':30,'max_calls':1,'max_cost_usd':0}
    policy={'schema':'rosy.conversation-policy/1','source_commit':cfg.get('source_commit'),
        'profile_hash':hashlib.sha256(canonical(profile).encode()).hexdigest(),
        'authority':'proposal_only','output_kinds':['CHAT','STATUS','CLARIFY','CONTROL','REFUSE']}
    if profile.get('revision')=='d728-semantic-v3-d831':
        policy['preprocessing_version']='d831-v1'
    if (set(cfg)-{'ssh_port'}!=fields-{'ssh_port'}
            or type(cfg.get('host')) is not str
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}',cfg['host'])
            or type(cfg.get('ssh_port',22)) is not int or cfg.get('ssh_port',22)!=22
            or cfg.get('key_file')!='/run/rosy-deliberation/broker.key'
            or cfg.get('known_hosts_file')!='/run/rosy-deliberation/known_hosts'
            or cfg.get('primary_admitted') is not True
            or type(cfg.get('source_commit')) is not str
            or not re.fullmatch('[0-9a-f]{40}',cfg['source_commit'])
            or canonical(profile)!=canonical(expected)
            or not re.fullmatch('d728-[a-z0-9-]{1,40}',str(profile.get('revision','')))
            or cfg.get('policy')!=policy
            or cfg.get('semantic_evidence_sha256')!=hashlib.sha256(raw).hexdigest()
            or proof.get('schema')!='rosy.conversation-evaluation/1'
            or proof.get('verdict')!='PASS' or proof.get('evaluation_owner')!='model_pc'
            or any(canonical(proof.get(k))!=canonical(cfg.get(k)) for k in ('source_commit','profile','policy'))
            or not finite(proof.get('evaluated_at')) or not 0<=time.time()-proof['evaluated_at']<=7*86400
            or not finite(cfg.get('valid_until')) or not time.time()<cfg['valid_until']<=proof['evaluated_at']+7*86400):
        raise ValueError('verified conversation admission proof required')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('config',type=Path);p.add_argument('known_hosts',type=Path);p.add_argument('public_key',type=Path)
    p.add_argument('--config-sha256',required=True);p.add_argument('--known-hosts-sha256',required=True)
    p.add_argument('--conversation',action='store_true')
    p.add_argument('--conversation-proof',type=Path);p.add_argument('--proof-sha256')
    p.add_argument('--public-key-sha256')
    args=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('root installation required')
    if args.conversation:
        if not all((args.conversation_proof,args.proof_sha256,args.public_key_sha256)):
            p.error('conversation requires reviewed proof and public key hashes')
        root=Path('/root/rosy-conversation-reviewed')
        config=reviewed_bytes(args.config,args.config_sha256,root)
        pins=reviewed_bytes(args.known_hosts,args.known_hosts_sha256,root)
        approved=reviewed_bytes(args.public_key,args.public_key_sha256,root)
        proof=reviewed_bytes(args.conversation_proof,args.proof_sha256,root)
        cfg=json.loads(config);validate_conversation(cfg,proof)
    else:
        install_status(args)
        return
    install_client(cfg,config,pins,approved,'conversation.json')


def install_status(args):
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
    if (not args.public_key.resolve().is_relative_to('/root/rosy-status-reviewed')
            or args.public_key.is_symlink() or args.public_key.stat().st_uid!=0):
        raise SystemExit('approved broker key changed')
    install_client(cfg,args.config.read_bytes(),args.known_hosts.read_bytes(),args.public_key.read_bytes(),'status.json')


def install_client(cfg,config,pins,approved,name):
    raw=pins.decode().strip().split()
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
        public=subprocess.check_output(['/usr/bin/ssh-keygen','-y','-f',str(snapshot)],text=True).strip().split()
    if public[:2]!=approved.decode().split()[:2]:raise SystemExit('approved broker key changed')
    parent=Path('/etc/rosy');trusted_directory(parent)
    destination=parent/'fleet-deliberation'
    destination.mkdir(mode=0o750,exist_ok=True);trusted_directory(destination)
    if any(destination.iterdir()) and (destination.stat().st_gid!=10001 or stat.S_IMODE(destination.stat().st_mode)!=0o750):
        raise SystemExit('foreign client directory refused')
    os.chown(destination,0,10001);destination.chmod(0o750)
    install_file(destination/'broker.key',key,0o640,10001)
    install_file(destination/'known_hosts',pins,0o640 if name=='conversation.json' else 0o644,
                 10001 if name=='conversation.json' else 0)
    install_file(destination/name,config,0o640,10001)
    print(f'PRIVATE_{name[:-5].upper()}_CLIENT_INSTALLED; signed Fleet deployment and fresh Discord readback remain required')


if __name__=='__main__':main()
