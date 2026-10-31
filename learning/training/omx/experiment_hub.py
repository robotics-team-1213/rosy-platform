"""A completed center model, previewed and then uploaded to an existing private HF repo (D-943 §4).

Only registry `hub_sync` talks to the Hub. The token is passed in per upload and never stored.
"""
import io
from pathlib import Path
import shutil
import sys
import threading
import zipfile

from experiment_io import identifier, read_json, write_json


def _hub_sync():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'registry' / 'policy'))
    import hub_sync
    return hub_sync


# request.json carries the host dataset path; it stays on the host.
PRIVATE = {'request.json'}


class Hub:
    def __init__(self, center):
        self.center, self.root = center, center.root / 'hub'
        self.root.mkdir(exist_ok=True)
        self.lock, self.active = threading.Lock(), set()

    def prepare(self, body):
        if set(body) != {'run_id', 'repo_id', 'request_id'}:
            raise ValueError('hub preview fields differ from schema')
        rid, bid = identifier(body['run_id']), identifier(body['request_id'])
        bundle = self.root / bid
        with self.lock:
            if bundle.exists():
                if not (bundle / 'source.json').exists():
                    raise ValueError('an earlier preview with this request failed; start a new one')
                if read_json(bundle / 'source.json') != {'run_id': rid, 'repo_id': body['repo_id']}:
                    raise ValueError('request identity already used with different inputs')
                return self.status(bid)
            archive = zipfile.ZipFile(io.BytesIO(self.center.artifact(rid)))
            names = [n for n in archive.namelist() if n not in PRIVATE]
            staging = self.root / (bid + '.staging')
            shutil.rmtree(staging, ignore_errors=True)
            for name in names:
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
            try:
                _hub_sync().prepare_bundle(staging, bundle, body['repo_id'], 'model', names)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            write_json(bundle / 'source.json', {'run_id': rid, 'repo_id': body['repo_id']})
            return self.status(bid)

    def status(self, bid):
        bundle = self.root / identifier(bid)
        manifest = read_json(bundle / 'manifest.json')
        doc = dict(bundle_id=bid, run_id=read_json(bundle / 'source.json')['run_id'], repo_id=manifest['repo_id'],
                   repo_type=manifest['repo_type'], files=manifest['files'], state='prepared')
        if bid in self.active:
            doc['state'] = 'uploading'
        elif (bundle / 'receipt.json').exists():
            doc.update(state='uploaded', receipt=read_json(bundle / 'receipt.json'))
        elif (bundle / 'error.json').exists():
            doc.update(state='failed', error=read_json(bundle / 'error.json')['error'])
        return doc

    def bundles(self):
        return [self.status(p.name) for p in sorted(self.root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                if p.is_dir() and (p / 'source.json').exists()]

    def repo_of(self, bid):
        return read_json(self.root / identifier(bid) / 'manifest.json')['repo_id']

    def upload(self, bid, token, *, api=None, operation=None, downloader=None):
        bundle = self.root / identifier(bid)
        with self.lock:
            if bid in self.active or (bundle / 'receipt.json').exists():
                return self.status(bid)
            self.active.add(bid)
            (bundle / 'error.json').unlink(missing_ok=True)

        def run(api=api, operation=operation, downloader=downloader):
            try:
                if api is None:  # inside the try: an import failure must not leave the bundle "uploading"
                    from functools import partial
                    from huggingface_hub import CommitOperationAdd, HfApi, snapshot_download
                    api, operation = HfApi(token=token), CommitOperationAdd
                    downloader = partial(snapshot_download, token=token)
                _hub_sync().upload_bundle(bundle, api=api, operation=operation, downloader=downloader)
            except Exception as exc:  # the public reason only; provider bodies may echo request details
                write_json(bundle / 'error.json', {'error': str(exc) if isinstance(exc, ValueError) else type(exc).__name__})
            finally:
                with self.lock:
                    self.active.discard(bid)
        threading.Thread(target=run, daemon=True).start()
        return self.status(bid)
