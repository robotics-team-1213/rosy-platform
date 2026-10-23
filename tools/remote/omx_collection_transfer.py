"""Copy one closed hardware collection from the configured site PC to the model PC."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_hosts

SSH_OPTIONS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2']


def _safe(value):
    if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', value):
        raise ValueError('session and destination must be safe basenames')
    return value


def _no_links(path):
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('collection links are not accepted')


def verify_tree(root):
    """Stream all declared files; the same verifier executes on both remote hosts."""
    root = Path(root).absolute()
    _no_links(root)
    if not root.is_dir():
        raise ValueError('collection directory is missing')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate manifest JSON key')
            result[key] = value
        return result
    manifest_path = root/'manifest.json'
    _no_links(manifest_path)
    if not manifest_path.is_file() or manifest_path.stat().st_nlink != 1:
        raise ValueError('regular manifest file required')
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw, object_pairs_hook=unique)
    if (not isinstance(manifest, dict) or manifest.get('schema') != 'rosy.omx-collection-session.v1'
            or manifest.get('state') != 'CLOSED' or manifest.get('mode') != 'hardware'
            or manifest.get('source_mode') not in ('scripted_teacher', 'leader_native')):
        raise ValueError('closed hardware collection manifest required')
    files = manifest.get('files')
    if not isinstance(files, dict) or not files or 'manifest.json' in files:
        raise ValueError('complete raw file hash map required')
    for name, digest in files.items():
        if (not isinstance(name, str) or '\\' in name or ':' in name
                or PurePosixPath(name).is_absolute() or PurePosixPath(name).as_posix() != name
                or any(p in ('', '.', '..') for p in PurePosixPath(name).parts)
                or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
            raise ValueError('unsafe manifest file path/hash')
    actual = {}
    for path in sorted(root.rglob('*')):
        _no_links(path)
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('collection file escapes its root')
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise ValueError('collection hard links are not accepted')
            name = path.relative_to(root).as_posix()
            if name != 'manifest.json':
                with path.open('rb') as stream:
                    actual[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
        elif not path.is_dir():
            raise ValueError('special collection files are not accepted')
    if actual != files or manifest_path.read_bytes() != raw:
        raise ValueError('collection file bytes or manifest changed')
    return dict(manifest_sha256=hashlib.sha256(raw).hexdigest(), file_count=len(actual))


def _receiver(action, session, destination, token, expected=''):
    _safe(session), _safe(destination), _safe(token)
    home = Path.home()/'rosy-test'
    source = home/'omx-collections'/session
    base = home/'omx-il-data'
    target = base/'collections'/destination
    lock = base/'transfer-locks'/(destination+'.lock')
    receipt = base/'transfer-receipts'/(destination+'.json')
    if action == 'source':
        return verify_tree(source)
    for path in (target, lock, receipt):
        _no_links(path)
    if action == 'reserve':
        if target.exists() or receipt.exists():
            raise ValueError('destination or transfer receipt exists; choose a new destination')
        for folder in (target.parent, lock.parent, receipt.parent):
            folder.mkdir(parents=True, exist_ok=True)
            _no_links(folder)
        with lock.open('x', encoding='utf-8') as stream:
            stream.write(token)
        return {}
    if not lock.is_file() or lock.read_text(encoding='utf-8') != token:
        raise ValueError('exclusive transfer reservation differs')
    if action == 'release':
        lock.unlink()
        return {}
    verified = verify_tree(target)
    if verified['manifest_sha256'] != expected:
        raise ValueError('received manifest differs from verified source')
    if action == 'destination':
        return verified
    if action != 'finish':
        raise ValueError('unknown transfer operation')
    document = dict(schema='rosy.omx-collection-transfer.v1', source_session=session,
                    destination=destination, verified=True, **verified,
                    physical_acceptance=False, task_success=None)
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump(document, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return document


def _remote(host, action, session, destination, token, expected=''):
    script = 'import hashlib,json,os,re,sys\nfrom pathlib import Path,PurePosixPath\n'
    script += '\n'.join(inspect.getsource(function) for function in (_safe, _no_links, verify_tree, _receiver))
    script += '\nprint(json.dumps(_receiver(*sys.argv[1:])))\n'
    command = 'python3 - ' + ' '.join(shlex.quote(v) for v in (action, session, destination, token, expected))
    result = subprocess.run(['ssh', *SSH_OPTIONS, '--', host, command], input=script,
                            capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise ValueError(f'transfer {action} failed: {result.stderr[-2000:]}')
    return json.loads(result.stdout)


def _copy(source, model, session, destination):
    result = subprocess.run(['scp', '-3', '-q', '-r', *SSH_OPTIONS, '--',
                             f'{source}:rosy-test/omx-collections/{session}',
                             f'{model}:rosy-test/omx-il-data/collections/{destination}'],
                            capture_output=True, text=True, timeout=1800)
    if result.returncode:
        raise ValueError('copy failed; partial destination preserved; choose a new destination: '
                         + result.stderr[-2000:])


def transfer(session, destination=None):
    session, destination = _safe(session), _safe(destination or session)
    config = lab_hosts.load()
    hosts = config.get('test_hosts')
    source = config.get('site_host')
    model = hosts[0] if isinstance(hosts, list) and hosts else None
    pattern = r'[A-Za-z0-9][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9_.-]*'
    if (not all(isinstance(h, str) and re.fullmatch(pattern, h) for h in (source, model)) or source == model):
        raise ValueError('private site_host and first test_hosts model destination must be distinct SSH endpoints')
    token = uuid.uuid4().hex
    original = _remote(source, 'source', session, destination, token)
    expected = original['manifest_sha256']
    _remote(model, 'reserve', session, destination, token, expected)
    try:
        _copy(source, model, session, destination)
        if _remote(model, 'destination', session, destination, token, expected) != original:
            raise ValueError('received collection differs from verified source')
        if _remote(source, 'source', session, destination, token) != original:
            raise ValueError('source changed during transfer')
        _remote(model, 'finish', session, destination, token, expected)
    finally:
        try:
            _remote(model, 'release', session, destination, token, expected)
        except (ValueError, OSError, subprocess.SubprocessError):
            pass  # A lost connection leaves the reservation; it never permits overwriting.
    return dict(verified=True, **original, source_host=source, model_host=model,
                session=session, destination=destination,
                raw_path=f'rosy-test/omx-il-data/collections/{destination}',
                receipt_path=f'rosy-test/omx-il-data/transfer-receipts/{destination}.json',
                uploaded=False, device_execution=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True)
    parser.add_argument('--destination')
    args = parser.parse_args()
    try:
        result = transfer(args.session, args.destination)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
