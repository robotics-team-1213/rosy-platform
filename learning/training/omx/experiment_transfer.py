"""Restartable sealed dataset delivery to HTTPS Learning or a bench loopback tunnel."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from experiment_io import identifier, read_json, sync_directory
from experiment_profile import profile_revision

PREFIX = '/api/learning/omx/center/'
CHUNK = 256 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Http:
    def __init__(self, origin):
        if (not isinstance(origin, str) or any(ord(c) <= 32 or ord(c) == 127 for c in origin)
                or any(c in origin for c in '\\?#')):
            raise ValueError('HTTPS origin or explicit HTTP loopback origin required')
        url = urllib.parse.urlsplit(origin)
        port = url.port
        if (url.scheme not in ('https', 'http') or not url.hostname
                or (':' not in url.hostname and not all(
                    re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                    for label in url.hostname.split('.')))
                or url.username is not None or url.password is not None
                or url.path not in ('', '/') or url.netloc.endswith(':') or port == 0
                or (url.scheme == 'http' and (url.hostname not in ('127.0.0.1', 'localhost', '::1') or not port))):
            raise ValueError('HTTPS origin or explicit HTTP loopback origin without URL credentials required')
        self.origin = origin.rstrip('/')
        self.cookie = os.environ.get('ROSY_LEARNING_SESSION_COOKIE', '')
        if len(self.cookie) > 16384 or any(c in self.cookie for c in '\r\n'):
            raise ValueError('invalid Learning session cookie')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.token = None

    def _request(self, path, body=None):
        headers = {'Origin': self.origin, 'Cookie': self.cookie}
        if body is not None:
            headers.update({'Content-Type': 'application/json', 'X-Pinky-Token': self.token})
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        request = urllib.request.Request(self.origin + path, data=data, headers=headers)
        with self.opener.open(request, timeout=30) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('bounded Learning response required')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('Learning object response required')
        return result

    def post(self, path, body):
        if self.token is None:
            self.token = self._request('/api/learning').get('token')
            if not isinstance(self.token, str) or not self.token:
                raise ValueError('authenticated Learning session token required')
        return self._request(path, body)


def _files(root):
    files = {}
    for path in sorted(root.iterdir()):
        if (path.is_symlink() or not path.is_file()
                or not re.fullmatch(r'((dataset|native-split-receipt|conversion-receipt)\.json|[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.npz)', path.name)):
            raise ValueError('sealed flat dataset files without links required')
        size = path.stat().st_size
        if size <= 0 or size > 512 * 1024 * 1024:
            raise ValueError('bounded nonempty dataset file required')
        with path.open('rb') as stream:
            files[path.name] = dict(size=size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())
    if ('dataset.json' not in files or len(files) > 1000
            or sum(f['size'] for f in files.values()) > 512 * 1024 * 1024):
        raise ValueError('dataset.json and at most 1000 files/512 MiB required')
    return files


def _checkpoint(path, binding):
    if path.is_symlink():
        raise ValueError('regular transfer checkpoint required')
    if not path.exists():
        temporary = path.with_name(path.name + '.' + str(uuid.uuid4()) + '.tmp')
        document = dict(binding, upload_id=str(uuid.uuid4()), request_id=str(uuid.uuid4()))
        try:
            with temporary.open('x', encoding='utf-8') as stream:
                json.dump(document, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass  # Another sender established the same checkpoint first.
        finally:
            temporary.unlink(missing_ok=True)
    sync_directory(path.parent)
    saved = read_json(path)
    if (not isinstance(saved, dict) or set(saved) != set(binding) | {'upload_id', 'request_id'}
            or any(saved.get(k) != v for k, v in binding.items())):
        raise ValueError('transfer checkpoint differs from target, source or run')
    identifier(saved['upload_id'])
    identifier(saved['request_id'])
    return saved


def transfer(root, checkpoint, *, origin, name, run_id=None, post=None):
    http = Http(origin)
    if run_id is not None:
        identifier(run_id)
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 128:
        raise ValueError('dataset display name required')
    root = Path(root)
    if root.is_symlink():
        raise ValueError('regular sealed dataset directory required')
    root = root.resolve(strict=True)
    checkpoint = Path(checkpoint).absolute()
    if (checkpoint.resolve().is_relative_to(root)
            or any((parent/'.git').exists() for parent in checkpoint.parents)):
        raise ValueError('transfer checkpoint belongs outside dataset and source checkouts')
    files = _files(root)
    if files['dataset.json']['size'] > 1024 * 1024:
        raise ValueError('bounded dataset manifest required')
    raw = (root/'dataset.json').read_bytes()
    manifest = json.loads(raw)
    revision = hashlib.sha256(raw + profile_revision(manifest['profile']).encode()).hexdigest()
    saved = _checkpoint(checkpoint, dict(schema='rosy.omx.transfer/1', origin=http.origin,
        root=str(root), name=name.strip(), run_id=run_id, files=files, dataset_revision=revision))
    send = post or http.post
    for filename, expected in files.items():
        offset = 0
        with (root/filename).open('rb') as stream:
            while chunk := stream.read(CHUNK):
                reply = send(PREFIX+'upload', dict(upload_id=saved['upload_id'], name=filename,
                    offset=offset, data=base64.b64encode(chunk).decode()))
                offset += len(chunk)
                if reply != dict(upload_id=saved['upload_id'], name=filename, offset=offset):
                    raise ValueError('upload acknowledgement differs from sent chunk')
        if offset != expected['size']:
            raise ValueError('sealed source changed during transfer')
    if _files(root) != files:
        raise ValueError('sealed source changed during transfer')
    dataset = send(PREFIX+'publish', dict(upload_id=saved['upload_id'], name=saved['name']))
    if dataset.get('id') != saved['upload_id'] or dataset.get('revision') != revision:
        raise ValueError('published dataset identity or revision differs')
    result = {'dataset': dataset}
    if run_id:
        item = send(PREFIX+'experience', dict(id=run_id, dataset_id=dataset['id'], request_id=saved['request_id']))
        if item.get('id') != saved['request_id'] or item.get('dataset_id') != dataset['id']:
            raise ValueError('experience acknowledgement differs')
        result['experience'] = item
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--origin', required=True, help='operator-configured HTTPS origin, or HTTP loopback with port for bench use')
    parser.add_argument('--name', required=True)
    parser.add_argument('--run-id')
    args = parser.parse_args(argv)
    try:
        result = transfer(args.dataset, args.checkpoint, origin=args.origin, name=args.name, run_id=args.run_id)
    except urllib.error.HTTPError as exc:
        parser.exit(2, f'Learning HTTP {exc.code}; retain checkpoint and verify session/server\n')
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f'transfer stopped ({type(exc).__name__}); retain checkpoint and verify source/connection\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
