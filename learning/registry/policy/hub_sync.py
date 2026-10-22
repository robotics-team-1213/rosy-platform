"""Preview selected artifact files, then explicitly sync to an existing private HF repo."""
import argparse
from policy_output_paths import in_source_checkout
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil


def _selection(relative, repo_type):
    if not isinstance(relative, str) or '\\' in relative:
        raise ValueError('file selection must use relative POSIX paths')
    path = PurePosixPath(relative)
    if path.is_absolute() or path.as_posix() != relative or any(part.startswith('.') for part in path.parts):
        raise ValueError('hidden or escaping file selection')
    if any(part.lower() in ('private', 'secrets', 'tokens', 'credentials') for part in path.parts):
        raise ValueError('private files cannot be selected')
    allowed = relative == 'README.md'
    if repo_type == 'dataset':
        allowed |= path.parts[0] == 'meta' and path.suffix in ('.json', '.parquet')
        allowed |= path.parts[0] == 'data' and path.suffix == '.parquet'
        allowed |= path.parts[0] == 'videos' and path.suffix == '.mp4'
    elif repo_type == 'model':
        allowed |= path.suffix in ('.safetensors', '.json')
    if not allowed:
        raise ValueError('file is outside the dataset/model upload allowlist')
    return path


def _hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _file(root, relative, repo_type):
    path = root / _selection(relative, repo_type)
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('symlink or escaping payload path')
    if not path.is_file():
        raise ValueError('selected artifact file is missing')
    return path


def _write(path, doc):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(doc, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def prepare_bundle(source, output, repo_id, repo_type, files):
    if repo_type not in ('dataset', 'model') or not re.fullmatch(r'[\w-]+/[\w.-]+', repo_id) or '..' in repo_id:
        raise ValueError('explicit namespace/repository and dataset/model type required')
    if not files or len(set(files)) != len(files):
        raise ValueError('select unique artifact files explicitly')
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or in_source_checkout(output) or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('bundle requires a new separate output outside the source checkout')
    selected = {relative: _file(source, relative, repo_type) for relative in sorted(files)}
    output.mkdir(parents=True)
    hashes = {}
    for relative, path in selected.items():
        expected = _hash(path)
        target = output / 'payload' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if _hash(target) != expected or _hash(path) != expected:
            raise ValueError('source changed while preparing bundle')
        hashes[relative] = expected
    _write(output / 'manifest.json', dict(repo_id=repo_id, repo_type=repo_type, files=hashes))
    return output


def upload_bundle(bundle, *, api=None, operation=None, downloader=None):
    bundle = Path(bundle).resolve()
    if in_source_checkout(bundle):
        raise ValueError('upload receipt and download belong outside the source checkout')
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    repo_id, repo_type = manifest['repo_id'], manifest['repo_type']
    if repo_type not in ('dataset', 'model') or not re.fullmatch(r'[\w-]+/[\w.-]+', repo_id) or '..' in repo_id:
        raise ValueError('invalid destination')
    if not isinstance(manifest.get('files'), dict) or not manifest['files']:
        raise ValueError('empty file manifest')
    selected = {name: _file(bundle / 'payload', name, repo_type) for name in manifest['files']}
    for name, path in selected.items():
        if _hash(path) != manifest['files'][name]:
            raise ValueError('payload hash differs from preview')
    if (bundle / 'receipt.json').exists():
        raise ValueError('bundle already has a success receipt')
    if api is None:
        from huggingface_hub import HfApi, CommitOperationAdd, snapshot_download
        api, operation, downloader = HfApi(), CommitOperationAdd, snapshot_download
    info = api.repo_info(repo_id=repo_id, repo_type=repo_type)
    if info.private is not True:
        raise ValueError('destination must already be private; no visibility changes are performed')
    if not re.fullmatch(r'[0-9a-f]{40}', info.sha or ''):
        raise ValueError('destination commit is missing')
    attempt = bundle / 'upload.json'
    if attempt.exists():
        previous = json.loads(attempt.read_text(encoding='utf-8'))
        if previous['manifest'] != manifest:
            raise ValueError('upload attempt differs from current manifest')
        revision = previous['revision']
    else:
        commit = api.create_commit(repo_id=repo_id, repo_type=repo_type, parent_commit=info.sha,
                                   operations=[operation(path_in_repo=name, path_or_fileobj=str(path))
                                               for name, path in selected.items()],
                                   commit_message='Upload reviewed OMX artifact files')
        revision = commit.oid
        _write(attempt, dict(manifest=manifest, revision=revision))
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('upload did not return an immutable commit')
    download_root = bundle / 'readback'
    if downloader is None:
        raise ValueError('revision downloader is required')
    downloader(repo_id=repo_id, repo_type=repo_type, revision=revision,
               local_dir=str(download_root), allow_patterns=list(selected))
    for name, expected in manifest['files'].items():
        if _hash(_file(download_root, name, repo_type)) != expected:
            raise ValueError('download hash differs from reviewed payload')
    if api.repo_info(repo_id=repo_id, repo_type=repo_type).private is not True:
        raise ValueError('repository visibility changed during sync')
    receipt = dict(repo_id=repo_id, repo_type=repo_type, revision=revision, files=manifest['files'],
                   bytes_verified=True, reader_verified=False)
    _write(bundle / 'receipt.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('source', type=Path)
    prepare.add_argument('--out', type=Path, required=True)
    prepare.add_argument('--repo-id', required=True)
    prepare.add_argument('--repo-type', choices=('dataset', 'model'), required=True)
    prepare.add_argument('--file', action='append', required=True)
    upload = commands.add_parser('upload')
    upload.add_argument('bundle', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            output = prepare_bundle(args.source, args.out, args.repo_id, args.repo_type, args.file)
            print((output / 'manifest.json').read_text(encoding='utf-8'))
        else:
            print(json.dumps(upload_bundle(args.bundle), indent=2))
    except Exception as exc:
        # SDK exception bodies can contain request details; do not print credentials or URLs.
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        parser.exit(2, f'sync failed: {message}; source and partial bundle preserved\n')


if __name__ == '__main__':
    main()
