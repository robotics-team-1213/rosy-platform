"""Add independent operator admission to an existing reviewed dual-channel snapshot."""
import argparse
import json
from pathlib import Path
import pwd
import time

from deploy.site import install_conversation_broker as base

CONFIG = Path('/etc/rosy-deliberation/operator.json')


def prepare(installed, raw, proof_sha):
    from deploy.ai_pc.operator_acceptance import validate_receipt
    from rosy.decision.conversation.operator import OperatorProfile
    if base.sha(raw) != proof_sha:
        raise ValueError('OPERATOR_PROOF_SHA_MISMATCH')
    proof = json.loads(raw)
    validate_receipt(proof, installed, OperatorProfile())
    return dict(source_commit=installed['source_commit'], profile=proof['profile'],
        valid_until=proof['evaluated_at']+7*86400, semantic_evidence_sha256=proof_sha,
        files=installed['files'] | {f'operator-evaluation-{proof_sha}.json':proof_sha})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proof', type=Path)
    parser.add_argument('--proof-sha256', required=True)
    parser.add_argument('--conversation-config-sha256', required=True)
    parser.add_argument('--previous-config-sha256')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    base.require_admin()
    if not args.proof.is_absolute() or not args.proof.is_relative_to(base.REVIEWED):
        raise ValueError('ROOT_REVIEWED_BUNDLE_REQUIRED')
    installed = json.loads(base.pinned(base.CONFIG, args.conversation_config_sha256))
    import re
    if re.fullmatch('[0-9a-f]{40}', installed.get('source_commit', '')) is None:
        raise ValueError('INSTALLED_SOURCE_COMMIT_REQUIRED')
    target = base.VERSIONS/installed['source_commit']
    base.trusted_directory(target)
    if base.protected(base.BROKER) != base.broker_wrapper(target):
        raise ValueError('INSTALLED_BROKER_SOURCE_MISMATCH')
    from deploy.ai_pc.conversation_acceptance import source_files
    names = source_files(target)
    if set(source_files(Path(__file__).resolve().parents[2])) != set(names):
        raise ValueError('RUN_INSTALLER_FROM_INSTALLED_SNAPSHOT')
    files = {name:installed['files'][name] for name in names}
    for name, sha in files.items():
        if base.sha(base.protected(target/name)) != sha:
            raise ValueError('INSTALLED_SOURCE_CHANGED')
    raw = base.pinned(args.proof, args.proof_sha256)
    cfg = prepare(dict(source_commit=installed['source_commit'], files=files), raw, args.proof_sha256)
    encoded = json.dumps(cfg, sort_keys=True).encode()
    account = pwd.getpwnam('rosy-deliberation')
    base.trusted_directory(CONFIG.parent)
    previous = None
    if CONFIG.exists() or CONFIG.is_symlink():
        previous = base.protected(CONFIG)
        info = CONFIG.stat()
        if info.st_mode & 0o777 != 0o640 or info.st_gid != account.pw_gid:
            raise ValueError('MANAGED_MODE_CONFLICT')
        if previous != encoded and (not args.previous_config_sha256 or base.sha(previous) != args.previous_config_sha256):
            raise ValueError('REVIEWED_PREVIOUS_SHA256_REQUIRED')
    elif args.previous_config_sha256:
        raise ValueError('REVIEWED_PREVIOUS_FILE_MISSING')
    run = lambda code:base.run('/usr/sbin/runuser', '-u', account.pw_name, '--',
        str(target/'venv/bin/python'), '-I', '-B', '-c', base.python_code(target, code), cwd=target,
        env={'PATH':'/usr/bin:/bin'})
    run('from deploy.ai_pc.deliberation_conversation_broker import configuration;configuration()')
    if args.check:
        print(json.dumps({'state':'OPERATOR_INPUTS_CHECKED_ONLY', 'inference_performed':False}))
        return 0
    evidence = target/f'operator-evaluation-{args.proof_sha256}.json'
    base.replace_managed(evidence, raw, 0o644, 0, ())
    def verify():
        run('from deploy.ai_pc.operator_broker import configuration;configuration()')
        run('from deploy.ai_pc.deliberation_conversation_broker import configuration;configuration()')
        if base.sha(base.protected(base.CONFIG)) != args.conversation_config_sha256:
            raise ValueError('DISCORD_CONFIGURATION_CHANGED')
    base.activate([(CONFIG, encoded, 0o640, account.pw_gid, () if previous is None else (previous,))],
                  verify, lambda:None)
    print(json.dumps({'state':'INSTALLED_TRANSPORT_ONLY', 'source_commit':cfg['source_commit'],
                      'valid_until':cfg['valid_until'], 'inference_performed':False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
