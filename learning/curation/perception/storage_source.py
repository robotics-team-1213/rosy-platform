"""Finalize explicit data inputs, or export registered artifacts of a terminal Isaac run.

seal SOURCE --profile dataset --provenance provenance.json
isaac-export --run-root OWNER_ROOT --run-id RUN_ID --out NEW_DATA_DIRECTORY
Neither command uploads, deletes source files, starts Isaac, or grants learning admission.
"""
import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
import sys

from storage_files import SOURCE, PROFILES, allowed, claim, directory, entry, file_open, names, parts
from storage_inventory import free_space, open_root

SOURCE_PENDING = SOURCE + '.pending'


def _finish_publication(fd):
    try: source = os.stat(SOURCE, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError: return False
    if not stat.S_ISREG(source.st_mode): raise ValueError('source marker is not a regular file')
    try: pending = os.stat(SOURCE_PENDING, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError: return True
    if (not stat.S_ISREG(pending.st_mode) or source.st_nlink != 2
            or (source.st_dev, source.st_ino) != (pending.st_dev, pending.st_ino)):
        raise ValueError('conflicting source publication files are preserved')
    os.unlink(SOURCE_PENDING, dir_fd=fd); os.fsync(fd)
    return True


def recover_source(root):
    try: fd = open_root(str(Path(root).absolute()))
    except FileNotFoundError: return False
    try:
        with claim(fd, exclusive=True): return _finish_publication(fd)
    finally: os.close(fd)


def _generated(fd, name, raw, *, resume=False):
    try:
        with directory(fd, parts(name)[:-1], create=True) as parent:
            descriptor = os.open(parts(name)[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent)
        output = os.fdopen(descriptor, 'wb')
    except FileExistsError:
        if not resume: raise
        with file_open(fd, name) as previous:
            before = os.fstat(previous.fileno())
            prefix = previous.read(len(raw) + 1)
        if not raw.startswith(prefix): raise ValueError('changed partial export is preserved')
        if prefix == raw: return
        with directory(fd, parts(name)[:-1]) as parent:
            descriptor = os.open(parts(name)[-1], os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        output = os.fdopen(descriptor, 'wb')
        info = os.fstat(output.fileno())
        if (not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)
                or info.st_size != len(prefix) or info.st_nlink != 1):
            output.close(); raise ValueError('partial export identity changed')
        output.seek(len(prefix)); raw = raw[len(prefix):]
    with output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    os.fsync(fd)


def _json(fd, name, value, *, resume=False):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n').encode()
    if len(raw) > 1024 ** 2: raise ValueError('source metadata exceeds 1 MiB')
    _generated(fd, name, raw, resume=resume)
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def seal(root, profile, provenance, *, expected_files=None):
    root = Path(root).absolute()
    if any((parent / '.git').exists() for parent in (root, *root.parents)):
        raise ValueError('archive data belongs outside a source checkout')
    if profile not in PROFILES or not isinstance(provenance, dict):
        raise ValueError('explicit data profile and provenance required')
    if profile == 'isaac' and (not isinstance(provenance.get('run_id'), str)
            or type(provenance.get('seed')) is not int or not isinstance(provenance.get('source_revision'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', provenance['source_revision'])):
        raise ValueError('Isaac run, seed and source revision required')
    fd = open_root(str(root))
    try:
        with claim(fd, exclusive=True):
            _finish_publication(fd)
            selected = names(fd) - {SOURCE_PENDING}
            if SOURCE in selected: raise ValueError('source is already finalized')
            if not selected or len(selected) > 9999: raise ValueError('select 1..9999 artifact files')
            if free_space(fd) < 1024 ** 2: raise ValueError('insufficient space for source metadata')
            for name in selected: allowed(name, profile)
            files = {name: entry(fd, name) for name in sorted(selected)}
            if expected_files is not None and files != expected_files:
                raise ValueError('Isaac export bytes or file set changed before finalization')
            result = dict(schema='rosy.storage-source/1', status='completed', profile=profile,
                          files=files, provenance=provenance)
            _json(fd, SOURCE_PENDING, result, resume=True)
            os.link(SOURCE_PENDING, SOURCE, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            os.fsync(fd)
            _finish_publication(fd)
            return result
    finally: os.close(fd)


def export_isaac_run(store, run_id, output):
    output = Path(output).absolute()
    if output.is_relative_to(store.root) or store.root.is_relative_to(output):
        raise ValueError('new export outside the owner store required')
    return export_isaac_snapshot(lambda: store.get(run_id), lambda item_id: store.artifact(run_id, item_id), run_id, output)


def export_isaac_snapshot(get, artifact, run_id, output, *, resume=False):
    row = get()
    if (row.get('snapshot') != 'FINAL' or row.get('status') not in ('SUCCEEDED', 'FAILED', 'STOPPED')
            or row.get('result', {}).get('cleanup') not in ('OWNED_PROCESSES_EXITED_GPU_RELEASED', 'SDK_NOT_STARTED')):
        raise ValueError('final Isaac owner result and confirmed cleanup required')
    output = Path(output).absolute()
    if any((parent / '.git').exists() for parent in (output, *output.parents)):
        raise ValueError('new export outside the owner store and source checkout required')
    items = row.get('artifacts', {}).get('files', [])
    if len(items) > 256: raise ValueError('Isaac export exceeds owner artifact limit')
    parent = open_root(str(output.parent))
    try:
        if free_space(parent) < sum(item['bytes'] for item in items) + 1024 ** 3:
            raise ValueError('insufficient local space for Isaac artifact export')
        try: os.mkdir(output.name, 0o700, dir_fd=parent)
        except FileExistsError:
            if not resume: raise
    finally: os.close(parent)
    fd = open_root(str(output))
    try:
        expected = {'observation.json', 'snapshot.json', *(item['name'] for item in items)}
        if resume and not names(fd) <= expected | {SOURCE_PENDING}: raise ValueError('unregistered files in partial export are preserved')
        expected_files = {'observation.json': _json(fd, 'observation.json', row, resume=resume)}
        for item in items:
            allowed(item['name'], 'isaac')
            blob = artifact(item['id'])
            data = blob['data']
            if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ValueError('Isaac owner artifact changed during export')
            _generated(fd, item['name'], data, resume=resume)
            expected_files[item['name']] = dict(bytes=item['bytes'], sha256=item['sha256'])
        expected_files['snapshot.json'] = _json(fd, 'snapshot.json', dict(snapshot='FINAL', run_id=run_id, files=items), resume=resume)
    finally: os.close(fd)
    current = get()
    if current.get('result_sha256') != row.get('result_sha256') or current.get('artifacts_sha256') != row.get('artifacts_sha256'):
        raise ValueError('Isaac completion changed during export')
    source = row['input']
    return seal(output, 'isaac', dict(run_id=run_id, seed=source['config']['seed'],
        source_revision=source['source_sha'], assets_sha256=source['assets_sha256'],
        verifier_sha256=source['verifier_sha256'], input_sha256=row['input_sha256'],
        completion_status=row['status'], result_sha256=row['result_sha256']), expected_files=expected_files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    finalize = commands.add_parser('seal')
    finalize.add_argument('source', type=Path)
    finalize.add_argument('--profile', choices=sorted(PROFILES), required=True)
    finalize.add_argument('--provenance', type=Path, required=True)
    isaac = commands.add_parser('isaac-export')
    isaac.add_argument('--run-root', type=Path, required=True)
    isaac.add_argument('--run-id', required=True)
    isaac.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'seal':
        result = seal(args.source, args.profile, json.loads(args.provenance.read_text(encoding='utf-8')))
    else:
        if not (args.run_root / 'runs').is_dir(): parser.error('existing Isaac owner run root required')
        sys.path.append(str(Path(__file__).resolve().parents[2] / 'envs/isaac'))
        from run_store import RunStore
        result = export_isaac_run(RunStore(args.run_root), args.run_id, args.out)
    print(json.dumps(dict(status=result['status'], profile=result['profile'], files=len(result['files']))))


if __name__ == '__main__': main()
