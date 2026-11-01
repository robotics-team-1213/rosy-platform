"""Prepare a signed, fixed-file OS transport repair on the operator PC; never contacts a device."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'deploy/robot/pinky_pro/release'))
sys.path.insert(0, str(ROOT / 'deploy/robot/pinky_pro/native'))
from signing import sign_checksums
from os_transport_repair import BASE_SOURCE, BASE_RELEASE, FILES, MAX_FILE, validate_package
from tools.release.external_os_signing import _local_private_key, _openssl_run
from tools.release.prepare_os_release import _approved_cms

SOURCE = 'deploy/robot/pinky_pro/native/'


def _blob(revision, filename, *, optional=False):
    result = subprocess.run(['git', 'show', revision + ':' + SOURCE + filename], cwd=ROOT, capture_output=True, check=False)
    if result.returncode:
        if optional: return None
        raise ValueError('required repair source is absent from the exact Git commit')
    if not 0 < len(result.stdout) <= MAX_FILE: raise ValueError('repair source exceeds its bound')
    return result.stdout


def prepare(output, private_key, public_key, cms_private_key, *, source_revision, canary):
    if os.environ.get('GITHUB_ACTIONS', '').lower() == 'true':
        raise ValueError('repair signing runs only on the operator PC')
    if not isinstance(source_revision, str) or not re.fullmatch('[0-9a-f]{40}', source_revision):
        raise ValueError('repair requires an exact target commit')
    output = Path(output).absolute()
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('repair output must be a new directory beneath an existing parent')
    if any(p.is_symlink() for p in (output.parent, *output.parents)):
        raise ValueError('redirected repair output')
    private_key = _local_private_key(private_key)
    cms_private_key = _local_private_key(cms_private_key)
    if any(key.is_relative_to(output) for key in (private_key, cms_private_key)):
        raise ValueError('private keys must stay outside repair output')
    approved = _approved_cms()
    files, records = {}, {}
    for name in FILES:
        content = _blob(source_revision, name)
        ast.parse(content, filename=name)  # Parsing is not candidate-code execution.
        previous = _blob(BASE_SOURCE, name, optional=name == FILES[-1])
        files[name] = content
        records[name] = dict(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                             preimage_sha256=hashlib.sha256(previous).hexdigest() if previous is not None else None)
    installer = _blob(source_revision, 'os_transport_repair.py')
    ast.parse(installer, filename='os_transport_repair.py')
    files['os_transport_repair.py'] = installer
    value = dict(schema_version=1, kind='os-transport-repair', base_release_id=BASE_RELEASE,
                 base_source_revision=BASE_SOURCE, source_revision=source_revision, canary=canary,
                 installer_sha256=hashlib.sha256(installer).hexdigest(), files=records)
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    files['transport-repair.json'] = raw
    files['transport-repair.json.sig'] = (sign_checksums(raw, private_key) + '\n').encode('ascii')
    with tempfile.TemporaryDirectory(prefix='rosy-transport-authority-') as temporary:
        certificate = Path(temporary) / 'authority.pem'
        certificate.write_bytes(approved['certificate'])
        files['transport-repair.cms'] = _openssl_run(['cms', '-sign', '-binary', '-signer', certificate,
            '-inkey', cms_private_key, '-nodetach', '-outform', 'DER'], data=raw)
    staged = Path(tempfile.mkdtemp(prefix='.' + output.name + '-', dir=output.parent))
    complete = False
    try:
        for name, content in files.items():
            with (staged / name).open('xb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        validate_package(staged, public_key, cms_certificate=approved['certificate'])
        if output.exists() or output.is_symlink(): raise ValueError('repair output appeared during preparation')
        os.rename(staged, output)
        complete = True
    finally:
        if not complete:
            for name in files:
                path = staged / name
                if path.is_file() and not path.is_symlink(): path.unlink()
            try: staged.rmdir()
            except OSError: pass  # Preserve any unexpected file; never recursively remove it.
    return dict(directory=str(output), source_revision=source_revision, base_release_id=BASE_RELEASE,
                installer_sha256=value['installer_sha256'], files=sorted(files))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--private-key', type=Path, required=True)
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--cms-private-key', type=Path, required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--canary', action='append', required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare(args.output, args.private_key, args.public_key, args.cms_private_key,
            source_revision=args.source_revision, canary=args.canary), sort_keys=True))
        return 0
    except (OSError, ValueError, SyntaxError) as exc:
        print('OS_TRANSPORT_REPAIR_PREPARE_HOLD: ' + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
